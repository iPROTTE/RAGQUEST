"""Contas de usuário do Ragquest (administrador do cliente e funcionários)."""
import hashlib, hmac, os, re, secrets, time
from . import db, licenca

SESSAO_DIAS = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS usuarios(
  id INTEGER PRIMARY KEY, login TEXT NOT NULL UNIQUE COLLATE NOCASE, nome TEXT NOT NULL,
  senha TEXT NOT NULL, papel TEXT NOT NULL DEFAULT 'usuario', ativo INTEGER NOT NULL DEFAULT 1,
  criado_em TEXT DEFAULT CURRENT_TIMESTAMP, ultimo_acesso TEXT);
CREATE TABLE IF NOT EXISTS sessoes(
  token TEXT PRIMARY KEY, usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE, expira REAL NOT NULL);
"""

def init():
    with db.conn() as c:
        c.executescript(SCHEMA)

# ---------------------------------------------------------------- senhas
def _hash(senha, salt=None):
    salt = salt or secrets.token_bytes(16)
    h = hashlib.scrypt(senha.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"

def _confere(senha, guardado):
    try:
        _, salt, h = guardado.split("$")
        return hmac.compare_digest(_hash(senha, bytes.fromhex(salt)).split("$")[2], h)
    except Exception:
        return False

def validar_senha(senha):
    if len(senha or "") < 6 or any(ch.isspace() for ch in senha):
        raise ValueError("A senha precisa ter pelo menos 6 caracteres e não pode ter espaços.")

def validar_login(login):
    login = (login or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9._-]{3,40}", login):
        raise ValueError("Login: 3 a 40 caracteres, só letras sem acento, números, ponto, hífen ou sublinhado.")
    return login

# ---------------------------------------------------------------- consultas
CAMPOS = "id, login, nome, papel, ativo, criado_em, ultimo_acesso"

def _dict(r):
    return dict(zip(["id", "login", "nome", "papel", "ativo", "criado_em", "ultimo_acesso"], r)) if r else None

def total():
    with db.conn() as c:
        return c.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]

def ativos():
    with db.conn() as c:
        return c.execute("SELECT COUNT(*) FROM usuarios WHERE ativo=1").fetchone()[0]

def listar():
    with db.conn() as c:
        return [_dict(r) for r in c.execute(f"SELECT {CAMPOS} FROM usuarios ORDER BY papel, nome")]

def obter(uid):
    with db.conn() as c:
        return _dict(c.execute(f"SELECT {CAMPOS} FROM usuarios WHERE id=?", (uid,)).fetchone())

def limite():
    """Máximo de usuários ativos permitido pela licença (None = sem limite)."""
    u = licenca.estado().get("usuarios")
    return int(u) if u else None

def _checar_limite(extra=1):
    lim = limite()
    if lim is not None and ativos() + extra > lim:
        raise ValueError(f"A licença permite até {lim} usuário(s) ativo(s). Desative alguém ou peça ao fornecedor para ampliar a licença.")

def _admins_ativos(c, exceto=None):
    return c.execute("SELECT COUNT(*) FROM usuarios WHERE papel='admin' AND ativo=1 AND id!=?", (exceto or 0,)).fetchone()[0]

# ---------------------------------------------------------------- alterações
def criar(nome, login, senha, papel="usuario"):
    nome = (nome or "").strip()
    if len(nome) < 2:
        raise ValueError("Informe o nome.")
    login = validar_login(login)
    validar_senha(senha)
    if papel not in ("admin", "usuario"):
        raise ValueError("Papel inválido.")
    _checar_limite()
    with db.lock, db.conn() as c:
        if c.execute("SELECT 1 FROM usuarios WHERE login=?", (login,)).fetchone():
            raise ValueError("Já existe um usuário com esse login.")
        uid = c.execute("INSERT INTO usuarios(login,nome,senha,papel) VALUES(?,?,?,?)",
                        (login, nome, _hash(senha), papel)).lastrowid
    return obter(uid)

def alterar(uid, nome=None, papel=None, ativo=None, senha=None):
    u = obter(uid)
    if not u:
        raise ValueError("Usuário não encontrado.")
    if ativo and not u["ativo"]:
        _checar_limite()
    with db.lock, db.conn() as c:
        if (papel == "usuario" or ativo is False) and u["papel"] == "admin" and _admins_ativos(c, uid) == 0:
            raise ValueError("É preciso manter pelo menos um administrador ativo.")
        if nome is not None:
            if len(nome.strip()) < 2: raise ValueError("Informe o nome.")
            c.execute("UPDATE usuarios SET nome=? WHERE id=?", (nome.strip(), uid))
        if papel is not None:
            if papel not in ("admin", "usuario"): raise ValueError("Papel inválido.")
            c.execute("UPDATE usuarios SET papel=? WHERE id=?", (papel, uid))
        if ativo is not None:
            c.execute("UPDATE usuarios SET ativo=? WHERE id=?", (1 if ativo else 0, uid))
            if not ativo:
                c.execute("DELETE FROM sessoes WHERE usuario_id=?", (uid,))
        if senha is not None:
            validar_senha(senha)
            c.execute("UPDATE usuarios SET senha=? WHERE id=?", (_hash(senha), uid))
            c.execute("DELETE FROM sessoes WHERE usuario_id=?", (uid,))
    return obter(uid)

def excluir(uid):
    u = obter(uid)
    if not u:
        return
    with db.lock, db.conn() as c:
        if u["papel"] == "admin" and _admins_ativos(c, uid) == 0:
            raise ValueError("É preciso manter pelo menos um administrador ativo.")
        c.execute("DELETE FROM sessoes WHERE usuario_id=?", (uid,))
        c.execute("DELETE FROM usuarios WHERE id=?", (uid,))

# ---------------------------------------------------------------- sessões
def entrar(login, senha):
    with db.conn() as c:
        r = c.execute("SELECT id, senha, ativo FROM usuarios WHERE login=?", ((login or "").strip().lower(),)).fetchone()
    if not r or not _confere(senha or "", r[1]):
        time.sleep(0.6)                      # dificulta tentativas em massa
        raise ValueError("Login ou senha incorretos.")
    if not r[2]:
        raise ValueError("Este usuário está desativado. Fale com o administrador.")
    token = secrets.token_urlsafe(32)
    with db.lock, db.conn() as c:
        c.execute("DELETE FROM sessoes WHERE expira < ?", (time.time(),))
        c.execute("INSERT INTO sessoes(token, usuario_id, expira) VALUES(?,?,?)", (token, r[0], time.time() + SESSAO_DIAS * 86400))
        c.execute("UPDATE usuarios SET ultimo_acesso=datetime('now','localtime') WHERE id=?", (r[0],))
    return token, obter(r[0])

def sair(token):
    with db.lock, db.conn() as c:
        c.execute("DELETE FROM sessoes WHERE token=?", (token,))

def por_token(token):
    if not token:
        return None
    with db.conn() as c:
        r = c.execute("""SELECT u.id FROM sessoes s JOIN usuarios u ON u.id=s.usuario_id
                         WHERE s.token=? AND s.expira>? AND u.ativo=1""", (token, time.time())).fetchone()
    return obter(r[0]) if r else None

def trocar_propria_senha(uid, atual, nova):
    with db.conn() as c:
        r = c.execute("SELECT senha FROM usuarios WHERE id=?", (uid,)).fetchone()
    if not r or not _confere(atual or "", r[0]):
        raise ValueError("Senha atual incorreta.")
    validar_senha(nova)
    with db.lock, db.conn() as c:
        c.execute("UPDATE usuarios SET senha=? WHERE id=?", (_hash(nova), uid))
