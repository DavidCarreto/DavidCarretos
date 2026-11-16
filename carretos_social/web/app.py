"""Dashboard web multiutilizador: visão geral, calendário, aprovação, criar, tarefas, assistente e equipa.

Cada pessoa entra com o seu utilizador. Permissões por conta, combináveis: criar e/ou aprovar.
O administrador (David) vê e faz tudo e gere a equipa. Arranque: `carretos web`.
"""
from __future__ import annotations

import calendar as cal
import hmac
import json
import os
import secrets
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeTimedSerializer

from ..config import DATA_DIR, ROOT, accounts, accounts_by_group, group_of, groups, load_env
from ..db import connect, get_post, media_paths, update_post
from . import jobs, mailer, users

load_env()
HERE = Path(__file__).parent
app = FastAPI(title="Carretos Social")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
tpl = Jinja2Templates(directory=HERE / "templates")

STATUS = {"idea": ("Ideia", "#7d8590"), "draft": ("Para aprovar", "#d29922"), "approved": ("Aprovado", "#3fb950"),
          "published": ("Publicado", "#D4AF37"), "failed": ("Falhou", "#f85149"),
          "assist_sent": ("Enviado p/ telemóvel", "#a371f7"), "rejected": ("Rejeitado", "#484f58")}
ICON = {"instagram": "IG", "tiktok": "TT", "facebook_profile": "FB", "facebook_page": "FB", "linkedin_member": "in",
        "linkedin_org": "in", "youtube": "YT"}
DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
SESSION_DAYS = 30


def _quando(dt) -> str:
    return f"{DIAS[dt.weekday()]} {dt:%d/%m %H:%M}" if dt else "sem data"


def _tema(pillar) -> str:
    from ..config import brand
    names = {p["id"]: p["name"] for p in brand().get("pillars", [])}
    return names.get(pillar or "", pillar or "Sem tema")


tpl.env.globals.update(STATUS=STATUS, ICON=ICON, accounts=accounts, tema=_tema, groups=groups,
                       accounts_by_group=accounts_by_group, group_of=group_of,
                       LEVELS=users.LEVELS, LEVEL_LABELS=users.LEVEL_LABELS)
tpl.env.filters["quando"] = _quando


# ------------------------------------------------------------------ sessão
def _secret() -> str:
    if os.environ.get("DASHBOARD_SECRET"):
        return os.environ["DASHBOARD_SECRET"]
    f = DATA_DIR / ".session_secret"
    if not f.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        f.write_text(secrets.token_hex(32))
        f.chmod(0o600)
    return f.read_text().strip()


def _signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_secret(), salt="carretos-session")


def _set_session(resp, user_id: int) -> None:
    resp.set_cookie("cs", _signer().dumps({"u": user_id}), max_age=SESSION_DAYS * 86400, httponly=True,
                    samesite="lax", secure=os.environ.get("DASHBOARD_HTTPS", "") == "1")


def _current_user(request: Request) -> users.User | None:
    token = request.cookies.get("cs")
    if not token:
        return None
    try:
        data = _signer().loads(token, max_age=SESSION_DAYS * 86400)
    except BadSignature:
        return None
    return users.load(int(data.get("u", 0)))


def _render(request: Request, name: str, ctx: dict):
    ctx.setdefault("page", "")
    ctx["me"] = request.state.user
    return tpl.TemplateResponse(request, name, ctx)


@app.middleware("http")
async def auth(request: Request, call_next):
    request.state.user = None
    open_paths = ("/login", "/static", "/configurar", "/recuperar", "/repor")
    users.bootstrap_admin()
    if users.count() == 0:  # ainda não há administrador: 1.ª configuração
        if not request.url.path.startswith(open_paths):
            return RedirectResponse("/configurar", 303)
        return await call_next(request)
    user = _current_user(request)
    request.state.user = user
    if user is None and not request.url.path.startswith(open_paths):
        return RedirectResponse("/login", 303)
    if user and user.must_change and not request.url.path.startswith(("/conta", "/sair", "/static")):
        return RedirectResponse("/conta?primeira=1", 303)   # palavra-passe temporária: tem de a mudar
    return await call_next(request)


