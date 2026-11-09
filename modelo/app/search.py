import re, threading, numpy as np
from . import db
from .llm import embed

_cache = {"ok": False}
_lock = threading.Lock()

def invalidate():
    _cache["ok"] = False

def _load():
    with _lock:
        if _cache["ok"]:
            return _cache
        with db.conn() as c:
            rows = c.execute("""SELECT c.id, c.embedding, d.tipo, d.setor, d.agente FROM chunks c
                                JOIN documents d ON d.id=c.document_id WHERE d.active=1""").fetchall()
        _cache["ids"] = np.array([r[0] for r in rows], dtype=np.int64)
        _cache["mat"] = np.vstack([np.frombuffer(r[1], dtype=np.float32) for r in rows]) if rows else np.zeros((0, 1), np.float32)
        _cache["tipo"] = np.array([r[2] for r in rows], dtype=object)
        _cache["setor"] = np.array([r[3] for r in rows], dtype=object)
        _cache["agente"] = np.array([r[4] for r in rows], dtype=object)
        _cache["ok"] = True
        return _cache

def _fts_query(q):
    words = [w for w in re.findall(r"\w+", q.lower()) if len(w) >= 3]
    return " OR ".join(f'"{w}"' for w in words[:20])

def hybrid(q, n=6, tipo=None, setor=None, areas=None):
    data = _load()
    if not len(data["ids"]):
        return [], 0.0
    mask = np.ones(len(data["ids"]), bool)
    if tipo: mask &= data["tipo"] == tipo
    if setor: mask &= data["setor"] == setor
    if areas is not None: mask &= np.isin(data["agente"], list(areas))
    if not mask.any():
        return [], 0.0
    rrf = {}
    qv = embed([q])[0]
    sims = data["mat"] @ qv
    sims[~mask] = -9
    best = float(sims.max()) if len(sims) else 0.0
    for rank, i in enumerate(np.argsort(-sims)[:20]):
        if sims[i] > -9:
            rrf[int(data["ids"][i])] = 1 / (60 + rank + 1)
    fq = _fts_query(q)
    allowed = set(data["ids"][mask].tolist())
    if fq:
        with db.conn() as c:
            try:
                kw = c.execute("SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT 40", (fq,)).fetchall()
            except Exception:
                kw = []
        rank = 0
        for (cid,) in kw:
            if cid in allowed:
                rrf[cid] = rrf.get(cid, 0) + 1 / (60 + rank + 1); rank += 1
                if rank >= 20: break
    top = sorted(rrf, key=rrf.get, reverse=True)[:n]
    if not top:
        return [], best
    with db.conn() as c:
        rows = {r[0]: r for r in c.execute(
            f"""SELECT c.id, c.content, c.page, d.title, d.version, d.tipo, d.id FROM chunks c
                JOIN documents d ON d.id=c.document_id WHERE c.id IN ({','.join('?'*len(top))})""", top)}
    return [dict(content=rows[i][1], page=rows[i][2], title=rows[i][3], version=rows[i][4],
                 tipo=rows[i][5], doc_id=rows[i][6], score=rrf[i]) for i in top if i in rows], best
