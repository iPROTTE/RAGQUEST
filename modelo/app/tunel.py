"""Acesso externo (pela internet) via Cloudflare Tunnel.

O servidor abre uma conexão de SAÍDA até a Cloudflare, então funciona atrás de CGNAT,
sem abrir portas no roteador e já com HTTPS.
  - modo "rapido": endereço aleatório *.trycloudflare.com (sem conta; muda ao reiniciar)
  - modo "fixo":   túnel criado no painel da Cloudflare (token) com o domínio da empresa
"""
import os, re, subprocess, threading, time, urllib.request, collections
from . import config, rede

URL_EXE = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
EXE = os.path.join(config.BASE, "bin", "cloudflared.exe")
NT = os.name == "nt"

_lk = threading.Lock()
_proc = None
_st = {"baixando": False, "conectado": False, "endereco": "", "erro": "", "desde": 0}
_log = collections.deque(maxlen=40)
_parar = threading.Event()
_job = None

def cfg():
    return {"ativo": os.environ.get("TUNEL_ATIVO", "0") == "1",
            "modo": os.environ.get("TUNEL_MODO", "rapido"),
            "token": os.environ.get("TUNEL_TOKEN", ""),
            "endereco": os.environ.get("TUNEL_ENDERECO", "")}

def endereco():
    """Endereço externo atual (com / no final) ou ''."""
    c = cfg()
    if not c["ativo"]:
        return ""
    e = c["endereco"] if c["modo"] == "fixo" else _st["endereco"]
    if not e:
        return ""
    if not re.match(r"(?i)^https?://", e):
        e = "https://" + e
    return e.rstrip("/") + "/"

# ---------------------------------------------------------------- processo filho morre junto com o Ragquest
def _job_object():
    """Job do Windows com KILL_ON_JOB_CLOSE: se o Ragquest fechar (mesmo à força), o túnel fecha junto."""
    global _job
    if _job or not NT:
        return _job
    try:
        import ctypes
        from ctypes import wintypes
        k = ctypes.windll.kernel32
        k.CreateJobObjectW.restype = wintypes.HANDLE
        h = k.CreateJobObjectW(None, None)
        class BASIC(ctypes.Structure):
            _fields_ = [("a", ctypes.c_int64), ("b", ctypes.c_int64), ("LimitFlags", wintypes.DWORD),
                        ("c", ctypes.c_size_t), ("d", ctypes.c_size_t), ("e", wintypes.DWORD),
                        ("f", ctypes.c_size_t), ("g", wintypes.DWORD), ("h", wintypes.DWORD)]
        class IOC(ctypes.Structure):
            _fields_ = [("x", ctypes.c_uint64 * 6)]
        class EXT(ctypes.Structure):
            _fields_ = [("Basic", BASIC), ("Io", IOC), ("p", ctypes.c_size_t), ("j", ctypes.c_size_t),
                        ("pp", ctypes.c_size_t), ("pj", ctypes.c_size_t)]
        info = EXT(); info.Basic.LimitFlags = 0x2000   # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        k.SetInformationJobObject(wintypes.HANDLE(h), 9, ctypes.byref(info), ctypes.sizeof(info))
        _job = h
    except Exception:
        _job = None
    return _job

def _prender_ao_job(p):
    h = _job_object()
    if not h:
        return
    try:
        import ctypes
        from ctypes import wintypes
        ctypes.windll.kernel32.AssignProcessToJobObject(wintypes.HANDLE(h), wintypes.HANDLE(int(p._handle)))
    except Exception:
        pass

# ---------------------------------------------------------------- download do cloudflared
def instalado():
    return os.path.exists(EXE) and os.path.getsize(EXE) > 5_000_000

def _baixar():
    os.makedirs(os.path.dirname(EXE), exist_ok=True)
    tmp = EXE + ".part"
    _st["baixando"] = True
    try:
        req = urllib.request.Request(URL_EXE, headers={"User-Agent": "Ragquest"})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as fh:
            while True:
                b = r.read(1 << 16)
                if not b:
                    break
                fh.write(b)
        with open(tmp, "rb") as fh:
            if fh.read(2) != b"MZ" or os.path.getsize(tmp) < 5_000_000:
                raise RuntimeError("arquivo baixado inválido")
        os.replace(tmp, EXE)
    finally:
        _st["baixando"] = False
        if os.path.exists(tmp):
            try: os.remove(tmp)
            except Exception: pass

