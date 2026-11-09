"""Skills de conhecimento: para cada documento indexado, o Ragquest escreve uma ficha (.md)
com assunto, quando usar, pontos-chave e termos. A ficha:
  - entra na busca (como um trecho extra do documento, ajuda a achar por sinônimos);
  - forma o catálogo "O que você sabe" que vai no prompt (o assistente sabe do que a base trata).
Pasta: skills/conhecimento/ (editável; o arquivo é recriado quando o documento muda de versão).
"""
import datetime, hashlib, os, re
from . import db, fila, llm, search
from .perfis import SKILLS_DIR, _frontmatter, _montar

DIR = os.path.join(SKILLS_DIR, "conhecimento")
PAGINA_SKILL = -1            # marca, na tabela chunks, o trecho que é a skill

PROMPT_SKILL = """Você cria uma SKILL de conhecimento (ficha em Markdown) a partir de um documento interno, para o assistente saber do que o documento trata e quando usá-lo.
Use só o que está no texto. Responda SOMENTE neste formato:
## Assunto
<1 ou 2 frases>
## Quando usar
- <situações / perguntas que este documento responde>
## Pontos-chave
- <até 8 fatos, valores, comandos ou passos importantes>
## Termos relacionados
<palavras-chave e sinônimos separados por vírgula>"""

def _arq(slug):
    base = re.sub(r"[^a-z0-9]+", "-", slug.lower().replace("pasta:", "")).strip("-")[:50] or "documento"
    return os.path.join(DIR, f"{base}-{hashlib.sha1(slug.encode()).hexdigest()[:6]}.md")

def _doc(doc_id):
    with db.conn() as c:
        r = c.execute("SELECT id, slug, title, version, active FROM documents WHERE id=?", (doc_id,)).fetchone()
    return dict(zip(["id", "slug", "title", "version", "active"], r)) if r else None

def _ler(slug):
    p = _arq(slug)
    if not os.path.exists(p):
        return None
    meta, corpo = _frontmatter(open(p, encoding="utf-8-sig").read())
    return {"meta": meta, "md": corpo}

def _assunto(md):
    m = re.search(r"##\s*Assunto\s*\n+([^\n#]+)", md or "")
    return m.group(1).strip() if m else ""

def gerar(doc_id, forcar=False):
    d = _doc(doc_id)
    if not d or not d["active"]:
        return
    atual = _ler(d["slug"])
    if atual and not forcar and str(atual["meta"].get("versao")) == str(d["version"]) and _tem_trecho(doc_id):
        return
    with db.conn() as c:
        partes = [r[0] for r in c.execute("SELECT content FROM chunks WHERE document_id=? AND COALESCE(page,0)!=? ORDER BY id",
                                          (doc_id, PAGINA_SKILL))]
    texto = "\n".join(partes)
    if len(texto) > 9000:
        texto = texto[:6500] + "\n[...]\n" + texto[-2500:]
    md = llm.chat([{"role": "system", "content": PROMPT_SKILL},
                   {"role": "user", "content": f"DOCUMENTO: {d['title']}\n\n{texto}"}], temperatura=0.1, max_tokens=700)
    md = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", md.strip()).strip()
    if "## Assunto" not in md:
        return
    if _doc(doc_id) is None or not _doc(doc_id)["active"]:      # documento mudou enquanto gerava
        return
    os.makedirs(DIR, exist_ok=True)
    meta = {"titulo": d["title"], "documento": d["slug"], "versao": d["version"], "doc_id": d["id"],
            "gerado_em": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
    with open(_arq(d["slug"]), "w", encoding="utf-8") as fh:
        fh.write(_montar(meta, md))
    _indexar(d, md)

def _tem_trecho(doc_id):
    with db.conn() as c:
        return c.execute("SELECT 1 FROM chunks WHERE document_id=? AND page=?", (doc_id, PAGINA_SKILL)).fetchone() is not None

def _indexar(d, md):
    conteudo = f'Resumo do documento "{d["title"]}" (skill de conhecimento):\n{md}'
    vec = llm.embed([conteudo])[0]
    with db.lock, db.conn() as c:
        velhos = [r[0] for r in c.execute("SELECT id FROM chunks WHERE document_id=? AND page=?", (d["id"], PAGINA_SKILL))]
        c.executemany("DELETE FROM chunks_fts WHERE rowid=?", [(i,) for i in velhos])
        c.executemany("DELETE FROM chunks WHERE id=?", [(i,) for i in velhos])
        cid = c.execute("INSERT INTO chunks(document_id,page,content,embedding) VALUES(?,?,?,?)",
                        (d["id"], PAGINA_SKILL, conteudo, vec.tobytes())).lastrowid
        c.execute("INSERT INTO chunks_fts(rowid, content) VALUES(?,?)", (cid, conteudo))
    search.invalidate()

def agendar(doc_id, forcar=False):
    fila.adicionar(("skill", doc_id), gerar, doc_id, forcar)

def apagar_por_slug(slug):
    p = _arq(slug)
    if os.path.exists(p):
        os.remove(p)

def _ativos(areas=None):
    with db.conn() as c:
        docs = [dict(zip(["id", "slug", "title", "version", "agente"], r)) for r in
                c.execute("SELECT id, slug, title, version, agente FROM documents WHERE active=1 ORDER BY title")]
    return [d for d in docs if areas is None or d["agente"] in areas]

def completar():
    """Agenda skills para documentos que ainda não têm (ou estão desatualizadas)."""
    for d in _ativos():
        s = _ler(d["slug"])
        if not s or str(s["meta"].get("versao")) != str(d["version"]) or not _tem_trecho(d["id"]):
            agendar(d["id"])

def catalogo(areas=None, max_chars=2200):
    linhas, total = [], 0
    docs = _ativos(areas)
    for i, d in enumerate(docs):
        s = _ler(d["slug"])
        assunto = _assunto(s["md"]) if s else ""
        titulo = re.sub(r"\.(pdf|docx|xlsx|xlsm|txt|md)$", "", d["title"], flags=re.I)
        l = f"- {titulo}" + (f": {assunto}" if assunto else "")
        if total + len(l) > max_chars:
            linhas.append(f"- ... e mais {len(docs) - i} documento(s).")
            break
        linhas.append(l); total += len(l) + 1
    return "\n".join(linhas)

def listar():
    out = []
    for d in _ativos():
        s = _ler(d["slug"])
        ok = bool(s and str(s["meta"].get("versao")) == str(d["version"]))
        out.append({"doc_id": d["id"], "titulo": d["title"], "versao": d["version"], "skill": ok, "agente": d["agente"],
                    "gerado_em": s["meta"].get("gerado_em") if s else None, "assunto": _assunto(s["md"]) if s else ""})
    return {"skills": out, "pendentes": fila.pendentes("skill")}

def ler_md(doc_id):
    d = _doc(doc_id)
    s = _ler(d["slug"]) if d else None
    return s["md"] if s else None
