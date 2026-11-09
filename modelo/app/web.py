"""Busca na web (DuckDuckGo, sem chave) usada quando a pasta não tem a resposta."""
import re, html, urllib.parse, httpx, numpy as np
from .extract import _Text, chunk
from .llm import embed

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36",
      "Accept-Language": "pt-BR,pt;q=0.9"}

def _clean(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()

def _real(u):
    if u.startswith("//"): u = "https:" + u
    q = urllib.parse.urlparse(u)
    if "duckduckgo.com" in q.netloc and q.path.startswith("/l/"):
        return urllib.parse.parse_qs(q.query).get("uddg", [u])[0]
    return u

def buscar(q, n=5):
    out = []
    try:
        r = httpx.post("https://html.duckduckgo.com/html/", data={"q": q, "kl": "br-pt"}, headers=UA, timeout=15, follow_redirects=True)
        links = re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S)
        snips = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', r.text, re.S)
        for i, (u, t) in enumerate(links):
            out.append({"url": _real(html.unescape(u)), "title": _clean(t), "snippet": _clean(snips[i]) if i < len(snips) else ""})
    except Exception:
        pass
    if not out:
        try:
            r = httpx.post("https://lite.duckduckgo.com/lite/", data={"q": q, "kl": "br-pt"}, headers=UA, timeout=15, follow_redirects=True)
            links = re.findall(r"<a[^>]+href=\"([^\"]+)\"[^>]*class='result-link'[^>]*>(.*?)</a>", r.text, re.S)
            snips = re.findall(r"class='result-snippet'[^>]*>(.*?)</td>", r.text, re.S)
            for i, (u, t) in enumerate(links):
                out.append({"url": _real(html.unescape(u)), "title": _clean(t), "snippet": _clean(snips[i]) if i < len(snips) else ""})
        except Exception:
            pass
    out = [o for o in out if o["url"].startswith("http") and "duckduckgo.com" not in o["url"]]
    return out[:n]

def _pagina(url):
    try:
        r = httpx.get(url, headers=UA, timeout=10, follow_redirects=True)
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            return ""
        p = _Text(); p.feed(r.text[:400000])
        return re.sub(r"\s+", " ", "".join(p.out))[:20000]
    except Exception:
        return ""

def contexto(q, n=5):
    """Retorna trechos relevantes da web: [{content,title,url}]."""
    res = buscar(q)
    pieces = []
    for r in res:
        if r["snippet"]:
            pieces.append({"content": r["snippet"], "title": r["title"], "url": r["url"]})
        for _, t in chunk([(None, _pagina(r["url"]))], size=800, overlap=100)[:15]:
            pieces.append({"content": t, "title": r["title"], "url": r["url"]})
    if not pieces:
        return []
    m = embed([p["content"] for p in pieces])
    qv = embed([q])[0]
    order = np.argsort(-(m @ qv))[:n]
    return [pieces[i] for i in order]