def _forbidden(msg: str = "Não tens permissão para isto.") -> HTMLResponse:
    return HTMLResponse(f"<body style='background:#000;color:#fff;font-family:sans-serif;padding:24px'>"
                        f"<h3>{msg}</h3><a style='color:#D4AF37' href='/'>Voltar</a></body>", 403)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, erro: str = ""):
    return tpl.TemplateResponse(request, "login.html", {"erro": erro})


@app.post("/login")
def login(username: str = Form("david"), password: str = Form(...)):
    ident = username.strip()
    if "@" in ident:  # também se pode entrar com o email
        uid = users.find_by_email(ident)
        u = users.load(uid) if uid else None
        ident = u.username if u else ident
    user = users.authenticate(ident, password)
    if not user:
        return RedirectResponse("/login?erro=1", 303)
    r = RedirectResponse("/", 303)
    _set_session(r, user.id)
    return r


# ------------------------------------------------------------------ esqueci-me da palavra-passe
def _base_url(request: Request) -> str:
    f = ROOT / "ENDERECO_DASHBOARD.txt"
    if f.exists() and f.read_text().strip():
        return f.read_text().strip().rstrip("/")
    return str(request.base_url).rstrip("/")


@app.get("/recuperar", response_class=HTMLResponse)
def forgot_page(request: Request, enviado: str = ""):
    return tpl.TemplateResponse(request, "forgot.html", {"enviado": enviado, "email_ok": mailer.configured()})


@app.post("/recuperar")
def forgot(request: Request, email: str = Form(...)):
    uid = users.find_by_email(email)
    if uid and mailer.configured():
        token = users.create_reset_token(uid)
        link = f"{_base_url(request)}/repor?codigo={token}"
        try:
            mailer.send(users.normalize_email(email), "Repor a palavra-passe",
                        f"Olá,\n\nPediste para repor a palavra-passe do dashboard das redes sociais.\n"
                        f"Abre este link (válido durante {users.RESET_MINUTES} minutos, uso único):\n\n{link}\n\n"
                        f"Se não foste tu, ignora este email.")
        except Exception:  # noqa: BLE001 — não revela se o email existe
            pass
    # resposta sempre igual: não revela se o email está registado
    return RedirectResponse("/recuperar?enviado=1", 303)


@app.get("/repor", response_class=HTMLResponse)
def reset_page(request: Request, codigo: str = "", erro: str = ""):
    valido = bool(users.reset_user_for(codigo))
    return tpl.TemplateResponse(request, "reset.html", {"codigo": codigo, "valido": valido, "erro": erro})


@app.post("/repor")
def reset(codigo: str = Form(...), nova: str = Form(...), confirmar: str = Form(...)):
    if nova != confirmar or len(nova) < 8:
        return RedirectResponse(f"/repor?codigo={codigo}&erro=1", 303)
    if not users.use_reset_token(codigo, nova):
        return RedirectResponse("/repor?erro=2", 303)
    return RedirectResponse("/login?reposta=1", 303)


@app.get("/sair")
def logout():
    r = RedirectResponse("/login", 303)
    r.delete_cookie("cs")
    return r


# ------------------------------------------------------------------ helpers
def _post_view(conn, r) -> dict:
    p = dict(r)
    ids = json.loads(p.get("media_ids") or "[]")
    p["media"] = [{"id": i, "video": path.lower().endswith((".mp4", ".mov"))}
                  for i, path in zip(ids, media_paths(conn, ids))]
    # origem das imagens/vídeos de stock (a Pixabay pede que se mostre a origem)
    sources: list[dict] = []
    if ids:
        for m in conn.execute(f"SELECT meta FROM media WHERE id IN ({','.join('?' * len(ids))})", ids):
            for src in (json.loads(m["meta"] or "{}").get("stock") or []):
                if src and src not in sources:
                    sources.append(src)
    p["stock_sources"] = sources
    # tipo de publicação, bem visível: vídeo (com duração), carrossel ou imagem
    videos = [m for m in p["media"] if m["video"]]
    images = [m for m in p["media"] if not m["video"]]
    if videos:
        secs = _duration(media_paths(conn, [videos[0]["id"]])[0])
        p["kind"] = ("video", f"🎬 Vídeo · {int(secs // 60)}:{int(secs % 60):02d}" if secs else "🎬 Vídeo")
    elif len(images) > 1:
        p["kind"] = ("carousel", f"🖼 Carrossel · {len(images)} imagens")
    elif images:
        p["kind"] = ("image", "🖼 Imagem")
    else:
        p["kind"] = ("none", "Ainda sem vídeo/imagem")
    p["is_video"] = bool(videos) or p.get("format") in ("reel", "video")
    p["account"] = accounts().get(p["account_id"])
    p["group"] = group_of(p["account_id"])
    p["when"] = datetime.fromisoformat(p["scheduled_at"][:19]) if p.get("scheduled_at") else None
    p["tags"] = " ".join(json.loads(p.get("hashtags") or "[]"))
    return p


