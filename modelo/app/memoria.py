"""Memória de longo prazo por usuário: fatos que a pessoa contou sobre si + resumos das conversas.

Arquivo dados/memoria/<login>.md (editável pelo próprio usuário em "Meu perfil").
"""
import json, os, re
from . import config, conversa, llm, fila
from .perfis import slug

DIR = os.path.join(config.DADOS, "memoria")
MAX_FATOS = 20
_SENSIVEL = re.compile(r"senha|password|cpf|rg\b|cart[aã]o|conta\s+banc|ag[eê]ncia|pix|token|chave\s+de", re.I)

def _arq(login):
    return os.path.join(DIR, slug(login) + ".md")

def ler(login):
    p = _arq(login)
    ativa, fatos = True, []
    if os.path.exists(p):
        for linha in open(p, encoding="utf-8-sig").read().splitlines():
            l = linha.strip()
            if l.lower().startswith("ativa:"):
                ativa = l.split(":", 1)[1].strip().lower() not in ("nao", "não", "0", "false")
            elif l.startswith("- "):
                fatos.append(l[2:].strip())
    return {"ativa": ativa, "fatos": fatos}

def salvar(login, fatos, ativa=True):
    os.makedirs(DIR, exist_ok=True)
    limpos, vistos = [], set()
    for f in fatos:
        f = " ".join(str(f).split()).strip("-• ").strip()
        if f and not _SENSIVEL.search(f) and f.lower() not in vistos and len(f) <= 200:
            vistos.add(f.lower()); limpos.append(f)
    with open(_arq(login), "w", encoding="utf-8") as fh:
        fh.write(f"ativa: {'sim' if ativa else 'nao'}\n# O que o Ragquest lembra sobre você\n")
        fh.write("".join(f"- {f}\n" for f in limpos[-MAX_FATOS:]))

def texto(login):
    return "\n".join(f"- {f}" for f in ler(login)["fatos"])

def apagar(login):
    p = _arq(login)
    if os.path.exists(p):
        os.remove(p)
    conversa.esquecer_resumos(login)

def bloco_conversas(login, atual=None, agente=None):
    linhas = []
    for quando, titulo, resumo in conversa.resumos_recentes(login, exceto=atual, n=6, agente=agente):
        linhas.append(f"- {quando[:10].split('-')[2]}/{quando[5:7]}: {resumo}")
    return "\n".join(linhas)

# ---------------------------------------------------------------- aprendizado em segundo plano
PROMPT_FATOS = """Você mantém a memória de longo prazo de um assistente sobre o USUÁRIO (a pessoa), não sobre assuntos técnicos.
Extraia das mensagens só fatos que o usuário contou SOBRE SI MESMO: nome, cargo, empresa, área, equipamentos/fabricantes com que trabalha, projetos e obras em andamento, cidade e preferências.
Quando o usuário pedir "lembra que...", "anota que...", "prefiro...", registre como fato (ex.: "preferência: respostas curtas").
Ignore: cumprimentos, perguntas (inclusive "você lembra de mim?"), perguntas e respostas técnicas, comandos, senhas, documentos, dados bancários, saúde, assuntos íntimos.
Escreva cada fato no formato "assunto: valor", em terceira pessoa, curto. Exemplos: "nome: Ana", "cargo: coordenadora de NOC", "empresa: Provedor X", "equipamentos: OLT Nokia", "preferência: respostas com passo a passo".
Responda em JSON: {"novos_fatos": [...]} com fatos novos ou que mudaram. Sem fatos novos: {"novos_fatos": []}."""

def _fato_valido(f):
    f = (f or "").strip()
    return bool(re.match(r"^[^:?]{2,30}:\s*\S", f)) and not f.endswith("?") and len(f) <= 160

PROMPT_RESUMO = """Resuma a conversa abaixo entre um usuário e o assistente Ragquest.
Responda em JSON: {"titulo": "título curto da conversa (máx. 6 palavras)", "resumo": "uma frase (máx. 25 palavras) com o assunto e o resultado, do ponto de vista do assistente"}."""

def _chave(f):
    m = re.match(r"\s*([^:]{2,30}):", f)
    return m.group(1).strip().lower() if m else None

_UNICOS = {"nome", "apelido", "cargo", "função", "funcao", "empresa", "cidade", "área", "area", "setor"}

def _mesclar(fatos, novos, remover):
    rem = {r.strip().lower() for r in remover if isinstance(r, str)}
    remk = {_chave(r) for r in remover if isinstance(r, str)} - {None}
    out = [f for f in fatos if f.lower() not in rem and (_chave(f) not in remk)]
    for n in novos:
        if not isinstance(n, str) or not n.strip():
            continue
        n = n.strip()
        k = _chave(n)
        if k in _UNICOS:
            out = [f for f in out if _chave(f) != k]
        out = [f for f in out if f.lower() != n.lower()]
        out.append(n)
    return out

def aprender(login, cid):
    """Atualiza o resumo/título da conversa e os fatos sobre o usuário."""
    c = conversa.obter(cid)
    if not c:
        return
    msgs = conversa.mensagens(cid)
    if not msgs:
        return
    texto_conv = "\n".join(("Usuário: " if m["papel"] == "user" else "Assistente: ") + m["conteudo"][:500] for m in msgs[-12:])
    try:
        r = json.loads(llm.chat([{"role": "system", "content": PROMPT_RESUMO}, {"role": "user", "content": texto_conv}],
                                temperatura=0.1, max_tokens=150, formato="json"))
        titulo = (r.get("titulo") or "").strip().strip('"')
        conversa.definir_resumo(cid, (r.get("resumo") or "").strip(), titulo if c["n_msgs"] <= 4 and titulo else None, c["n_msgs"])
    except Exception:
        pass
    mem = ler(login)
    if not mem["ativa"]:
        return
    falas = [m["conteudo"][:400] for m in msgs if m["papel"] == "user"][-8:]
    atual = "\n".join(f"- {f}" for f in mem["fatos"]) or "(vazia)"
    try:
        r = json.loads(llm.chat([{"role": "system", "content": PROMPT_FATOS},
                                 {"role": "user", "content": f"MEMÓRIA ATUAL:\n{atual}\n\nMENSAGENS DO USUÁRIO:\n" +
                                  "\n".join(f"{i}. {f}" for i, f in enumerate(falas, 1))}],
                                temperatura=0, max_tokens=300, formato="json"))
        novos = [n for n in (r.get("novos_fatos") or []) if isinstance(n, str) and _fato_valido(n)]
        mem2 = ler(login)                           # relê: o usuário pode ter editado no meio
        limpos = [f for f in mem2["fatos"] if not f.strip().endswith("?")]
        if mem2["ativa"] and (novos or len(limpos) != len(mem2["fatos"])):
            salvar(login, _mesclar(limpos, novos, []), True)
    except Exception:
        pass

def apos_resposta(login, cid):
    c = conversa.obter(cid)
    if c and (c["n_msgs"] - c["resumo_n"] >= conversa.RESUMIR_A_CADA or c["n_msgs"] == 2):
        fila.adicionar(("memoria", cid), aprender, login, cid)
