import os, json, re, threading, time, datetime, traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException, Depends, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel
from . import config, db, extract, ingest as ing, search, llm, pasta, web, licenca, perfis, preparo, contas, rede, conversa, memoria, conhecimento, fila, agentes, tunel

def _token(authorization: str = Header(default="")):
    return authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""

def usuario_atual(authorization: str = Header(default="")):
    """Exige licença válida e um usuário logado."""
    if not licenca.valida():
        raise HTTPException(402, licenca.estado()["motivo"] or "Ragquest não está ativado.")
    if contas.total() == 0:
        raise HTTPException(409, "O Ragquest ainda não foi configurado. Crie o administrador no servidor.")
    u = contas.por_token(_token(authorization))
    if not u:
        raise HTTPException(401, "Faça login para continuar.")
    return u

def admin_atual(u: dict = Depends(usuario_atual)):
    if u["papel"] != "admin":
        raise HTTPException(403, "Apenas o administrador pode fazer isso.")
    return u

auth = usuario_atual   # compatibilidade

def recrawl():
    """Re-lê as URLs cadastradas; só reindexa se o conteúdo mudou."""
    with db.conn() as c:
        rows = c.execute("SELECT slug,title,tipo,setor,source_url,agente FROM documents WHERE active=1 AND source_url IS NOT NULL").fetchall()
    out = []
    for slug, title, tipo, setor, url, agente in rows:
        try:
            out.append((url, ing.ingest(slug, title, tipo, setor, url, extract.from_url(url), agente=agente)[2]))
        except Exception as e:
            out.append((url, f"erro: {e}"))
    return out

def _agendador():
    last = None
    while True:
        now = datetime.datetime.now()
        if now.hour == config.RECRAWL_HOUR and last != now.date():
            last = now.date()
            try: recrawl()
            except Exception: traceback.print_exc()
        time.sleep(600)

def _completar_skills():
    """Quando os modelos estiverem prontos, escreve as skills dos documentos que ainda não têm."""
    while not (licenca.valida() and preparo.pronto()):
        time.sleep(20)
    time.sleep(30)
    try: conhecimento.completar()
    except Exception: traceback.print_exc()

@asynccontextmanager
async def lifespan(_):
    db.init()
    contas.init()
    conversa.init()
    agentes.init()
    pasta.criar_pastas()
    perfis.preparar()
    fila.iniciar()
    threading.Thread(target=_completar_skills, daemon=True).start()
    threading.Thread(target=pasta.loop, daemon=True).start()
    threading.Thread(target=_agendador, daemon=True).start()
    tunel.iniciar()          # acesso externo (Cloudflare), se estiver ligado
    yield
    tunel.parar()

app = FastAPI(title="Ragquest", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

_CF = ("cf-connecting-ip", "cf-ray", "cf-ipcountry", "cdn-loop")

def _local(req: Request):
    """Só o próprio computador. Pedidos que chegam pelo túnel da Cloudflare também vêm de 127.0.0.1,
    mas trazem cabeçalhos da Cloudflare: esses NUNCA contam como locais."""
    if any(h in req.headers for h in _CF):
        return False
    return req.client is not None and req.client.host in ("127.0.0.1", "::1", "localhost")

def _ip(req: Request):
    return req.headers.get("cf-connecting-ip") or (req.client.host if req.client else "?")

# bloqueio de tentativas de senha (importante com o acesso pela internet ligado)
_falhas = {}            # chave -> [timestamps]
_MAX_FALHAS, _JANELA = 5, 15 * 60

def _bloqueado(*chaves):
    agora = time.time()
    for k in chaves:
        _falhas[k] = [t for t in _falhas.get(k, []) if agora - t < _JANELA]
        if len(_falhas[k]) >= _MAX_FALHAS:
            return int((_JANELA - (agora - _falhas[k][0])) / 60) + 1
    return 0

@app.get("/licenca")
def ver_licenca(request: Request):
    st = dict(licenca.estado())
    st["versao"] = config.VERSAO
    st["local"] = _local(request)
    return st

@app.get("/preparo")
def ver_preparo():
    return preparo.status()

@app.post("/preparo/iniciar")
def iniciar_preparo():
    preparo.iniciar()
    return preparo.status()

@app.post("/desligar", include_in_schema=False)
def desligar(request: Request):
    """Usado pelo instalador/desinstalador e pelo atalho 'Parar Ragquest'."""
    if not _local(request):
        raise HTTPException(403, "Só no próprio computador.")
    tunel.parar()
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return {"ok": True}

# ---------------------------------------------------------------- contas e login
@app.get("/auth/estado")
def auth_estado(request: Request, authorization: str = Header(default="")):
    u = contas.por_token(_token(authorization)) if contas.total() else None
    return {"precisa_setup": contas.total() == 0, "local": _local(request), "usuario": u}

class Setup(BaseModel):
    nome: str
    login: str
    senha: str

@app.post("/auth/setup")
def auth_setup(b: Setup, request: Request):
    """Cria o primeiro administrador. Só no próprio servidor e só se ainda não houver usuários."""
    if not _local(request):
        raise HTTPException(403, "O administrador deve ser criado no computador onde o Ragquest está instalado.")
    if not licenca.valida():
        raise HTTPException(402, "Ative o Ragquest primeiro.")
    if contas.total() > 0:
        raise HTTPException(409, "O administrador já foi criado.")
    try:
        contas.criar(b.nome, b.login, b.senha, "admin")
        token, u = contas.entrar(b.login, b.senha)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"token": token, "usuario": u}