# ---------------------------------------------------------------- execução
def _comando(c):
    base = [EXE, "tunnel", "--no-autoupdate"]
    if c["modo"] == "fixo":
        return base + ["run", "--token", c["token"]]
    return base + ["--url", f"http://127.0.0.1:{config.PORTA}"]

def _ler_saida(p):
    for linha in iter(p.stdout.readline, b""):
        t = linha.decode("utf-8", "replace").strip()
        if not t:
            continue
        t = re.sub(r"(--token\s+)\S+", r"\1***", t)
        _log.append(t)
        m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", t)
        if m and "api.trycloudflare" not in m.group(0):
            _st["endereco"] = m.group(0)
        if "Registered tunnel connection" in t or "Connection registered" in t:
            _st["conectado"] = True; _st["erro"] = ""
        if "ERR" in t and ("Unauthorized" in t or "invalid" in t.lower() and "token" in t.lower()):
            _st["erro"] = "Token recusado pela Cloudflare. Confira o token do túnel."

def _supervisor():
    global _proc
    espera = 3
    while not _parar.is_set():
        c = cfg()
        if not c["ativo"]:
            break
        try:
            if not instalado():
                _log.append("Baixando o cloudflared (conector da Cloudflare)...")
                _baixar()
            if c["modo"] == "fixo" and not c["token"]:
                _st["erro"] = "Informe o token do túnel."; break
            kw = {}
            if NT:
                si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW; si.wShowWindow = 0
                kw = {"creationflags": 0x08000000 | 0x00000200, "startupinfo": si}
            _st.update(conectado=False, endereco="" if c["modo"] == "rapido" else _st["endereco"], desde=time.time())
            with _lk:
                _proc = subprocess.Popen(_comando(c), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, close_fds=True, **kw)
                _prender_ao_job(_proc)
            threading.Thread(target=_ler_saida, args=(_proc,), daemon=True).start()
            inicio = time.time()
            _proc.wait()
            _st["conectado"] = False
            if _parar.is_set():
                break
            espera = 3 if time.time() - inicio > 60 else min(espera * 2, 120)
            _log.append(f"Conector parou; tentando de novo em {espera}s.")
        except Exception as e:
            _st["erro"] = f"Não consegui iniciar o acesso externo: {e}"
            espera = min(espera * 2, 120)
        _parar.wait(espera)

def iniciar():
    """Sobe o túnel (se estiver ligado no config.env). Pode ser chamado de novo após mudar a configuração."""
    parar()
    _parar.clear()
    _st["erro"] = ""
    if cfg()["ativo"]:
        threading.Thread(target=_supervisor, daemon=True).start()

def parar():
    global _proc
    _parar.set()
    with _lk:
        p, _proc = _proc, None
    if p and p.poll() is None:
        try:
            p.terminate(); p.wait(5)
        except Exception:
            try: p.kill()
            except Exception: pass
    _st.update(conectado=False)

def configurar(ativo=None, modo=None, token=None, endereco_fixo=None):
    if modo in ("rapido", "fixo"):
        rede._gravar_cfg("TUNEL_MODO", modo)
    if token is not None:
        t = token.strip()
        m = re.search(r"eyJ[A-Za-z0-9_\-=]{40,}", t)      # aceita o comando inteiro colado do painel
        rede._gravar_cfg("TUNEL_TOKEN", m.group(0) if m else t)
    if endereco_fixo is not None:
        e = re.sub(r"(?i)^https?://", "", endereco_fixo.strip()).strip("/")
        rede._gravar_cfg("TUNEL_ENDERECO", e)
    if ativo is not None:
        rede._gravar_cfg("TUNEL_ATIVO", "1" if ativo else "0")
    iniciar()

def status():
    c = cfg()
    return {"ativo": c["ativo"], "modo": c["modo"], "tem_token": bool(c["token"]),
            "endereco_fixo": c["endereco"], "endereco": endereco(), "conectado": _st["conectado"],
            "baixando": _st["baixando"], "instalado": instalado(), "erro": _st["erro"],
            "log": list(_log)[-8:], "windows": NT}
