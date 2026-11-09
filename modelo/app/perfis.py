"""Perfis de comunicação por usuário (arquivos .md) e skills de estilo (.md).

- skills/<id>.md: estilos de resposta editáveis (técnico, didático...).
- dados/perfis/<usuario>.md: perfil aprendido de cada usuário.
O perfil molda APENAS o estilo da resposta; os fatos vêm sempre dos documentos.
"""
import os, re, shutil, threading, unicodedata, traceback
import httpx
from . import config

SKILLS_DIR = os.path.join(config.BASE, "skills")
PERFIS_DIR = os.path.join(config.DADOS, "perfis")
_PADRAO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills_padrao")
_locks = {}
ATUALIZAR_A_CADA = int(os.environ.get("PERFIL_A_CADA", "3"))   # interações entre atualizações

def preparar():
    os.makedirs(SKILLS_DIR, exist_ok=True)
    os.makedirs(PERFIS_DIR, exist_ok=True)
    if os.path.isdir(_PADRAO):
        for f in os.listdir(_PADRAO):
            dst = os.path.join(SKILLS_DIR, f)
            if f.endswith(".md") and not os.path.exists(dst):   # não sobrescreve skills editadas
                shutil.copy(os.path.join(_PADRAO, f), dst)

def _frontmatter(txt):
    meta, corpo = {}, txt
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", txt, re.S)
    if m:
        for linha in m.group(1).splitlines():
            if ":" in linha:
                k, v = linha.split(":", 1)
                meta[k.strip()] = v.strip()
        corpo = m.group(2)
    return meta, corpo.strip()

def _montar(meta, corpo):
    return "---\n" + "\n".join(f"{k}: {v}" for k, v in meta.items()) + "\n---\n" + corpo.strip() + "\n"

def skills():
    preparar()
    out = []
    for f in sorted(os.listdir(SKILLS_DIR)):
        if f.endswith(".md"):
            meta, corpo = _frontmatter(open(os.path.join(SKILLS_DIR, f), encoding="utf-8-sig").read())
            out.append({"id": f[:-3], "nome": meta.get("nome", f[:-3]), "descricao": meta.get("descricao", ""), "texto": corpo})
    return out

def slug(nome):
    s = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:40]

MODELO_CORPO = """# Perfil de comunicação

## Estilo detectado
(ainda aprendendo)

## Nível técnico
(ainda aprendendo)

## Preferências
- (ainda aprendendo)

## Observações
- (ainda aprendendo)
"""

def ler(usuario, nome=None):
    u = slug(usuario)
    if not u:
        return None
    p = os.path.join(PERFIS_DIR, u + ".md")
    if os.path.exists(p):
        meta, corpo = _frontmatter(open(p, encoding="utf-8-sig").read())
    else:
        meta, corpo = {}, MODELO_CORPO
    meta.setdefault("usuario", (nome or usuario).strip())
    meta.setdefault("estilo", "auto")
    meta.setdefault("aprendizado", "ligado")
    meta.setdefault("interacoes", "0")
    return {"id": u, "meta": meta, "md": corpo}

def salvar(usuario, meta, md):
    u = slug(usuario)
    os.makedirs(PERFIS_DIR, exist_ok=True)
    with open(os.path.join(PERFIS_DIR, u + ".md"), "w", encoding="utf-8") as fh:
        fh.write(_montar(meta, md))

def apagar(usuario):
    p = os.path.join(PERFIS_DIR, slug(usuario) + ".md")
    if os.path.exists(p):
        os.remove(p)

def _estilo_detectado(md):
    m = re.search(r"##\s*Estilo detectado\s*\n+\s*([^\n]+)", md)
    return (m.group(1).strip().lower() if m else "")

def instrucoes(usuario, nome=None):
    """Texto a acrescentar ao prompt de sistema para este usuário."""
    p = ler(usuario, nome) if usuario else None
    if not p:
        return ""
    sk = {s["id"]: s for s in skills()}
    estilo = p["meta"].get("estilo", "auto")
    if estilo == "auto":
        estilo = _estilo_detectado(p["md"])
    partes = [f"Você está conversando com {p['meta'].get('usuario')}."]
    if estilo in sk:
        partes.append(sk[estilo]["texto"])
    if "(ainda aprendendo)" not in p["md"] or p["meta"].get("estilo") != "auto":
        partes.append("Perfil de comunicação deste usuário:\n" + p["md"])
    return ("\n\n## Como se comunicar com este usuário\n"
            "(Estas orientações mudam apenas o estilo e o formato. Os fatos continuam vindo só dos trechos fornecidos.)\n"
            + "\n\n".join(partes))

PROMPT_ATUALIZAR = """Você mantém o PERFIL DE COMUNICAÇÃO de um usuário de um assistente técnico.
Com base no perfil atual e nas mensagens recentes do usuário, devolva o perfil atualizado.
Observe: vocabulário técnico usado, se pede detalhes ou respostas curtas, tom, formato preferido (passos, comandos, resumo), área de atuação.
Não invente fatos pessoais; registre só o que as mensagens indicam. Seja breve (máx. 12 linhas no total).
O "Estilo detectado" deve ser EXATAMENTE um destes ids: {ids}.

Responda SOMENTE neste formato Markdown:
# Perfil de comunicação

## Estilo detectado
<id>

## Nível técnico
<iniciante | intermediário | avançado>

## Preferências
- <preferência>

## Observações
- <observação>

PERFIL ATUAL:
{perfil}

MENSAGENS RECENTES DO USUÁRIO:
{msgs}
"""

def _atualizar(usuario, mensagens, nome=None):
    lock = _locks.setdefault(slug(usuario), threading.Lock())
    if not lock.acquire(blocking=False):
        return
    try:
        p = ler(usuario, nome)
        ids = [s["id"] for s in skills()]
        prompt = PROMPT_ATUALIZAR.format(ids=", ".join(ids), perfil=p["md"],
                                         msgs="\n".join("- " + m for m in mensagens[-8:]))
        r = httpx.post(f"{config.OLLAMA_URL}/api/chat", timeout=300, json={
            "model": config.CHAT_MODEL, "stream": False, "options": {"temperature": 0.1},
            "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        novo = r.json()["message"]["content"].strip()
        novo = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", novo).strip()
        if "## Estilo detectado" not in novo or len(novo) > 3000:
            return                                     # resposta fora do formato: mantém o anterior
        if _estilo_detectado(novo) not in ids:
            novo = re.sub(r"(##\s*Estilo detectado\s*\n+)\s*[^\n]+", r"\1objetivo", novo)
        p = ler(usuario, nome)                         # relê (pode ter sido editado no meio)
        if p["meta"].get("aprendizado") == "ligado":
            salvar(usuario, p["meta"], novo)
    except Exception:
        traceback.print_exc()
    finally:
        lock.release()

def registrar_interacao(usuario, pergunta, historico, nome=None):
    """Conta a interação e, a cada N, atualiza o perfil em segundo plano."""
    p = ler(usuario, nome) if usuario else None
    if not p or p["meta"].get("aprendizado") != "ligado":
        return
    n = int(p["meta"].get("interacoes", "0") or 0) + 1
    p["meta"]["interacoes"] = str(n)
    salvar(usuario, p["meta"], p["md"])
    if n == 1 or n % ATUALIZAR_A_CADA == 0:
        msgs = [h.get("content", "") for h in (historico or []) if h.get("role") == "user"] + [pergunta]
        threading.Thread(target=_atualizar, args=(usuario, msgs, nome), daemon=True).start()
