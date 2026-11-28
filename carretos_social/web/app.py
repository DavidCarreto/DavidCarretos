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

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeTimedSerializer

from ..config import DATA_DIR, ROOT, accounts, accounts_by_group, group_of, groups, load_env
from ..db import add_media, connect, get_post, media_paths, update_post
from . import jobs, mailer, users

load_env()
HERE = Path(__file__).parent
app = FastAPI(title="Carretos Social")
log = __import__("logging").getLogger("carretos.web")


def _back_with_error(pid: int, msg: str) -> RedirectResponse:
    from urllib.parse import quote
    return RedirectResponse(f"/post/{pid}?falha={quote(msg[:2000])}", 303)


@app.exception_handler(Exception)
async def friendly_error(request: Request, exc: Exception):
    """Em vez do ecrã branco 'Internal Server Error': regista o erro (journalctl) e explica-o na página."""
    log.exception("Erro em %s %s", request.method, request.url.path)
    import re as _re
    m = _re.match(r"^/post/(\d+)", request.url.path)
    if request.method == "POST" and m:
        return _back_with_error(int(m.group(1)), f"Não foi possível concluir a ação: {exc}")
    return HTMLResponse(f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                        f"<body style='background:#000;color:#eee;font-family:system-ui;padding:24px'>"
                        f"<h2 style='color:#D4AF37'>Algo correu mal</h2><p>{_esc(str(exc))[:400]}</p>"
                        f"<p><a style='color:#D4AF37' href='javascript:history.back()'>‹ voltar</a></p>", 500)


def _esc(s: str) -> str:
    import html
    return html.escape(s)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
tpl = Jinja2Templates(directory=HERE / "templates")

STATUS = {"idea": ("Ideia", "#7d8590"), "draft": ("Para aprovar", "#d29922"), "approved": ("Aprovado", "#3fb950"),
          "published": ("Publicado", "#D4AF37"), "failed": ("Falhou", "#f85149"),
          "assist_sent": ("Enviado p/ telemóvel", "#a371f7"),
          "tiktok_draft": ("No TikTok: falta publicar na app", "#25F4EE"), "rejected": ("Rejeitado", "#484f58")}
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
    if ctx["me"] and getattr(ctx["me"], "is_admin", False):
        from . import system
        from ..expiry import expiring
        ctx.setdefault("reboot", system.reboot_notice())
        ctx.setdefault("expiring", expiring())
        from .. import health
        ctx.setdefault("health_bad", health.failing())
    return tpl.TemplateResponse(request, name, ctx)


@app.middleware("http")
async def auth(request: Request, call_next):
    request.state.user = None
    open_paths = ("/login", "/static", "/configurar", "/recuperar", "/repor", "/publico/", "/privacidade", "/termos",
                  "/webhooks/")
    verify = os.environ.get("TIKTOK_VERIFY_FILE", "")
    if verify and request.url.path == "/" + verify:       # verificação do domínio na TikTok (sem sessão)
        return PlainTextResponse(os.environ.get("TIKTOK_VERIFY_CONTENT", ""))
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
    # tipo de publicação (o escolhido) e verificação de tamanho/ecrã para a rede (media/formats.py)
    from ..media.formats import KINDS, check, kind_of, kinds_for
    acc_obj = accounts().get(p["account_id"])
    platform = acc_obj.platform if acc_obj else ""
    paths = media_paths(conn, ids)
    p["fmt"] = check(platform, p.get("format"), paths)
    p["type"] = kind_of(p.get("format"))
    p["types"] = kinds_for(platform) or {p["type"]: KINDS.get(p["type"], p["type"])}
    items = p["fmt"].items
    # a etiqueta segue o TIPO escolhido; ✕ quando o conteúdo não bate certo com o tipo/rede
    n = len(p["media"])
    bad = " ✕" if p["fmt"].problems else ""
    if p["type"] == "video":
        secs = next((i.seconds for i in items if i.video), 0)
        p["kind"] = ("video", (f"🎬 Vídeo · {int(secs // 60)}:{int(secs % 60):02d}" if secs else "🎬 Vídeo") + bad)
    elif p["type"] == "carousel":
        p["kind"] = ("carousel", f"📷 Carrossel · {n} {'imagem' if n == 1 else 'imagens'}{bad}")
    elif p["type"] == "text":
        p["kind"] = ("none", "Só texto" + bad)
    else:
        p["kind"] = ("image", f"📷 Imagem{bad}")
    if not n and p["type"] != "text":
        p["kind"] = (p["kind"][0], p["kind"][1].split(" ·")[0].replace(" ✕", "") + " · sem ficheiro ✕")
    p["is_video"] = p["type"] == "video"
    import re as _re
    p["placeholders"] = _re.findall(r"\[PREENCHER[^\]]*\]?", p.get("caption") or "")
    from ..content.guard import found_terms
    p["forbidden"] = [w for _, w in found_terms(p["account_id"], p.get("caption") or "")]
    from .. import linkcard
    p["card_problems"] = linkcard.text_problems(p, platform)       # palavras proibidas no título/descrição do cartão
    p["card_warn"] = linkcard.warnings(p, platform)
    from ..media.formats import spec_for
    p["carousel_max"] = spec_for(platform, "carousel").get("count", (2, 10))[1]
    p["account"] = accounts().get(p["account_id"])
    p["group"] = group_of(p["account_id"])
    p["when"] = datetime.fromisoformat(p["scheduled_at"][:19]) if p.get("scheduled_at") else None
    p["tags"] = " ".join(json.loads(p.get("hashtags") or "[]"))
    return p


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


def _li_preview(p: dict) -> dict | None:
    """Pré-visualização ao estilo do LinkedIn (só contas LinkedIn). Sem publicar nada."""
    import re as _re2
    a = p.get("account")
    if not a or a.platform not in ("linkedin_member", "linkedin_org"):
        return None
    from . import linkpreview
    from .. import linkedin_connect as lc
    from ..scheduler import caption_with_tags
    text = caption_with_tags(p)                         # o texto que vai mesmo para o LinkedIn (legenda + hashtags)
    org = a.platform == "linkedin_org"
    name = (lc.saved().get("name") if not org else "") or _re2.sub(r"\s*\([^)]*\)\s*$", "", a.name)
    from .. import linkcard
    link = linkpreview.first_url(text)
    card = linkcard.for_post(p, a.platform)
    shown = linkpreview.li_display(text)                # parágrafos como no LinkedIn real
    return {"name": name, "org": org, "text": shown, "short": linkpreview.li_collapsed(text),
            "html": linkpreview.li_html(shown),
            "sub": "" if org else os.environ.get("LINKEDIN_HEADLINE", "").strip(),
            "link": link, "card": bool(card), "c": card or {}, "chars": len(text),
            "ov": linkcard.overrides(p)}


@app.get("/post/{pid}/link-preview")
def post_link_preview(request: Request, pid: int):
    """Dados da pré-visualização do LinkedIn lidos de fora: cartão do link (só sem imagem) e seguidores da página."""
    me = request.state.user
    with connect() as conn:
        p = _post_view(conn, get_post(conn, pid))
    if not me.can_see(p["account_id"]):
        return JSONResponse({}, status_code=403)
    li = _li_preview(p)
    if not li:
        return JSONResponse({})
    from . import linkpreview
    out: dict = {"card": None, "sub": ""}
    if li["card"] and li["c"].get("mode") == "auto":
        fresh = request.query_params.get("fresh") == "1" and me.can_create(p["account_id"])
        out["card"] = {k: v for k, v in linkpreview.preview(li["link"], fresh=fresh).items() if not k.startswith("_")}
    if li["org"]:
        from .. import linkedin_connect as lc
        n = lc.followers(p["account"])
        out["sub"] = f"{n:,} seguidores".replace(",", ".") if n is not None else ""     # como o LinkedIn: 1.517
    return JSONResponse(out)


import threading as _threading
_SAMPLE_LOCK = _threading.Lock()


def _read_card_image(f: UploadFile | None) -> tuple[bytes, str] | None:
    """Imagem do cartão do link: PNG, JPG ou GIF até 5 MB (formatos aceites pelo LinkedIn)."""
    if not f or not f.filename:
        return None
    data = f.file.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        raise ValueError("a imagem tem mais de 5 MB")
    ext = ".png" if data[:8] == b"\x89PNG\r\n\x1a\n" else ".jpg" if data[:3] == b"\xff\xd8\xff" else \
        ".gif" if data[:4] == b"GIF8" else ""
    if not ext:
        raise ValueError("a imagem tem de ser PNG, JPG ou GIF (o LinkedIn não aceita SVG nem WebP)")
    return data, ext


@app.get("/post/{pid}/cartao.png")
def post_card_image(request: Request, pid: int):
    from .. import linkcard
    me = request.state.user
    with connect() as conn:
        row = get_post(conn, pid)
    if not me.can_see(row["account_id"]):
        return _forbidden()
    acc = accounts().get(row["account_id"])
    card = linkcard.for_post(row, acc.platform if acc else "")
    if not card or not card.get("image"):
        return PlainTextResponse("sem imagem", status_code=404)
    return FileResponse(card["image"], headers={"Cache-Control": "no-store"})


@app.post("/post/{pid}/cartao")
def post_card_save(request: Request, pid: int, titulo: str = Form(""), descricao: str = Form(""),
                   repor: str = Form(""), imagem: UploadFile | None = File(None)):
    """Título, descrição e imagem do cartão do link deste rascunho (LinkedIn só texto + link)."""
    from urllib.parse import quote
    from .. import linkcard
    me = request.state.user
    with connect() as conn:
        row = get_post(conn, pid)
        if not me.can_create(row["account_id"]):
            return _forbidden("Nesta conta só tens acesso para ver.")
        extra = json.loads(row["script"] or "{}")
        if repor:
            extra.pop("link_card", None)
            old = linkcard.post_image(pid)
            if old:
                old.unlink()
        else:
            try:
                img = _read_card_image(imagem)
            except ValueError as exc:
                return RedirectResponse(f"/post/{pid}?falha=" + quote(f"Cartão do link: {exc}"), 303)
            extra["link_card"] = {"title": titulo.strip()[:200], "description": descricao.strip()[:300]}
            if img:
                old = linkcard.post_image(pid)
                if old:
                    old.unlink()
                linkcard.post_image_dir().mkdir(parents=True, exist_ok=True)
                (linkcard.post_image_dir() / f"{pid}{img[1]}").write_bytes(img[0])
        update_post(conn, pid, _by=me.id, script=json.dumps(extra, ensure_ascii=False))
    return RedirectResponse(f"/post/{pid}#li-post", 303)


@app.get("/configurar/registos", response_class=HTMLResponse)
def config_logs(request: Request, post: int = 0):
    """Falhas de publicação e últimas linhas do registo do agendador (sem tokens)."""
    from . import system
    from ..scheduler import failures
    me = _current_user(request)
    if not (me and me.is_admin):
        return _forbidden()
    from .. import inbox as _inbox
    return _render(request, "logs.html", {"fails": failures(post or None), "post": post, "avisos": _inbox.avisos_log(),
                                          "journal": system.agendador_log(filtro=f"#{post}" if post else "")})