@__import__("functools").lru_cache(maxsize=512)
def _duration_cached(path: str, mtime: float) -> float:
    from ..media.video_editor import probe
    try:
        return probe(path).duration
    except Exception:  # noqa: BLE001
        return 0.0


def _duration(path: str) -> float:
    try:
        return _duration_cached(path, Path(path).stat().st_mtime)
    except OSError:
        return 0.0


def _group_posts(posts: list[dict]) -> list[tuple[dict, list[dict]]]:
    """[(grupo, publicações)] pela ordem dos grupos; grupos sem publicações são omitidos."""
    return [(g, [p for p in posts if p["group"]["id"] == g["id"]]) for g in groups()
            if any(p["group"]["id"] == g["id"] for p in posts)]


def _visible_clause(user: users.User) -> tuple[str, list]:
    acc = user.visible_accounts
    if user.is_admin:
        return "1=1", []
    if not acc:
        return "0=1", []
    return f"account_id IN ({','.join('?' * len(acc))})", acc


# ------------------------------------------------------------------ páginas
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    from ..analytics.analyzer import summary
    me = request.state.user
    where, params = _visible_clause(me)
    with connect() as conn:
        report = [summary(conn, a, 30) for a in me.visible_accounts]
        report_groups = [(g, [r for r in report if accounts()[r["account_id"]].group == g["id"]]) for g in groups()]
        report_groups = [(g, rs) for g, rs in report_groups if rs]
        drafts = conn.execute(f"SELECT account_id FROM posts WHERE status='draft' AND {where}", params).fetchall()
        drafts_n = sum(1 for d in drafts if me.can_approve(d["account_id"]))
        nxt = [_post_view(conn, r) for r in conn.execute(
            f"SELECT * FROM posts WHERE scheduled_at >= ? AND status IN ('approved','draft') AND {where} "
            f"ORDER BY scheduled_at LIMIT 12", [datetime.now().isoformat(), *params])]
        running = conn.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
    return _render(request, "home.html", {"report_groups": report_groups, "drafts": drafts_n,
                                          "next_groups": _group_posts(nxt), "running": running, "page": "home"})


@app.get("/calendario", response_class=HTMLResponse)
def calendar_page(request: Request, mes: str = "", grupo: str = ""):
    me = request.state.user
    where, params = _visible_clause(me)
    first = date.fromisoformat(mes + "-01") if mes else date.today().replace(day=1)
    weeks = cal.Calendar(firstweekday=0).monthdatescalendar(first.year, first.month)
    start, end = weeks[0][0], weeks[-1][-1] + timedelta(1)
    with connect() as conn:
        rows = [_post_view(conn, r) for r in conn.execute(
            f"SELECT * FROM posts WHERE substr(scheduled_at,1,10) >= ? AND substr(scheduled_at,1,10) < ? "
            f"AND status != 'rejected' AND {where} ORDER BY scheduled_at", [start.isoformat(), end.isoformat(), *params])]
    if grupo:
        rows = [p for p in rows if p["group"]["id"] == grupo]
    by_day: dict[str, list] = {}
    for p in rows:
        by_day.setdefault(p["scheduled_at"][:10], []).append(p)
    prev_m = (first - timedelta(1)).strftime("%Y-%m")
    next_m = (first + timedelta(32)).replace(day=1).strftime("%Y-%m")
    meses = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
             "outubro", "novembro", "dezembro"]
    return _render(request, "calendar.html", {
        "weeks": weeks, "by_day": by_day, "first": first, "today": date.today(), "prev_m": prev_m,
        "next_m": next_m, "titulo": f"{meses[first.month - 1].capitalize()} {first.year}", "page": "cal",
        "grupo": grupo, "mes": first.strftime("%Y-%m"),
        "grupos_visiveis": [g for g in groups() if any(accounts()[a].group == g["id"] for a in me.visible_accounts)]})


