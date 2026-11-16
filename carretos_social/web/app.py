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

from ..config import DATA_DIR, ROOT, accounts, load_env
from ..db import connect, get_post, media_paths, update_post
from . import jobs, users

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


tpl.env.globals.update(STATUS=STATUS, ICON=ICON, accounts=accounts, tema=_tema)
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
    open_paths = ("/login", "/static", "/configurar")
    users.bootstrap_admin()
    if users.count() == 0:  # ainda não há administrador: 1.ª configuração
        if not request.url.path.startswith(open_paths):
            return RedirectResponse("/configurar", 303)
        return await call_next(request)
    user = _current_user(request)
    request.state.user = user
    if user is None and not request.url.path.startswith(open_paths):
        return RedirectResponse("/login", 303)
    return await call_next(request)


def _forbidden(msg: str = "Não tens permissão para isto.") -> HTMLResponse:
    return HTMLResponse(f"<body style='background:#000;color:#fff;font-family:sans-serif;padding:24px'>"
                        f"<h3>{msg}</h3><a style='color:#D4AF37' href='/'>Voltar</a></body>", 403)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, erro: str = ""):
    return tpl.TemplateResponse(request, "login.html", {"erro": erro})


@app.post("/login")
def login(username: str = Form("david"), password: str = Form(...)):
    user = users.authenticate(username, password)
    if not user:
        return RedirectResponse("/login?erro=1", 303)
    r = RedirectResponse("/", 303)
    _set_session(r, user.id)
    return r


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
    p["account"] = accounts().get(p["account_id"])
    p["when"] = datetime.fromisoformat(p["scheduled_at"][:19]) if p.get("scheduled_at") else None
    p["tags"] = " ".join(json.loads(p.get("hashtags") or "[]"))
    return p


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
        drafts = conn.execute(f"SELECT account_id FROM posts WHERE status='draft' AND {where}", params).fetchall()
        drafts_n = sum(1 for d in drafts if me.can_approve(d["account_id"]))
        nxt = [_post_view(conn, r) for r in conn.execute(
            f"SELECT * FROM posts WHERE scheduled_at >= ? AND status IN ('approved','draft') AND {where} "
            f"ORDER BY scheduled_at LIMIT 6", [datetime.now().isoformat(), *params])]
        running = conn.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
    return _render(request, "home.html", {"report": report, "drafts": drafts_n, "next": nxt, "running": running,
                                          "page": "home"})


@app.get("/calendario", response_class=HTMLResponse)
def calendar_page(request: Request, mes: str = ""):
    me = request.state.user
    where, params = _visible_clause(me)
    first = date.fromisoformat(mes + "-01") if mes else date.today().replace(day=1)
    weeks = cal.Calendar(firstweekday=0).monthdatescalendar(first.year, first.month)
    start, end = weeks[0][0], weeks[-1][-1] + timedelta(1)
    with connect() as conn:
        rows = [_post_view(conn, r) for r in conn.execute(
            f"SELECT * FROM posts WHERE substr(scheduled_at,1,10) >= ? AND substr(scheduled_at,1,10) < ? "
            f"AND status != 'rejected' AND {where} ORDER BY scheduled_at", [start.isoformat(), end.isoformat(), *params])]
    by_day: dict[str, list] = {}
    for p in rows:
        by_day.setdefault(p["scheduled_at"][:10], []).append(p)
    prev_m = (first - timedelta(1)).strftime("%Y-%m")
    next_m = (first + timedelta(32)).replace(day=1).strftime("%Y-%m")
    meses = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
             "outubro", "novembro", "dezembro"]
    return _render(request, "calendar.html", {
        "weeks": weeks, "by_day": by_day, "first": first, "today": date.today(), "prev_m": prev_m,
        "next_m": next_m, "titulo": f"{meses[first.month - 1].capitalize()} {first.year}", "page": "cal"})


@app.get("/aprovar", response_class=HTMLResponse)
def approve_page(request: Request):
    me = request.state.user
    where, params = _visible_clause(me)
    with connect() as conn:
        rows = [_post_view(conn, r) for r in conn.execute(
            f"SELECT * FROM posts WHERE status='draft' AND {where} ORDER BY scheduled_at IS NULL, scheduled_at", params)]
    return _render(request, "approve.html", {"posts": rows, "page": "approve"})


