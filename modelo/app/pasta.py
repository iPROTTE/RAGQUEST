"""Monitora a pasta de conhecimento: indexa arquivos novos/alterados e remove os apagados."""
import os, shutil, time, threading, traceback
from . import config, db, extract, ingest as ing, licenca, preparo, agentes

EXTS = (".pdf", ".docx", ".xlsx", ".xlsm", ".txt", ".md")
TIPOS = {"pop", "manual", "diretriz"}
_scan_lock = threading.Lock()
estado = {"ultima": None, "erros": {}, "processando": None}

def criar_pastas():
    try:
        agentes.criar_pastas()
    except Exception:                      # banco ainda não iniciado
        for t in sorted(TIPOS) + ["outros"]:
            os.makedirs(os.path.join(config.KNOWLEDGE_DIR, t), exist_ok=True)

def _rel(path):
    return os.path.relpath(path, config.KNOWLEDGE_DIR).replace("\\", "/")

def _tipo(rel):
    first = rel.split("/")[0].lower()
    return first if first in TIPOS and "/" in rel else "outros"

def _arquivos():
    for root, dirs, files in os.walk(config.KNOWLEDGE_DIR):
        dirs[:] = [d for d in dirs if not d.startswith((".", "_"))]
        for f in files:
            if f.lower().endswith(EXTS) and not f.startswith(("~$", ".", "_")):
                p = os.path.join(root, f)
                if agentes.localizar(_rel(p)):           # ignora pastas que não são de nenhum agente
                    yield p

def indexar_arquivo(path):
    rel = _rel(path)
    st = os.stat(path)
    estado["processando"] = rel
    try:
        with open(path, "rb") as fh:
            pages = extract.from_file(path, fh.read())
        agente, tipo = agentes.localizar(rel) or (agentes.GERAL, "outros")
        res = ing.ingest("pasta:" + rel, os.path.basename(path), tipo, None, None, pages, agente=agente)
        estado["erros"].pop(rel, None)
    except Exception as e:
        estado["erros"][rel] = str(e)
        res = None
    finally:
        estado["processando"] = None
    with db.lock, db.conn() as c:   # registra mesmo com erro, para não repetir até o arquivo mudar
        c.execute("INSERT OR REPLACE INTO files(path,mtime,size) VALUES(?,?,?)", (rel, st.st_mtime, st.st_size))
    return res

def varrer():
    if not _scan_lock.acquire(blocking=False):
        return {"status": "varredura já em andamento"}
    try:
        criar_pastas()
        with db.conn() as c:
            known = {r[0]: (r[1], r[2]) for r in c.execute("SELECT path,mtime,size FROM files")}
        vistos, novos = set(), 0
        for path in _arquivos():
            rel = _rel(path)
            vistos.add(rel)
            st = os.stat(path)
            if known.get(rel) != (st.st_mtime, st.st_size):
                if time.time() - st.st_mtime < 3:   # arquivo ainda sendo copiado
                    vistos.discard(rel); continue
                indexar_arquivo(path); novos += 1
        removidos = 0
        for rel in set(known) - vistos:
            if os.path.exists(os.path.join(config.KNOWLEDGE_DIR, rel)):
                continue
            ing.delete_slug("pasta:" + rel)
            with db.lock, db.conn() as c:
                c.execute("DELETE FROM files WHERE path=?", (rel,))
            estado["erros"].pop(rel, None)
            removidos += 1
        estado["ultima"] = time.strftime("%d/%m %H:%M:%S")
        return {"status": f"{novos} indexado(s), {removidos} removido(s)"}
    finally:
        _scan_lock.release()

def salvar_upload(nome, data, tipo, agente=None):
    tipo = tipo if tipo in TIPOS else "outros"
    nome = os.path.basename(nome)
    ag = agentes.por_slug(agente) if agente and agente != agentes.GERAL else None
    base = agentes.caminho(ag) if ag else config.KNOWLEDGE_DIR
    dest = os.path.join(base, tipo, nome)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as fh:
        fh.write(data)
    return dest

def mover_para_lixeira(rel):
    src = os.path.join(config.KNOWLEDGE_DIR, rel)
    if os.path.exists(src):
        dest = os.path.join(config.TRASH_DIR, time.strftime("%Y%m%d-%H%M%S_") + os.path.basename(rel))
        os.makedirs(config.TRASH_DIR, exist_ok=True)
        shutil.move(src, dest)
    with db.lock, db.conn() as c:
        c.execute("DELETE FROM files WHERE path=?", (rel,))

def loop():
    while True:
        try:
            if licenca.valida() and preparo.pronto(): varrer()
        except Exception: traceback.print_exc()
        time.sleep(config.SCAN_SECONDS)
