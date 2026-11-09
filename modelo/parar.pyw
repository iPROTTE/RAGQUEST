"""Desliga o Ragquest (atalho 'Parar Ragquest')."""
import os, http.client
porta = 8765
try:
    for linha in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.env"), encoding="utf-8-sig"):
        if linha.strip().startswith("PORTA="):
            porta = int(linha.split("=", 1)[1].strip())
except Exception:
    pass
try:
    c = http.client.HTTPConnection("127.0.0.1", porta, timeout=3)
    c.request("POST", "/desligar"); c.getresponse()
except Exception:
    pass
