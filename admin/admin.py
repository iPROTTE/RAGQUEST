"""Ragquest Admin — uso exclusivo do fornecedor.
Gera chaves de licença assinadas e monta o instalador do Ragquest para clientes."""
import base64, csv, datetime, hashlib, json, os, platform, re, secrets, shutil, subprocess, sys, threading, time, urllib.request, zipfile
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
import hmac
from pydantic import BaseModel
import ed25519

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
CHAVES = os.path.join(BASE, "chaves")
PRIV = os.path.join(CHAVES, "chave_privada.key")
PUB = os.path.join(CHAVES, "chave_publica.txt")
CSV = os.path.join(BASE, "licencas_emitidas.csv")
MODELO = os.path.join(BASE, "modelo")
CACHE = os.path.join(BASE, "cache")
BUILD = os.path.join(BASE, "build")
SAIDA = os.path.join(BASE, "saida")
VERSAO = os.path.join(BASE, "versao.txt")

# ---------------------------------------------------------------- chaves
def chaves():
    os.makedirs(CHAVES, exist_ok=True)
    if not os.path.exists(PRIV):
        sk = secrets.token_bytes(32)
        open(PRIV, "w").write(sk.hex())
        open(PUB, "w").write(ed25519.public_key(sk).hex())
    sk = bytes.fromhex(open(PRIV).read().strip())
    return sk, ed25519.public_key(sk).hex()

