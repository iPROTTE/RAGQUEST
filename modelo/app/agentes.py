"""Agentes: áreas de negócio com conhecimento separado dentro da mesma licença.

- Cada agente tem pasta própria em "Ragquest - Conhecimento\\<Pasta do agente>\\(pop|manual|diretriz|outros)".
- As pastas pop/manual/diretriz/outros na raiz formam a base GERAL, que o agente pode (ou não) consultar.
- O administrador do cliente define quais usuários acessam cada agente (administradores acessam todos).
- A licença pode limitar quantos agentes existem (campo "a" da chave).
"""
import os, re, unicodedata
from . import config, db, licenca

GERAL = "geral"
TIPOS = ("pop", "manual", "diretriz", "outros")
RESERVADAS = set(TIPOS) | {"_lixeira", "geral"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS agentes(
  id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE, nome TEXT NOT NULL, icone TEXT NOT NULL DEFAULT '🤖',
  descricao TEXT NOT NULL DEFAULT '', instrucoes TEXT NOT NULL DEFAULT '', pasta TEXT NOT NULL UNIQUE COLLATE NOCASE,
  usa_geral INTEGER NOT NULL DEFAULT 1, busca_web INTEGER NOT NULL DEFAULT 1,
  criado_em TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS agente_usuarios(
  agente_id INTEGER NOT NULL REFERENCES agentes(id) ON DELETE CASCADE,
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  PRIMARY KEY(agente_id, usuario_id));
"""
CAMPOS = ["id", "slug", "nome", "icone", "descricao", "instrucoes", "pasta", "usa_geral", "busca_web", "criado_em"]

def _coluna(c, tabela, coluna, ddl):
    if coluna not in [r[1] for r in c.execute(f"PRAGMA table_info({tabela})")]:
        c.execute(f"ALTER TABLE {tabela} ADD COLUMN {ddl}")

def init():
    with db.conn() as c:
        c.executescript(SCHEMA)
        _coluna(c, "documents", "agente", f"agente TEXT NOT NULL DEFAULT '{GERAL}'")
        _coluna(c, "conversas", "agente", "agente TEXT")
        if not c.execute("SELECT 1 FROM agentes").fetchone():
            # agente padrão: mantém o comportamento das versões anteriores (usa a base geral)
            aid = c.execute("""INSERT INTO agentes(slug,nome,icone,descricao,pasta,usa_geral,busca_web)
                               VALUES('assistente','Assistente','🤖','Assistente geral da empresa','Assistente',1,1)""").lastrowid
            c.execute("INSERT OR IGNORE INTO agente_usuarios(agente_id, usuario_id) SELECT ?, id FROM usuarios", (aid,))
            c.execute("UPDATE conversas SET agente='assistente' WHERE agente IS NULL")
        if c.execute("PRAGMA user_version").fetchone()[0] < 2:
            # 1.1.1: agentes criados por você ficam isolados (só a pasta deles); o Assistente continua com a base geral
            c.execute("UPDATE agentes SET usa_geral=0 WHERE slug!='assistente'")
            c.execute("PRAGMA user_version=2")
    criar_pastas()

def _dict(r):
    if not r:
        return None
    d = dict(zip(CAMPOS, r))
    d["usa_geral"], d["busca_web"] = bool(d["usa_geral"]), bool(d["busca_web"])
    return d

def listar():
    with db.conn() as c:
        return [_dict(r) for r in c.execute(f"SELECT {','.join(CAMPOS)} FROM agentes ORDER BY id")]

def obter(aid):
    with db.conn() as c:
        return _dict(c.execute(f"SELECT {','.join(CAMPOS)} FROM agentes WHERE id=?", (aid,)).fetchone())

def por_slug(slug):
    with db.conn() as c:
        return _dict(c.execute(f"SELECT {','.join(CAMPOS)} FROM agentes WHERE slug=?", (slug,)).fetchone())

def por_pasta(nome):
    with db.conn() as c:
        return _dict(c.execute(f"SELECT {','.join(CAMPOS)} FROM agentes WHERE pasta=? COLLATE NOCASE", (nome,)).fetchone())

def limite():
    a = licenca.estado().get("agentes")
    return int(a) if a else None

def caminho(ag):
    return os.path.join(config.KNOWLEDGE_DIR, ag["pasta"])

def criar_pastas():
    for t in TIPOS:
        os.makedirs(os.path.join(config.KNOWLEDGE_DIR, t), exist_ok=True)
    for ag in listar():
        for t in TIPOS:
            os.makedirs(os.path.join(caminho(ag), t), exist_ok=True)

# ---------------------------------------------------------------- criar / alterar / excluir
def _slug(nome):
    s = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40] or "agente"

def _pasta(nome):
    p = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", nome).strip().rstrip(".")[:60]
    return p or "Agente"

def _validar(nome, icone, descricao, instrucoes):
    nome = " ".join((nome or "").split())
    if len(nome) < 2 or len(nome) > 40:
        raise ValueError("O nome do agente precisa ter de 2 a 40 caracteres.")
    if len(descricao or "") > 300:
        raise ValueError("Descrição muito longa (máx. 300 caracteres).")
    if len(instrucoes or "") > 3000:
        raise ValueError("Instruções muito longas (máx. 3000 caracteres).")
    return nome, (icone or "🤖").strip()[:4] or "🤖", (descricao or "").strip(), (instrucoes or "").strip()

def criar(nome, icone="🤖", descricao="", instrucoes="", usa_geral=False, busca_web=True):
    nome, icone, descricao, instrucoes = _validar(nome, icone, descricao, instrucoes)
    lim = limite()
    if lim is not None and len(listar()) >= lim:
        raise ValueError(f"A licença permite até {lim} agente(s). Exclua um agente ou peça ao fornecedor para ampliar a licença.")
    slug, pasta = _slug(nome), _pasta(nome)
    if pasta.lower() in RESERVADAS or slug == GERAL:
        raise ValueError("Esse nome é reservado. Escolha outro nome para o agente.")
    with db.lock, db.conn() as c:
        if c.execute("SELECT 1 FROM agentes WHERE slug=? OR pasta=? COLLATE NOCASE", (slug, pasta)).fetchone():
            raise ValueError("Já existe um agente com esse nome.")
        aid = c.execute("""INSERT INTO agentes(slug,nome,icone,descricao,instrucoes,pasta,usa_geral,busca_web)
                           VALUES(?,?,?,?,?,?,?,?)""",
                        (slug, nome, icone, descricao, instrucoes, pasta, int(usa_geral), int(busca_web))).lastrowid
    criar_pastas()
    return obter(aid)

def alterar(aid, nome=None, icone=None, descricao=None, instrucoes=None, usa_geral=None, busca_web=None):
    """Altera o agente. Se o nome mudar, a pasta é renomeada junto (documentos e índice acompanham)."""
    ag = obter(aid)
    if not ag:
        raise ValueError("Agente não encontrado.")
    n, i, d, ins = _validar(nome if nome is not None else ag["nome"], icone if icone is not None else ag["icone"],
                            descricao if descricao is not None else ag["descricao"],
                            instrucoes if instrucoes is not None else ag["instrucoes"])
    nova = _pasta(n)
    if nova != ag["pasta"]:
        if nova.lower() in RESERVADAS:
            raise ValueError("Esse nome é reservado. Escolha outro nome para o agente.")
        with db.conn() as c:
            if c.execute("SELECT 1 FROM agentes WHERE pasta=? COLLATE NOCASE AND id!=?", (nova, aid)).fetchone():
                raise ValueError("Já existe um agente com esse nome.")
        velho_dir, novo_dir = caminho(ag), os.path.join(config.KNOWLEDGE_DIR, nova)
        if os.path.exists(novo_dir) and os.path.normcase(novo_dir) != os.path.normcase(velho_dir):
            raise ValueError(f'Já existe uma pasta "{nova}" na pasta de conhecimento. Renomeie ou apague essa pasta antes.')
        try:
            if os.path.exists(velho_dir):
                os.rename(velho_dir, novo_dir)
        except OSError:
            raise ValueError("Não consegui renomear a pasta do agente (ela pode estar aberta no Explorador). Feche a pasta e tente de novo.")
        velho_pref, novo_pref = ag["pasta"] + "/", nova + "/"
        with db.lock, db.conn() as c:
            c.execute("UPDATE agentes SET pasta=? WHERE id=?", (nova, aid))
            c.execute("UPDATE documents SET slug='pasta:' || ? || substr(slug, ?) WHERE slug LIKE ?",
                      (novo_pref, len("pasta:" + velho_pref) + 1, "pasta:" + velho_pref.replace("%", "") + "%"))
            c.execute("UPDATE files SET path=? || substr(path, ?) WHERE path LIKE ?",
                      (novo_pref, len(velho_pref) + 1, velho_pref.replace("%", "") + "%"))
    with db.lock, db.conn() as c:
        c.execute("""UPDATE agentes SET nome=?, icone=?, descricao=?, instrucoes=?, usa_geral=COALESCE(?,usa_geral),
                     busca_web=COALESCE(?,busca_web) WHERE id=?""",
                  (n, i, d, ins, None if usa_geral is None else int(usa_geral), None if busca_web is None else int(busca_web), aid))
    criar_pastas()
    return obter(aid)

def excluir(aid):
    """Tira o agente e o conhecimento dele do índice. Os arquivos da pasta NÃO são apagados."""
    ag = obter(aid)
    if not ag:
        return []
    if len(listar()) <= 1:
        raise ValueError("É preciso manter pelo menos um agente.")
    with db.conn() as c:
        slugs = [r[0] for r in c.execute("SELECT DISTINCT slug FROM documents WHERE agente=?", (ag["slug"],))]
    with db.lock, db.conn() as c:
        c.execute("DELETE FROM agentes WHERE id=?", (aid,))
        c.execute("DELETE FROM files WHERE path LIKE ?", (ag["pasta"] + "/%",))
    return slugs

# ---------------------------------------------------------------- acesso
def acessiveis(usuario):
    if usuario["papel"] == "admin":
        return listar()
    with db.conn() as c:
        rows = c.execute(f"""SELECT {','.join('a.' + x for x in CAMPOS)} FROM agentes a
                             JOIN agente_usuarios au ON au.agente_id=a.id WHERE au.usuario_id=? ORDER BY a.id""",
                         (usuario["id"],)).fetchall()
    return [_dict(r) for r in rows]

def escolher(usuario, slug=None):
    """Agente pedido (se o usuário tem acesso) ou o primeiro disponível; None se não tem nenhum."""
    lista = acessiveis(usuario)
    for ag in lista:
        if slug and ag["slug"] == slug:
            return ag
    return None if slug else (lista[0] if lista else None)

def acessos_de(uid):
    with db.conn() as c:
        return [r[0] for r in c.execute("SELECT agente_id FROM agente_usuarios WHERE usuario_id=? ORDER BY agente_id", (uid,))]

def definir_acesso(uid, ids):
    validos = {a["id"] for a in listar()}
    with db.lock, db.conn() as c:
        c.execute("DELETE FROM agente_usuarios WHERE usuario_id=?", (uid,))
        c.executemany("INSERT OR IGNORE INTO agente_usuarios(agente_id, usuario_id) VALUES(?,?)",
                      [(int(i), uid) for i in ids if int(i) in validos])

def usuarios_de(aid):
    with db.conn() as c:
        return c.execute("SELECT COUNT(*) FROM agente_usuarios WHERE agente_id=?", (aid,)).fetchone()[0]

def areas(ag):
    """Bases de conhecimento que o agente consulta."""
    return [ag["slug"]] + ([GERAL] if ag["usa_geral"] else [])

# ---------------------------------------------------------------- pasta -> agente
def localizar(rel):
    """'pop/x.pdf' -> ('geral','pop'); 'Comercial/manual/y.pdf' -> ('comercial','manual'); pasta sem agente -> None."""
    partes = rel.split("/")
    if len(partes) == 1:
        return GERAL, "outros"
    primeira = partes[0].lower()
    if primeira in TIPOS:
        return GERAL, primeira if primeira != "outros" else "outros"
    ag = por_pasta(partes[0])
    if not ag:
        return None
    tipo = partes[1].lower() if len(partes) > 2 and partes[1].lower() in TIPOS else "outros"
    return ag["slug"], tipo
