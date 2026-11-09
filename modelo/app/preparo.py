"""Primeira execução: baixa os modelos de IA pelo Ollama mostrando o progresso na tela."""
import json, threading, httpx
from . import config

estado = {"baixando": False, "modelo": None, "completo": 0, "total": 0, "fase": "", "erro": None}
_lock = threading.Lock()

def _nome(m):
    return m if ":" in m else m + ":latest"

def modelos_instalados():
    r = httpx.get(config.OLLAMA_URL + "/api/tags", timeout=3)
    r.raise_for_status()
    return {_nome(m["name"]) for m in r.json().get("models", [])}

def faltando():
    inst = modelos_instalados()
    return [m for m in (config.EMBED_MODEL, config.CHAT_MODEL) if _nome(m) not in inst]

def pronto():
    try:
        return not faltando()
    except Exception:
        return False

def _baixar():
    try:
        for m in faltando():
            estado.update(modelo=m, completo=0, total=0, fase="iniciando", erro=None)
            with httpx.stream("POST", config.OLLAMA_URL + "/api/pull", json={"model": m, "stream": True}, timeout=None) as r:
                r.raise_for_status()
                for linha in r.iter_lines():
                    if not linha:
                        continue
                    d = json.loads(linha)
                    if d.get("error"):
                        raise RuntimeError(d["error"])
                    estado["fase"] = d.get("status", "")
                    if d.get("total"):
                        estado["total"] = d["total"]; estado["completo"] = d.get("completed", 0)
    except Exception as e:
        estado["erro"] = f"{type(e).__name__}: {e}"
    finally:
        estado["baixando"] = False

def iniciar():
    with _lock:
        if estado["baixando"]:
            return
        estado.update(baixando=True, erro=None)
        threading.Thread(target=_baixar, daemon=True).start()

def status():
    try:
        falta = faltando(); ollama = True
    except Exception:
        falta = [config.EMBED_MODEL, config.CHAT_MODEL]; ollama = False
    return {"ollama": ollama, "pronto": ollama and not falta, "faltando": falta, "modelo_chat": config.CHAT_MODEL, **estado}