def _b64(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")

CAMPOS_CSV = ["emitida_em", "cliente", "maquina", "validade", "usuarios", "agentes", "observacao", "chave"]

def _migrar_csv():
    """Acrescenta a coluna 'usuarios' em históricos antigos."""
    if not os.path.exists(CSV):
        return
    with open(CSV, encoding="utf-8-sig") as fh:
        linhas = list(csv.DictReader(fh, delimiter=";"))
        fh.seek(0)
        cab = fh.readline()
    faltam = [k for k in CAMPOS_CSV if k not in cab.strip().split(";")]
    if not faltam:
        return
    with open(CSV, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS_CSV, delimiter=";")
        w.writeheader()
        for l in linhas:
            for k in faltam:
                l[k] = "sem limite" if k in ("usuarios", "agentes") else ""
            w.writerow({k: l.get(k, "") for k in CAMPOS_CSV})

def gerar_licenca(cliente, maquina, validade, obs="", usuarios=None, agentes=None):
    sk, _ = chaves()
    maquina = (maquina or "*").strip().upper() or "*"
    if maquina != "*" and not re.fullmatch(r"[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}", maquina):
        raise ValueError("Código da máquina inválido (formato XXXX-XXXX-XXXX).")
    if validade:
        datetime.date.fromisoformat(validade)
    if usuarios not in (None, "", 0):
        usuarios = int(usuarios)
        if not 1 <= usuarios <= 100000:
            raise ValueError("Limite de usuários inválido.")
    else:
        usuarios = None
    if agentes not in (None, "", 0):
        agentes = int(agentes)
        if not 1 <= agentes <= 1000:
            raise ValueError("Limite de agentes inválido.")
    else:
        agentes = None
    dados = {"c": cliente.strip(), "m": maquina, "e": validade or None,
             "i": datetime.date.today().isoformat(), "n": secrets.token_hex(4)}
    if usuarios:
        dados["u"] = usuarios
    if agentes:
        dados["a"] = agentes
    payload = json.dumps(dados, separators=(",", ":"), ensure_ascii=False).encode()
    chave = "RAGQUEST-" + _b64(payload) + "." + _b64(ed25519.sign(sk, payload))
    _migrar_csv()
    novo = not os.path.exists(CSV)
    with open(CSV, "a", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        if novo:
            w.writerow(CAMPOS_CSV)
        w.writerow([datetime.datetime.now().strftime("%d/%m/%Y %H:%M"), cliente, maquina, validade or "sem validade",
                    usuarios or "sem limite", agentes or "sem limite", obs, chave])
    return chave

def licencas():
    _migrar_csv()
    if not os.path.exists(CSV):
        return []
    with open(CSV, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh, delimiter=";"))[::-1]

# ---------------------------------------------------------------- backup da chave mestra
ULTIMO_BACKUP = os.path.join(BASE, "ultimo_backup.txt")

def _chaves_cripto(senha, salt):
    k = hashlib.scrypt(senha.encode("utf-8"), salt=salt, n=2**15, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=64)
    return k[:32], k[32:]

def _fluxo(chave, nonce, n):
    out, i = b"", 0
    while len(out) < n:
        out += hmac.new(chave, nonce + i.to_bytes(8, "big"), hashlib.sha256).digest(); i += 1
    return out[:n]

def gerar_backup(senha):
    """Arquivo cifrado (scrypt + HMAC-SHA256 em modo contador, autenticado) com a chave mestra e o histórico."""
    sk, pub = chaves()
    dados = json.dumps({"chave_privada": sk.hex(), "chave_publica": pub,
                        "licencas_csv": open(CSV, encoding="utf-8-sig").read() if os.path.exists(CSV) else "",
                        "criado_em": datetime.datetime.now().isoformat(timespec="seconds")}).encode()
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(16)
    ke, km = _chaves_cripto(senha, salt)
    ct = bytes(a ^ b for a, b in zip(dados, _fluxo(ke, nonce, len(dados))))
    tag = hmac.new(km, salt + nonce + ct, hashlib.sha256).digest()
    open(ULTIMO_BACKUP, "w").write(datetime.datetime.now().strftime("%d/%m/%Y %H:%M"))
    return json.dumps({"formato": "ragquest-backup-1", "salt": _b64(salt), "nonce": _b64(nonce),
                       "dados": _b64(ct), "tag": _b64(tag)}, indent=1).encode()

def ler_backup(conteudo, senha):
    def d(x): return base64.urlsafe_b64decode(x + "=" * (-len(x) % 4))
    try:
        b = json.loads(conteudo)
        assert b.get("formato") == "ragquest-backup-1"
        salt, nonce, ct, tag = d(b["salt"]), d(b["nonce"]), d(b["dados"]), d(b["tag"])
    except Exception:
        raise ValueError("Arquivo de backup inválido.")
    ke, km = _chaves_cripto(senha, salt)
    if not hmac.compare_digest(tag, hmac.new(km, salt + nonce + ct, hashlib.sha256).digest()):
        raise ValueError("Senha incorreta ou arquivo alterado.")
    dados = json.loads(bytes(a ^ b for a, b in zip(ct, _fluxo(ke, nonce, len(ct)))))
    sk = bytes.fromhex(dados["chave_privada"])
    if ed25519.public_key(sk).hex() != dados["chave_publica"]:
        raise ValueError("Backup corrompido.")
    return dados

def restaurar_backup(conteudo, senha):
    dados = ler_backup(conteudo, senha)
    os.makedirs(CHAVES, exist_ok=True)
    if os.path.exists(PRIV):   # guarda a chave atual antes de substituir
        guarda = os.path.join(CHAVES, "substituida_" + time.strftime("%Y%m%d-%H%M%S"))
        os.makedirs(guarda); shutil.copy(PRIV, guarda); shutil.copy(PUB, guarda)
    open(PRIV, "w").write(dados["chave_privada"])
    open(PUB, "w").write(dados["chave_publica"])
    if dados.get("licencas_csv"):
        open(CSV, "w", encoding="utf-8-sig", newline="").write(dados["licencas_csv"])
    return dados

# ---------------------------------------------------------------- instalador
build = {"rodando": False, "log": [], "arquivo": None}

def log(msg):
    build["log"].append(time.strftime("%H:%M:%S ") + msg)

def _baixar(url, dest):
    tmp = dest + ".part"
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as fh:
        total = int(r.headers.get("Content-Length") or 0); lido = 0; ult = 0
        while True:
            b = r.read(1 << 20)
            if not b: break
            fh.write(b); lido += len(b)
            if total and lido * 100 // total >= ult + 20:
                ult = lido * 100 // total; log(f"   {ult}%")
    os.replace(tmp, dest)

def _run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=0x08000000, **kw)
    if r.returncode != 0:
        raise RuntimeError((r.stdout + r.stderr)[-1500:])
    return r

INNO_DIR = os.path.join(BASE, "ferramentas", "InnoSetup")

