"""Agendador: publica automaticamente o que está aprovado e chegou à hora."""
from __future__ import annotations

import json
import time
import traceback
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import notify
from .config import account, strategy
from .db import connect, get_post, media_paths, update_post
from .publishers import PublishRequest, get_publisher


def _tz():
    return ZoneInfo(strategy().get("timezone", "Europe/Lisbon"))


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=_tz())


def caption_with_tags(row) -> str:
    tags = json.loads(row["hashtags"] or "[]")
    caption = row["caption"] or ""
    missing = [t if t.startswith("#") else f"#{t}" for t in tags if t.lstrip("#").lower() not in caption.lower()]
    return caption + ("\n\n" + " ".join(missing) if missing else "")


def ready_problems(row) -> list[str]:
    problems = []
    if not row["scheduled_at"]:
        problems.append("sem data/hora")
    if not row["caption"]:
        problems.append("sem legenda")
    if "[PREENCHER" in (row["caption"] or ""):
        problems.append("legenda por preencher ([PREENCHER…])")
    from .content.guard import found_terms
    for _, warning in found_terms(row["account_id"], row["caption"] or ""):
        problems.append(warning)
    if row["format"] not in ("text",) and not json.loads(row["media_ids"] or "[]"):
        problems.append("sem vídeo/imagem associado")
    from . import linkcard
    from .config import accounts
    acc = accounts().get(row["account_id"])
    if acc:
        problems += linkcard.text_problems(row, acc.platform)
    return problems


def format_report(conn, row):
    """Verificação do tipo/tamanho/duração para a rede da publicação (ver media/formats.py)."""
    from .media.formats import check
    paths = media_paths(conn, json.loads(row["media_ids"] or "[]"))
    return check(account(row["account_id"]).platform, row["format"], paths)


def all_problems(conn, row) -> list[str]:
    """Tudo o que impede aprovar/publicar: dados em falta e formato que tem de ser editado."""
    problems = ready_problems(row)
    if "sem vídeo/imagem associado" not in problems:
        problems += [f"formato: {p}" for p in format_report(conn, row).blocking()]
    return problems


def publish_post(conn, post_id: int, dry_run: bool = False) -> str:
    row = get_post(conn, post_id)
    acc = account(row["account_id"])
    if not acc.connected:
        update_post(conn, post_id, error="conta por ligar (falta o handle/os tokens): não publicado")
        return f"#{post_id} não publicado: a conta {acc.name} ainda está por ligar"
    problems = all_problems(conn, row)
    if problems:
        update_post(conn, post_id, error="; ".join(problems))
        return f"#{post_id} não publicado: {', '.join(problems)}"
    media = media_paths(conn, json.loads(row["media_ids"] or "[]"))
    cover = media_paths(conn, [row["cover_id"]])[0] if row["cover_id"] else None
    from . import linkcard
    card = linkcard.for_post(row, acc.platform)
    req = PublishRequest(account=acc, format=row["format"], caption=caption_with_tags(row), media=media,
                         cover=cover, title=row["title"] or "")
    if dry_run:
        return f"#{post_id} [simulação] {acc.name}: {row['format']} com {len(media)} ficheiro(s)"
    try:
        if card and acc.mode == "auto":
            req.article = linkcard.resolve(card)          # lê o site só na altura de publicar
        res = get_publisher(acc).publish(req)
    except Exception as exc:  # noqa: BLE001
        update_post(conn, post_id, status="failed", error=str(exc)[:1000])
        notify.send(f"⚠️ Falhou a publicação #{post_id} em {acc.name}: {exc}")
        traceback.print_exc()
        return f"#{post_id} FALHOU: {exc}"
    status = res.status or "published"
    update_post(conn, post_id, status=status, remote_id=res.remote_id, remote_url=res.url, error=res.note or None)
    _confirm(acc, row, status, res)
    return f"#{post_id} {status} em {acc.name} {res.url or ''} {res.note}".strip()


def _confirm(acc, row, status: str, res) -> None:
    """Confirmação pelo Telegram quando uma publicação sai. (O modo assistido e os vídeos do TikTok já têm a sua
    própria mensagem, com a legenda.)"""
    from .media.formats import kind_of
    from .routine import dashboard_url
    title = row["title"] or row["pillar"] or f"#{row['id']}"
    try:
        if status == "published":
            notify.send(f"✅ Publicado em {acc.name}: {title}" + (f"\n{res.url}" if res.url else ""))
        elif status == "tiktok_draft" and kind_of(row["format"]) != "video":
            notify.send(f"♪ Rascunho enviado para o TikTok de @{acc.handle}: {title}\n"
                        "Abra a notificação da TikTok, confirme a privacidade e publique.\n"
                        f"Depois marque \"Já publiquei\" em {dashboard_url('/manual')}")
    except Exception:  # noqa: BLE001
        pass


def due_posts(conn, now: datetime | None = None) -> list:
    now = now or datetime.now(_tz())
    rows = conn.execute("SELECT * FROM posts WHERE status='approved' AND scheduled_at IS NOT NULL").fetchall()
    return [r for r in rows if parse_dt(r["scheduled_at"]) <= now]


def auto_approve(conn) -> None:
    """Contas com auto_approve: rascunhos completos passam a aprovados."""
    for r in conn.execute("SELECT * FROM posts WHERE status='draft'").fetchall():
        if account(r["account_id"]).auto_approve and not all_problems(conn, r):
            update_post(conn, r["id"], status="approved")


def tick(dry_run: bool = False) -> list[str]:
    with connect() as conn:
        auto_approve(conn)
        return [publish_post(conn, r["id"], dry_run) for r in due_posts(conn)]


def run_forever(interval: int = 60, sync_every_hours: int = 6) -> None:
    from .analytics.analyzer import sync

    print(f"Agendador ativo (verifica a cada {interval}s). Ctrl+C para parar.")
    from .config import ROOT
    env_file = ROOT / ".env"
    env_mtime = env_file.stat().st_mtime if env_file.exists() else 0
    last_sync = 0.0
    while True:
        for line in tick():
            print(datetime.now().strftime("%H:%M"), line)
        if time.time() - last_sync > sync_every_hours * 3600:
            with connect() as conn:
                for acc, st in sync(conn).items():
                    print(f"métricas {acc}: {st}")
            last_sync = time.time()
        try:                                   # rotinas a horas fixas (08:30 e 09:00), sem repetir no mesmo dia
            from .routine import run_due
            for line in run_due():
                print(datetime.now().strftime("%H:%M"), line)
        except Exception as exc:  # noqa: BLE001
            print("rotinas:", exc)
        if env_file.exists() and env_file.stat().st_mtime != env_mtime:
            # chaves novas (ex.: conta ligada no dashboard, token do TikTok renovado): relê sem reiniciar
            from .envfile import reload_env
            reload_env()
            env_mtime = env_file.stat().st_mtime
            print("Configuração relida.")
        time.sleep(interval)
