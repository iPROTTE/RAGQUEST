"""Conversa com o modelo local (Ollama): classificação, reescrita, respostas em streaming."""
import datetime, json, re
import httpx, numpy as np
from .config import OLLAMA_URL, CHAT_MODEL, EMBED_MODEL

NUM_CTX = 8192
NAO = "NAO_ENCONTRADO"
KEEP = "30m"   # mantém o modelo carregado (menos recargas = mais rápido)

def embed(texts):
    vecs = []
    for i in range(0, len(texts), 32):
        r = httpx.post(f"{OLLAMA_URL}/api/embed", json={"model": EMBED_MODEL, "input": texts[i:i + 32], "keep_alive": KEEP}, timeout=300)
        r.raise_for_status()
        vecs.extend(r.json()["embeddings"])
    a = np.asarray(vecs, dtype=np.float32)
    return a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-9)

def chat(msgs, temperatura=0.3, max_tokens=None, formato=None, timeout=600):
    opts = {"temperature": temperatura, "num_ctx": NUM_CTX}
    if max_tokens:
        opts["num_predict"] = max_tokens
    body = {"model": CHAT_MODEL, "stream": False, "messages": msgs, "options": opts, "keep_alive": KEEP}
    if formato:
        body["format"] = formato
    r = httpx.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()["message"]["content"].strip()

def chat_stream(msgs, temperatura=0.3):
    body = {"model": CHAT_MODEL, "stream": True, "messages": msgs, "keep_alive": KEEP,
            "options": {"temperature": temperatura, "num_ctx": NUM_CTX}}
    with httpx.stream("POST", f"{OLLAMA_URL}/api/chat", json=body, timeout=600) as r:
        r.raise_for_status()
        for linha in r.iter_lines():
            if not linha:
                continue
            d = json.loads(linha)
            pedaco = d.get("message", {}).get("content", "")
            if pedaco:
                yield pedaco
            if d.get("done"):
                break

# ---------------------------------------------------------------- conversa x conhecimento
_SOCIAL = re.compile(r"""\b(oi+|ol[aá]|opa|e\s*a[ií]|eae|bom\s+dia|boa\s+(tarde|noite)|tudo\s+(bem|bom|certo|joia|tranquilo)|
    blz|beleza|valeu|vlw|obrigad[oa]|brigad[oa]|muito|show|top|perfeito|[oó]timo|legal|massa|entendi|ok(ay)?|certo|
    tchau|at[eé]\s+(mais|logo|amanh[aã])|falou|fui|kk+|haha+|rs+|e\s+(voc[eê]|vc|a[ií])|com\s+(voc[eê]|vc)|pela\s+ajuda|
    ajudou|demais|sim|n[aã]o|claro|pois\s+[eé]|boa|bom)\b""", re.I | re.X)

def _so_social(m):
    total = len(re.findall(r"\w+", m))
    resto = len(re.findall(r"\w+", _SOCIAL.sub(" ", m)))
    return total > 0 and (resto == 0 or (resto == 1 and total >= 3))

_META = re.compile(r"""(qual\s+(é\s+)?o?\s*seu\s+nome|quem\s+(é|e)\s+voc[eê]|o\s+que\s+voc[eê]\s+(sabe|faz|pode)|
    como\s+voc[eê]\s+funciona|voc[eê]\s+(lembra|se\s+lembra|sabe\s+quem)|lembra\s+de\s+mim|quem\s+sou\s+eu|
    (resum[ea]|recapitul[ea])\s+(a\s+|nossa\s+|essa\s+|esta\s+)?(conversa|o\s+que\s+(conversamos|falamos))|
    meu\s+nome\s+(é|e)|me\s+chamo|eu\s+sou\s+(o|a)\s+\w+)""", re.I | re.X)

PROMPT_CLASSE = """Classifique a ÚLTIMA mensagem do usuário para um assistente técnico de uma empresa.
CONVERSA = cumprimento, despedida, agradecimento, apresentação pessoal, elogio, papo informal, perguntas sobre o assistente (quem é, o que sabe fazer), sobre o próprio usuário (lembra de mim?) ou sobre esta conversa (resuma, o que eu perguntei).
CONHECIMENTO = pede informação técnica, procedimento, comando, valor, norma, explicação de um conceito ou qualquer fato do mundo.
Responda com UMA palavra: CONVERSA ou CONHECIMENTO."""

