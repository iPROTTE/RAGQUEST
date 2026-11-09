"""Inicia o Ragquest em segundo plano e abre o navegador."""
import os, sys, time, socket, threading, subprocess, webbrowser
BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
if BASE not in sys.path:
    sys.path.insert(0, BASE)
os.makedirs(os.path.join(BASE, "dados"), exist_ok=True)
_log = open(os.path.join(BASE, "dados", "ragquest.log"), "a", encoding="utf-8", buffering=1)
sys.stdout = sys.stderr = _log
print(f"\n=== Ragquest iniciando {time.strftime('%d/%m/%Y %H:%M:%S')} ===")

from app import config
SEM_NAVEGADOR = "--sem-navegador" in sys.argv     # usado ao iniciar com o Windows e ao reiniciar
URL = f"http://localhost:{config.PORTA}/"

def porta_ativa():
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", config.PORTA)) == 0

def ollama_ok():
    with socket.socket() as s:
        s.settimeout(1.5)
        return s.connect_ex(("127.0.0.1", 11434)) == 0

if "--reiniciar" in sys.argv:          # espera o Ragquest anterior fechar
    for _ in range(40):
        if not porta_ativa(): break
        time.sleep(0.5)
    time.sleep(1)

if porta_ativa():                      # já está rodando: só abre o navegador
    if not SEM_NAVEGADOR:
        webbrowser.open(URL)
    sys.exit(0)

if not ollama_ok():   # liga o motor de IA em segundo plano, sem abrir janela nenhuma
    oll = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe")
    if os.path.exists(oll):
        # CREATE_NO_WINDOW + novo grupo (NUNCA DETACHED_PROCESS: com ele o Windows ignora o NO_WINDOW
        # e cada vez que o Ollama carrega o modelo abre uma tela preta de terminal)
        si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW; si.wShowWindow = 0
        amb = dict(os.environ, OLLAMA_KEEP_ALIVE="30m")
        subprocess.Popen([oll, "serve"], creationflags=0x08000000 | 0x00000200, startupinfo=si, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=amb)
    for _ in range(60):
        if ollama_ok(): break
        time.sleep(1)

def abrir():
    for _ in range(120):
        if porta_ativa():
            webbrowser.open(URL); return
        time.sleep(0.5)
if not SEM_NAVEGADOR:
    threading.Thread(target=abrir, daemon=True).start()

# ACESSO_REDE=1 libera o acesso de outros computadores/celulares da rede (todos entram com login e senha)
host = "0.0.0.0" if os.environ.get("ACESSO_REDE", "0") == "1" else "127.0.0.1"
print(f"Escutando em {host}:{config.PORTA}")

import uvicorn
uvicorn.run("app.main:app", host=host, port=config.PORTA, log_level="info")
