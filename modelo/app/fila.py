"""Fila única de tarefas em segundo plano (resumos, memória, skills), uma de cada vez,
para não disputar a placa de vídeo com as respostas ao usuário."""
import queue, threading, traceback

_q = queue.Queue()
_pendentes = set()
_lock = threading.Lock()
_iniciada = False

def adicionar(chave, fn, *args):
    """Agenda fn(*args). Tarefas com a mesma chave ainda na fila não se repetem."""
    with _lock:
        if chave in _pendentes:
            return
        _pendentes.add(chave)
    _q.put((chave, fn, args))

def pendentes(prefixo=""):
    with _lock:
        return sum(1 for k in _pendentes if str(k[0] if isinstance(k, tuple) else k).startswith(prefixo))

def _trabalhar():
    while True:
        chave, fn, args = _q.get()
        try:
            fn(*args)
        except Exception:
            traceback.print_exc()
        finally:
            with _lock:
                _pendentes.discard(chave)

def iniciar():
    global _iniciada
    if not _iniciada:
        _iniciada = True
        threading.Thread(target=_trabalhar, daemon=True).start()
