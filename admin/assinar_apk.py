"""Assina um APK (Android APK Signature Scheme v2) com a chave do Ragquest.

Uso: python assinar_apk.py entrada.apk saida.apk chave.jks senha
A chave (.jks/PKCS12) fica só com o Protti; o GitHub compila o APK sem assinatura.
"""
import hashlib, struct, sys
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import pkcs12

V2_ID = 0x7109871A
ALG_RSA_PKCS1_SHA256 = 0x0103
MAGIC = b"APK Sig Block 42"
CHUNK = 1024 * 1024

def lp(b):                                   # prefixo de tamanho uint32
    return struct.pack("<I", len(b)) + b

def seq(itens):
    return lp(b"".join(lp(i) for i in itens))

def _eocd(dados):
    for i in range(len(dados) - 22, max(-1, len(dados) - 22 - 65536), -1):
        if dados[i:i + 4] == b"PK\x05\x06":
            return i
    raise ValueError("Arquivo não é um ZIP/APK válido.")

def _digest(secoes):
    pedacos = []
    for s in secoes:
        for i in range(0, len(s), CHUNK):
            c = s[i:i + CHUNK]
            pedacos.append(hashlib.sha256(b"\xa5" + struct.pack("<I", len(c)) + c).digest())
    return hashlib.sha256(b"\x5a" + struct.pack("<I", len(pedacos)) + b"".join(pedacos)).digest()

def assinar(entrada, saida, jks, senha):
    dados = open(entrada, "rb").read()
    e = _eocd(dados)
    cd_tam, cd_off = struct.unpack("<II", dados[e + 12:e + 20])
    if dados[cd_off - 16:cd_off] == MAGIC:
        raise ValueError("O APK já está assinado.")
    zip_entradas, cd, eocd = dados[:cd_off], dados[cd_off:cd_off + cd_tam], dados[e:]

    chave, cert, _ = pkcs12.load_key_and_certificates(open(jks, "rb").read(), senha.encode())
    cert_der = cert.public_bytes(serialization.Encoding.DER)
    pub_der = chave.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)

    dig = _digest([zip_entradas, cd, eocd])
    signed_data = (seq([struct.pack("<I", ALG_RSA_PKCS1_SHA256) + lp(dig)])
                   + seq([cert_der])
                   + seq([]))
    assinatura = chave.sign(signed_data, padding.PKCS1v15(), hashes.SHA256())
    signer = lp(signed_data) + seq([struct.pack("<I", ALG_RSA_PKCS1_SHA256) + lp(assinatura)]) + lp(pub_der)
    valor = seq([signer])

    par = struct.pack("<Q", 4 + len(valor)) + struct.pack("<I", V2_ID) + valor
    tam = len(par) + 8 + 16
    bloco = struct.pack("<Q", tam) + par + struct.pack("<Q", tam) + MAGIC

    novo_eocd = bytearray(eocd)
    struct.pack_into("<I", novo_eocd, 16, cd_off + len(bloco))
    with open(saida, "wb") as fh:
        fh.write(zip_entradas + bloco + cd + bytes(novo_eocd))

if __name__ == "__main__":
    assinar(*sys.argv[1:5])
    print("APK assinado:", sys.argv[2])