@app.get("/aprovar", response_class=HTMLResponse)
def approve_page(request: Request):
    me = request.state.user
    where, params = _visible_clause(me)
    with connect() as conn:
        rows = [_post_view(conn, r) for r in conn.execute(
            f"SELECT * FROM posts WHERE status='draft' AND {where} ORDER BY scheduled_at IS NULL, scheduled_at", params)]
    return _render(request, "approve.html", {"posts": rows, "post_groups": _group_posts(rows), "page": "approve"})


@app.get("/post/{pid}", response_class=HTMLResponse)
def post_page(request: Request, pid: int):
    me = request.state.user
    with connect() as conn:
        p = _post_view(conn, get_post(conn, pid))
    if not me.can_see(p["account_id"]):
        return _forbidden()
    extra = json.loads(p.get("script") or "{}")
    acc = p["account_id"]
    return _render(request, "post.html", {"p": p, "extra": extra, "can_create": me.can_create(acc),
                                          "can_approve": me.can_approve(acc)})


@app.post("/post/{pid}")
def post_action(request: Request, pid: int, action: str = Form(...), caption: str = Form(""),
                quando: str = Form("")):
    from ..scheduler import parse_dt, ready_problems
    me = request.state.user
    with connect() as conn:
        row = get_post(conn, pid)
        acc = row["account_id"]
        if not me.can_see(acc):
            return _forbidden()
        if action in ("aprovar", "rejeitar") and not me.can_approve(acc):
            return _forbidden("Podes criar e editar nesta conta, mas não aprovar. Pede a um aprovador.")
        if not me.can_create(acc):
            return _forbidden("Nesta conta só tens acesso para ver.")
        fields: dict = {}
        if caption.strip() and caption.strip() != (row["caption"] or ""):
            fields["caption"] = caption.strip()
        if quando:
            new_when = parse_dt(quando).isoformat()
            if new_when[:16] != (row["scheduled_at"] or "")[:16]:
                if not me.can_approve(acc):
                    return _forbidden("Agendar (mudar a data) é para quem aprova nesta conta.")
                fields["scheduled_at"] = new_when
        if fields:
            update_post(conn, pid, **fields)
        if action == "aprovar":
            problems = ready_problems(get_post(conn, pid))
            if problems:
                update_post(conn, pid, error="; ".join(problems))
            else:
                update_post(conn, pid, status="approved", error=None, approved_by=me.id)
        elif action == "rejeitar":
            update_post(conn, pid, status="rejected", approved_by=me.id)
        elif action == "refazer":
            if not me.can_create(acc):
                return _forbidden()
            update_post(conn, pid, media_ids=[], status="idea")
            if row["format"] in ("reel", "video"):
                jobs.enqueue("create-video", ["--account", acc, "--post", str(pid)], f"Refazer #{pid}",
                             user_id=me.id)
    return RedirectResponse(f"/post/{pid}" if action == "guardar" else "/aprovar", 303)


@app.get("/media/{mid}")
def media(request: Request, mid: int):
    me = request.state.user
    with connect() as conn:
        row = conn.execute("SELECT path FROM media WHERE id=?", (mid,)).fetchone()
        if not me.is_admin:  # só media ligada a publicações de contas a que a pessoa tem acesso
            posts = conn.execute("SELECT account_id, media_ids, cover_id FROM posts").fetchall()
            allowed = any(me.can_see(p["account_id"]) and (mid in json.loads(p["media_ids"] or "[]")
                                                            or p["cover_id"] == mid) for p in posts)
            if not allowed:
                return _forbidden()
    if not row or not Path(row["path"]).exists():
        return HTMLResponse("não encontrado", 404)
    return FileResponse(row["path"])


@app.get("/criar", response_class=HTMLResponse)
def create_page(request: Request):
    me = request.state.user
    contas = [accounts()[a] for a in me.creatable_accounts]
    contas_grupos = [(g, [a for a in contas if a.group == g["id"]]) for g in groups()]
    return _render(request, "create.html", {"page": "create", "contas": contas,
                                            "contas_grupos": [(g, cs) for g, cs in contas_grupos if cs]})


