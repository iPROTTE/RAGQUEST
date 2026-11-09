import os, shutil, ctypes
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _load():
    p = os.path.join(BASE, "config.env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8-sig"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
_load()

VERSAO = "1.0.0"
PORTA = int(os.environ.get("PORTA", "8765"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
def _ram_gb():
    try:
        class M(ctypes.Structure):
            _fields_ = [("l", ctypes.c_ulong), ("m", ctypes.c_ulong), ("t", ctypes.c_ulonglong), ("a", ctypes.c_ulonglong),
                        ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong), ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
        m = M(); m.l = ctypes.sizeof(M)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.t / 2**30
    except Exception:
        return 8

def _escolher_modelo():
    """Com placa NVIDIA e 12 GB+ de RAM usa o modelo 7b; senão o 3b (mais leve)."""
    nvidia = bool(shutil.which("nvidia-smi")) or os.path.exists(r"C:\Windows\System32\nvidia-smi.exe")
    m = "qwen2.5:7b" if nvidia and _ram_gb() >= 12 else "qwen2.5:3b"
    try:   # registra no config.env para ficar visível/editável
        with open(os.path.join(BASE, "config.env"), "a", encoding="utf-8") as fh:
            fh.write(f"\nOLLAMA_MODEL={m}\n")
    except Exception:
        pass
    return m

CHAT_MODEL = os.environ.get("OLLAMA_MODEL") or _escolher_modelo()
EMBED_MODEL = os.environ.get("EMBED_MODEL", "bge-m3")
DADOS = os.path.join(BASE, "dados")
DB_PATH = os.path.join(DADOS, "ragquest.db")
RECRAWL_HOUR = int(os.environ.get("RECRAWL_HOUR", "3"))
KNOWLEDGE_DIR = os.path.join(BASE, os.environ.get("PASTA_CONHECIMENTO", "conhecimento"))
TRASH_DIR = os.path.join(KNOWLEDGE_DIR, "_lixeira")
SCAN_SECONDS = int(os.environ.get("SCAN_SEGUNDOS", "30"))
WEB_FALLBACK = os.environ.get("BUSCA_WEB", "1") == "1"
MIN_SIM = float(os.environ.get("SIMILARIDADE_MINIMA", "0.35"))
