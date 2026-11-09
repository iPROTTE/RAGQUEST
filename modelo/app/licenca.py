"""Licença do Ragquest: chave assinada (Ed25519) vinculada à máquina e com validade."""
import base64, datetime, hashlib, json, os, time
from . import ed25519
from .config import DADOS

CHAVE_PUBLICA = "__CHAVE_PUBLICA__"   # substituída pelo Ragquest Admin ao gerar o instalador
ARQ = os.path.join(DADOS, "licenca.txt")
MARCA = os.path.join(DADOS, ".lc")
_cache = {"t": 0, "v": None}

def codigo_maquina():
    guid = ""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                           winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
        guid = winreg.QueryValueEx(k, "MachineGuid")[0]
    except Exception:
        import uuid; guid = str(uuid.getnode())
    h = hashlib.sha256(("ragquest:" + guid).encode()).hexdigest().upper()
    return f"{h[0:4]}-{h[4:8]}-{h[8:12]}"

def _b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

def decodificar(chave):
    """Valida assinatura e máquina/validade. Retorna (ok, dados|motivo)."""
    try:
        chave = "".join(chave.split())
        if chave.upper().startswith("RAGQUEST-"): chave = chave[len("RAGQUEST-"):]
        corpo, assin = chave.split(".")
        payload = _b64d(corpo)
        if not ed25519.verify(bytes.fromhex(CHAVE_PUBLICA), payload, _b64d(assin)):
            return False, "Chave de licença inválida."
        dados = json.loads(payload)
    except Exception:
        return False, "Chave de licença inválida."
    if dados.get("m") not in ("*", codigo_maquina()):
        return False, "Esta licença é de outro computador."
    hoje = datetime.date.today()
    try:   # proteção simples contra voltar o relógio
        ultimo = datetime.date.fromisoformat(open(MARCA).read().strip())
        if hoje < ultimo - datetime.timedelta(days=1):
            return False, "Data do computador inconsistente. Ajuste o relógio."
    except Exception:
        pass
    if dados.get("e") and hoje > datetime.date.fromisoformat(dados["e"]):
        return False, f"Licença expirada em {datetime.date.fromisoformat(dados['e']):%d/%m/%Y}."
    return True, dados

def estado(forcar=False):
    if not forcar and _cache["v"] and time.time() - _cache["t"] < 60:
        return _cache["v"]
    st = {"valida": False, "codigo_maquina": codigo_maquina(), "motivo": "Ragquest ainda não foi ativado."}
    if os.path.exists(ARQ):
        ok, r = decodificar(open(ARQ, encoding="utf-8").read())
        if ok:
            st = {"valida": True, "codigo_maquina": st["codigo_maquina"], "cliente": r.get("c"),
                  "validade": r.get("e"), "usuarios": r.get("u"), "agentes": r.get("a"), "motivo": ""}
            try:
                os.makedirs(DADOS, exist_ok=True)
                open(MARCA, "w").write(datetime.date.today().isoformat())
            except Exception:
                pass
        else:
            st["motivo"] = r
    _cache.update(t=time.time(), v=st)
    return st

def ativar(chave):
    ok, r = decodificar(chave)
    if not ok:
        return False, r
    os.makedirs(DADOS, exist_ok=True)
    with open(ARQ, "w", encoding="utf-8") as fh:
        fh.write("".join(chave.split()))
    return True, estado(forcar=True)

def valida():
    return estado()["valida"]