def _inno():
    """Localiza o compilador do Inno Setup; se não houver, baixa e instala (só para este usuário)."""
    cands = [os.path.join(INNO_DIR, "ISCC.exe"),
             os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
             r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe", r"C:\Program Files\Inno Setup 6\ISCC.exe"]
    for c in cands:
        if os.path.exists(c):
            return c
    log("   baixando o Inno Setup (só na primeira vez)...")
    inst = os.path.join(CACHE, "innosetup.exe")
    ok = False
    try:   # versão oficial publicada no GitHub do Inno Setup
        req = urllib.request.Request("https://api.github.com/repos/jrsoftware/issrc/releases/latest",
                                     headers={"User-Agent": "ragquest-admin", "Accept": "application/vnd.github+json"})
        rel = json.loads(urllib.request.urlopen(req, timeout=30).read())
        url = next(a["browser_download_url"] for a in rel.get("assets", [])
                   if re.fullmatch(r"innosetup-\d+\.\d+\.\d+\.exe", a["name"]))
        _baixar(url, inst)
        ok = open(inst, "rb").read(2) == b"MZ" and os.path.getsize(inst) > 1_000_000
    except Exception as e:
        log(f"   GitHub indisponível ({e}); tentando pelo winget...")
    if ok:
        subprocess.run([inst, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER", "/NOICONS",
                        f"/DIR={INNO_DIR}"], creationflags=0x08000000, timeout=600)
    else:
        subprocess.run(["winget", "install", "-e", "--id", "JRSoftware.InnoSetup", "--scope", "user", "--silent",
                        "--accept-package-agreements", "--accept-source-agreements"],
                       creationflags=0x08000000, timeout=900)
    for c in cands:
        if os.path.exists(c):
            return c
    raise RuntimeError("Não foi possível instalar o Inno Setup. Instale manualmente em jrsoftware.org e gere de novo.")

def gerar_instalador(versao):
    try:
        build.update(rodando=True, log=[], arquivo=None)
        _, pub = chaves()
        open(VERSAO, "w").write(versao)
        pyver = platform.python_version()
        tag = "".join(pyver.split(".")[:2])
        os.makedirs(CACHE, exist_ok=True)

        log(f"1/6 Python embutido {pyver}...")
        emb = os.path.join(CACHE, f"python-{pyver}-embed-amd64.zip")
        if not os.path.exists(emb):
            _baixar(f"https://www.python.org/ftp/python/{pyver}/python-{pyver}-embed-amd64.zip", emb)
        else:
            log("   (em cache)")

        log("2/6 Bibliotecas...")
        req = os.path.join(MODELO, "requirements.txt")
        h = hashlib.sha1((open(req).read() + pyver).encode()).hexdigest()[:8]
        sp = os.path.join(CACHE, f"site-packages-{h}")
        if not os.path.exists(sp):
            _run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--only-binary=:all:",
                  "--target", sp + ".tmp", "-r", req])
            os.replace(sp + ".tmp", sp)
        else:
            log("   (em cache)")

        log("3/6 Montando o Ragquest...")
        shutil.rmtree(BUILD, ignore_errors=True)
        app_dir = os.path.join(BUILD, "Ragquest")
        pydir = os.path.join(app_dir, "python")
        os.makedirs(pydir)
        zipfile.ZipFile(emb).extractall(pydir)
        pth = os.path.join(pydir, f"python{tag}._pth")
        open(pth, "w").write(f"python{tag}.zip\n.\nLib\\site-packages\n..\nimport site\n")
        shutil.copytree(sp, os.path.join(pydir, "Lib", "site-packages"))
        shutil.copytree(os.path.join(MODELO, "app"), os.path.join(app_dir, "app"),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for f in ("iniciar.pyw", "parar.pyw", "_LEIA-ME.txt"):
            shutil.copy(os.path.join(MODELO, f), app_dir)
        open(os.path.join(app_dir, "versao.txt"), "w").write(versao)
        lic = os.path.join(app_dir, "app", "licenca.py")
        s = open(lic, encoding="utf-8").read()
        if "__CHAVE_PUBLICA__" not in s:
            raise RuntimeError("Marcador da chave pública não encontrado em licenca.py")
        open(lic, "w", encoding="utf-8").write(s.replace("__CHAVE_PUBLICA__", pub))
        cfg = os.path.join(app_dir, "app", "config.py")
        s = open(cfg, encoding="utf-8").read()
        open(cfg, "w", encoding="utf-8").write(re.sub(r'VERSAO = "[^"]*"', f'VERSAO = "{versao}"', s))

        log("4/6 Protegendo o código (compilando)...")
        _run([os.path.join(pydir, "python.exe"), "-m", "compileall", "-b", "-q", os.path.join(app_dir, "app")])
        for root, _, files in os.walk(os.path.join(app_dir, "app")):
            for f in files:
                if f.endswith(".py"):
                    os.remove(os.path.join(root, f))
        # teste rápido: o app importa com o Python embutido?
        _run([os.path.join(pydir, "python.exe"), "-c",
              "import app.main, app.licenca as l; assert len(l.CHAVE_PUBLICA)==64; print('ok')"],
             cwd=app_dir, env={**os.environ, "OLLAMA_MODEL": "teste"})
        for lixo in ("config.env", "dados", "skills"):      # nada de configuração do build vai para o cliente
            alvo_l = os.path.join(app_dir, lixo)
            if os.path.isdir(alvo_l): shutil.rmtree(alvo_l, ignore_errors=True)
            elif os.path.exists(alvo_l): os.remove(alvo_l)
        log("   teste de importação OK")

        log("5/6 Preparando o Inno Setup...")
        iscc = _inno()
        log("6/6 Gerando o instalador .exe...")
        os.makedirs(SAIDA, exist_ok=True)
        alvo = os.path.join(SAIDA, f"Ragquest-Instalador-{versao}.exe")
        if os.path.exists(alvo):
            os.remove(alvo)
        _run([iscc, "/Q", f"/DVersao={versao}", f"/DFonte={app_dir}", f"/DSaida={SAIDA}",
              os.path.join(MODELO, "ragquest.iss")])
        if not os.path.exists(alvo):
            raise RuntimeError("O Inno Setup não gerou o instalador.")
        build["arquivo"] = alvo
        log(f"PRONTO: {alvo} ({os.path.getsize(alvo) / 1e6:.0f} MB)")
    except Exception as e:
        log(f"ERRO: {e}")
    finally:
        build["rodando"] = False

# ---------------------------------------------------------------- web
app = FastAPI(title="Ragquest Admin", docs_url=None, redoc_url=None, openapi_url=None)

@app.get("/", include_in_schema=False)
def home():
    return FileResponse(os.path.join(BASE, "admin.html"), headers={"Cache-Control": "no-store"})

@app.get("/favicon.ico", include_in_schema=False)
def ico():
    return FileResponse(os.path.join(MODELO, "app", "static", "ragquest.ico"))

@app.get("/api/status")
def status():
    _, pub = chaves()
    inst = sorted([f for f in os.listdir(SAIDA) if f.endswith(".exe")]) if os.path.isdir(SAIDA) else []
    return {"chave_publica": pub, "impressao": pub[:8].upper() + "-" + pub[-8:].upper(), "pasta_chaves": CHAVES,
            "pasta_saida": SAIDA, "instaladores": inst, "versao": open(VERSAO).read().strip() if os.path.exists(VERSAO) else "1.0.0",
            "total_licencas": len(licencas()),
            "ultimo_backup": open(ULTIMO_BACKUP).read().strip() if os.path.exists(ULTIMO_BACKUP) else None}

class Lic(BaseModel):
    cliente: str
    maquina: str = "*"
    validade: str = ""
    obs: str = ""
    usuarios: int | None = None
    agentes: int | None = None

@app.post("/api/licenca")
def nova_licenca(b: Lic):
    if not b.cliente.strip():
        raise HTTPException(422, "Informe o nome do cliente.")
    try:
        return {"chave": gerar_licenca(b.cliente, b.maquina, b.validade, b.obs, b.usuarios, b.agentes)}
    except ValueError as e:
        raise HTTPException(422, str(e))

@app.get("/api/licencas")
def lista():
    return licencas()

class Build(BaseModel):
    versao: str = "1.0.0"

@app.post("/api/instalador")
def novo_instalador(b: Build):
    if build["rodando"]:
        raise HTTPException(409, "Já existe um instalador sendo gerado.")
    if not re.fullmatch(r"\d+\.\d+\.\d+", b.versao):
        raise HTTPException(422, "Versão no formato 1.0.0")
    threading.Thread(target=gerar_instalador, args=(b.versao,), daemon=True).start()
    return {"ok": True}

@app.get("/api/instalador")
def status_instalador():
    return build

class Senha(BaseModel):
    senha: str

@app.post("/api/backup")
def baixar_backup(b: Senha):
    if len(b.senha) < 10:
        raise HTTPException(422, "Use uma senha de backup com pelo menos 10 caracteres.")
    nome = f"ragquest-chave-mestra-{datetime.date.today():%Y%m%d}.rqbak"
    return Response(gerar_backup(b.senha), media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{nome}"'})

class Restaurar(BaseModel):
    conteudo: str
    senha: str

@app.post("/api/restaurar")
def restaurar(b: Restaurar):
    try:
        d = restaurar_backup(b.conteudo, b.senha)
    except ValueError as e:
        raise HTTPException(422, str(e))
    _, pub = chaves()
    return {"ok": True, "impressao": pub[:8].upper() + "-" + pub[-8:].upper(), "criado_em": d.get("criado_em")}

class ApkIn(BaseModel):
    b64: str

@app.post("/api/apk")
def receber_apk(b: ApkIn):
    """Recebe o APK sem assinatura (compilado pelo GitHub), assina com a chave do Protti e coloca no instalador."""
    try:
        import cryptography  # noqa: F401
    except ImportError:      # a assinatura precisa da biblioteca cryptography (instala uma vez)
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "cryptography"],
                       creationflags=0x08000000, timeout=600, capture_output=True)
    import assinar_apk
    dados = base64.b64decode(b.b64)
    if dados[:2] != b"PK" or len(dados) < 10_000:
        raise HTTPException(422, "Isso não parece um APK.")
    os.makedirs(SAIDA, exist_ok=True)
    cru = os.path.join(SAIDA, "ragquest-sem-assinatura.apk")
    pronto = os.path.join(SAIDA, "Ragquest-Android.apk")
    open(cru, "wb").write(dados)
    senha = open(os.path.join(CHAVES, "android-senha.txt"), encoding="utf-8").read().strip()
    assinar_apk.assinar(cru, pronto, os.path.join(CHAVES, "ragquest-android.jks"), senha)
    shutil.copy(pronto, os.path.join(MODELO, "app", "static", "ragquest.apk"))
    return {"ok": True, "bytes": os.path.getsize(pronto), "sha256": hashlib.sha256(open(pronto, "rb").read()).hexdigest()[:16]}

