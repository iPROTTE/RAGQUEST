import hashlib
from . import db, search
from .extract import chunk
from .llm import embed

def ingest(slug, title, tipo, setor, source_url, pages, agente="geral"):
    """Cria nova versão só se o conteúdo mudou. Retorna (doc_id, version, status)."""
    full = "\n".join(t for _, t in pages)
    h = hashlib.sha256(full.encode()).hexdigest()
    with db.conn() as c:
        old = c.execute("SELECT id, version, content_hash, agente FROM documents WHERE slug=? AND active=1", (slug,)).fetchone()
    if old and old[2] == h and old[3] == agente:
        return old[0], old[1], "sem alterações"
    ch = chunk(pages)
    if not ch:
        raise ValueError("Documento sem texto extraível (PDF escaneado? OCR ainda não implementado)")
    vecs = embed([t for _, t in ch])          # fora do lock (demora)
    with db.lock, db.conn() as c:
        version = old[1] + 1 if old else 1
        if old:
            c.execute("UPDATE documents SET active=0 WHERE slug=? AND active=1", (slug,))
        doc_id = c.execute(
            "INSERT INTO documents(slug,title,tipo,setor,source_url,content_hash,version,agente) VALUES(?,?,?,?,?,?,?,?)",
            (slug, title, tipo, setor, source_url, h, version, agente)).lastrowid
        for (p, t), v in zip(ch, vecs):
            cid = c.execute("INSERT INTO chunks(document_id,page,content,embedding) VALUES(?,?,?,?)",
                            (doc_id, p, t, v.tobytes())).lastrowid
            c.execute("INSERT INTO chunks_fts(rowid, content) VALUES(?,?)", (cid, t))
    search.invalidate()
    from . import conhecimento
    conhecimento.agendar(doc_id)                 # escreve a skill do documento em segundo plano
    return doc_id, version, "atualizado" if old else "criado"

def delete_slug(slug):
    with db.lock, db.conn() as c:
        ids = [r[0] for r in c.execute(
            "SELECT c.id FROM chunks c JOIN documents d ON d.id=c.document_id WHERE d.slug=?", (slug,))]
        c.executemany("DELETE FROM chunks_fts WHERE rowid=?", [(i,) for i in ids])
        c.execute("DELETE FROM documents WHERE slug=?", (slug,))   # remove todas as versões
    search.invalidate()
    from . import conhecimento
    conhecimento.apagar_por_slug(slug)

def slug_of(doc_id):
    with db.conn() as c:
        r = c.execute("SELECT slug FROM documents WHERE id=?", (doc_id,)).fetchone()
    return r[0] if r else None