class Login(BaseModel):
    login: str
    senha: str

@app.post("/auth/login")
def auth_login(b: Login, request: Request):
    if not licenca.valida():
        raise HTTPException(402, licenca.estado()["motivo"] or "Ragquest não está ativado.")
    externo = any(h in request.headers for h in _CF)
    kip, klog = "ip:" + _ip(request), "login:" + (b.login or "").strip().lower()
    # o bloqueio por login só vale para quem vem da internet: um ataque de fora não tranca o funcionário na empresa
    chaves = (kip, klog) if externo else (kip,)
    min_ = _bloqueado(*chaves)
    if min_:
        raise HTTPException(429, f"Muitas tentativas de senha. Tente de novo em {min_} min.")
    try:
        token, u = contas.entrar(b.login, b.senha)
    except ValueError as e:
        if "incorretos" in str(e):
            for k in chaves:
                _falhas.setdefault(k, []).append(time.time())
        raise HTTPException(401, str(e))
    _falhas.pop(klog, None)
    return {"token": token, "usuario": u}

@app.post("/auth/sair")
def auth_sair(authorization: str = Header(default="")):
    contas.sair(_token(authorization))
    return {"ok": True}

class TrocaSenha(BaseModel):
    atual: str
    nova: str

@app.post("/auth/senha")
def auth_senha(b: TrocaSenha, u: dict = Depends(usuario_atual)):
    try:
        contas.trocar_propria_senha(u["id"], b.atual, b.nova)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"ok": True}

@app.get("/usuarios")
def usuarios_listar(u: dict = Depends(admin_atual)):
    lista = contas.listar()
    for x in lista:
        x["agentes"] = agentes.acessos_de(x["id"])
    return {"usuarios": lista, "ativos": contas.ativos(), "limite": contas.limite()}

class NovoUsuario(BaseModel):
    nome: str
    login: str
    senha: str
    papel: str = "usuario"
    agentes: list[int] | None = None

@app.post("/usuarios")
def usuarios_criar(b: NovoUsuario, u: dict = Depends(admin_atual)):
    try:
        novo = contas.criar(b.nome, b.login, b.senha, b.papel)
        agentes.definir_acesso(novo["id"], b.agentes if b.agentes is not None else [a["id"] for a in agentes.listar()[:1]])
        return novo
    except ValueError as e:
        raise HTTPException(422, str(e))

class EditaUsuario(BaseModel):
    nome: str | None = None
    papel: str | None = None
    ativo: bool | None = None
    senha: str | None = None
    agentes: list[int] | None = None

@app.put("/usuarios/{uid}")
def usuarios_alterar(uid: int, b: EditaUsuario, u: dict = Depends(admin_atual)):
    try:
        r = contas.alterar(uid, b.nome, b.papel, b.ativo, b.senha)
        if b.agentes is not None:
            agentes.definir_acesso(uid, b.agentes)
        return r
    except ValueError as e:
        raise HTTPException(422, str(e))