@app.get("/configurar/marca/{theme}/exemplo.jpg")
def config_brand_sample(request: Request, theme: str):
    """Imagem de exemplo ("Imagem com frase") com o logótipo e a assinatura atuais da marca."""
    import hashlib
    import threading
    from ..config import set_theme
    from ..media import brand_assets, image_gen
    if not _current_user(request):
        return _forbidden()
    ident = brand_assets.get(theme)
    if not ident:
        return PlainTextResponse("marca desconhecida", status_code=404)
    logo = ident["logo"]
    key = hashlib.sha1(json.dumps([theme, str(logo), logo.stat().st_mtime if logo else 0, ident["signature"],
                                   ident.get("accent", "")])
                       .encode()).hexdigest()[:12]
    out = DATA_DIR / "marcas" / "exemplos" / f"{theme}-{key}.jpg"
    if not out.exists():
        with _SAMPLE_LOCK:
            set_theme(theme)
            try:
                image_gen.quote_card("Exemplo de frase: assim fica a imagem com o logótipo e a assinatura desta marca.",
                                     out, size=(1080, 1350))
            finally:
                set_theme(None)
    return FileResponse(out, headers={"Cache-Control": "no-store"})


@app.post("/configurar/marca/{theme}")
def config_brand_save(request: Request, theme: str, assinatura: str = Form(""), sem_logo: str = Form(""),
                      repor: str = Form(""), cor: str = Form(""), repor_cor: str = Form(""),
                      logo: UploadFile | None = File(None)):
    from urllib.parse import quote
    from ..media import brand_assets
    me = _current_user(request)
    if not (me and me.is_admin):
        return _forbidden()
    if theme not in brand_assets.BRANDS:
        return _forbidden("Marca desconhecida.")
    if repor:
        brand_assets.reset_logo(theme)
        return RedirectResponse(f"/configurar?marca=ok#marca-{theme}", 303)
    try:
        img = _read_card_image(logo)
    except ValueError as exc:
        return RedirectResponse(f"/configurar?marca=" + quote(str(exc)) + f"#marca-{theme}", 303)
    if img and img[1] == ".gif":
        return RedirectResponse(f"/configurar?marca=" + quote("o logótipo tem de ser PNG (de preferência com fundo transparente) ou JPG") + f"#marca-{theme}", 303)
    if img:
        brand_assets.save_logo(theme, *img)
    sig = assinatura.strip()[:60]
    if theme != "pessoal" and "carreto" in sig.lower() and "david" in sig.lower():
        return RedirectResponse(f"/configurar?marca=" + quote("o nome do David só pode aparecer nas contas pessoais") + f"#marca-{theme}", 303)
    import re as _re3
    extra = {}
    if repor_cor:
        extra["accent"] = ""
    elif _re3.fullmatch(r"#[0-9A-Fa-f]{6}", cor.strip()):
        extra["accent"] = cor.strip().upper()
    brand_assets.save(theme, signature=sig, no_logo=bool(sem_logo) and not img, **extra)
    return RedirectResponse(f"/configurar?marca=ok#marca-{theme}", 303)


@app.get("/configurar/cartao-link.png")
def config_card_image(request: Request):
    from .. import linkcard
    if not _current_user(request):
        return _forbidden()
    return FileResponse(linkcard.default_image(), headers={"Cache-Control": "no-store"})


@app.post("/configurar/cartao-link")
def config_card_save(request: Request, titulo: str = Form(""), descricao: str = Form(""), repor: str = Form(""),
                     imagem: UploadFile | None = File(None)):
    from urllib.parse import quote
    from .. import linkcard
    me = _current_user(request)
    if not (me and me.is_admin):
        return _forbidden()
    if repor:
        old = linkcard.custom_default_image()
        if old:
            old.unlink()
        return RedirectResponse("/configurar?cartao=ok#cartao-link", 303)
    try:
        img = _read_card_image(imagem)
    except ValueError as exc:
        return RedirectResponse("/configurar?cartao=" + quote(str(exc)) + "#cartao-link", 303)
    if img:
        old = linkcard.custom_default_image()
        if old:
            old.unlink()
        linkcard._cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
        (linkcard._cfg.DATA_DIR / f"link_card{img[1]}").write_bytes(img[0])
    linkcard.save_settings(title=titulo.strip()[:200], description=descricao.strip()[:300])
    return RedirectResponse("/configurar?cartao=ok#cartao-link", 303)


@app.get("/post/{pid}", response_class=HTMLResponse)
def post_page(request: Request, pid: int):
    me = request.state.user
    with connect() as conn:
        p = _post_view(conn, get_post(conn, pid))
        history = _history_view(conn, pid, p)
        suggested = None
        if not p["when"] and p["status"] in ("idea", "draft"):
            from ..content.planner import suggested_slot
            try:
                s = suggested_slot(conn, pid, p["account_id"])
                suggested = datetime.fromisoformat(s[:19]) if s else None
            except Exception:  # noqa: BLE001
                suggested = None
    if not me.can_see(p["account_id"]):
        return _forbidden()
    extra = json.loads(p.get("script") or "{}")
    acc = p["account_id"]
    return _render(request, "post.html", {"p": p, "extra": extra, "li": _li_preview(p), "can_create": me.can_create(acc),
                                          "can_approve": me.can_approve(acc), "history": history,
                                          "suggested": suggested, "fix_hint": _fix_hint(p.get("error") or ""),
                                          "approve_error": request.query_params.get("erro") == "aprovar"})


HIST_FIELDS = {"status": "Estado", "media_ids": "Imagem/vídeo", "cover_id": "Capa", "format": "Tipo",
               "scheduled_at": "Data", "caption": "Legenda"}


def _fix_hint(error: str) -> str:
    """Frase de ajuda que corresponde aos problemas que impediram a aprovação."""
    e = error.lower()
    steps = []
    if "sem data" in e:
        steps.append('escolha a <a href="#quando" class="gold">data e hora</a>')
    if "preencher" in e:
        steps.append("complete a legenda (substitua os [PREENCHER…])")
    elif "sem legenda" in e:
        steps.append("escreva a legenda (ou peça-a à IA)")
    if "sem vídeo/imagem" in e:
        steps.append("acrescente a imagem/vídeo")
    if "não se usa" in e or "informação interna" in e:
        steps.append("retire da legenda o que não se pode publicar (ver o aviso por baixo da legenda)")
    if "formato:" in e:
        steps.append("corrija o formato (ver o painel \"Formato para publicar\")")
    if not steps:
        return ""
    text = steps[0] if len(steps) == 1 else ", ".join(steps[:-1]) + " e " + steps[-1]
    return text[0].upper() + text[1:] + ' e carregue outra vez em "Guardar e aprovar".'


def _describe_media_change(old: list, new: list) -> str:
    """Descrição legível de uma mudança de imagens quando não ficou nota (ex.: alterações antigas)."""
    parts = []
    removed = [i + 1 for i, m in enumerate(old) if m not in new]
    added = [i + 1 for i, m in enumerate(new) if m not in old]
    if removed:
        parts.append("Retirada" + ("s imagens " if len(removed) > 1 else " imagem ") + ", ".join(map(str, removed)))
    if added:
        parts.append("Acrescentada" + ("s imagens " if len(added) > 1 else " imagem ") + ", ".join(map(str, added)))
    if not parts and set(old) == set(new) and old != new:
        moved = [f"imagem {old.index(m) + 1} → posição {i + 1}" for i, m in enumerate(new) if old.index(m) != i]
        parts.append("Ordem alterada: " + ", ".join(moved))
    if not parts and old and new and len(old) == len(new):
        parts.append("Substituída(s) por nova versão")
    return "; ".join(parts)


def _history_view(conn, pid: int, p: dict) -> list[dict]:
    from ..db import post_history
    from ..media.formats import KINDS, kind_of
    out = []
    for h in post_history(conn, pid):
        def show(v, field=h["field"]):
            if v in (None, ""):
                return "—"
            if field == "status":
                return STATUS.get(v, (v,))[0]
            if field == "media_ids":
                n = len(json.loads(v or "[]"))
                return "nenhum" if not n else f"{n} imagem/vídeo" if n == 1 else f"{n} imagens/vídeos"
            if field == "format":
                return KINDS.get(kind_of(v), v)
            if field == "scheduled_at":
                return v[:16].replace("T", " ")
            if field == "caption":
                return (v[:60] + "…") if len(v) > 60 else v
            return v
        restorable = (h["field"] == "media_ids" and json.loads(h["old"] or "[]")
                      and h["old"] != p.get("media_ids"))
        note = h["note"] if "note" in h.keys() else None
        if h["field"] == "media_ids" and not note:
            note = _describe_media_change(json.loads(h["old"] or "[]"), json.loads(h["new"] or "[]"))
        out.append({"note": note,
                    "id": h["id"], "at": h["at"][:16].replace("T", " "), "who": h["user_name"] or "sistema",
                    "field": HIST_FIELDS.get(h["field"], h["field"]), "old": show(h["old"]), "new": show(h["new"]),
                    "restorable": bool(restorable)})
    return out


