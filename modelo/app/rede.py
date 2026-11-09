"""Modo servidor: acesso pela rede, endereços, QR code, firewall e início com o Windows."""
import ipaddress, os, re, socket, subprocess, sys, threading, time
from . import config

REGRA = "Ragquest"
NT = os.name == "nt"
SEM_JANELA = 0x08000000
PYTHONW = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
INICIAR = os.path.join(config.BASE, "iniciar.pyw")
CFG = os.path.join(config.BASE, "config.env")

def ativo():
    return os.environ.get("ACESSO_REDE", "0") == "1"

# ---------------------------------------------------------------- endereços
def _ips():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except Exception:
        pass
    try:   # IP da interface que sai para a rede (não envia nada)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ips.add(s.getsockname()[0])
    except Exception:
        pass
    return ips

def enderecos():
    out = []
    for ip in _ips():
        a = ipaddress.ip_address(ip)
        if a.is_loopback or a.is_link_local:
            continue
        if a in ipaddress.ip_network("100.64.0.0/10"):
            tipo, ordem = "Tailscale (acesso de fora da empresa)", 1
        elif a.is_private:
            tipo, ordem = "Rede local / Wi-Fi da empresa", 0
        else:
            tipo, ordem = "Outro", 2
        out.append({"url": f"http://{ip}:{config.PORTA}/", "tipo": tipo, "ordem": ordem, "ip": ip})
    out.sort(key=lambda e: (e["ordem"], [int(p) for p in e["ip"].split(".")]))
    nome = socket.gethostname()
    if nome:
        out.append({"url": f"http://{nome.lower()}:{config.PORTA}/", "tipo": "Nome do computador (só computadores Windows da rede)", "ordem": 3, "ip": ""})
    return out

# ---------------------------------------------------------------- QR code
def qr_svg(texto):
    import qrcode
    q = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(texto)
    q.make(fit=True)
    m = q.get_matrix()
    n = len(m)
    caminho = "".join(f"M{x},{y}h1v1h-1z" for y, linha in enumerate(m) for x, v in enumerate(linha) if v)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" shape-rendering="crispEdges">'
            f'<rect width="{n}" height="{n}" fill="#fff"/><path d="{caminho}" fill="#000"/></svg>')

# ---------------------------------------------------------------- firewall do Windows
def firewall_ok():
    """True/False no Windows; None quando não dá para saber (outro sistema)."""
    if not NT:
        return None
    try:
        r = subprocess.run(["netsh", "advfirewall", "firewall", "show", "rule", f"name={REGRA}"],
                           capture_output=True, creationflags=SEM_JANELA, timeout=15)
        return r.returncode == 0
    except Exception:
        return None

def _executar_como_admin(exe, params):
    """Abre o pedido de permissão do Windows (UAC) e espera terminar. Devolve True se rodou."""
    import ctypes
    from ctypes import wintypes
    class SEI(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]
    sei = SEI(cbSize=ctypes.sizeof(SEI), fMask=0x00000040, lpVerb="runas", lpFile=exe, lpParameters=params, nShow=0)
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)):
        return False                      # usuário recusou o pedido de permissão
    if sei.hProcess:
        ctypes.windll.kernel32.WaitForSingleObject(sei.hProcess, 60000)
        ctypes.windll.kernel32.CloseHandle(sei.hProcess)
    return True

def liberar_firewall():
    if not NT or firewall_ok():
        return True
    params = (f'advfirewall firewall add rule name="{REGRA}" dir=in action=allow protocol=TCP '
              f'localport={config.PORTA} program="{PYTHONW}" profile=any '
              f'description="Acesso dos funcionarios ao Ragquest (login e senha obrigatorios)"')
    _executar_como_admin("netsh.exe", params)
    return bool(firewall_ok())

# ---------------------------------------------------------------- iniciar com o Windows
_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"

def inicia_com_windows():
    if not NT:
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN) as k:
            winreg.QueryValueEx(k, "Ragquest")
        return True
    except OSError:
        return False

def definir_inicio(ligar):
    if not NT:
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN, 0, winreg.KEY_SET_VALUE) as k:
        if ligar:
            winreg.SetValueEx(k, "Ragquest", 0, winreg.REG_SZ, f'"{PYTHONW}" "{INICIAR}" --sem-navegador')
        else:
            try: winreg.DeleteValue(k, "Ragquest")
            except OSError: pass

# ---------------------------------------------------------------- aplicar
def _gravar_cfg(chave, valor):
    linhas = open(CFG, encoding="utf-8-sig").read().splitlines() if os.path.exists(CFG) else []
    achou = False
    for i, l in enumerate(linhas):
        if re.match(rf"\s*{chave}\s*=", l):
            linhas[i] = f"{chave}={valor}"; achou = True
    if not achou:
        linhas.append(f"{chave}={valor}")
    with open(CFG, "w", encoding="utf-8") as fh:
        fh.write("\n".join(linhas) + "\n")
    os.environ[chave] = valor

def reiniciar():
    """Sobe um novo Ragquest (que espera este fechar) e encerra o atual."""
    if NT and os.path.exists(PYTHONW):
        subprocess.Popen([PYTHONW, INICIAR, "--sem-navegador", "--reiniciar"], cwd=config.BASE,
                         creationflags=SEM_JANELA | 0x00000200, close_fds=True)
    threading.Timer(1.0, lambda: os._exit(0)).start()

def status():
    return {"ativo": ativo(), "porta": config.PORTA, "enderecos": enderecos() if ativo() else [],
            "firewall": firewall_ok() if ativo() else None, "inicia_com_windows": inicia_com_windows(),
            "windows": NT}