@app.delete("/usuarios/{uid}")
def usuarios_excluir(uid: int, u: dict = Depends(admin_atual)):
    if uid == u["id"]:
        raise HTTPException(422, "Você não pode excluir a sua própria conta.")
    alvo = contas.obter(uid)
    try:
        contas.excluir(uid)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if alvo:
        conversa.apagar_todas(alvo["login"])
        memoria.apagar(alvo["login"])
    return {"ok": True}

class Ativacao(BaseModel):
    chave: str

@app.post("/licenca")
def ativar(b: Ativacao, request: Request, authorization: str = Header(default="")):
    if not _local(request):   # pela rede, só um administrador logado pode trocar a licença
        u = contas.por_token(_token(authorization))
        if not u or u["papel"] != "admin":
            raise HTTPException(403, "A ativação deve ser feita no servidor ou por um administrador.")
    ok, r = licenca.ativar(b.chave)
    if not ok:
        raise HTTPException(422, r)
    threading.Thread(target=pasta.varrer, daemon=True).start()
    return r

def _err(e):
    if isinstance(e, ValueError):
        raise HTTPException(422, str(e))
    traceback.print_exc()
    raise HTTPException(500, f"{type(e).__name__}: {e}")

_STATIC = os.path.join(os.path.dirname(__file__), "static")

# ---------------------------------------------------------------- modo servidor (acesso pela rede)
@app.get("/rede")
def ver_rede(request: Request, u: dict = Depends(admin_atual)):
    st = rede.status()
    st["local"] = _local(request)
    return st

@app.get("/rede/qr", dependencies=[Depends(admin_atual)])
def qr_rede(url: str):
    if len(url) > 300:
        raise HTTPException(422, "Endereço muito longo.")
    return Response(rede.qr_svg(url), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})

class RedeIn(BaseModel):
    ativo: bool | None = None
    iniciar_com_windows: bool | None = None
    liberar_firewall: bool | None = None

@app.post("/rede")
def mudar_rede(b: RedeIn, request: Request, u: dict = Depends(admin_atual)):
    """Liga/desliga o acesso pela rede. Só no próprio servidor (pede permissão do Windows para o firewall)."""
    if not _local(request):
        raise HTTPException(403, "Faça isso no computador onde o Ragquest está instalado.")
    out = {"reiniciando": False, "firewall": None}
    if b.iniciar_com_windows is not None:
        rede.definir_inicio(b.iniciar_com_windows)
    if b.liberar_firewall:
        out["firewall"] = rede.liberar_firewall()
    if b.ativo is not None and b.ativo != rede.ativo():
        if b.ativo:
            out["firewall"] = rede.liberar_firewall()
            if out["firewall"] is False:
                raise HTTPException(409, "O Windows não liberou o acesso (o pedido de permissão foi recusado). Tente de novo e clique em 'Sim'.")
        rede._gravar_cfg("ACESSO_REDE", "1" if b.ativo else "0")
        rede.reiniciar()
        out["reiniciando"] = True
    return out

# ---------------------------------------------------------------- acesso externo (internet, via Cloudflare)
@app.get("/externo")
def ver_externo(request: Request, u: dict = Depends(admin_atual)):
    st = tunel.status()
    st["local"] = _local(request)
    return st

class ExternoIn(BaseModel):
    ativo: bool | None = None
    modo: str | None = None
    token: str | None = None
    endereco: str | None = None

@app.post("/externo")
def mudar_externo(b: ExternoIn, request: Request, u: dict = Depends(admin_atual)):
    if not _local(request):
        raise HTTPException(403, "Faça isso no computador onde o Ragquest está instalado.")
    if b.modo == "fixo" and b.ativo and not ((b.token or "").strip() or tunel.cfg()["token"]):
        raise HTTPException(422, "Cole o token do túnel criado no painel da Cloudflare.")
    if b.modo == "fixo" and b.ativo and not ((b.endereco or "").strip() or tunel.cfg()["endereco"]):
        raise HTTPException(422, "Informe o endereço (ex.: ragquest.suaempresa.com.br).")
    tunel.configurar(b.ativo, b.modo, b.token if b.token else None, b.endereco)
    return tunel.status()

@app.get("/app/enderecos", include_in_schema=False)
def app_enderecos():
    """Endereços que o app guarda para trocar sozinho entre a rede da empresa e a internet."""
    internos = [e["url"] for e in (rede.enderecos() if rede.ativo() else []) if e["ordem"] in (0, 1)]
    return {"externo": tunel.endereco() or None, "internos": internos}

