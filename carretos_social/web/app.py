"""Dashboard web: visão geral, calendário, aprovação, criar conteúdos, tarefas e assistente.

Arranque: `carretos web` (porta 8000). Acesso protegido por DASHBOARD_PASSWORD (.env).
"""
from __future__ import annotations

import calendar as cal
import hashlib
import hmac
import json
import os
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..config import DATA_DIR, accounts, load_env
from ..db import connect, get_post, media_paths, update_post
from . import jobs

load_env()
HERE = Path(__file__).parent
app = FastAPI(title="Carretos Social")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
tpl = Jinja2Templates(directory=HERE / "templates")

STATUS = {"idea": ("Ideia", "#7d8590"), "draft": ("Para aprovar", "#d29922"), "approved": ("Aprovado", "#3fb950"),
          "published": ("Publicado", "#D4AF37"), "failed": ("Falhou", "#f85149"),
          "assist_sent": ("Enviado p/ telemóvel", "#a371f7"), "rejected": ("Rejeitado", "#484f58")}
ICON = {"instagram": "IG", "tiktok": "TT", "facebook_profile": "FB", "linkedin_member": "in", "linkedin_org": "in"}
DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def _quando(dt) -> str:
    return f"{DIAS[dt.weekday()]} {dt:%d/%m %H:%M}" if dt else "sem data"


def _tema(pillar) -> str:
    from ..config import brand
    names = {p["id"]: p["name"] for p in brand().get("pillars", [])}
    return names.get(pillar or "", pillar or "Sem tema")


tpl.env.globals.update(STATUS=STATUS, ICON=ICON, accounts=accounts, tema=_tema)
tpl.env.filters["quando"] = _quando


# ------------------------------------------------------------------ autenticação
def _secret() -> bytes:
    return (os.environ.get("DASHBOARD_SECRET") or os.environ.get("DASHBOARD_PASSWORD", "") + "carretos").encode()


def _token() -> str:
    return hmac.new(_secret(), b"ok", hashlib.sha256).hexdigest()


@app.middleware("http")
async def auth(request: Request, call_next):
    open_paths = ("/login", "/static")
    if not os.environ.get("DASHBOARD_PASSWORD"):
        if not request.url.path.startswith(open_paths):
            return HTMLResponse("<h3>Define DASHBOARD_PASSWORD no .env para usar o dashboard.</h3>", 503)
    elif not request.url.path.startswith(open_paths) and request.cookies.get("cs") != _token():
        return RedirectResponse("/login", 303)
    return await call_next(request)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, erro: str = ""):
    return tpl.TemplateResponse(request, "login.html", {"erro": erro})


@app.post("/login")
def login(password: str = Form(...)):
    if hmac.compare_digest(password, os.environ.get("DASHBOARD_PASSWORD", "")):
        r = RedirectResponse("/", 303)
        r.set_cookie("cs", _token(), max_age=60 * 60 * 24 * 60, httponly=True, samesite="lax")
        return r
    return RedirectResponse("/login?erro=1", 303)


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


# ------------------------------------------------------------------ páginas
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    from ..analytics.analyzer import full_report
    with connect() as conn:
        report = full_report(conn, 30)
        drafts = conn.execute("SELECT COUNT(*) FROM posts WHERE status='draft'").fetchone()[0]
        nxt = [_post_view(conn, r) for r in conn.execute(
            "SELECT * FROM posts WHERE scheduled_at >= ? AND status IN ('approved','draft') ORDER BY scheduled_at "
            "LIMIT 6", (datetime.now().isoformat(),))]
        running = conn.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
    return tpl.TemplateResponse(request, "home.html", {"report": report, "drafts": drafts, "next": nxt,
                                                       "running": running, "page": "home"})


@app.get("/calendario", response_class=HTMLResponse)
def calendar_page(request: Request, mes: str = ""):
    first = date.fromisoformat(mes + "-01") if mes else date.today().replace(day=1)
    weeks = cal.Calendar(firstweekday=0).monthdatescalendar(first.year, first.month)
    start, end = weeks[0][0], weeks[-1][-1] + timedelta(1)
    with connect() as conn:
        rows = [_post_view(conn, r) for r in conn.execute(
            "SELECT * FROM posts WHERE substr(scheduled_at,1,10) >= ? AND substr(scheduled_at,1,10) < ? "
            "AND status != 'rejected' ORDER BY scheduled_at", (start.isoformat(), end.isoformat()))]
    by_day: dict[str, list] = {}
    for p in rows:
        by_day.setdefault(p["scheduled_at"][:10], []).append(p)
    prev_m = (first - timedelta(1)).strftime("%Y-%m")
    next_m = (first + timedelta(32)).replace(day=1).strftime("%Y-%m")
    meses = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
             "outubro", "novembro", "dezembro"]
    return tpl.TemplateResponse(request, "calendar.html", {
        "weeks": weeks, "by_day": by_day, "first": first, "today": date.today(), "prev_m": prev_m,
        "next_m": next_m, "titulo": f"{meses[first.month - 1].capitalize()} {first.year}", "page": "cal"})


