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
    conn.commit()                         # nada fica por gravar enquanto se espera pela rede
    try:
        if card and acc.mode == "auto":
            try:
                req.article = linkcard.resolve(card)      # lê o site só na altura de publicar
            except Exception as exc:  # noqa: BLE001
                from .publishers.base import PublishStepError
                raise PublishStepError("preparar o cartão do link", exc) from exc
        res = get_publisher(acc).publish(req)
    except Exception as exc:  # noqa: BLE001
        from .redact import redact
        msg = redact(str(exc) or type(exc).__name__)
        when = datetime.now().strftime("%d/%m %H:%M")
        update_post(conn, post_id, status="failed", error=f"[{when}] {msg}"[:1500])
        _log_failure(post_id, acc.name, msg, redact(traceback.format_exc()))
        try:
            notify.send(f"⚠️ Falhou a publicação #{post_id} em {acc.name} ({when}).\nMotivo: {msg[:1200]}\n"
                        f"Veja o rascunho no dashboard; depois de corrigir, use \"Tentar outra vez\".")
        except Exception as nexc:  # noqa: BLE001
            print("notificação falhou:", nexc)
        print(redact(traceback.format_exc()))
        return f"#{post_id} FALHOU: {msg}"
    status = res.status or "published"
    update_post(conn, post_id, status=status, remote_id=res.remote_id, remote_url=res.url, error=res.note or None)
    _confirm(acc, row, status, res)
    return f"#{post_id} {status} em {acc.name} {res.url or ''} {res.note}".strip()


def _log_failure(post_id: int, account_name: str, msg: str, tb: str) -> None:
    """Registo das falhas de publicação (dashboard → ⚙ Configurar → Registos), já sem tokens."""
    from . import config as _cfg
    path = _cfg.DATA_DIR / "publicacoes_falhadas.jsonl"
    try:
        _cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
        lines = path.read_text(encoding="utf-8").splitlines()[-99:] if path.exists() else []
        lines.append(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "post": post_id,
                                 "conta": account_name, "erro": msg, "detalhe": tb[-6000:]}, ensure_ascii=False))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as exc:
        print("registo de falhas:", exc)


def failures(post_id: int | None = None, limit: int = 20) -> list[dict]:
    from . import config as _cfg
    path = _cfg.DATA_DIR / "publicacoes_falhadas.jsonl"
    try:
        rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    except (OSError, ValueError):
        return []
    rows = [r for r in rows if post_id is None or r.get("post") == post_id]
    return rows[-limit:][::-1]


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
        conn.commit()
        out = []
        for r in due_posts(conn):
            out.append(publish_post(conn, r["id"], dry_run))
            conn.commit()                 # cada publicação gravada logo (não bloqueia o dashboard)
            if not dry_run and get_post(conn, r["id"])["status"] == "published":
                JUST_PUBLISHED.add(r["account_id"])
        return out


JUST_PUBLISHED: set[str] = set()          # contas com publicações novas: métricas recolhidas logo a seguir


def _code_rev() -> str:
    import subprocess
    from .config import ROOT
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _write_status(rev: str) -> None:
    """Versão do código que o agendador tem em memória (o dashboard mostra-a e avisa se for antiga)."""
    import os
    from . import config as _cfg
    try:
        _cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
        (_cfg.DATA_DIR / "agendador_estado.json").write_text(json.dumps(
            {"rev": rev, "pid": os.getpid(), "started": datetime.now().isoformat(timespec="seconds")}), encoding="utf-8")
    except OSError:
        pass


def run_forever(interval: int = 60, sync_every_hours: int = 6) -> None:
    from .analytics.analyzer import sync

    import sys
    try:                                  # o registo (journalctl) mostra cada linha logo, sem ficar em memória
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except AttributeError:
        pass
    print(f"Agendador ativo (verifica a cada {interval}s, versão {_code_rev() or '?'}). Ctrl+C para parar.")
    from .config import ROOT
    rev = _code_rev()
    _write_status(rev)
    env_file = ROOT / ".env"
    env_mtime = env_file.stat().st_mtime if env_file.exists() else 0
    last_sync = 0.0
    last_li_poll = 0.0
    while True:
        for line in tick():
            print(datetime.now().strftime("%H:%M"), line)
        try:                                            # comentários das Páginas de Facebook (além dos webhooks)
            from .inbox import poll_facebook_pages
            for line in poll_facebook_pages():
                print(datetime.now().strftime("%H:%M"), line)
        except Exception as exc:  # noqa: BLE001
            print("Facebook comentários:", exc)
        try:                                            # comentários da página LinkedIn (intervalo guardado)
            from .linkedin_inbox import poll_due
            for line in poll_due():
                print(datetime.now().strftime("%H:%M"), line)
        except Exception as exc:  # noqa: BLE001
            print(datetime.now().strftime("%H:%M"), "LinkedIn comentários: erro —", exc)
        from .linkedin_mail import interval_minutes as mail_minutes, poll_safe as mail_poll
        if time.time() - last_li_poll >= mail_minutes() * 60:     # avisos de mensagens privadas (emails)
            last_li_poll = time.time()
            for line in mail_poll():
                print(datetime.now().strftime("%H:%M"), line)
        if JUST_PUBLISHED and time.time() - last_sync <= sync_every_hours * 3600:
            accs, _ = sorted(JUST_PUBLISHED), JUST_PUBLISHED.clear()
            try:
                with connect() as conn:
                    for acc_id, st in sync(conn, accs).items():
                        print(f"métricas {acc_id} (depois de publicar): {st}")
            except Exception as exc:  # noqa: BLE001
                print("métricas depois de publicar:", exc)
        if time.time() - last_sync > sync_every_hours * 3600:
            JUST_PUBLISHED.clear()
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
        new_rev = _code_rev()
        if rev and new_rev and new_rev != rev:
            # código atualizado e este processo ainda tem o antigo em memória: sai e o systemd arranca o novo
            print(f"Código atualizado ({rev} → {new_rev}): o agendador vai reiniciar com a versão nova.")
            raise SystemExit(0)
        if env_file.exists() and env_file.stat().st_mtime != env_mtime:
            # chaves novas (ex.: conta ligada no dashboard, token do TikTok renovado): relê sem reiniciar
            from .envfile import reload_env
            reload_env()
            env_mtime = env_file.stat().st_mtime
            print("Configuração relida.")
        time.sleep(interval)