@app.post("/post/{pid}")
def post_action(request: Request, pid: int, action: str = Form(...), caption: str = Form(""),
                quando: str = Form(""), tipo: str = Form(""), hist: int = Form(0), idx: int = Form(-1),
                dir: int = Form(0), img: str = Form(""), sem_data: str = Form("")):
    from ..media.formats import format_for, kind_of, kinds_for
    from ..scheduler import all_problems, parse_dt
    me = request.state.user
    with connect() as conn:
        row = get_post(conn, pid)
        acc = row["account_id"]
        if not me.can_see(acc):
            return _forbidden()
        if action in ("aprovar", "rejeitar", "repetir") and not me.can_approve(acc):
            return _forbidden("Podes criar e editar nesta conta, mas não aprovar. Pede a um aprovador.")
        if not me.can_create(acc):
            return _forbidden("Nesta conta só tens acesso para ver.")
        fields: dict = {}
        if caption.strip() and caption.strip() != (row["caption"] or ""):
            fields["caption"] = caption.strip()
        if sem_data and row["scheduled_at"] and not quando:
            if not me.can_approve(acc):
                return _forbidden("Agendar (mudar a data) é para quem aprova nesta conta.")
            fields["scheduled_at"] = None
        if quando:
            new_when = parse_dt(quando).isoformat()
            if new_when[:16] != (row["scheduled_at"] or "")[:16]:
                if not me.can_approve(acc):
                    return _forbidden("Agendar (mudar a data) é para quem aprova nesta conta.")
                fields["scheduled_at"] = new_when
        platform = accounts()[acc].platform if acc in accounts() else ""
        if tipo and tipo != kind_of(row["format"]):
            if tipo not in kinds_for(platform):
                return _forbidden("Esse tipo de publicação não existe para esta rede.")
            fields["format"] = format_for(tipo, platform)
        if fields:
            update_post(conn, pid, _by=me.id, **fields)
        if action in ("mover", "retirar"):   # gerir as imagens do carrossel (não aprova nada)
            ids = json.loads(get_post(conn, pid)["media_ids"] or "[]")
            if not 0 <= idx < len(ids):
                return _forbidden("Essa imagem já não existe nesta publicação.")
            if action == "mover":
                new = idx + (1 if dir > 0 else -1)
                if 0 <= new < len(ids):
                    ids[idx], ids[new] = ids[new], ids[idx]
                    update_post(conn, pid, _by=me.id, media_ids=ids,
                                _note=f"Imagem {idx + 1} movida para a posição {new + 1}")
                    idx = new
            else:
                if len(ids) == 1:
                    return _forbidden("É a única imagem: acrescente outra antes de retirar esta.")
                ids.pop(idx)                       # sai do post; o ficheiro fica guardado (e no histórico)
                update_post(conn, pid, _by=me.id, media_ids=ids, _note=f"Retirada imagem {idx + 1}")
                idx = min(idx, len(ids) - 1)
            return RedirectResponse(f"/post/{pid}#img={idx + 1}", 303)
        if action == "repor":   # repõe a imagem/vídeo de uma versão anterior (histórico)
            h = conn.execute("SELECT * FROM post_history WHERE id=? AND post_id=? AND field='media_ids'",
                             (hist, pid)).fetchone()
            if not h or not json.loads(h["old"] or "[]"):
                return _forbidden("Essa versão não existe.")
            restore = {"media_ids": h["old"], "error": None}
            if row["status"] == "idea":
                restore["status"] = "draft"
            update_post(conn, pid, _by=me.id, _note="Reposta uma versão anterior das imagens", **restore)
            return RedirectResponse(f"/post/{pid}", 303)
        if action == "legenda_ia":
            try:
                refazer = bool((get_post(conn, pid)["caption"] or "").strip())
                jobs.enqueue("legenda-ia", [str(pid)],
                             f"{'Refazer legenda' if refazer else 'Legenda pela IA'} #{pid}", user_id=me.id, conn=conn)
            except Exception as exc:  # noqa: BLE001
                log.exception("legenda_ia #%s", pid)
                return _back_with_error(pid, f"Não foi possível pedir a legenda à IA: {exc}")
            return RedirectResponse("/tarefas", 303)
        if action == "ajustar":
            jobs.enqueue("ajustar-formato", [str(pid)], f"Ajustar formato #{pid}", user_id=me.id, conn=conn)
            return RedirectResponse("/tarefas", 303)
        if action in ("aprovar", "rejeitar") and row["status"] in ("published", "assist_sent", "tiktok_draft"):
            return _forbidden("Esta publicação já saiu: não se aprova nem rejeita outra vez.")
        if action == "aprovar":
            problems = all_problems(conn, get_post(conn, pid))
            if problems:   # fica (ou vai) para a página da publicação, com o erro em cima
                update_post(conn, pid, error="; ".join(problems))
                return RedirectResponse(f"/post/{pid}?erro=aprovar" + (f"#img={img}" if img.isdigit() else ""), 303)
            else:
                update_post(conn, pid, _by=me.id, status="approved", error=None, approved_by=me.id)
        elif action == "repetir":
            # "Tentar outra vez" depois de "Falhou": volta a aprovado; se a hora já passou, sai daqui a 2 minutos
            cur = get_post(conn, pid)
            if cur["status"] != "failed":
                return _forbidden("Só se pode tentar outra vez uma publicação que falhou.")
            problems = all_problems(conn, cur)
            if problems:
                update_post(conn, pid, error="; ".join(problems))
                return RedirectResponse(f"/post/{pid}?erro=aprovar", 303)
            fields = {"status": "approved", "error": None, "approved_by": me.id}
            from ..scheduler import _tz
            now = datetime.now(_tz())
            if not cur["scheduled_at"] or parse_dt(cur["scheduled_at"]) < now:
                fields["scheduled_at"] = (now + timedelta(minutes=2)).isoformat(timespec="seconds")
            update_post(conn, pid, _by=me.id, _note="tentar outra vez", **fields)
            return RedirectResponse(f"/post/{pid}?repetir=1", 303)
        elif action == "rejeitar":
            update_post(conn, pid, _by=me.id, status="rejected", approved_by=me.id)
        elif action == "refazer":
            # Só para vídeos. O vídeo atual FICA até o novo estar pronto (a tarefa substitui-o no fim;
            # o anterior continua no histórico). Nunca apaga a media nem muda o estado.
            if kind_of(get_post(conn, pid)["format"]) != "video":
                return _forbidden("'Refazer vídeo' só existe para publicações de vídeo.")
            jobs.enqueue("create-video", ["--account", acc, "--post", str(pid)], f"Refazer #{pid}",
                         user_id=me.id, conn=conn)
            return RedirectResponse("/tarefas", 303)
    return RedirectResponse(f"/post/{pid}" if action == "guardar" else "/aprovar", 303)


MAX_IMAGE_BYTES = 30 * 1024 * 1024


@app.post("/post/{pid}/imagens")
def post_add_images(request: Request, pid: int, imagens: list[UploadFile] = File(default=[])):
    """Acrescenta imagens ao carrossel (do computador/telemóvel), até ao máximo da rede."""
    from PIL import Image, ImageOps
    from ..media.formats import spec_for
    me = request.state.user
    with connect() as conn:
        row = get_post(conn, pid)
        acc = row["account_id"]
        if not me.can_create(acc):
            return _forbidden("Nesta conta só tens acesso para ver.")
        platform = accounts()[acc].platform if acc in accounts() else ""
        mx = spec_for(platform, "carousel").get("count", (2, 10))[1]
        ids = json.loads(row["media_ids"] or "[]")
        folder = DATA_DIR / "media" / "uploads" / f"post{pid}"
        folder.mkdir(parents=True, exist_ok=True)
        added = 0
        notes: list[str] = []
        for f in imagens:
            if not f.filename:
                continue
            if len(ids) >= mx:
                return _forbidden(f"O carrossel já tem o máximo desta rede ({mx} imagens).")
            data = f.file.read(MAX_IMAGE_BYTES + 1)
            if len(data) > MAX_IMAGE_BYTES:
                return _forbidden("Imagem demasiado grande (máx. 30 MB).")
            dest = folder / f"{datetime.now():%Y%m%d_%H%M%S}_{len(ids) + 1:02d}.jpg"
            try:
                import io
                with Image.open(io.BytesIO(data)) as im:
                    ImageOps.exif_transpose(im).convert("RGB").save(dest, quality=95)
            except Exception:  # noqa: BLE001
                return _forbidden(f"'{f.filename}' não é uma imagem que eu consiga abrir (JPG, PNG ou WEBP).")
            ids.append(add_media(conn, "image", str(dest), None, {"upload": f.filename}))
            added += 1
            from ..media.formats import _ratio_name, measure
            w, h, *_ = measure(str(dest))
            notes.append(f"Acrescentada imagem {len(ids)} ({w}×{h} · {_ratio_name(w / h)})")
        if added:
            update_post(conn, pid, _by=me.id, media_ids=ids, _note="; ".join(notes))
    return RedirectResponse(f"/post/{pid}#img={len(ids)}", 303)


@app.get("/factos")
def facts_redirect(marca: str = "geral"):
    return RedirectResponse(f"/conhecimento?marca={marca}", 303)


# ------------------------------------------------------------------ base de conhecimento
def _kb_brands() -> list[dict]:
    from ..config import facts_brands
    return [*facts_brands(), {"id": "todas", "name": "Todas as marcas", "groups": []}]


@app.get("/conhecimento", response_class=HTMLResponse)
def knowledge_page(request: Request, marca: str = "geral", ok: str = "", erro: str = "", editar: int = 0):
    from .. import knowledge as kb
    from ..config import facts_brand
    from ..content.facts_check import contradictions, usage
    if not request.state.user.is_admin:
        return _forbidden("Só o administrador edita a base de conhecimento.")
    brands = _kb_brands()
    if marca not in {b["id"] for b in brands}:
        marca = "geral"
    with connect() as conn:
        its = kb.items(conn, marca)
        tone, words = kb.tone(conn, marca), kb.forbidden_words(conn, marca)
        novos = kb.new_base_items(conn, marca)
        hist = kb.history(conn, marca)
        accs = {i: a for i, a in accounts().items() if marca == "todas" or facts_brand(i) == marca}
        caps = [r["caption"] or "" for r in conn.execute("SELECT account_id, caption FROM posts WHERE status != 'rejected'")
                if r["account_id"] in accs]
    texts = [i["text"] for i in its if i["status"] == "publicavel"]
    used = {u["fact"]: u for u in usage(texts, caps)}
    for i in its:
        u = used.get(i["text"])
        i["used"] = None if not u or not u["terms"] else u["used"]
    by_section = [(sid, label, [i for i in its if i["section"] == sid]) for sid, label in kb.SECTIONS.items()]
    return _render(request, "knowledge.html", {
        "marca": marca, "brands": brands, "marca_nome": next(b["name"] for b in brands if b["id"] == marca),
        "sections": by_section, "tone": tone, "words": words, "novos": novos, "hist": hist,
        "contradicoes": contradictions(texts, accs), "accs": accs, "SECTIONS": kb.SECTIONS, "STATUS": kb.STATUS,
        "ROLES": kb.ROLES, "ok": ok, "erro": erro, "editar": editar, "page": "conhecimento"})


@app.post("/conhecimento/ficha")
async def knowledge_save(request: Request):
    from urllib.parse import quote
    from .. import knowledge as kb
    me = request.state.user
    if not me.is_admin:
        return _forbidden("Só o administrador edita a base de conhecimento.")
    form = await request.form()
    data = {k: str(form.get(k, "")) for k in ("brand", "section", "text", "answer", "status", "role", "value",
                                                "keywords", "valid_until")}
    data["accounts"] = [str(a) for a in form.getlist("accounts")]
    marca = data["brand"] if data["brand"] in {b["id"] for b in _kb_brands()} else "geral"
    data["brand"] = marca
    item_id = int(form.get("id") or 0)
    try:
        with connect() as conn:
            row = kb.clean(data)
            if form.get("acao") == "apagar" and item_id:
                kb.delete(conn, item_id, me.id)
                msg = "Ficha apagada."
            elif item_id:
                kb.update(conn, item_id, row, me.id)
                msg = "Ficha guardada."
            else:
                kb.create(conn, row, me.id)
                msg = "Ficha acrescentada."
    except ValueError as exc:
        return RedirectResponse(f"/conhecimento?marca={marca}&erro={quote(str(exc))}#{data['section']}", 303)
    return RedirectResponse(f"/conhecimento?marca={marca}&ok={quote(msg)}#{data['section']}", 303)


@app.post("/conhecimento/regras")
def knowledge_rules(request: Request, marca: str = Form("geral"), tom: str = Form(""), proibidas: str = Form("")):
    from urllib.parse import quote
    from .. import knowledge as kb
    if not request.state.user.is_admin:
        return _forbidden("Só o administrador edita a base de conhecimento.")
    with connect() as conn:
        kb.save_brand_rules(conn, marca, tom, proibidas.split(","), request.state.user.id)
    return RedirectResponse(f"/conhecimento?marca={marca}&ok={quote('Tom e palavras proibidas guardados.')}", 303)