def _save_uploads(files: list[UploadFile]) -> list[str]:
    folder = DATA_DIR / "uploads" / datetime.now().strftime("%Y%m%d_%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for f in files:
        if not f.filename:
            continue
        dest = folder / Path(f.filename).name
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out)
        paths.append(str(dest))
    return paths


@app.post("/criar")
def create(request: Request, tipo: str = Form(...), conta: str = Form(...), tema: str = Form(""),
           segundos: int = Form(35), quando: str = Form(""), texto: str = Form(""),
           ficheiros: list[UploadFile] = File(default=[])):
    me = request.state.user
    if not me.can_create(conta):
        return _forbidden("Não tens permissão para criar nesta conta.")
    sched = ["--schedule", quando] if quando else []
    if tipo == "zero":
        jobs.enqueue("create-video", ["--account", conta, "--topic", tema, "--seconds", str(segundos), *sched],
                     f"Vídeo do zero: {tema[:50]}", user_id=me.id)
    elif tipo in ("editar", "montagem"):
        paths = _save_uploads(ficheiros)
        if not paths:
            return RedirectResponse("/criar?erro=ficheiros", 303)
        if tipo == "editar" and len(paths) == 1:
            jobs.enqueue("edit-video", [paths[0], "--account", conta, "--seconds", str(segundos), "--fill", "crop",
                                        *(["--goal", tema] if tema else []), *sched],
                         f"Editar vídeo: {Path(paths[0]).name}", user_id=me.id)
        else:
            jobs.enqueue("montage", [*paths, "--account", conta, "--seconds", str(segundos),
                                     *(["--goal", tema] if tema else []), *sched],
                         f"Montagem de {len(paths)} vídeos", user_id=me.id)
    elif tipo == "imagem":
        jobs.enqueue("image", ["quote", "--account", conta, "--text", texto or tema], "Imagem com frase",
                     user_id=me.id)
    return RedirectResponse("/tarefas", 303)


MAX_AUDIO_BYTES = 25 * 1024 * 1024  # ~3 minutos de voz chegam e sobram