@app.get("/post/{pid}", response_class=HTMLResponse)
def post_page(request: Request, pid: int):
    me = request.state.user
    with connect() as conn:
        p = _post_view(conn, get_post(conn, pid))
    if not me.can_see(p["account_id"]):
        return _forbidden()
    extra = json.loads(p.get("script") or "{}")
    return _render(request, "post.html", {"p": p, "extra": extra})


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
        fields: dict = {}
        if caption.strip():
            fields["caption"] = caption.strip()
        if quando:
            fields["scheduled_at"] = parse_dt(quando).isoformat()
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
    return _render(request, "create.html", {"page": "create",
                                            "contas": [accounts()[a] for a in me.creatable_accounts]})


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
@app.get("/equipa", response_class=HTMLResponse)
def team_page(request: Request, criado: str = "", senha: str = ""):
    me = request.state.user
    if not me.is_admin:
        return _forbidden()
    with connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM users ORDER BY is_admin DESC, name")]
    people = [{**r, "u": users.load(r["id"]) if r["active"] else None} for r in rows]
    return _render(request, "team.html", {"people": people, "contas": list(accounts().values()),
                                          "criado": criado, "senha": senha, "page": "team"})


@app.post("/equipa/novo")
def team_new(request: Request, username: str = Form(...), name: str = Form(...)):
    if not request.state.user.is_admin:
        return _forbidden()
    temp = secrets.token_urlsafe(8)
    try:
        users.create(username, name, temp)
    except Exception:  # noqa: BLE001 — utilizador repetido
        return RedirectResponse("/equipa?criado=erro", 303)
    return RedirectResponse(f"/equipa?criado={username}&senha={temp}", 303)


@app.post("/equipa/{uid}")
async def team_update(request: Request, uid: int):
    me = request.state.user
    if not me.is_admin:
        return _forbidden()
    form = await request.form()
    action = form.get("action", "guardar")
    if action == "senha":
        temp = secrets.token_urlsafe(8)
        users.set_password(uid, temp)
        return RedirectResponse(f"/equipa?criado=senha&senha={temp}", 303)
    if action in ("desativar", "ativar"):
        if uid == me.id:
            return _forbidden("Não te podes desativar a ti próprio.")
        with connect() as conn:
            conn.execute("UPDATE users SET active=? WHERE id=?", (int(action == "ativar"), uid))
        return RedirectResponse("/equipa", 303)
    perms = {a: {"create": f"c_{a}" in form, "approve": f"a_{a}" in form} for a in accounts()}
    users.set_perms(uid, perms)
    return RedirectResponse("/equipa", 303)


@app.get("/conta", response_class=HTMLResponse)
def my_account(request: Request, ok: str = ""):
    return _render(request, "account.html", {"ok": ok})


@app.post("/conta")
def my_account_save(request: Request, atual: str = Form(...), nova: str = Form(...)):
    me = request.state.user
    if len(nova) < 8 or not users.authenticate(me.username, atual):
        return RedirectResponse("/conta?ok=erro", 303)
    users.set_password(me.id, nova)
    return RedirectResponse("/conta?ok=1", 303)


# ------------------------------------------------------------------ configuração (chaves)
CONFIG_FIELDS = [  # (variável, rótulo, secreta)
    ("SOCIAL_ANTHROPIC_API_KEY", "Chave da IA (carretos-redes-sociais)", True),
    ("ELEVENLABS_API_KEY", "Chave da ElevenLabs", True),
    ("ELEVENLABS_VOICE_ID", "Voice ID da voz 'David Carreto'", False),
    ("PEXELS_API_KEY", "Chave do Pexels", True),
]


@app.get("/configurar", response_class=HTMLResponse)
def config_page(request: Request, ok: str = ""):
    first = users.count() == 0
    me = _current_user(request) if not first else None
    if not first and not (me and me.is_admin):
        return RedirectResponse("/login", 303)
    request.state.user = me
    fields = [(k, label, secret, bool(os.environ.get(k))) for k, label, secret in CONFIG_FIELDS]
    return _render(request, "config.html", {"fields": fields, "first": first, "ok": ok})


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
        admin_id = users.create("david", "David Carreto", pw, is_admin=True)
    else:
        me = _current_user(request)
        if not (me and me.is_admin):
            return _forbidden()
        admin_id = me.id
    env = ROOT / ".env"
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    for key, _, _ in CONFIG_FIELDS:
        value = str(form.get(key, "")).strip()
        if not value:
            continue                                         # vazio = manter o valor atual
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
    r = RedirectResponse("/configurar?ok=1", 303)
    _set_session(r, admin_id)
    return r


@app.on_event("startup")
def _startup():
    jobs.start_worker()
