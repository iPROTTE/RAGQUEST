"""Conversas salvas por usuário (histórico, título e resumo de cada conversa)."""
import json
from . import db

MAX_CONVERSAS = 60          # por usuário; as mais antigas são apagadas
RESUMIR_A_CADA = 4          # mensagens (2 trocas) entre resumos

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversas(
  id INTEGER PRIMARY KEY, login TEXT NOT NULL, titulo TEXT NOT NULL, resumo TEXT,
  criada TEXT DEFAULT (datetime('now','localtime')), atualizada TEXT DEFAULT (datetime('now','localtime')),
  n_msgs INTEGER NOT NULL DEFAULT 0, resumo_n INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS conv_login ON conversas(login, atualizada);
CREATE TABLE IF NOT EXISTS mensagens(
  id INTEGER PRIMARY KEY, conversa_id INTEGER NOT NULL REFERENCES conversas(id) ON DELETE CASCADE,
  papel TEXT NOT NULL, conteudo TEXT NOT NULL, fontes TEXT, origem TEXT,
  criada TEXT DEFAULT (datetime('now','localtime')));
CREATE INDEX IF NOT EXISTS msg_conv ON mensagens(conversa_id);
"""

def init():
    with db.conn() as c:
        c.executescript(SCHEMA)

def criar(login, titulo, agente=None):
    titulo = " ".join((titulo or "Nova conversa").split())
    if len(titulo) > 60:
        titulo = titulo[:57].rstrip() + "..."
    with db.lock, db.conn() as c:
        cid = c.execute("INSERT INTO conversas(login, titulo, agente) VALUES(?,?,?)", (login, titulo, agente)).lastrowid
        velhas = c.execute("SELECT id FROM conversas WHERE login=? ORDER BY atualizada DESC, id DESC LIMIT -1 OFFSET ?",
                           (login, MAX_CONVERSAS)).fetchall()
        c.executemany("DELETE FROM conversas WHERE id=?", velhas)
    return cid

def dono(cid, login):
    with db.conn() as c:
        r = c.execute("SELECT 1 FROM conversas WHERE id=? AND login=?", (cid, login)).fetchone()
    if not r:
        raise LookupError("Conversa não encontrada.")

def obter(cid):
    with db.conn() as c:
        r = c.execute("SELECT id, titulo, resumo, criada, atualizada, n_msgs, resumo_n, login, agente FROM conversas WHERE id=?", (cid,)).fetchone()
    return dict(zip(["id", "titulo", "resumo", "criada", "atualizada", "n_msgs", "resumo_n", "login", "agente"], r)) if r else None

def listar(login, agente=None, limite=MAX_CONVERSAS):
    with db.conn() as c:
        rows = c.execute("""SELECT id, titulo, atualizada, n_msgs, agente FROM conversas WHERE login=? AND (? IS NULL OR agente=?)
                            ORDER BY atualizada DESC, id DESC LIMIT ?""", (login, agente, agente, limite)).fetchall()
    return [dict(zip(["id", "titulo", "atualizada", "n_msgs", "agente"], r)) for r in rows]

def mensagens(cid):
    with db.conn() as c:
        rows = c.execute("SELECT papel, conteudo, fontes, origem, criada FROM mensagens WHERE conversa_id=? ORDER BY id", (cid,)).fetchall()
    return [{"papel": r[0], "conteudo": r[1], "fontes": json.loads(r[2]) if r[2] else [], "origem": r[3], "criada": r[4]} for r in rows]

def historico(cid, n=10):
    """Últimas n mensagens no formato do modelo."""
    with db.conn() as c:
        rows = c.execute("SELECT papel, conteudo FROM mensagens WHERE conversa_id=? ORDER BY id DESC LIMIT ?", (cid, n)).fetchall()
    return [{"role": r[0], "content": r[1][:1500]} for r in reversed(rows)]

def ultima_troca(cid):
    """(pergunta do usuário, origem da resposta) da última troca da conversa."""
    with db.conn() as c:
        rows = c.execute("SELECT papel, conteudo, origem FROM mensagens WHERE conversa_id=? ORDER BY id DESC LIMIT 2", (cid,)).fetchall()
    if len(rows) == 2 and rows[0][0] == "assistant" and rows[1][0] == "user":
        return rows[1][1], rows[0][2]
    return None, None

def adicionar(cid, papel, conteudo, fontes=None, origem=None):
    with db.lock, db.conn() as c:
        c.execute("INSERT INTO mensagens(conversa_id, papel, conteudo, fontes, origem) VALUES(?,?,?,?,?)",
                  (cid, papel, conteudo, json.dumps(fontes, ensure_ascii=False) if fontes else None, origem))
        c.execute("UPDATE conversas SET n_msgs=n_msgs+1, atualizada=datetime('now','localtime') WHERE id=?", (cid,))

def renomear(cid, titulo):
    titulo = " ".join((titulo or "").split())[:60]
    if not titulo:
        raise ValueError("Informe o título.")
    with db.lock, db.conn() as c:
        c.execute("UPDATE conversas SET titulo=? WHERE id=?", (titulo, cid))

def definir_resumo(cid, resumo, titulo=None, n=None):
    with db.lock, db.conn() as c:
        if titulo:
            c.execute("UPDATE conversas SET titulo=? WHERE id=?", (titulo[:60], cid))
        c.execute("UPDATE conversas SET resumo=?, resumo_n=COALESCE(?, n_msgs) WHERE id=?", (resumo, n, cid))

def apagar(cid):
    with db.lock, db.conn() as c:
        c.execute("DELETE FROM conversas WHERE id=?", (cid,))

def apagar_todas(login):
    with db.lock, db.conn() as c:
        c.execute("DELETE FROM conversas WHERE login=?", (login,))

def esquecer_resumos(login):
    with db.lock, db.conn() as c:
        c.execute("UPDATE conversas SET resumo=NULL WHERE login=?", (login,))

def resumos_recentes(login, exceto=None, n=6, agente=None):
    with db.conn() as c:
        rows = c.execute("""SELECT atualizada, titulo, resumo FROM conversas
                            WHERE login=? AND id!=? AND resumo IS NOT NULL AND resumo!='' AND (? IS NULL OR agente=?)
                            ORDER BY atualizada DESC LIMIT ?""", (login, exceto or 0, agente, agente, n)).fetchall()
    return rows

def total(login):
    with db.conn() as c:
        return c.execute("SELECT COUNT(*) FROM conversas WHERE login=?", (login,)).fetchone()[0]