_TECNICO = re.compile(r"\b(como|qual|quais|onde|quando|por\s*que|quanto|o\s+que|configur\w*|comando\w*|ativ\w*|provision\w*|instal\w*|onu|olt|erro|problema|procedimento|pop|manual)\b", re.I)

def classificar(msg, ultima_resposta=""):
    m = msg.strip()
    if _META.search(m) or (_so_social(m) and not _TECNICO.search(m)):
        return "conversa"
    try:
        u = (f'Resposta anterior do assistente: "{ultima_resposta[:300]}"\n\n' if ultima_resposta else "") + f'Mensagem do usuário: "{m}"'
        r = chat([{"role": "system", "content": PROMPT_CLASSE}, {"role": "user", "content": u}], temperatura=0, max_tokens=5)
        return "conversa" if "CONVERSA" in r.upper() else "conhecimento"
    except Exception:
        return "conhecimento"

PROMPT_REESCREVER = """Reescreva a última mensagem do usuário como uma pergunta completa e independente, usando o contexto da conversa (assunto, fabricante, equipamento). Não responda a pergunta. Responda só com a pergunta reescrita."""

def reescrever(msg, historico):
    """'e na ZTE?' -> 'Qual a potência mínima para ativar uma ONU ZTE?' (só para a busca)."""
    if not historico or len(msg.split()) > 14:
        return msg
    conv = "\n".join(("Usuário: " if h["role"] == "user" else "Assistente: ") + h["content"][:300] for h in historico[-4:])
    try:
        r = chat([{"role": "system", "content": PROMPT_REESCREVER},
                  {"role": "user", "content": f"Conversa:\n{conv}\n\nÚltima mensagem: {msg}"}], temperatura=0, max_tokens=80)
        r = r.strip().strip('"').splitlines()[0] if r.strip() else ""
        return r if 3 < len(r) < 300 else msg
    except Exception:
        return msg

# ---------------------------------------------------------------- respostas
_DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]

def sistema(nome, estilo="", memoria="", conversas="", catalogo="", agente=None):
    hoje = datetime.date.today()
    if agente:
        quem = f"Você é o {agente['nome']}, um agente do Ragquest" + (f" ({agente['descricao']})" if agente.get("descricao") else "") + "."
        extra = f"\n\nINSTRUÇÕES DO ADMINISTRADOR PARA ESTE AGENTE\n{agente['instrucoes']}" if agente.get("instrucoes") else ""
    else:
        quem, extra = "Você é o Ragquest, o assistente de conhecimento da empresa.", ""
    return f"""{quem} Converse de forma natural, cordial e fluida, em português do Brasil, como um colega experiente e prestativo. Não diga que é um modelo de linguagem.{extra}
Hoje é {_DIAS[hoje.weekday()]}, {hoje.strftime('%d/%m/%Y')}. Você está conversando com {nome}.

O QUE VOCÊ SABE (documentos da base de conhecimento)
{catalogo or '(a base ainda não tem documentos)'}

MEMÓRIA SOBRE {nome.upper()}
{memoria or '(ainda não sei nada sobre esta pessoa)'}

CONVERSAS ANTERIORES COM {nome.upper()}
{conversas or '(nenhuma)'}
{estilo}"""