@app.post("/transcrever")
def transcribe_audio(request: Request, audio: UploadFile = File(...)):
    """Ditado por microfone (Assistente e Criar): o áudio é transcrito NO SERVIDOR (faster-whisper),
    não é enviado a serviços externos e é apagado logo a seguir."""
    import tempfile
    from ..media.video_editor import dictate
    data = audio.file.read(MAX_AUDIO_BYTES + 1)
    if not data:
        return JSONResponse({"erro": "Não recebi áudio."}, 400)
    if len(data) > MAX_AUDIO_BYTES:
        return JSONResponse({"erro": "Gravação demasiado longa (máx. ~3 minutos)."}, 413)
    suffix = Path(audio.filename or "voz.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            texto = dictate(tmp.name)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"erro": f"Não consegui transcrever: {exc}"}, 500)
    return JSONResponse({"texto": texto})


@app.get("/tarefas", response_class=HTMLResponse)
def jobs_page(request: Request):
    me = request.state.user
    with connect() as conn:
        if me.is_admin:
            rows = conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 30")
        else:
            rows = conn.execute("SELECT * FROM jobs WHERE created_by=? ORDER BY id DESC LIMIT 30", (me.id,))
        rows = [dict(r) for r in rows]
    return _render(request, "jobs.html", {"jobs": rows, "page": "jobs"})


@app.get("/assistente", response_class=HTMLResponse)
def chat_page(request: Request):
    me = request.state.user
    with connect() as conn:
        msgs = [dict(r) for r in conn.execute("SELECT * FROM chat WHERE user_id=? ORDER BY id DESC LIMIT 40",
                                              (me.id,))][::-1]
    return _render(request, "chat.html", {"msgs": msgs, "page": "chat"})


@app.post("/assistente")
def chat_send(request: Request, mensagem: str = Form(...)):
    from .assistant import reply
    try:
        text = reply(mensagem, request.state.user)
    except Exception as exc:  # noqa: BLE001
        text = f"Ocorreu um erro: {exc}"
    return JSONResponse({"reply": text})


# ------------------------------------------------------------------ equipa (só administrador)
def _invite(request: Request, uid: int, email: str, name: str, temp: str, novo: bool) -> bool:
    """Envia o convite / a reposição por email, se o envio estiver configurado. Devolve True se enviou."""
    if not (email and mailer.configured()):
        return False
    token = users.create_reset_token(uid)
    link = f"{_base_url(request)}/repor?codigo={token}"
    assunto = "Convite para o dashboard" if novo else "Repor a palavra-passe"
    corpo = (f"Olá {name},\n\n" +
             ("Foste convidado/a para o dashboard das redes sociais.\n" if novo else
              "O administrador pediu a reposição da tua palavra-passe.\n") +
             f"Define a tua palavra-passe neste link (válido {users.RESET_MINUTES} min, uso único):\n\n{link}\n\n"
             f"Endereço do dashboard: {_base_url(request)}\n")
    try:
        mailer.send(email, assunto, corpo)
        return True
    except Exception:  # noqa: BLE001
        return False


@app.get("/equipa", response_class=HTMLResponse)
def team_page(request: Request, msg: str = "", senha: str = "", quem: str = ""):
    me = request.state.user
    if not me.is_admin:
        return _forbidden()
    with connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM users ORDER BY is_admin DESC, active DESC, name")]
    people = [{**r, "u": users.load(r["id"]) if r["active"] else None} for r in rows]
    ativos = sum(1 for r in rows if r["active"])
    tabelas = [(g, accs, [p for p in people if p["active"]]) for g, accs in accounts_by_group()]
    return _render(request, "team.html", {"people": people, "tabelas": tabelas, "msg": msg, "senha": senha,
                                          "quem": quem, "ativos": ativos, "max_users": users.MAX_USERS,
                                          "email_ok": mailer.configured(), "page": "team"})


@app.post("/equipa/novo")
def team_new(request: Request, username: str = Form(...), name: str = Form(...), email: str = Form(...)):
    if not request.state.user.is_admin:
        return _forbidden()
    if not users.valid_email(email):
        return RedirectResponse("/equipa?msg=email_invalido", 303)
    temp = secrets.token_urlsafe(9)
    try:
        uid = users.create(username, name, temp, must_change=True, email=email)   # sem acesso a nenhuma conta
    except users.LimitError:
        return RedirectResponse("/equipa?msg=limite", 303)
    except ValueError:
        return RedirectResponse("/equipa?msg=email_repetido", 303)
    except Exception:  # noqa: BLE001 — utilizador repetido
        return RedirectResponse("/equipa?msg=repetido", 303)
    if _invite(request, uid, users.normalize_email(email), name, temp, novo=True):
        return RedirectResponse(f"/equipa?msg=convite_enviado&quem={username}", 303)
    return RedirectResponse(f"/equipa?msg=criado&quem={username}&senha={temp}", 303)


@app.post("/equipa/permissoes/{grupo}")
async def team_levels(request: Request, grupo: str):
    """Grava a tabela de permissões de UM grupo (linhas = utilizadores, colunas = contas do grupo)."""
    if not request.state.user.is_admin:
        return _forbidden()
    form = await request.form()
    contas = [a.id for g, accs in accounts_by_group() if g["id"] == grupo for a in accs]
    with connect() as conn:
        uids = [r["id"] for r in conn.execute("SELECT id FROM users WHERE active=1 AND is_admin=0")]
    for uid in uids:
        levels = {acc: str(form.get(f"lvl_{uid}_{acc}", "nenhum")) for acc in contas}
        users.set_levels(uid, levels, only_accounts=contas)
    return RedirectResponse(f"/equipa?msg=permissoes#grupo-{grupo}", 303)


@app.post("/equipa/{uid}")
async def team_update(request: Request, uid: int):
    me = request.state.user
    if not me.is_admin:
        return _forbidden()
    form = await request.form()
    action = form.get("action", "")
    target = users.load(uid)
    if action == "senha":
        temp = secrets.token_urlsafe(9)
        users.set_password(uid, temp, must_change=True)
        if target and _invite(request, uid, target.email, target.name, temp, novo=False):
            return RedirectResponse(f"/equipa?msg=reposicao_enviada&quem={target.username}", 303)
        return RedirectResponse(f"/equipa?msg=senha&quem={target.username if target else ''}&senha={temp}", 303)
    if action in ("desativar", "ativar"):
        if uid == me.id:
            return _forbidden("Não te podes desativar a ti próprio.")
        try:
            users.set_active(uid, action == "ativar")
        except users.LimitError:
            return RedirectResponse("/equipa?msg=limite", 303)
        return RedirectResponse("/equipa", 303)
    if action == "email":
        email = str(form.get("email", ""))
        if not users.valid_email(email):
            return RedirectResponse("/equipa?msg=email_invalido", 303)
        try:
            users.set_email(uid, email)
        except ValueError:
            return RedirectResponse("/equipa?msg=email_repetido", 303)
        return RedirectResponse("/equipa?msg=email_ok", 303)
    return RedirectResponse("/equipa", 303)


@app.get("/conta", response_class=HTMLResponse)
def my_account(request: Request, ok: str = "", primeira: str = ""):
    return _render(request, "account.html", {"ok": ok, "primeira": primeira or request.state.user.must_change})


@app.post("/conta")
def my_account_save(request: Request, atual: str = Form(...), nova: str = Form(""), confirmar: str = Form(""),
                    email: str = Form("")):
    me = request.state.user
    if not users.authenticate(me.username, atual):
        return RedirectResponse("/conta?ok=erro", 303)
    if email.strip() and users.normalize_email(email) != me.email:
        if not users.valid_email(email):
            return RedirectResponse("/conta?ok=email_invalido", 303)
        try:
            users.set_email(me.id, email)
        except ValueError:
            return RedirectResponse("/conta?ok=email_repetido", 303)
    if nova or me.must_change:
        if len(nova) < 8 or nova != confirmar or nova == atual:
            return RedirectResponse("/conta?ok=erro", 303)
        users.set_password(me.id, nova, must_change=False)
    if not users.load(me.id).email:
        return RedirectResponse("/conta?ok=falta_email", 303)
    return RedirectResponse("/conta?ok=1", 303)


# ------------------------------------------------------------------ configuração (chaves)
CONFIG_FIELDS = [  # (variável, rótulo, secreta)
    ("SOCIAL_ANTHROPIC_API_KEY", "Chave da IA", True),
    ("ELEVENLABS_API_KEY", "Chave da ElevenLabs", True),
    ("ELEVENLABS_VOICE_ID", "Voice ID da voz 'David Carreto'", False),
    ("PIXABAY_API_KEY", "Chave da Pixabay", True),
    ("PEXELS_API_KEY", "Chave do Pexels (opcional; se existir, tem prioridade sobre a Pixabay)", True),
    # envio de emails (convites e "esqueci-me da palavra-passe"): conta PRÓPRIA deste sistema
    ("SMTP_HOST", "Email · servidor SMTP (ex.: smtp.gmail.com)", False),
    ("SMTP_PORT", "Email · porta (587 ou 465)", False),
    ("SMTP_USER", "Email · utilizador (endereço de envio)", False),
    ("SMTP_PASSWORD", "Email · palavra-passe de aplicação (NÃO usar a 'carretos-avaliacoes')", True),
    ("SMTP_FROM", "Email · remetente (opcional, ex.: Redes Sociais <endereco@…>)", False),
]


import re as _re

# formato esperado de cada chave: evita guardar por engano um utilizador/palavra-passe preenchido pelo browser
KEY_FORMATS = {
    "SOCIAL_ANTHROPIC_API_KEY": (_re.compile(r"^sk-ant-[A-Za-z0-9_\-]{20,}$"), "começa por sk-ant-"),
    "ELEVENLABS_API_KEY": (_re.compile(r"^(sk_)?[0-9a-fA-F]{32,64}$"), "começa por sk_ seguido de letras/números"),
    "ELEVENLABS_VOICE_ID": (_re.compile(r"^[A-Za-z0-9]{15,40}$"), "só letras e números, sem espaços (~20)"),
    "PIXABAY_API_KEY": (_re.compile(r"^\d+-[0-9a-fA-F]{20,}$"), "números, um hífen e letras/números"),
    "PEXELS_API_KEY": (_re.compile(r"^[A-Za-z0-9]{40,64}$"), "~56 letras e números"),
    "SMTP_HOST": (_re.compile(r"^[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"), "um servidor, ex.: smtp.gmail.com"),
    "SMTP_PORT": (_re.compile(r"^(25|465|587|2525)$"), "587 ou 465"),
    "SMTP_USER": (_re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$"), "um endereço de email"),
    "SMTP_PASSWORD": (_re.compile(r"^\S{8,}$"), "a palavra-passe de aplicação, sem espaços"),
}


def _bad_key(key: str, value: str) -> str | None:
    fmt = KEY_FORMATS.get(key)
    if fmt and not fmt[0].match(value):
        return fmt[1]
    return None


@app.get("/configurar", response_class=HTMLResponse)
def config_page(request: Request, ok: str = "", erro: str = "", teste: str = "", motivo: str = ""):
    first = users.count() == 0
    me = _current_user(request) if not first else None
    if not first and not (me and me.is_admin):
        return RedirectResponse("/login", 303)
    request.state.user = me
    fields = [(k, label, secret, bool(os.environ.get(k))) for k, label, secret in CONFIG_FIELDS]
    labels = {k: label for k, label, _ in CONFIG_FIELDS}
    erros = [(labels.get(k, k), KEY_FORMATS[k][1]) for k in erro.split(",") if k in KEY_FORMATS]
    return _render(request, "config.html", {"fields": fields, "first": first, "ok": ok, "erros": erros,
                                            "teste": teste, "motivo": motivo, "email_ok": mailer.configured()})


@app.post("/configurar")
async def config_save(request: Request):
    form = await request.form()
    first = users.count() == 0
    if first:
        expected = os.environ.get("SETUP_CODE", "")
        if not expected or not hmac.compare_digest(str(form.get("codigo", "")), expected):
            return HTMLResponse("Código de configuração errado.", 403)
        pw = str(form.get("admin_password", ""))
        if len(pw) < 8:
            return HTMLResponse("A palavra-passe tem de ter pelo menos 8 caracteres.", 400)
        admin_email = str(form.get("admin_email", ""))
        if not users.valid_email(admin_email):
            return HTMLResponse("Indica um email válido para o administrador.", 400)
        admin_id = users.create("david", "David Carreto", pw, is_admin=True, email=admin_email)
    else:
        me = _current_user(request)
        if not (me and me.is_admin):
            return _forbidden()
        admin_id = me.id
    env = ROOT / ".env"
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    rejected = []
    for key, _, _ in CONFIG_FIELDS:
        value = str(form.get(key, "")).strip()
        if key == "SMTP_PASSWORD":
            value = value.replace(" ", "")                    # o Gmail mostra-a em blocos de 4 com espaços
        if not value:
            continue                                         # vazio = manter o valor atual
        if _bad_key(key, value):
            rejected.append(key)                              # formato errado: não guarda
            continue
        os.environ[key] = value
        replaced = False
        for i, line in enumerate(lines):
            if line.split("=", 1)[0].strip() == key and not line.startswith("#"):
                lines[i] = f"{key}={value}"
                replaced = True
        if not replaced:
            lines.append(f"{key}={value}")
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env.chmod(0o600)
    r = RedirectResponse("/configurar?ok=1" + (f"&erro={','.join(rejected)}" if rejected else ""), 303)
    _set_session(r, admin_id)
    return r


@app.post("/configurar/testar-email")
def config_test_email(request: Request):
    """Envia um email de teste ao administrador (confirma a configuração SMTP)."""
    me = _current_user(request)
    if not (me and me.is_admin):
        return _forbidden()
    if not me.email:
        return RedirectResponse("/configurar?teste=sem_email", 303)
    if not mailer.configured():
        return RedirectResponse("/configurar?teste=nao_configurado", 303)
    try:
        mailer.send(me.email, "Email de teste",
                    "Olá David,\n\nO envio de emails do dashboard das redes sociais está a funcionar.\n"
                    "A partir de agora os convites e o 'esqueci-me da palavra-passe' chegam por email.\n")
    except Exception as exc:  # noqa: BLE001 — mostra o motivo (nunca a palavra-passe)
        motivo = type(exc).__name__ + ": " + str(exc).replace(os.environ.get("SMTP_PASSWORD", "\0"), "***")[:200]
        from urllib.parse import quote
        return RedirectResponse(f"/configurar?teste=erro&motivo={quote(motivo)}", 303)
    return RedirectResponse("/configurar?teste=ok", 303)


@app.on_event("startup")
def _startup():
    jobs.start_worker()
    if os.environ.get("DICTATION_PRELOAD", "1") == "1":  # modelo do ditado já em memória
        import threading
        from ..media.video_editor import preload_dictation
        threading.Thread(target=preload_dictation, daemon=True).start()
