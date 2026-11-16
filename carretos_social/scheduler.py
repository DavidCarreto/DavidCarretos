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
        problems.append("legenda tem [PREENCHER]")
    if row["format"] not in ("text",) and not json.loads(row["media_ids"] or "[]"):
        problems.append("sem vídeo/imagem associado")
    return problems


def publish_post(conn, post_id: int, dry_run: bool = False) -> str:
    row = get_post(conn, post_id)
    acc = account(row["account_id"])
    if not acc.connected:
        update_post(conn, post_id, error="conta por ligar (falta o handle/os tokens): não publicado")
        return f"#{post_id} não publicado: a conta {acc.name} ainda está por ligar"
    problems = ready_problems(row)
    if problems:
        update_post(conn, post_id, error="; ".join(problems))
        return f"#{post_id} não publicado: {', '.join(problems)}"
    media = media_paths(conn, json.loads(row["media_ids"] or "[]"))
    cover = media_paths(conn, [row["cover_id"]])[0] if row["cover_id"] else None
    req = PublishRequest(account=acc, format=row["format"], caption=caption_with_tags(row), media=media,
                         cover=cover, title=row["title"] or "")
    if dry_run:
        return f"#{post_id} [simulação] {acc.name}: {row['format']} com {len(media)} ficheiro(s)"
    try:
        res = get_publisher(acc).publish(req)
    except Exception as exc:  # noqa: BLE001
        update_post(conn, post_id, status="failed", error=str(exc)[:1000])
        notify.send(f"⚠️ Falhou a publicação #{post_id} em {acc.name}: {exc}")
        traceback.print_exc()
        return f"#{post_id} FALHOU: {exc}"
    status = "assist_sent" if acc.publish_mode == "assist" else "published"
    update_post(conn, post_id, status=status, remote_id=res.remote_id, remote_url=res.url, error=res.note or None)
    return f"#{post_id} {status} em {acc.name} {res.url or ''} {res.note}".strip()


def due_posts(conn, now: datetime | None = None) -> list:
    now = now or datetime.now(_tz())
    rows = conn.execute("SELECT * FROM posts WHERE status='approved' AND scheduled_at IS NOT NULL").fetchall()
    return [r for r in rows if parse_dt(r["scheduled_at"]) <= now]


def auto_approve(conn) -> None:
    """Contas com auto_approve: rascunhos completos passam a aprovados."""
    for r in conn.execute("SELECT * FROM posts WHERE status='draft'").fetchall():
        if account(r["account_id"]).auto_approve and not ready_problems(r):
            update_post(conn, r["id"], status="approved")


def remind_pending(conn, hours: int = 24) -> None:
    """Avisa sobre rascunhos que vão sair nas próximas horas e ainda não foram aprovados."""
    limit = datetime.now(_tz()) + timedelta(hours=hours)
    rows = [r for r in conn.execute("SELECT * FROM posts WHERE status IN ('idea','draft')").fetchall()
            if r["scheduled_at"] and parse_dt(r["scheduled_at"]) <= limit]
    if rows:
        lines = [f"#{r['id']} {r['scheduled_at'][5:16]} {r['account_id']} — {r['title'] or r['pillar']} "
                 f"({r['status']})" for r in rows]
        notify.send("📝 Por aprovar nas próximas 24h:\n" + "\n".join(lines) +
                    "\n\nAprova com: carretos approve <id>")


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
    last_sync = last_reminder = 0.0
    while True:
        for line in tick():
            print(datetime.now().strftime("%H:%M"), line)
        if time.time() - last_sync > sync_every_hours * 3600:
            with connect() as conn:
                for acc, st in sync(conn).items():
                    print(f"métricas {acc}: {st}")
            last_sync = time.time()
        if time.time() - last_reminder > 12 * 3600:
            with connect() as conn:
                remind_pending(conn)
            last_reminder = time.time()
        if env_file.exists() and env_file.stat().st_mtime != env_mtime:
            print("Configuração alterada: a reiniciar para carregar as chaves novas.")
            raise SystemExit(0)  # o systemd volta a arrancar o serviço
        time.sleep(interval)