REGRAS = {
    "conversa": """
COMO RESPONDER AGORA
Esta mensagem é de conversa. Responda com naturalidade e simpatia, sem citar documentos. Use a memória para mostrar que se lembra da pessoa quando fizer sentido, sem exagerar.
Se perguntarem o que você sabe, descreva a sua área e os assuntos da base de conhecimento acima.
Você só tem acesso ao conhecimento listado em "O QUE VOCÊ SABE". Se perguntarem se você conhece um assunto que não está lá, diga com sinceridade que esse conhecimento não está na sua base e que pode pesquisar na internet, sem incorporar o resultado ao seu conhecimento.
Nunca invente valores, comandos ou procedimentos técnicos: se a pessoa pedir algo técnico, diga que pode procurar nos documentos.""",
    "documentos": f"""
COMO RESPONDER AGORA
Use SOMENTE os TRECHOS DOS DOCUMENTOS enviados com a mensagem e cite as fontes com [1], [2]... Não liste as referências no final (o sistema já mostra).
Seja natural e direto; use passos numerados para procedimentos e não omita alertas de segurança.
Em cálculos, use a fórmula e o exemplo dos documentos, faça a conta passo a passo e só dê o resultado depois de calcular (confira se o número final bate com a conta).
Nunca use LaTeX nem símbolos como \\[ \\]; escreva fórmulas em texto simples (ex.: Potência = Consumo ÷ HSP).
Nunca invente valores, comandos ou passos. Se os trechos não contêm a informação pedida, responda exatamente {NAO} e nada mais.""",
    "web": """
COMO RESPONDER AGORA
Os documentos internos não tinham a resposta, então você recebeu trechos de páginas da internet.
Comece avisando, de forma natural, que não encontrou nos documentos internos e que a resposta vem da internet.
{AVISO_WEB}
Use apenas esses trechos e cite as fontes com [1], [2]... Não liste as referências no final. Nunca use LaTeX; fórmulas em texto simples.
Se os trechos não respondem, diga que não encontrou nem nos documentos nem na internet.""",
}

def _contexto(hits, web):
    def cab(h):
        if web:
            return f"{h['title']} ({h['url']})"
        if (h.get('page') or 0) < 0:
            return f"{h['title']} (resumo do documento)"
        return f"{h['title']} (v{h['version']}{', pág. ' + str(h['page']) if (h.get('page') or 0) > 0 else ''})"
    return "\n\n".join(f"[{i}] {cab(h)}\n{h['content']}" for i, h in enumerate(hits, 1))

def responder(modo, msg, hits, historico, sistema_txt, aviso=""):
    """Gera a resposta em pedaços. modo: conversa | documentos | web."""
    regras = REGRAS[modo].replace("{AVISO_WEB}", aviso)
    msgs = [{"role": "system", "content": sistema_txt + regras}] + list(historico or [])
    if modo == "conversa":
        msgs.append({"role": "user", "content": msg})
    else:
        rot = "TRECHOS DE PÁGINAS DA INTERNET" if modo == "web" else "TRECHOS DOS DOCUMENTOS"
        msgs.append({"role": "user", "content": f"{rot}:\n{_contexto(hits, modo == 'web')}\n\nMENSAGEM DO USUÁRIO: {msg}"})
    return chat_stream(msgs, temperatura=0.4 if modo == "conversa" else 0.2)

PROMPT_ESCOPO = """Você decide se uma pergunta pertence à área de atuação de um agente de uma empresa.
Considere o nome, a descrição, as instruções e os documentos do agente. Perguntas genéricas da mesma área contam como DENTRO.
Responda com UMA palavra: DENTRO ou FORA."""

def no_escopo(msg, agente, catalogo):
    """True se o assunto é da área do agente (ou se não dá para saber)."""
    if not agente:
        return True
    info = (f"AGENTE: {agente['nome']}\nDESCRIÇÃO: {agente.get('descricao') or '(sem descrição)'}\n"
            f"INSTRUÇÕES: {(agente.get('instrucoes') or '(nenhuma)')[:600]}\nDOCUMENTOS DO AGENTE:\n{catalogo or '(nenhum ainda)'}")
    try:
        r = chat([{"role": "system", "content": PROMPT_ESCOPO},
                  {"role": "user", "content": f"{info}\n\nPERGUNTA: {msg}"}], temperatura=0, max_tokens=5)
        return "FORA" not in r.upper()
    except Exception:
        return True

_SIM = re.compile(r"^\W*(sim|s|pode|pode\s+sim|pesquis\w*|quero|ok|claro|manda|vai|busca|procura|isso|por\s+favor|beleza|bora)\b", re.I)

def aceitou(msg):
    return bool(_SIM.match(msg.strip())) and len(msg.split()) <= 8

def eh_nao(texto):
    t = texto.strip().upper().replace("Ã", "A").replace(" ", "_")
    return t.startswith(NAO) or (NAO in t and len(t) < 40)
