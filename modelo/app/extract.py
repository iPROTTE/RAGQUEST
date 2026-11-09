"""Extrai texto de arquivos/URLs. Retorna lista de (pagina|None, texto)."""
import io, re, httpx
from html.parser import HTMLParser
from pypdf import PdfReader
import docx, openpyxl

def from_file(name, data):
    n = name.lower()
    if n.endswith(".pdf"):
        r = PdfReader(io.BytesIO(data))
        return [(i + 1, p.extract_text() or "") for i, p in enumerate(r.pages)]
    if n.endswith(".docx"):
        d = docx.Document(io.BytesIO(data))
        parts = [p.text for p in d.paragraphs if p.text.strip()]
        for t in d.tables:
            for row in t.rows:
                parts.append(" | ".join(c.text.strip() for c in row.cells))
        return [(None, "\n".join(parts))]
    if n.endswith((".xlsx", ".xlsm")):
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        out = []
        for ws in wb.worksheets:
            rows = [" | ".join("" if v is None else str(v) for v in r) for r in ws.iter_rows(values_only=True)]
            out.append((None, f"# {ws.title}\n" + "\n".join(rows)))
        return out
    if n.endswith((".txt", ".md")):
        return [(None, data.decode("utf-8", "ignore"))]
    raise ValueError("Formato não suportado (use PDF, DOCX, XLSX, TXT ou MD)")

class _Text(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "header", "noscript", "svg", "form"}
    BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "tr", "br", "section", "article", "td"}
    def __init__(self):
        super().__init__(); self.out = []; self.skip = 0
    def handle_starttag(self, t, a):
        if t in self.SKIP: self.skip += 1
        if t in self.BLOCK: self.out.append("\n")
    def handle_endtag(self, t):
        if t in self.SKIP and self.skip: self.skip -= 1
    def handle_data(self, d):
        if not self.skip: self.out.append(d)

def from_url(url):
    r = httpx.get(url, follow_redirects=True, timeout=30, headers={"User-Agent": "Mozilla/5.0 rag-manuais"})
    r.raise_for_status()
    if "pdf" in r.headers.get("content-type", ""):
        return from_file("x.pdf", r.content)
    p = _Text(); p.feed(r.text)
    txt = re.sub(r"[ \t]+", " ", "".join(p.out))
    txt = re.sub(r"\n\s*\n+", "\n", txt).strip()
    if len(txt) < 50:
        raise ValueError("Não foi possível extrair conteúdo da URL")
    return [(None, txt)]

def chunk(pages, size=1000, overlap=150):
    out = []
    for page, text in pages:
        text = re.sub(r"[ \t]+", " ", text).strip()
        i = 0
        while i < len(text):
            piece = text[i:i + size].strip()
            if piece:
                out.append((page, piece))
            if i + size >= len(text):
                break
            i += size - overlap
    return out