# ---------------------------------------------------------------- backup do código no GitHub (sem segredos)
_FORA_DIRS = {".venv", "cache", "build", "saida", "chaves", "__pycache__", "dados", "app-android", ".git"}
_FORA_ARQ = {"licencas_emitidas.csv", "ultimo_backup.txt", "android-senha.txt", "ragquest.apk"}
_FORA_EXT = (".key", ".jks", ".rqbak", ".pyc", ".apk", ".exe", ".log")

@app.get("/api/fonte")
def fonte():
    """Arquivos de código agrupados por pasta (para subir no GitHub). Nunca inclui chaves, licenças ou keystore."""
    grupos = {}
    for raiz, dirs, arqs in os.walk(BASE):
        dirs[:] = [d for d in dirs if d not in _FORA_DIRS]
        rel = os.path.relpath(raiz, BASE).replace("\\", "/")
        destino = "admin" if rel == "." else (rel if rel.startswith("modelo") else "admin/" + rel)
        for a in arqs:
            if a in _FORA_ARQ or a.lower().endswith(_FORA_EXT):
                continue
            caminho = os.path.join(raiz, a)
            if os.path.getsize(caminho) > 5_000_000:
                continue
            grupos.setdefault(destino, []).append({"nome": a, "b64": base64.b64encode(open(caminho, "rb").read()).decode()})
    return grupos

@app.get("/api/saida/{nome}")
def arquivo_saida(nome: str):
    caminho = os.path.join(SAIDA, os.path.basename(nome))
    if not os.path.exists(caminho) or not nome.lower().endswith((".exe", ".apk")):
        raise HTTPException(404, "Arquivo não encontrado.")
    return FileResponse(caminho, filename=os.path.basename(nome))

@app.post("/api/abrir/{qual}")
def abrir(qual: str):
    pasta = {"saida": SAIDA, "chaves": CHAVES, "base": BASE}.get(qual)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
        os.startfile(pasta)
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn, webbrowser
    chaves()
    threading.Timer(1.5, lambda: webbrowser.open("http://localhost:8766/")).start()
    uvicorn.run(app, host="127.0.0.1", port=8766, log_level="warning")