@app.get("/", include_in_schema=False)
def home():
    return FileResponse(os.path.join(_STATIC, "index.html"), headers={"Cache-Control": "no-store"})

_ICONES = {"icone-192.png", "icone-512.png", "icone-maskable-512.png", "apple-touch-icon.png"}

@app.get("/icones/{nome}", include_in_schema=False)
def icone(nome: str):
    if nome not in _ICONES:
        raise HTTPException(404)
    return FileResponse(os.path.join(_STATIC, nome), headers={"Cache-Control": "max-age=86400"})

_APK = os.path.join(_STATIC, "ragquest.apk")

@app.get("/app/info", include_in_schema=False)
def app_info():
    return {"android": os.path.exists(_APK)}

@app.get("/app/ragquest.apk", include_in_schema=False)
def app_apk():
    if not os.path.exists(_APK):
        raise HTTPException(404, "App Android não incluído nesta versão.")
    return FileResponse(_APK, media_type="application/vnd.android.package-archive", filename="Ragquest.apk")

@app.get("/manifest.webmanifest", include_in_schema=False)
def manifesto():
    return Response(json.dumps({
        "name": "Ragquest", "short_name": "Ragquest", "description": "Assistente de conhecimento",
        "start_url": "/", "scope": "/", "display": "standalone", "lang": "pt-BR",
        "background_color": "#f5f4f7", "theme_color": "#16538f",
        "icons": [{"src": "/icones/icone-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                  {"src": "/icones/icone-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                  {"src": "/icones/icone-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]},
        ensure_ascii=False), media_type="application/manifest+json")

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(os.path.join(_STATIC, "ragquest.ico"))

@app.post("/documents", dependencies=[Depends(admin_atual)])
def upload(file: UploadFile = File(...), tipo: str = Form("manual"), setor: str = Form(None), title: str = Form(None),
           agente: str = Form(None)):
    """Salva o arquivo na pasta de conhecimento e indexa na hora."""
    try:
        data = file.file.read()
        extract.from_file(file.filename, data)          # valida formato antes de salvar
        dest = pasta.salvar_upload(file.filename, data, tipo, agente)
        res = pasta.indexar_arquivo(dest)
        if res is None:
            raise ValueError(pasta.estado["erros"].get(pasta._rel(dest), "falha ao indexar"))
        d, v, st = res
    except Exception as e:
        _err(e)
    return {"id": d, "version": v, "status": st}

class Crawl(BaseModel):
    url: str
    tipo: str = "manual"
    setor: str | None = None
    title: str | None = None
    agente: str | None = None

@app.post("/crawl", dependencies=[Depends(admin_atual)])
def crawl(b: Crawl):
    try:
        ag = b.agente if b.agente and agentes.por_slug(b.agente) else agentes.GERAL
        d, v, st = ing.ingest(b.url, b.title or b.url, b.tipo, b.setor, b.url, extract.from_url(b.url), agente=ag)
    except Exception as e:
        _err(e)
    return {"id": d, "version": v, "status": st}

@app.get("/documents", dependencies=[Depends(auth)])
def list_docs(tipo: str | None = None, setor: str | None = None):
    with db.conn() as c:
        r = c.execute("""SELECT id,title,tipo,setor,version,source_url,created_at,slug,agente FROM documents
                         WHERE active=1 AND (? IS NULL OR tipo=?) AND (? IS NULL OR setor=?) ORDER BY title""",
                      (tipo, tipo, setor, setor)).fetchall()
    out = []
    for x in r:
        d = dict(zip(["id", "title", "tipo", "setor", "version", "source_url", "created_at"], x[:7]))
        d["origem"] = x[7][6:] if x[7].startswith("pasta:") else (x[5] or "")
        d["agente"] = x[8]
        out.append(d)
    return out

@app.get("/pasta", dependencies=[Depends(auth)])
def status_pasta():
    return {"caminho": config.KNOWLEDGE_DIR, "ultima_varredura": pasta.estado["ultima"],
            "processando": pasta.estado["processando"], "erros": pasta.estado["erros"]}

@app.post("/pasta/varrer", dependencies=[Depends(admin_atual)])
def varrer_agora():
    return pasta.varrer()

@app.delete("/documents/{doc_id}", dependencies=[Depends(admin_atual)])
def delete(doc_id: int):
    slug = ing.slug_of(doc_id)
    if slug:
        if slug.startswith("pasta:"):
            pasta.mover_para_lixeira(slug[6:])   # arquivo vai para a pasta "lixeira"
        ing.delete_slug(slug)
    return {"deleted": doc_id}

class Query(BaseModel):
    question: str
    tipo: str | None = None
    setor: str | None = None
    conversa_id: int | None = None
    agente: str | None = None
    pesquisar_web: bool = False          # usuário aceitou pesquisar fora do escopo (não incorpora)

def _fontes_docs(hits):
    return [{"n": i, "title": h["title"], "version": h["version"],
             "page": h["page"] if (h.get("page") or 0) > 0 else None, "doc_id": h["doc_id"]} for i, h in enumerate(hits, 1)]

def _citadas(fontes, resposta):
    """Mostra só as fontes que a resposta citou ([1], [2]...); se não citou nenhuma, mostra todas."""
    nums = {int(n) for grupo in re.findall(r"\[(\d+(?:\s*,\s*\d+)*)\]", resposta) for n in re.findall(r"\d+", grupo)}
    usadas = [f for f in fontes if f["n"] in nums]
    return usadas or fontes

def _fontes_web(wh):
    src, seen = [], {}
    for i, h in enumerate(wh, 1):                       # agrupa trechos da mesma página
        if h["url"] in seen:
            seen[h["url"]]["n"] += f",{i}"
        else:
            seen[h["url"]] = {"n": str(i), "title": h["title"], "url": h["url"]}
            src.append(seen[h["url"]])
    return src

def _repassar(gerador, detectar_nao):
    """Repassa os pedaços da resposta. Se o modelo responder NAO_ENCONTRADO, para e devolve None."""
    buf, texto, liberado = "", "", not detectar_nao
    for p in gerador:
        texto += p
        if liberado:
            yield {"t": "delta", "texto": p}
            continue
        buf += p
        if len(buf.strip()) >= 16 or "\n" in buf.strip():
            if llm.eh_nao(buf):
                gerador.close()
                return None
            liberado = True
            yield {"t": "delta", "texto": buf}
    if not liberado:
        if not buf.strip() or llm.eh_nao(buf):
            return None
        yield {"t": "delta", "texto": buf}
    return texto.strip() or None

def pipeline(u, msg, cid=None, tipo=None, setor=None, agente=None, pesquisar_web=False):
    """Gera eventos: inicio, status, delta (texto), fim. Salva a conversa e alimenta a memória."""
    msg = (msg or "").strip()
    if not msg:
        raise HTTPException(422, "Mensagem vazia.")
    login, nome = u["login"], u["nome"]
    if cid:
        try:
            conversa.dono(cid, login)
            agente = (conversa.obter(cid) or {}).get("agente") or agente
        except LookupError:
            cid = None
    ag = agentes.escolher(u, agente)
    if not ag:
        raise HTTPException(403, "Você não tem acesso a este agente. Fale com o administrador.")
    if not cid:
        cid = conversa.criar(login, msg, ag["slug"])
    hist = conversa.historico(cid, 10)
    pergunta_ant, origem_ant = conversa.ultima_troca(cid)
    if not pesquisar_web and origem_ant == "fora_escopo" and llm.aceitou(msg):
        pesquisar_web, busca_externa = True, pergunta_ant      # "sim, pode pesquisar"
    else:
        busca_externa = msg
    conversa.adicionar(cid, "user", msg)
    yield {"t": "inicio", "conversa_id": cid, "agente": ag["slug"]}

    mem_on = memoria.ler(login)["ativa"]
    sis = llm.sistema(nome.split()[0] if nome else login,
                      estilo=perfis.instrucoes(login, nome),
                      memoria=memoria.texto(login) if mem_on else "",
                      conversas=memoria.bloco_conversas(login, cid, ag["slug"]) if mem_on else "",
                      catalogo=conhecimento.catalogo(agentes.areas(ag)), agente=ag)
    ultima = hist[-1]["content"] if hist and hist[-1]["role"] == "assistant" else ""
    resposta, fontes, origem, sugerir, oferecer = None, [], "conversa", False, False
    web_ok = config.WEB_FALLBACK and ag["busca_web"]
    aviso_externo = ("Avise também, em uma frase, que esta pesquisa serve só para esta resposta e NÃO foi incorporada "
                     f"ao conhecimento do agente {ag['nome']}.")
    if pesquisar_web:
        if not web_ok:
            resposta = f"A busca na internet está desligada para o agente {ag['nome']}. Fale com o administrador se precisar dela."
            yield {"t": "delta", "texto": resposta}
            origem = "nenhuma"
        else:
            yield {"t": "status", "texto": "Pesquisando na internet..."}
            wh = web.contexto(llm.reescrever(busca_externa, hist) if busca_externa != msg else busca_externa)
            if wh:
                resposta = yield from _repassar(llm.responder("web", busca_externa, wh, hist, sis, aviso_externo), False)
                fontes, origem = _fontes_web(wh), "web_externa"     # não oferece incorporar
            if not resposta:
                resposta = "Pesquisei na internet, mas não encontrei nada confiável sobre isso."
                origem = "nenhuma"
                yield {"t": "delta", "texto": resposta}
    elif llm.classificar(msg, ultima) == "conversa":
        resposta = yield from _repassar(llm.responder("conversa", msg, [], hist, sis), False)
    else:
        yield {"t": "status", "texto": "Procurando nos documentos..."}
        busca = llm.reescrever(msg, hist)
        hits, best = search.hybrid(busca, tipo=tipo, setor=setor, areas=agentes.areas(ag))
        if hits and best >= config.MIN_SIM:
            resposta = yield from _repassar(llm.responder("documentos", msg, hits, hist, sis), True)
            if resposta:
                fontes, origem = _citadas(_fontes_docs(hits), resposta), "documentos"
        if not resposta and not llm.no_escopo(busca, ag, conhecimento.catalogo(agentes.areas(ag))):
            # assunto fora da área do agente: avisa e só pesquisa se o usuário pedir (sem incorporar)
            area = f" ({ag['descricao']})" if ag.get("descricao") else ""
            resposta = (f"Esse assunto foge da minha área{area}, então não tenho esse conhecimento na minha base. " +
                        ("Se quiser, posso pesquisar na internet: a pesquisa serve só para esta resposta e não será incorporada ao meu conhecimento."
                         if web_ok else "Procure o agente responsável por esse assunto."))
            origem, oferecer = "fora_escopo", web_ok
            yield {"t": "delta", "texto": resposta}
        if not resposta and web_ok:
            yield {"t": "status", "texto": "Não achei nos documentos. Procurando na internet..."}
            wh = web.contexto(busca)
            if wh:
                resposta = yield from _repassar(llm.responder("web", msg, wh, hist, sis), False)
                fontes, origem = _fontes_web(wh), "web"
                sugerir = u["papel"] == "admin"     # NADA é indexado sem o usuário aprovar
        if not resposta:
            resposta = ("Não encontrei isso nos meus documentos" +
                        (" nem na internet." if web_ok else ".") +
                        " Se puder, me dê mais detalhes (fabricante, modelo, situação) que eu procuro de novo.")
            origem = "nenhuma"
            yield {"t": "delta", "texto": resposta}
    conversa.adicionar(cid, "assistant", resposta, fontes, origem)
    try:
        perfis.registrar_interacao(login, msg, hist, nome)
        memoria.apos_resposta(login, cid)
    except Exception:
        traceback.print_exc()
    c = conversa.obter(cid)
    yield {"t": "fim", "conversa_id": cid, "titulo": c["titulo"] if c else "", "fontes": fontes,
           "origem": origem, "sugerir_indexar": sugerir, "oferecer_web": oferecer, "resposta": resposta}

@app.post("/chat")
def chat_stream(b: Query, u: dict = Depends(usuario_atual)):
    """Resposta em tempo real (uma linha JSON por evento)."""
    def gerar():
        try:
            for ev in pipeline(u, b.question, b.conversa_id, b.tipo, b.setor, b.agente, b.pesquisar_web):
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        except HTTPException as e:
            yield json.dumps({"t": "erro", "texto": e.detail}, ensure_ascii=False) + "\n"
        except Exception as e:
            traceback.print_exc()
            yield json.dumps({"t": "erro", "texto": f"Erro ao responder: {e}"}, ensure_ascii=False) + "\n"
    return StreamingResponse(gerar(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"})

@app.post("/query")
def query(b: Query, u: dict = Depends(usuario_atual)):
    """Mesma resposta, de uma vez (para integrações)."""
    try:
        fim = {}
        for ev in pipeline(u, b.question, b.conversa_id, b.tipo, b.setor, b.agente):
            if ev["t"] == "fim":
                fim = ev
        return {"answer": fim.get("resposta", ""), "sources": fim.get("fontes", []), "origem": fim.get("origem"),
                "sugerir_indexar": fim.get("sugerir_indexar", False), "conversa_id": fim.get("conversa_id")}
    except HTTPException:
        raise
    except Exception as e:
        _err(e)

# ---------------------------------------------------------------- conversas e memória
@app.get("/conversas")
def conversas_listar(agente: str | None = None, u: dict = Depends(usuario_atual)):
    return conversa.listar(u["login"], agente)

def _minha(cid, u):
    try:
        conversa.dono(cid, u["login"])
    except LookupError:
        raise HTTPException(404, "Conversa não encontrada.")

@app.get("/conversas/{cid}")
def conversas_ver(cid: int, u: dict = Depends(usuario_atual)):
    _minha(cid, u)
    c = conversa.obter(cid)
    return {"id": cid, "titulo": c["titulo"], "agente": c.get("agente"), "mensagens": conversa.mensagens(cid)}

class TituloIn(BaseModel):
    titulo: str

@app.put("/conversas/{cid}")
def conversas_renomear(cid: int, b: TituloIn, u: dict = Depends(usuario_atual)):
    _minha(cid, u)
    try: conversa.renomear(cid, b.titulo)
    except ValueError as e: raise HTTPException(422, str(e))
    return {"ok": True}

@app.delete("/conversas/{cid}")
def conversas_apagar(cid: int, u: dict = Depends(usuario_atual)):
    _minha(cid, u)
    conversa.apagar(cid)
    return {"ok": True}

@app.delete("/conversas")
def conversas_apagar_todas(u: dict = Depends(usuario_atual)):
    conversa.apagar_todas(u["login"])
    return {"ok": True}

@app.get("/memoria")
def memoria_ver(u: dict = Depends(usuario_atual)):
    m = memoria.ler(u["login"])
    return {"ativa": m["ativa"], "texto": "\n".join(m["fatos"]), "conversas": conversa.total(u["login"]),
            "resumos": len(conversa.resumos_recentes(u["login"], n=1000))}

class MemoriaIn(BaseModel):
    ativa: bool = True
    texto: str = ""

@app.put("/memoria")
def memoria_salvar(b: MemoriaIn, u: dict = Depends(usuario_atual)):
    memoria.salvar(u["login"], [l for l in b.texto.splitlines() if l.strip()], b.ativa)
    return {"ok": True}

@app.delete("/memoria")
def memoria_apagar(u: dict = Depends(usuario_atual)):
    ativa = memoria.ler(u["login"])["ativa"]
    memoria.apagar(u["login"])
    memoria.salvar(u["login"], [], ativa)
    return {"ok": True}

# ---------------------------------------------------------------- agentes
def _publico(a):
    return {k: a[k] for k in ("id", "slug", "nome", "icone", "descricao")}

@app.get("/agentes")
def agentes_meus(u: dict = Depends(usuario_atual)):
    return [_publico(a) for a in agentes.acessiveis(u)]

@app.get("/agentes/admin", dependencies=[Depends(admin_atual)])
def agentes_admin():
    with db.conn() as c:
        docs = dict(c.execute("SELECT agente, COUNT(*) FROM documents WHERE active=1 GROUP BY agente").fetchall())
    lista = []
    for a in agentes.listar():
        a = dict(a, documentos=docs.get(a["slug"], 0), usuarios=agentes.usuarios_de(a["id"]), caminho=agentes.caminho(a))
        lista.append(a)
    return {"agentes": lista, "limite": agentes.limite(), "geral": {"documentos": docs.get(agentes.GERAL, 0), "caminho": config.KNOWLEDGE_DIR}}

class AgenteIn(BaseModel):
    nome: str | None = None
    icone: str | None = None
    descricao: str | None = None
    instrucoes: str | None = None
    usa_geral: bool | None = None
    busca_web: bool | None = None

@app.post("/agentes", dependencies=[Depends(admin_atual)])
def agentes_criar(b: AgenteIn):
    try:
        return agentes.criar(b.nome or "", b.icone or "🤖", b.descricao or "", b.instrucoes or "",
                             bool(b.usa_geral), True if b.busca_web is None else b.busca_web)
    except ValueError as e:
        raise HTTPException(422, str(e))

@app.put("/agentes/{aid}", dependencies=[Depends(admin_atual)])
def agentes_alterar(aid: int, b: AgenteIn):
    try:
        with pasta._scan_lock:                       # não renomeia a pasta no meio de uma varredura
            r = agentes.alterar(aid, b.nome, b.icone, b.descricao, b.instrucoes, b.usa_geral, b.busca_web)
        search.invalidate()
        conhecimento.completar()
        return r
    except ValueError as e:
        raise HTTPException(422, str(e))

@app.delete("/agentes/{aid}", dependencies=[Depends(admin_atual)])
def agentes_excluir(aid: int):
    try:
        slugs = agentes.excluir(aid)
    except ValueError as e:
        raise HTTPException(422, str(e))
    for sl in slugs:
        ing.delete_slug(sl)
    return {"ok": True, "documentos_removidos": len(slugs)}

@app.post("/agentes/{aid}/abrir")
def agentes_abrir_pasta(aid: int, request: Request, u: dict = Depends(admin_atual)):
    """Abre a pasta do agente no Explorador (só no próprio servidor)."""
    if not _local(request):
        raise HTTPException(403, "Só funciona no computador onde o Ragquest está instalado.")
    a = agentes.obter(aid) if aid else None
    alvo = agentes.caminho(a) if a else config.KNOWLEDGE_DIR
    os.makedirs(alvo, exist_ok=True)
    if os.name == "nt":
        os.startfile(alvo)
    return {"ok": True, "caminho": alvo}

# ---------------------------------------------------------------- skills de conhecimento
@app.get("/conhecimento", dependencies=[Depends(admin_atual)])
def conhecimento_listar():
    return conhecimento.listar()

@app.get("/conhecimento/{doc_id}", dependencies=[Depends(admin_atual)])
def conhecimento_ver(doc_id: int):
    md = conhecimento.ler_md(doc_id)
    if md is None:
        raise HTTPException(404, "Skill ainda não gerada.")
    return {"md": md}

@app.post("/conhecimento/{doc_id}/gerar", dependencies=[Depends(admin_atual)])
def conhecimento_gerar(doc_id: int):
    conhecimento.agendar(doc_id, True)
    return {"ok": True}

# ---------------------------------------------------------------- perfis e skills
@app.get("/skills", dependencies=[Depends(auth)])
def listar_skills():
    return [{k: s[k] for k in ("id", "nome", "descricao")} for s in perfis.skills()]

@app.get("/perfil")
def ver_perfil(u: dict = Depends(usuario_atual)):
    p = perfis.ler(u["login"], u["nome"])
    return {"usuario": p["meta"]["usuario"], "estilo": p["meta"]["estilo"], "aprendizado": p["meta"]["aprendizado"] == "ligado",
            "interacoes": int(p["meta"].get("interacoes", 0) or 0), "md": p["md"]}

class PerfilIn(BaseModel):
    estilo: str = "auto"
    aprendizado: bool = True
    md: str | None = None

@app.put("/perfil")
def salvar_perfil(b: PerfilIn, u: dict = Depends(usuario_atual)):
    p = perfis.ler(u["login"], u["nome"])
    ids = {s["id"] for s in perfis.skills()}
    if b.estilo != "auto" and b.estilo not in ids:
        raise HTTPException(422, "Estilo desconhecido.")
    p["meta"].update(usuario=u["nome"], estilo=b.estilo, aprendizado="ligado" if b.aprendizado else "desligado")
    perfis.salvar(u["login"], p["meta"], b.md if b.md is not None else p["md"])
    return {"ok": True}

@app.delete("/perfil")
def apagar_perfil(u: dict = Depends(usuario_atual)):
    perfis.apagar(u["login"])
    return {"ok": True}

@app.post("/recrawl", dependencies=[Depends(admin_atual)])
def recrawl_now():
    return {"status": f"{len(recrawl())} URL(s) verificadas"}