@app.post("/conhecimento/juntar")
def knowledge_add_base(request: Request, marca: str = Form("geral")):
    from urllib.parse import quote
    from .. import knowledge as kb
    if not request.state.user.is_admin:
        return _forbidden("Só o administrador edita a base de conhecimento.")
    with connect() as conn:
        n = kb.add_base_items(conn, marca, request.state.user.id)
    return RedirectResponse(f"/conhecimento?marca={marca}&ok={quote(f'{n} ficha(s) acrescentada(s).')}", 303)


@app.get("/conhecimento/exportar")
def knowledge_export(request: Request):
    import tempfile
    from .. import knowledge as kb
    if not request.state.user.is_admin:
        return _forbidden("Só o administrador.")
    tmp = Path(tempfile.mkdtemp()) / f"conhecimento_{datetime.now():%Y%m%d}.xlsx"
    with connect() as conn:
        kb.export_xlsx(conn, tmp)
    return FileResponse(tmp, filename=tmp.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.post("/conhecimento/importar")
def knowledge_import(request: Request, ficheiro: UploadFile = File(...)):
    import tempfile
    from urllib.parse import quote
    from .. import knowledge as kb
    if not request.state.user.is_admin:
        return _forbidden("Só o administrador.")
    data = ficheiro.file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024 or not (ficheiro.filename or "").lower().endswith(".xlsx"):
        return RedirectResponse(f"/conhecimento?erro={quote('Envie um ficheiro Excel (.xlsx) até 10 MB.')}", 303)
    tmp = Path(tempfile.mkdtemp()) / "importar.xlsx"
    tmp.write_bytes(data)
    try:
        with connect() as conn:
            created, updated, errors = kb.import_xlsx(conn, tmp, request.state.user.id)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/conhecimento?erro={quote('Não consegui ler o Excel: ' + str(exc)[:150])}", 303)
    msg = f"Importação: {created} nova(s), {updated} atualizada(s)."
    err = "; ".join(errors[:8])
    return RedirectResponse(f"/conhecimento?ok={quote(msg)}&erro={quote(err)}", 303)


# ------------------------------------------------------------------ contas (ligar redes)
@app.get("/contas", response_class=HTMLResponse)
def accounts_page(request: Request, msg: str = "", erro: str = ""):
    from .. import meta_connect as mc
    if not request.state.user.is_admin:
        return _forbidden("Só o administrador liga as contas.")
    found = mc.discovered()
    over = __import__("carretos_social.config", fromlist=["account_overrides"]).account_overrides()
    rows = []
    for g, accs in accounts_by_group():
        items = []
        for a in accs:
            meta = a.platform in ("instagram", "facebook_page")
            items.append({"a": a, "meta": meta, "over": over.get(a.id) or {},
                          "options": mc.options_for(a, found) if meta else [],
                          "suggest": mc.suggestion(a, found) if meta and not a.connected else ""})
        rows.append((g, items))
    from .. import linkedin_connect as lc
    from .. import tiktok_connect as tc
    from .. import health
    return _render(request, "accounts.html", {"rows": rows, "found": found, "configured": mc.configured(),
                                              "health": health.results(),
                                              "li": {"configured": lc.configured(), "org": lc.org_enabled(),
                                                     "org_app": lc.configured("pagina"),
                                                     "saved": lc.saved(),
                                                     "redirect": _base_url(request) + "/contas/linkedin/callback"},
                                              "tt": {"configured": tc.configured(),
                                                     "redirect": _base_url(request) + "/contas/tiktok/callback"},
                                              "redirect": _base_url(request) + "/contas/meta/callback",
                                              "msg": msg, "erro": erro, "page": "contas"})


@app.get("/contas/meta/ligar")
def meta_login(request: Request):
    from .. import meta_connect as mc
    if not request.state.user.is_admin:
        return _forbidden("Só o administrador liga as contas.")
    if not mc.configured():
        return RedirectResponse("/contas?erro=Primeiro+preencha+o+App+ID+e+o+App+Secret+da+Meta+em+⚙+Configurar", 303)
    state = secrets.token_urlsafe(24)
    r = RedirectResponse(mc.login_url(_base_url(request) + "/contas/meta/callback", state), 303)
    r.set_cookie("meta_state", state, max_age=900, httponly=True, samesite="lax",
                 secure=os.environ.get("DASHBOARD_HTTPS", "") == "1")
    return r


@app.get("/contas/meta/callback")
def meta_callback(request: Request, code: str = "", state: str = "", error_description: str = "", error: str = ""):
    from urllib.parse import quote
    from .. import meta_connect as mc
    if not request.state.user.is_admin:
        return _forbidden("Só o administrador liga as contas.")
    if error or not code:
        return RedirectResponse(f"/contas?erro={quote('O Facebook não autorizou: ' + (error_description or error or 'cancelado'))}", 303)
    if not state or not hmac.compare_digest(state, request.cookies.get("meta_state", "")):
        return RedirectResponse("/contas?erro=Pedido+expirado:+carregue+outra+vez+em+Ligar+com+o+Facebook", 303)
    try:
        token = mc.exchange_code(code, _base_url(request) + "/contas/meta/callback")
        found = mc.discover(token)
    except Exception as exc:  # noqa: BLE001
        log.exception("meta callback")
        return RedirectResponse(f"/contas?erro={quote('Não foi possível ligar: ' + str(exc))}", 303)
    n = len(found["pages"])
    n_ig = sum(1 for p in found["pages"] if p.get("ig"))
    text = (f"Autorizado por {found['user']}: {n} Página(s) e {n_ig} Instagram(s). "
            "Confirme abaixo a que conta corresponde cada uma.")
    r = RedirectResponse(f"/contas?msg={quote(text)}", 303)
    r.delete_cookie("meta_state")
    return r


@app.post("/contas/meta/associar")
async def meta_associate(request: Request):
    from urllib.parse import quote
    from .. import envfile
    from .. import meta_connect as mc
    if not request.state.user.is_admin:
        return _forbidden("Só o administrador liga as contas.")
    form = await request.form()
    updates: dict[str, str] = {}
    done, errors = [], []
    for a in mc.meta_accounts():
        choice = str(form.get(f"acc_{a.id}", "")).strip()
        if not choice:
            continue
        try:
            updates.update(mc.link(a, choice))
            done.append(a.name)
        except ValueError as exc:
            errors.append(f"{a.name}: {exc}")
    if updates:
        envfile.set_env(updates, root=ROOT)
    msg = f"Ligadas: {', '.join(done)}." if done else ""
    return RedirectResponse(f"/contas?msg={quote(msg)}&erro={quote('; '.join(errors))}", 303)


@app.post("/contas/{acc_id}/testar")
def account_test(request: Request, acc_id: str):
    from urllib.parse import quote
    from .. import health
    if not request.state.user.is_admin or acc_id not in accounts():
        return _forbidden()
    acc = accounts()[acc_id]
    ok, text = health.test_account(acc)
    key = "msg" if ok else "erro"
    return RedirectResponse(f"/contas?{key}={quote(accounts()[acc_id].name + ': ' + text)}", 303)


@app.post("/contas/verificar")
def accounts_check_all(request: Request):
    from urllib.parse import quote
    from .. import health
    if not request.state.user.is_admin:
        return _forbidden()
    res = health.check_all(alert=False)
    bad = [r["name"] for r in res.values() if not r["ok"]]
    text = f"Verificadas {len(res)} ligações: " + ("todas a funcionar." if not bad else f"com problemas: {', '.join(bad)}.")
    return RedirectResponse(f"/contas?{'msg' if not bad else 'erro'}={quote(text)}", 303)


@app.post("/contas/{acc_id}/desligar")
def account_unlink(request: Request, acc_id: str):
    from urllib.parse import quote
    from .. import envfile
    from .. import meta_connect as mc
    if not request.state.user.is_admin or acc_id not in accounts():
        return _forbidden()
    acc = accounts()[acc_id]
    if acc.platform == "tiktok":
        from .. import tiktok_connect as tc
        envfile.set_env(tc.unlink(acc), root=ROOT)
    else:
        envfile.set_env(mc.unlink(acc), root=ROOT)
    return RedirectResponse(f"/contas?msg={quote(accounts()[acc_id].name + ': desligada.')}", 303)


# ---------------- LinkedIn
@app.get("/contas/linkedin/ligar")
def linkedin_login(request: Request, app_: str = Query("perfil", alias="app")):
    from .. import linkedin_connect as lc
    if not request.state.user.is_admin:
        return _forbidden("Só o administrador liga as contas.")
    app_ = "pagina" if app_ == "pagina" else "perfil"
    if not lc.configured(app_):
        what = "da 2.ª app (página)" if app_ == "pagina" else "do LinkedIn"
        return RedirectResponse(f"/contas?erro=Primeiro+preencha+o+Client+ID+e+o+Client+Secret+{what.replace(' ', '+')}+em+⚙+Configurar", 303)
    state = secrets.token_urlsafe(24)
    r = RedirectResponse(lc.login_url(_base_url(request) + "/contas/linkedin/callback", state, app_), 303)
    r.set_cookie("li_state", f"{state}|{app_}", max_age=900, httponly=True, samesite="lax",
                 secure=os.environ.get("DASHBOARD_HTTPS", "") == "1")
    return r


@app.get("/contas/linkedin/callback")
def linkedin_callback(request: Request, code: str = "", state: str = "", error: str = "", error_description: str = ""):
    from urllib.parse import quote
    from .. import envfile
    from .. import linkedin_connect as lc
    if not request.state.user.is_admin:
        return _forbidden("Só o administrador liga as contas.")
    if error or not code:
        return RedirectResponse(f"/contas?erro={quote('O LinkedIn não autorizou: ' + (error_description or error or 'cancelado'))}", 303)
    saved_state, _, app_ = request.cookies.get("li_state", "").partition("|")
    if not state or not hmac.compare_digest(state, saved_state):
        return RedirectResponse("/contas?erro=Pedido+expirado:+carregue+outra+vez+em+Ligar+com+o+LinkedIn", 303)
    redirect = _base_url(request) + "/contas/linkedin/callback"
    try:
        if app_ == "pagina":
            updates, info = lc.connect_org(lc.exchange(code, redirect, "pagina"))
            text = ("Páginas encontradas: " + ", ".join(o["name"] for o in info["orgs"]) + "."
                    if info["orgs"] else "Não encontrei páginas de que seja administrador.")
            if updates:
                text += " Página da Carretos Group ligada."
        else:
            updates, info = lc.connect_member(lc.exchange(code, redirect, "perfil"))
            text = f"LinkedIn de {info['name']} ligado."
        envfile.set_env(updates, root=ROOT)
    except lc.WrongAccount as exc:                     # outra conta LinkedIn: nada foi guardado
        return RedirectResponse(f"/contas?erro={quote(str(exc))}", 303)
    except Exception as exc:  # noqa: BLE001
        log.exception("linkedin callback")
        return RedirectResponse(f"/contas?erro={quote('Não foi possível ligar o LinkedIn: ' + str(exc))}", 303)
    r = RedirectResponse(f"/contas?msg={quote(text)}", 303)
    r.delete_cookie("li_state")
    return r


@app.post("/contas/linkedin/associar")
def linkedin_associate(request: Request, urn: str = Form("")):
    from urllib.parse import quote
    from .. import envfile
    from .. import linkedin_connect as lc
    if not request.state.user.is_admin:
        return _forbidden("Só o administrador liga as contas.")
    try:
        envfile.set_env(lc.link_org(urn), root=ROOT)
    except ValueError as exc:
        return RedirectResponse(f"/contas?erro={quote(str(exc))}", 303)
    return RedirectResponse("/contas?msg=Página+do+LinkedIn+ligada.", 303)


@app.post("/contas/{acc_id}/tiktok-teste")
def tiktok_test_draft(request: Request, acc_id: str):
    me = request.state.user
    if not me.is_admin or acc_id not in accounts() or accounts()[acc_id].platform != "tiktok":
        return _forbidden()
    jobs.enqueue("tiktok-teste", ["--account", acc_id], f"Teste de rascunho TikTok · {accounts()[acc_id].name}",
                 user_id=me.id)
    return RedirectResponse("/tarefas", 303)


# ---------------- TikTok (cada conta autoriza à parte)
@app.get("/contas/tiktok/ligar")
def tiktok_login(request: Request, conta: str = ""):
    from .. import tiktok_connect as tc
    if not request.state.user.is_admin:
        return _forbidden("Só o administrador liga as contas.")
    if conta not in accounts() or accounts()[conta].platform != "tiktok":
        return _forbidden("Conta TikTok desconhecida.")
    if not tc.configured():
        return RedirectResponse("/contas?erro=Primeiro+preencha+o+Client+key+e+o+Client+secret+da+TikTok+em+⚙+Configurar", 303)
    state = secrets.token_urlsafe(24)
    r = RedirectResponse(tc.login_url(_base_url(request) + "/contas/tiktok/callback", state), 303)
    r.set_cookie("tt_state", f"{state}|{conta}", max_age=900, httponly=True, samesite="lax",
                 secure=os.environ.get("DASHBOARD_HTTPS", "") == "1")
    return r


@app.get("/contas/tiktok/callback")
def tiktok_callback(request: Request, code: str = "", state: str = "", error: str = "", error_description: str = ""):
    from urllib.parse import quote
    from .. import envfile
    from .. import tiktok_connect as tc
    if not request.state.user.is_admin:
        return _forbidden("Só o administrador liga as contas.")
    if error or not code:
        return RedirectResponse(f"/contas?erro={quote('A TikTok não autorizou: ' + (error_description or error or 'cancelado'))}", 303)
    saved_state, _, conta = request.cookies.get("tt_state", "").partition("|")
    if not state or not hmac.compare_digest(state, saved_state) or conta not in accounts():
        return RedirectResponse("/contas?erro=Pedido+expirado:+carregue+outra+vez+em+Ligar+esta+conta", 303)
    acc = accounts()[conta]
    try:
        envfile.set_env(tc.link(acc, tc.exchange(code, _base_url(request) + "/contas/tiktok/callback")), root=ROOT)
    except Exception as exc:  # noqa: BLE001
        log.exception("tiktok callback")
        return RedirectResponse(f"/contas?erro={quote('Não foi possível ligar ' + acc.name + ': ' + str(exc))}", 303)
    handle = accounts()[conta].handle
    r = RedirectResponse(f"/contas?msg={quote(acc.name + ' ligada (@' + handle + ').')}", 303)
    r.delete_cookie("tt_state")
    return r


_LEGAL = {
    "privacidade": ("Política de privacidade", [
        "O Carretos Studio é a ferramenta interna da Carretos Group (ANTÓNIO DAVID GROU CARRETO, UNIPESSOAL, LDA) para "
        "criar, agendar e publicar conteúdos nas suas próprias contas de redes sociais e para gerir os comentários e as "
        "mensagens que essas contas recebem.",
        "Que dados tratamos: quando alguém comenta ou envia uma mensagem a uma conta nossa (Facebook, Instagram, "
        "LinkedIn), recebemos o texto, o nome público ou nome de utilizador, o identificador da conta e a data. Usamos "
        "estes dados só para mostrar o comentário ou a mensagem à nossa equipa e responder (cada resposta é aprovada por "
        "uma pessoa). Não os vendemos, não os partilhamos com terceiros e não os usamos para publicidade.",
        "Das nossas próprias contas lemos também a lista de Páginas e contas profissionais que gerimos (incluindo as dos "
        "portefólios empresariais), as nossas publicações e as estatísticas agregadas dessas publicações (alcance, "
        "visualizações, gostos, comentários, partilhas), para planear e avaliar os conteúdos.",
        "As autorizações das redes sociais (chaves de acesso) ficam guardadas só no nosso servidor e não são partilhadas. "
        "O acesso pode ser retirado a qualquer momento no Carretos Studio (Contas → Desligar) ou nas definições de "
        "aplicações de cada rede social; ao desligar, as chaves dessa conta são apagadas do servidor.",
        "Guardamos os comentários e as mensagens enquanto forem úteis para o atendimento e no máximo 12 meses; depois são "
        "apagados automaticamente.",
        "#Eliminação de dados",
        "Pode pedir a eliminação dos seus dados (comentários e mensagens) enviando um email para davidcarreto@carretos.pt "
        "com o assunto \"Eliminar dados\" e a conta ou rede em causa. Apagamos no prazo de 30 dias e confirmamos por "
        "email. Também pode apagar o seu comentário na própria rede social.",
        "Contacto: davidcarreto@carretos.pt · WhatsApp 211 45 46 46.",
        "#Privacy policy (English)",
        "Carretos Studio is the internal tool of Carretos Group (ANTÓNIO DAVID GROU CARRETO, UNIPESSOAL, LDA) to create, "
        "schedule and publish content on its own social media accounts and to manage the comments and messages those "
        "accounts receive.",
        "Data we process: when someone comments on or messages one of our accounts (Facebook, Instagram, LinkedIn), we "
        "receive the text, the public name or username, the account ID and the date. We use this data only to show the "
        "comment or message to our team and to reply (every reply is approved by a person). We do not sell or share it "
        "with third parties and do not use it for advertising.",
        "From our own accounts we also read the list of Pages and professional accounts we manage (including those in our "
        "business portfolios), our own posts and their aggregated statistics (reach, views, likes, comments, shares), to "
        "plan and evaluate our content.",
        "Social network access tokens are stored only on our server and are never shared. Access can be removed at any "
        "time in Carretos Studio (Accounts → Disconnect) or in each social network's app settings; tokens are then "
        "deleted from our server.",
        "We keep comments and messages while useful for customer support, for a maximum of 12 months; after that they are "
        "deleted automatically.",
        "#Data deletion",
        "You can request deletion of your data by emailing davidcarreto@carretos.pt with the subject \"Delete my data\" "
        "and the account or network concerned. We delete it within 30 days and confirm by email. You can also delete your "
        "comment on the social network itself.",
        "Contact: davidcarreto@carretos.pt · WhatsApp +351 211 45 46 46."]),
    "termos": ("Termos de utilização", [
        "O Carretos Studio é uma ferramenta de uso interno da Carretos Group e só é usada pela sua equipa, com contas "
        "pessoais protegidas por palavra-passe.",
        "Só publica nas contas de redes sociais da própria Carretos Group, do David Carreto e das marcas do grupo, e "
        "apenas depois de aprovação de um responsável.",
        "A utilização das redes sociais através do Carretos Studio respeita os termos de cada rede (Meta, LinkedIn e TikTok).",
        "Contacto: WhatsApp 211 45 46 46."]),
}


@app.get("/privacidade", response_class=HTMLResponse)
@app.get("/termos", response_class=HTMLResponse)
def legal_page(request: Request):
    title, paras = _LEGAL[request.url.path.strip("/")]
    def _block(p: str) -> str:
        if p.startswith("#"):                       # subtítulo (com âncora: #eliminacao, #data-deletion…)
            t = p[1:]
            anchor = {"Eliminação de dados": "eliminacao", "Data deletion": "data-deletion",
                      "Privacy policy (English)": "english"}.get(t, "")
            return f"<h2 id='{anchor}' style='color:#D4AF37;font-size:20px;margin-top:28px'>{_esc(t)}</h2>"
        return f"<p>{_esc(p)}</p>"
    body = "".join(_block(p) for p in paras)
    return HTMLResponse(f"<!doctype html><html lang=pt-PT><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                        f"<title>{title} · Carretos Studio</title><body style='background:#000;color:#eee;font:16px/1.6 "
                        f"system-ui;max-width:760px;margin:0 auto;padding:24px'><h1 style='color:#D4AF37'>{title}</h1>"
                        f"<p style='color:#999'>Carretos Studio · Carretos Group</p>{body}</body></html>")


@app.get("/publico/{name}")
def public_file(name: str):
    """Ficheiros que o Instagram/Facebook vão buscar ao publicar (nomes de 32 carateres impossíveis de adivinhar)."""
    if not _re.fullmatch(r"[0-9a-f]{32}\.(jpg|jpeg|png|mp4|mov)", name):
        return HTMLResponse("não encontrado", 404)
    f = DATA_DIR / "publico" / name
    if not f.exists():
        return HTMLResponse("não encontrado", 404)
    return FileResponse(f)


# ------------------------------------------------------------------ para publicar à mão
@app.get("/manual", response_class=HTMLResponse)
def manual_page(request: Request, ok: str = ""):
    """Posts em modo assistido (Facebook pessoal, página LinkedIn, TikTok recusado) e rascunhos do TikTok por
    publicar: legenda para copiar, ficheiros para descarregar e "Já publiquei"."""
    me = request.state.user
    clause, args = _visible_clause(me)
    with connect() as conn:
        rows = [_post_view(conn, r) for r in conn.execute(
            f"SELECT * FROM posts WHERE status IN ('assist_sent','tiktok_draft') AND {clause} "
            "ORDER BY scheduled_at DESC, id DESC LIMIT 60", args)]
    return _render(request, "manual.html", {"posts": rows, "ok": ok, "page": "manual",
                                            "tg_ok": notify_enabled()})


@app.post("/manual/{pid}/publicado")
def manual_done(request: Request, pid: int, link: str = Form("")):
    me = request.state.user
    with connect() as conn:
        row = get_post(conn, pid)
        if not me.can_create(row["account_id"]):
            return _forbidden("Nesta conta só tens acesso para ver.")
        fields = {"status": "published", "error": None}
        if link.strip().startswith("http"):
            fields["remote_url"] = link.strip()
        update_post(conn, pid, _by=me.id, **fields)
    return RedirectResponse("/manual?ok=1", 303)


# ------------------------------------------------------------------ respostas automáticas (webhooks da Meta)
@app.get("/webhooks/meta")
def meta_webhook_verify(request: Request):
    from .. import inbox
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and hmac.compare_digest(q.get("hub.verify_token", ""), inbox.verify_token()):
        return PlainTextResponse(q.get("hub.challenge", ""))
    return PlainTextResponse("token inválido", 403)


@app.post("/webhooks/meta")
async def meta_webhook(request: Request):
    from .. import inbox
    body = await request.body()
    ok = inbox.valid_signature(body, request.headers.get("x-hub-signature-256", ""))
    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        payload = None
    inbox.log_event(payload if ok else None, ok)            # diagnóstico: o que a Meta envia (sem tokens)
    if not ok:
        return PlainTextResponse("assinatura inválida", 403)
    try:
        inbox.receive(payload or {})
    except Exception:  # noqa: BLE001 — responder sempre 200 para a Meta não desativar o webhook
        log.exception("webhook meta")
    return PlainTextResponse("ok")


def _approver_names(rows: list[dict]) -> dict:
    out = {}
    for r in rows:
        if r.get("approved_by") and r["approved_by"] not in out:
            u = users.load(r["approved_by"])
            out[r["approved_by"]] = (u.name or u.username) if u else f"utilizador {r['approved_by']}"
    return out


def _li_calls() -> dict:
    from .. import linkedin_connect as lc, linkedin_inbox as li
    used, budget = li.calls_today(), li.daily_budget()
    # os pedidos dos comentários também passam pelo total; o total nunca é menor (antes desta contagem existir,
    # ou com dois processos a escrever ao mesmo tempo, podia ficar atrás)
    total = max(lc.calls_today_total(), used)
    free = max(0, lc.MEMBER_DAILY_LIMIT - total - max(0, budget - used))
    return {"total": total, "limit": lc.MEMBER_DAILY_LIMIT, "comments": used, "budget": budget, "publish": free,
            "next": li.next_poll_at()}


def _li_mail_addr() -> str:
    try:
        from .. import linkedin_mail
        return linkedin_mail.receive_address(create=True)
    except Exception:  # noqa: BLE001
        return ""


def _service_state(name: str) -> str:
    import subprocess
    try:
        return subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


@app.get("/mensagens", response_class=HTMLResponse)
def inbox_page(request: Request, ok: str = "", erro: str = ""):
    from .. import inbox
    me = request.state.user
    accs = [a for a in inbox.eligible_accounts() if me.can_see(a.id)]
    with connect() as conn:
        ids = [a.id for a in accounts().values() if me.can_see(a.id)]
        # filtro (ex.: para gravar o vídeo da Meta sem mostrar outros clientes): ?conta=<id>&desde=AAAA-MM-DD
        conta, desde = request.query_params.get("conta", ""), request.query_params.get("desde", "")
        if conta:
            ids = [i for i in ids if i == conta]
        rows = [dict(r) for r in conn.execute(
            f"SELECT * FROM inbox WHERE account_id IN ({','.join('?' * len(ids)) or 'NULL'}) AND created_at >= ? "
            "ORDER BY id DESC LIMIT 100", [*ids, desde or "0"])] if ids else []
    names = {a.id: a.name for a in accounts().values()}
    return _render(request, "mensagens.html", {
        "accs": [(a, inbox.account_settings(a.id)) for a in accs], "rows": rows, "names": names, "ok": ok,
        "erro": erro, "page": "mensagens", "callback": _base_url(request) + "/webhooks/meta",
        "verify": (inbox.verify_token()[:4] + "…") if me.is_admin else "", "test": None,
        "events": inbox.recent_events()[:30] if me.is_admin else [],
        "li_minutes": __import__("carretos_social.linkedin_inbox", fromlist=["x"]).interval_minutes(),
        "li_calls": _li_calls(),
        "li_mail": __import__("carretos_social.linkedin_mail", fromlist=["x"]).enabled(),
        "li_mail_addr": _li_mail_addr() if me.is_admin else "",
        "correio": _service_state("carretos-correio") if me.is_admin else "",
        "imap_user": os.environ.get("IMAP_USER", "") if me.is_admin else "",
        "li_last": __import__("carretos_social.linkedin_inbox", fromlist=["x"]).last_round(),
        "mail_minutes": __import__("carretos_social.linkedin_mail", fromlist=["x"]).interval_minutes(),
        "approvers": _approver_names(rows),
        "meta_diag": inbox.last_meta_diagnose() if me.is_admin else {}})


@app.post("/mensagens/conta/{acc_id}")
def inbox_toggle(request: Request, acc_id: str, enabled: str = Form(""), private: str = Form(""),
                 modo: str = Form("")):
    from urllib.parse import quote
    from .. import inbox
    from ..db import now as _now
    me = request.state.user
    if not me.can_approve(acc_id):
        return _forbidden("Ligar respostas automáticas é para quem aprova nesta conta.")
    before = inbox.account_settings(acc_id)
    fields = {"enabled": bool(enabled), "private": bool(private)}
    if modo in ("propor", "auto"):
        fields["mode"] = modo
    if enabled and not before.get("enabled"):
        fields["enabled_at"] = _now()           # não responde a comentários anteriores a este momento
    inbox.save_account_settings(acc_id, **fields)
    state = ("ligadas (" + ("propõe e espera pela aprovação" if inbox.account_settings(acc_id)["mode"] == "propor"
                            else "responde sozinho") + ")") if enabled else "desligadas"
    return RedirectResponse(f"/mensagens?ok={quote(accounts()[acc_id].name + ': respostas automáticas ' + state + '.')}", 303)


@app.post("/mensagens/subscrever/{acc_id}")
def inbox_subscribe(request: Request, acc_id: str):
    from urllib.parse import quote
    from .. import inbox
    if not request.state.user.is_admin or acc_id not in accounts():
        return _forbidden()
    try:
        pid = inbox.subscribe(accounts()[acc_id])
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/mensagens?erro={quote(accounts()[acc_id].name + ': ' + str(exc))}", 303)
    return RedirectResponse(f"/mensagens?ok={quote(accounts()[acc_id].name + f': a Meta passa a enviar os comentários e as mensagens (Página {pid}).')}", 303)


@app.post("/mensagens/linkedin/existentes")
def inbox_linkedin_existing(request: Request):
    """Traz os comentários já existentes (últimos 30 dias) da página LinkedIn, só como propostas."""
    from urllib.parse import quote
    from .. import linkedin_inbox
    me = request.state.user
    if not me.can_approve(linkedin_inbox.ORG_ACCOUNT):
        return _forbidden()
    try:
        lines = linkedin_inbox.poll(include_old=True)
    except Exception as exc:  # noqa: BLE001
        from ..redact import redact
        return RedirectResponse("/mensagens?erro=" + quote("LinkedIn: " + redact(str(exc))[:500]), 303)
    return RedirectResponse("/mensagens?ok=" + quote("LinkedIn: " + (lines[0] if lines else "nada a ler")
                                                     + ". Os comentários trazidos ficam à espera de aprovação."), 303)


@app.get("/mensagens/item/{iid}", response_class=HTMLResponse)
def inbox_item(request: Request, iid: int, acao: str = ""):
    me = request.state.user
    with connect() as conn:
        row = conn.execute("SELECT * FROM inbox WHERE id=?", (iid,)).fetchone()
    if not row:
        resp = _render(request, "nao_existe.html", {"page": "mensagens"})
        resp.status_code = 404
        return resp
    if not me.can_see(row["account_id"] or ""):
        return _forbidden()
    from .. import inbox
    approver = ""
    if row["approved_by"]:
        u = users.load(row["approved_by"])
        approver = (u.name or u.username) if u else f"utilizador {row['approved_by']}"
    return _render(request, "mensagem_item.html", {"r": dict(row), "acao": acao, "page": "mensagens", "approver": approver,
                                                   "acc": accounts().get(row["account_id"]),
                                                   "link": inbox.post_link(row),
                                                   "can_approve": me.can_approve(row["account_id"] or "")})


@app.post("/mensagens/item/{iid}")
def inbox_item_action(request: Request, iid: int, acao: str = Form(...), texto: str = Form(""),
                      origem: str = Form("dashboard")):
    from urllib.parse import quote
    from .. import inbox
    me = request.state.user
    with connect() as conn:
        row = conn.execute("SELECT * FROM inbox WHERE id=?", (iid,)).fetchone()
    if not row or not me.can_approve(row["account_id"] or ""):
        return _forbidden("Aprovar respostas é para quem aprova nesta conta.")
    try:
        if acao == "ignorar":
            inbox.ignore(iid)
            msg = f"Comentário #{iid}: ignorado (não responde)."
        else:
            inbox.approve(iid, texto if texto.strip() else None, user_id=me.id, via=origem)
            msg = f"Comentário #{iid}: resposta enviada."
    except Exception as exc:  # noqa: BLE001
        from ..redact import redact
        return RedirectResponse(f"/mensagens/item/{iid}?erro=" + quote(redact(str(exc))[:500]), 303)
    return RedirectResponse("/mensagens?ok=" + quote(msg), 303)


@app.post("/mensagens/linkedin/emails")
def inbox_linkedin_mail_check(request: Request):
    """Verifica agora a caixa de email (avisos de mensagens do LinkedIn)."""
    from urllib.parse import quote
    from .. import linkedin_mail
    if not request.state.user.is_admin:
        return _forbidden()
    if not linkedin_mail.enabled():
        return RedirectResponse("/mensagens?erro=" + quote("Ligue primeiro em ⚙ Configurar → 'LinkedIn · avisar no Telegram as mensagens privadas' = sim."), 303)
    try:
        lines = linkedin_mail.poll()
    except Exception as exc:  # noqa: BLE001
        from ..redact import redact
        return RedirectResponse("/mensagens?erro=" + quote("Caixa de email: " + redact(str(exc))[:400]), 303)
    return RedirectResponse("/mensagens?ok=" + quote("Caixa de email verificada: " + (lines[0] if lines else "nenhuma mensagem nova do LinkedIn") + "."), 303)


@app.post("/mensagens/meta/diagnostico")
def inbox_meta_diag(request: Request):
    """Só leitura: o que a Meta está configurada para enviar (app e cada Página)."""
    from urllib.parse import quote
    from .. import inbox
    if not request.state.user.is_admin:
        return _forbidden()
    try:
        inbox.meta_diagnose()
    except Exception as exc:  # noqa: BLE001
        from ..redact import redact
        return RedirectResponse("/mensagens?erro=" + quote("Diagnóstico da Meta: " + redact(str(exc))[:400]), 303)
    return RedirectResponse("/mensagens?ok=" + quote("Diagnóstico da Meta atualizado (em baixo).") + "#meta-diag", 303)


@app.post("/mensagens/token-webhook")
def inbox_verify_token_copy(request: Request):
    """Token de verificação do webhook da Meta (só administrador, a pedido, para copiar; não fica na página)."""
    from .. import inbox
    if not request.state.user.is_admin:
        return _forbidden()
    return PlainTextResponse(inbox.verify_token(), headers={"Cache-Control": "no-store"})


@app.post("/mensagens/testar", response_class=HTMLResponse)
def inbox_test(request: Request, conta: str = Form(...), tipo: str = Form("comment"), texto: str = Form(""),
               quem: str = Form("")):
    from .. import inbox
    me = request.state.user
    if conta not in accounts() or not me.can_see(conta):
        return _forbidden()
    acc = accounts()[conta]
    quem = quem.strip() or ("cliente_exemplo" if acc.platform == "instagram" else "João Silva")
    res = inbox.compose(acc, "message" if tipo == "message" else "comment", texto, quem)
    page = inbox_page(request)
    page.context["test"] = {"conta": conta, "tipo": tipo, "texto": texto, "quem": quem, "platform": acc.platform, **res}
    return tpl.TemplateResponse(request, "mensagens.html", page.context)


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
def create_page(request: Request, erro: str = "", form: dict | None = None):
    me = request.state.user
    contas = [accounts()[a] for a in me.creatable_accounts]
    contas_grupos = [(g, [a for a in contas if a.group == g["id"]]) for g in groups()]
    return _render(request, "create.html", {"page": "create", "contas": contas, "erro": erro,
                                            "form": form or {"tipo": "zero"},
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
            return create_page(request, "Escolhe pelo menos um vídeo.",
                               {"tipo": tipo, "conta": conta, "tema": tema, "quando": quando, "segundos": segundos})
        if tipo == "editar" and len(paths) == 1:
            jobs.enqueue("edit-video", [paths[0], "--account", conta, "--seconds", str(segundos), "--fill", "crop",
                                        *(["--goal", tema] if tema else []), *sched],
                         f"Editar vídeo: {Path(paths[0]).name}", user_id=me.id)
        else:
            jobs.enqueue("montage", [*paths, "--account", conta, "--seconds", str(segundos),
                                     *(["--goal", tema] if tema else []), *sched],
                         f"Montagem de {len(paths)} vídeos", user_id=me.id)
    elif tipo == "carrossel":
        frases = [x.strip() for x in (texto or tema).splitlines() if x.strip()]
        if not 2 <= len(frases) <= 10:
            return create_page(request, f"Um carrossel de frases leva 2 a 10 frases, uma por linha "
                                        f"(escreveste {len(frases)}).",
                               {"tipo": tipo, "conta": conta, "tema": texto or tema, "quando": quando})
        args = ["--account", conta, *sum((["--frase", x] for x in frases), []), *sched]
        jobs.enqueue("carrossel-frases", args, f"Carrossel de {len(frases)} frases", user_id=me.id)
    elif tipo == "texto":
        # rascunho só com texto (LinkedIn e Facebook): fica logo pronto para rever, sem IA
        from ..media.formats import kinds_for
        acc = accounts().get(conta)
        txt = (texto or tema).strip()
        if not acc or "text" not in kinds_for(acc.platform):
            return create_page(request, "Esta conta não aceita publicações só de texto (use LinkedIn ou Facebook).",
                               {"tipo": tipo, "conta": conta, "tema": txt, "quando": quando})
        if not txt:
            return create_page(request, "Escreva o texto da publicação.", {"tipo": tipo, "conta": conta, "quando": quando})
        from ..db import add_post
        with connect() as conn:
            pid = add_post(conn, account_id=conta, format="text", caption=txt[:3000], status="draft",
                           title=txt.splitlines()[0][:60])
        return RedirectResponse(f"/post/{pid}", 303)
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
    # Telegram: recebe o modo assistido (posts para publicar à mão), lembretes e alertas
    ("TELEGRAM_BOT_TOKEN", "Telegram · token do bot (dado pelo @BotFather)", True),
    ("TELEGRAM_CHAT_ID", "Telegram · chat (preenche-se sozinho com o botão \"Descobrir o chat\")", False),
    # ligação às Páginas de Facebook e aos Instagrams (app da Meta; ver docs/GUIA_META.md)
    ("META_APP_ID", "Meta · App ID (da app em developers.facebook.com)", False),
    ("META_APP_SECRET", "Meta · App Secret", True),
    ("META_LOGIN_CONFIG_ID", "Meta · Configuration ID (só se a app usar 'Facebook Login for Business')", False),
    # LinkedIn (ver docs/GUIA_LINKEDIN.md)
    ("LINKEDIN_CLIENT_ID", "LinkedIn (perfil pessoal) · Client ID", False),
    ("LINKEDIN_CLIENT_SECRET", "LinkedIn (perfil pessoal) · Client Secret", True),
    ("LINKEDIN_ORG_CLIENT_ID", "LinkedIn (2.ª app, página da empresa) · Client ID", False),
    ("LINKEDIN_ORG_CLIENT_SECRET", "LinkedIn (2.ª app, página da empresa) · Client Secret", True),
    ("LINKEDIN_ORG_API", "LinkedIn · Community Management API aprovada? (sim/não)", False),
    ("LINKEDIN_COMMENTS_MINUTES", "LinkedIn · ler os comentários da página de quantos em quantos minutos (60 por omissão; mínimo 15)", False),
    ("LINKEDIN_COMMENTS_DAILY_CALLS", "LinkedIn · pedidos por dia para os comentários (60 por omissão; o LinkedIn dá 100 por dia no Nível de Desenvolvimento)", False),
    ("CANDIDATURAS_EMAIL", "Respostas · email para candidaturas de emprego (público; rh@carretos.pt por omissão)", False),
    ("PARCERIAS_EMAIL_PUBLICO", "Respostas · email para parcerias (público; davidcarreto@carretos.pt por omissão)", False),
    ("PARCERIAS_AVISOS_EMAILS", "Respostas · avisos de parcerias por email (separados por vírgula; davidcarreto@carretos.pt e marcia.palmeirao@carretos.pt por omissão)", False),
    ("LINKEDIN_EMAILS_MINUTES", "LinkedIn · ler a caixa dos avisos de mensagens de quantos em quantos minutos (10 por omissão; não gasta pedidos do LinkedIn)", False),
    ("LINKEDIN_EMAILS_ATIVO", "LinkedIn · avisar no Telegram as mensagens privadas (pelos emails do LinkedIn reencaminhados)? (sim/não)", False),
    ("LINKEDIN_EMAILS_CAIXA", "Microsoft 365 · caixa que recebe os emails do LinkedIn (ex.: studio@carretos.pt)", False),
    ("MS_TENANT_ID", "Microsoft 365 · ID do diretório (inquilino) da app \"Carretos Studio\"", False),
    ("MS_CLIENT_ID", "Microsoft 365 · ID da aplicação (cliente) da app \"Carretos Studio\"", False),
    ("MS_CLIENT_SECRET", "Microsoft 365 · segredo do cliente (Valor) da app \"Carretos Studio\"", True),
    ("IMAP_HOST", "Caixa dedicada (alternativa) · servidor de entrada IMAP", False),
    ("IMAP_USER", "Caixa dedicada (alternativa) · email/utilizador da caixa que recebe os avisos do LinkedIn", False),
    ("IMAP_PASSWORD", "Caixa dedicada (alternativa) · palavra-passe de aplicação dessa caixa", True),
    ("LINKEDIN_HEADLINE", "LinkedIn · cargo do perfil, por baixo do nome (só para a pré-visualização; ex.: CEO · Carretos Group)", False),
    # TikTok (ver docs/GUIA_TIKTOK.md)
    ("TIKTOK_CLIENT_KEY", "TikTok · Client key", False),
    ("TIKTOK_CLIENT_SECRET", "TikTok · Client secret", True),
    ("TIKTOK_CAPTION_EMAIL", "TikTok · email para onde vão as legendas dos vídeos (rascunhos)", False),
    ("TIKTOK_PULL_FROM_URL", "TikTok · domínio verificado na TikTok? (sim/não; com sim, os vídeos vão pelo endereço público)", False),
    ("TIKTOK_VERIFY_FILE", "TikTok · nome do ficheiro de verificação do domínio (ex.: tiktokAbC123.txt)", False),
    ("TIKTOK_VERIFY_CONTENT", "TikTok · conteúdo desse ficheiro (tiktok-developers-site-verification=…)", False),
]


import re as _re

# formato esperado de cada chave: evita guardar por engano um utilizador/palavra-passe preenchido pelo browser
KEY_FORMATS = {
    "SOCIAL_ANTHROPIC_API_KEY": (_re.compile(r"^sk-ant-[A-Za-z0-9_\-]{20,}$"), "começa por sk-ant-"),
    "ELEVENLABS_API_KEY": (_re.compile(r"^(sk_)?[0-9a-fA-F]{32,64}$"), "começa por sk_ seguido de letras/números"),
    "ELEVENLABS_VOICE_ID": (_re.compile(r"^[A-Za-z0-9]{15,40}$"), "só letras e números, sem espaços (~20)"),
    "PIXABAY_API_KEY": (_re.compile(r"^\d+-[0-9a-fA-F]{20,}$"), "números, um hífen e letras/números"),
    "TELEGRAM_BOT_TOKEN": (_re.compile(r"^\d{6,12}:[A-Za-z0-9_\-]{30,}$"), "números, dois pontos e letras (ex.: 123456:ABC…)"),
    "TELEGRAM_CHAT_ID": (_re.compile(r"^-?\d{4,20}$"), "só números (pode começar por -)"),
    "META_APP_ID": (_re.compile(r"^\d{10,20}$"), "só números (10 a 20)"),
    "META_APP_SECRET": (_re.compile(r"^[0-9a-fA-F]{32}$"), "32 letras/números (0-9, a-f)"),
    "META_LOGIN_CONFIG_ID": (_re.compile(r"^\d{10,20}$"), "só números (10 a 20)"),
    "LINKEDIN_CLIENT_ID": (_re.compile(r"^[A-Za-z0-9]{8,30}$"), "letras e números, sem espaços"),
    "LINKEDIN_CLIENT_SECRET": (_re.compile(r"^[A-Za-z0-9_.=/+:~\-]{10,200}$"), "letras, números e símbolos (_ . = / + - :), sem espaços"),
    "LINKEDIN_ORG_CLIENT_ID": (_re.compile(r"^[A-Za-z0-9]{8,30}$"), "letras e números, sem espaços"),
    "LINKEDIN_ORG_CLIENT_SECRET": (_re.compile(r"^[A-Za-z0-9_.=/+:~\-]{10,200}$"), "letras, números e símbolos (_ . = / + - :), sem espaços"),
    "LINKEDIN_ORG_API": (_re.compile(r"^(sim|não|nao)$", _re.I), "escreva sim ou não"),
    "LINKEDIN_COMMENTS_MINUTES": (_re.compile(r"^\d{2,3}$"), "um número de minutos (15 ou mais, ex.: 60)"),
    "LINKEDIN_COMMENTS_DAILY_CALLS": (_re.compile(r"^\d{2}$"), "um número entre 10 e 90 (ex.: 60)"),
    "CANDIDATURAS_EMAIL": (_re.compile(r"^[^@\s,]+@[^@\s,]+\.[a-z]{2,}$", _re.I), "um email"),
    "PARCERIAS_EMAIL_PUBLICO": (_re.compile(r"^[^@\s,]+@[^@\s,]+\.[a-z]{2,}$", _re.I), "um email"),
    "PARCERIAS_AVISOS_EMAILS": (_re.compile(r"^[^@\s,]+@[^@\s,]+\.[a-z]{2,}(\s*,\s*[^@\s,]+@[^@\s,]+\.[a-z]{2,})*$", _re.I),
                                "um ou mais emails separados por vírgula"),
    "LINKEDIN_EMAILS_MINUTES": (_re.compile(r"^\d{1,3}$"), "um número de minutos (5 ou mais)"),
    "LINKEDIN_EMAILS_ATIVO": (_re.compile(r"^(sim|não|nao)$", _re.I), "escreva sim ou não"),
    "LINKEDIN_EMAILS_CAIXA": (_re.compile(r"^[^@\s,]+@[^@\s,]+\.[a-z]{2,}$", _re.I), "um email (ex.: studio@carretos.pt)"),
    "MS_TENANT_ID": (_re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", _re.I), "um ID com o formato 00000000-0000-0000-0000-000000000000"),
    "MS_CLIENT_ID": (_re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", _re.I), "um ID com o formato 00000000-0000-0000-0000-000000000000"),
    "MS_CLIENT_SECRET": (_re.compile(r"^[A-Za-z0-9_.~\-]{20,120}$"), "o Valor do segredo (não o ID do segredo)"),
    "IMAP_USER": (_re.compile(r"^[^@\s,]+@[^@\s,]+\.[a-z]{2,}$", _re.I), "um email"),
    "IMAP_HOST": (_re.compile(r"^[a-z0-9.-]{4,100}$", _re.I), "só o nome do servidor (ex.: imap.exemplo.pt)"),
    "LINKEDIN_HEADLINE": (_re.compile(r"^[^\n\r\"'=#]{2,120}$"), "texto simples, até 120 caracteres, sem aspas"),
    "TIKTOK_CLIENT_KEY": (_re.compile(r"^[A-Za-z0-9]{10,40}$"), "letras e números, sem espaços"),
    "TIKTOK_CLIENT_SECRET": (_re.compile(r"^[A-Za-z0-9_\-]{16,80}$"), "letras e números, sem espaços"),
    "TIKTOK_CAPTION_EMAIL": (_re.compile(r"^[^@\s,]+@[^@\s,]+\.[a-z]{2,}(,[^@\s,]+@[^@\s,]+\.[a-z]{2,})*$", _re.I),
                             "um email (ou vários separados por vírgula)"),
    "TIKTOK_PULL_FROM_URL": (_re.compile(r"^(sim|não|nao)$", _re.I), "escreva sim ou não"),
    "TIKTOK_VERIFY_FILE": (_re.compile(r"^tiktok[A-Za-z0-9_\-]{4,80}\.txt$"), "nome do ficheiro .txt dado pela TikTok"),
    "TIKTOK_VERIFY_CONTENT": (_re.compile(r"^tiktok-developers-site-verification=[A-Za-z0-9_\-]{8,200}$"),
                              "o texto completo do ficheiro dado pela TikTok"),
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


def notify_enabled() -> bool:
    from .. import notify
    return notify.enabled()


@app.get("/configurar", response_class=HTMLResponse)
def config_page(request: Request, ok: str = "", erro: str = "", teste: str = "", motivo: str = "", tg: str = ""):
    first = users.count() == 0
    me = _current_user(request) if not first else None
    if not first and not (me and me.is_admin):
        return RedirectResponse("/login", 303)
    request.state.user = me
    # valores que não são segredos aparecem (só ao administrador); as chaves e palavras-passe nunca
    fields = [(k, label, secret, bool(os.environ.get(k)),
               "" if (secret or first) else os.environ.get(k, "")) for k, label, secret in CONFIG_FIELDS]
    labels = {k: label for k, label, _ in CONFIG_FIELDS}
    erros = [(labels.get(k, k), KEY_FORMATS[k][1]) for k in erro.split(",") if k in KEY_FORMATS]
    from .. import linkcard
    from . import system as _system
    from ..media import brand_assets
    from ..config import set_theme, brand as _brand
    _acc = {}
    for _t in brand_assets.BRANDS:
        set_theme(_t)
        _acc[_t] = _brand()["visual"]["colors"]["accent"]
    set_theme(None)
    from ..config import _brand_base
    _bb = _brand_base()
    _base_cor = {t: ((_bb.get("themes") or {}).get(t) or {}).get("colors", {}).get("accent")
                 or _bb["visual"]["colors"]["accent"] for t in brand_assets.BRANDS}
    return _render(request, "config.html", {"marcas": {t: brand_assets.get(t) for t in brand_assets.BRANDS}, "marca_cor": _acc,
                                            "marca_cor_base": _base_cor,"lcard": linkcard.settings(), "lcard_custom": bool(linkcard.custom_default_image()),
                                            "ag": _system.agendador_status(), "web_rev": _system.git_rev(),
                                            "fields": fields, "first": first, "ok": ok, "erros": erros,
                                            "teste": teste, "motivo": motivo, "email_ok": mailer.configured(),
                                            "tg": tg, "tg_ok": notify_enabled(),
                                            "tg_token": bool(os.environ.get("TELEGRAM_BOT_TOKEN")),
                                            "tg_bot": os.environ.get("TELEGRAM_BOT_USERNAME", "")})


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
    rejected = []
    updates: dict[str, str] = {}
    for key, _, _ in CONFIG_FIELDS:
        value = str(form.get(key, "")).strip()
        if key == "SMTP_PASSWORD":
            value = value.replace(" ", "")                    # o Gmail mostra-a em blocos de 4 com espaços
        if not value:
            continue                                         # vazio = manter o valor atual
        if _bad_key(key, value):
            rejected.append(key)                              # formato errado: não guarda
            continue
        updates[key] = value
    from .. import envfile
    envfile.set_env(updates, root=ROOT)
    if "TELEGRAM_BOT_TOKEN" in updates:
        _telegram_username()
    r = RedirectResponse("/configurar?ok=1" + (f"&erro={','.join(rejected)}" if rejected else ""), 303)
    _set_session(r, admin_id)
    return r


def _admin_only(request: Request):
    me = _current_user(request)
    if not (me and me.is_admin):
        return None
    request.state.user = me
    return me


@app.post("/configurar/atualizar")
def update_system(request: Request):
    from . import system
    me = _admin_only(request)
    if not me:
        return _forbidden("Só o administrador pode atualizar o sistema.")
    system.start_update(me.username)
    return RedirectResponse("/configurar/atualizacao", 303)


@app.get("/configurar/atualizacao", response_class=HTMLResponse)
def update_page(request: Request):
    from . import system
    if not _admin_only(request):
        return _forbidden("Só o administrador.")
    return _render(request, "update.html", {"r": system.update_report()})


@app.get("/configurar/atualizacao.json")
def update_json(request: Request):
    from . import system
    if not _admin_only(request):
        return JSONResponse({"erro": "só o administrador"}, 403)
    return JSONResponse(system.update_report())


@app.get("/verificacao", response_class=HTMLResponse)
def duplicates_page(request: Request):
    from .. import duplicates
    if not _admin_only(request):
        return _forbidden("Só o administrador.")
    found = duplicates.find()
    return _render(request, "duplicates.html", {"found": found, "total": duplicates.total(found)})


@app.post("/configurar/post-teste")
def create_test_post(request: Request):
    me = _admin_only(request)
    if not me:
        return _forbidden("Só o administrador.")
    jobs.enqueue("exemplo-carrossel", [], "Post de teste (carrossel)", user_id=me.id)
    return RedirectResponse("/tarefas", 303)


@app.post("/configurar/reinicio-visto")
def reboot_seen(request: Request):
    from . import system
    if _admin_only(request):
        system.dismiss_reboot()
    return RedirectResponse(request.headers.get("referer") or "/", 303)


def _telegram_username() -> str:
    """@ do bot configurado (pedido ao Telegram e guardado em TELEGRAM_BOT_USERNAME)."""
    from .. import envfile
    from ..http import request as http
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return ""
    try:
        user = http("GET", f"https://api.telegram.org/bot{token}/getMe", retries=1).json().get("result", {}).get("username", "")
    except Exception:  # noqa: BLE001
        return os.environ.get("TELEGRAM_BOT_USERNAME", "")
    if user and user != os.environ.get("TELEGRAM_BOT_USERNAME"):
        envfile.set_env({"TELEGRAM_BOT_USERNAME": user}, root=ROOT)
    return user


@app.post("/configurar/telegram-chat")
def config_telegram_chat(request: Request):
    """Descobre o chat do Telegram: depois de escrever uma mensagem ao bot, lê-a e guarda o número do chat."""
    from urllib.parse import quote
    from .. import envfile
    from ..http import request as http
    me = _current_user(request)
    if not (me and me.is_admin):
        return _forbidden()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return RedirectResponse("/configurar?tg=erro&motivo=" + quote("primeiro guarde o token do bot"), 303)
    bot = _telegram_username()
    try:
        updates = http("GET", f"https://api.telegram.org/bot{token}/getUpdates", retries=1).json().get("result", [])
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse("/configurar?tg=erro&motivo=" + quote(str(exc).replace(token, "***")), 303)
    chats = [u.get("message", u.get("my_chat_member", {})).get("chat", {}) for u in updates]
    chats = [c for c in chats if c.get("id")]
    if not chats:
        where = f"abra @{bot} (https://t.me/{bot})" if bot else "abra o bot no Telegram"
        return RedirectResponse("/configurar?tg=erro&motivo=" + quote(
            f"ainda não há mensagens: {where}, envie /start e tente de novo dentro de alguns segundos"), 303)
    envfile.set_env({"TELEGRAM_CHAT_ID": str(chats[-1]["id"])}, root=ROOT)
    return RedirectResponse("/configurar?tg=chat", 303)


@app.post("/configurar/reiniciar-agendador")
def config_restart_scheduler(request: Request):
    from . import system
    me = _current_user(request)
    if not (me and me.is_admin):
        return _forbidden()
    ok = system.restart_agendador()
    return RedirectResponse("/configurar?ag=" + ("ok" if ok else "erro") + "#manutencao", 303)


@app.post("/configurar/testar-telegram")
def config_test_telegram(request: Request):
    from urllib.parse import quote
    from .. import notify
    me = _current_user(request)
    if not (me and me.is_admin):
        return _forbidden()
    if not notify.enabled():
        return RedirectResponse("/configurar?tg=erro&motivo=" + quote("falta o token do bot ou o chat"), 303)
    try:
        notify.send("Teste: o Telegram do Carretos Studio está a funcionar. Aqui vão chegar os posts para publicar "
                    "à mão, os lembretes e os alertas.")
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).replace(os.environ.get("TELEGRAM_BOT_TOKEN", "\0"), "***")
        return RedirectResponse("/configurar?tg=erro&motivo=" + quote(msg), 303)
    return RedirectResponse("/configurar?tg=ok", 303)


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
    try:
        from .. import inbox
        inbox.process_pending()        # respostas que ficaram por enviar (ex.: reinício durante a espera de 60 s)
    except Exception:  # noqa: BLE001
        log.exception("respostas pendentes")
    try:
        from . import system
        system.check_reboot()          # aviso "O servidor reiniciou às HH:MM" (com a causa provável)
        system.finish_update()         # guarda o registo/resultado da atualização que reiniciou o dashboard
    except Exception:  # noqa: BLE001
        log.exception("verificação de reinício")
    if os.environ.get("DICTATION_PRELOAD", "1") == "1":  # modelo do ditado já em memória
        import threading
        from ..media.video_editor import preload_dictation
        threading.Thread(target=preload_dictation, daemon=True).start()