@app.get("/aprovar", response_class=HTMLResponse)
def approve_page(request: Request):
    with connect() as conn:
        rows = [_post_view(conn, r) for r in conn.execute(
            "SELECT * FROM posts WHERE status='draft' ORDER BY scheduled_at IS NULL, scheduled_at")]
    return tpl.TemplateResponse(request, "approve.html", {"posts": rows, "page": "approve"})


@app.get("/post/{pid}", response_class=HTMLResponse)
def post_page(request: Request, pid: int):
    with connect() as conn:
        p = _post_view(conn, get_post(conn, pid))
    extra = json.loads(p.get("script") or "{}")
    return tpl.TemplateResponse(request, "post.html", {"p": p, "extra": extra, "page": ""})


@app.post("/post/{pid}")
def post_action(pid: int, action: str = Form(...), caption: str = Form(""), quando: str = Form("")):
    from ..scheduler import parse_dt, ready_problems
    with connect() as conn:
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
                update_post(conn, pid, status="approved", error=None)
        elif action == "rejeitar":
            update_post(conn, pid, status="rejected")
        elif action == "refazer":
            row = get_post(conn, pid)
            update_post(conn, pid, media_ids=[], status="idea")
            if row["format"] in ("reel", "video"):
                jobs.enqueue("create-video", ["--account", row["account_id"], "--post", str(pid)],
                             f"Refazer #{pid}")
    return RedirectResponse(f"/post/{pid}" if action == "guardar" else "/aprovar", 303)


@app.get("/media/{mid}")
def media(mid: int):
    with connect() as conn:
        row = conn.execute("SELECT path FROM media WHERE id=?", (mid,)).fetchone()
    if not row or not Path(row["path"]).exists():
        return HTMLResponse("não encontrado", 404)
    return FileResponse(row["path"])


@app.get("/criar", response_class=HTMLResponse)
def create_page(request: Request):
    return tpl.TemplateResponse(request, "create.html", {"page": "create"})


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
def create(tipo: str = Form(...), conta: str = Form(...), tema: str = Form(""), segundos: int = Form(35),
           quando: str = Form(""), texto: str = Form(""), ficheiros: list[UploadFile] = File(default=[])):
    sched = ["--schedule", quando] if quando else []
    if tipo == "zero":
        jobs.enqueue("create-video", ["--account", conta, "--topic", tema, "--seconds", str(segundos), *sched],
                     f"Vídeo do zero: {tema[:50]}")
    elif tipo in ("editar", "montagem"):
        paths = _save_uploads(ficheiros)
        if not paths:
            return RedirectResponse("/criar?erro=ficheiros", 303)
        if tipo == "editar" and len(paths) == 1:
            jobs.enqueue("edit-video", [paths[0], "--account", conta, "--seconds", str(segundos), "--fill", "crop",
                                        *(["--goal", tema] if tema else []), *(sched or ["--schedule",
                                        (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT19:00")])],
                         f"Editar vídeo: {Path(paths[0]).name}")
        else:
            jobs.enqueue("montage", [*paths, "--account", conta, "--seconds", str(segundos),
                                     *(["--goal", tema] if tema else []), *sched],
                         f"Montagem de {len(paths)} vídeos")
    elif tipo == "imagem":
        jobs.enqueue("image", ["quote", "--account", conta, "--text", texto or tema], "Imagem com frase")
    return RedirectResponse("/tarefas", 303)


@app.get("/tarefas", response_class=HTMLResponse)
def jobs_page(request: Request):
    with connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 30")]
    return tpl.TemplateResponse(request, "jobs.html", {"jobs": rows, "page": "jobs"})


@app.get("/assistente", response_class=HTMLResponse)
def chat_page(request: Request):
    with connect() as conn:
        msgs = [dict(r) for r in conn.execute("SELECT * FROM chat ORDER BY id DESC LIMIT 40")][::-1]
    return tpl.TemplateResponse(request, "chat.html", {"msgs": msgs, "page": "chat"})


@app.post("/assistente")
def chat_send(mensagem: str = Form(...)):
    from .assistant import reply
    try:
        text = reply(mensagem)
    except Exception as exc:  # noqa: BLE001
        text = f"Ocorreu um erro: {exc}"
    return JSONResponse({"reply": text})


@app.on_event("startup")
def _startup():
    jobs.start_worker()
