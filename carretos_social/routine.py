"""Rotinas a horas fixas (hora de Lisboa), feitas pelo agendador. A data do último envio fica guardada em
data/agendador.json: um reinício do agendador nunca repete uma mensagem já enviada nesse dia.

  08:30  verificação de todas as ligações (alerta só quando uma passa a falhar)
  09:00  "Por aprovar nas próximas 24h" (só se houver)
  09:00  ligações a expirar: a 14, 7, 3 e 1 dia(s) e no próprio dia (depois de expirar: todos os dias)
  09:00 de segunda-feira  resumo semanal
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from . import config as _cfg
from .config import ROOT

HEALTH_AT, MORNING_AT = (8, 30), (9, 0)
EXPIRY_DAYS = {14, 7, 3, 1, 0}


def dashboard_url(path: str = "/") -> str:
    f = ROOT / "ENDERECO_DASHBOARD.txt"
    base = f.read_text().strip().rstrip("/") if f.exists() and f.read_text().strip() else "https://carretosstudio.duckdns.org"
    return base + path


def _state_path():
    return _cfg.DATA_DIR / "agendador.json"


def _state() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8")) if _state_path().exists() else {}
    except (OSError, ValueError):
        return {}


def _save(state: dict) -> None:
    _cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(json.dumps(state), encoding="utf-8")


def _due(state: dict, key: str, now: datetime, at: tuple[int, int], period: str = "day") -> bool:
    """Já passou a hora de hoje (ou desta semana, à segunda-feira) e ainda não foi feito?"""
    if (now.hour, now.minute) < at:
        return False
    if period == "week":
        if now.weekday() != 0:
            return False
        stamp = now.strftime("%G-W%V")
    else:
        stamp = now.date().isoformat()
    return state.get(key) != stamp


def _mark(state: dict, key: str, now: datetime, period: str = "day") -> None:
    state[key] = now.strftime("%G-W%V") if period == "week" else now.date().isoformat()
    _save(state)


def run_due(now: datetime | None = None) -> list[str]:
    """Faz as rotinas que estão na hora. Devolve o que foi feito (para o registo do agendador)."""
    from .scheduler import _tz
    now = now or datetime.now(_tz())
    state, done = _state(), []
    if _due(state, "health", now, HEALTH_AT):
        _mark(state, "health", now)                     # marca antes: um erro não repete o envio
        from .health import check_all
        bad = [k for k, r in check_all().items() if not r["ok"]]
        done.append("ligações verificadas" + (f"; com problemas: {', '.join(bad)}" if bad else ": todas OK"))
    if _due(state, "pending", now, MORNING_AT):
        _mark(state, "pending", now)
        n = remind_pending(now)
        done.append(f"lembrete 'por aprovar': {n} publicação(ões)")
    if _due(state, "expiry", now, MORNING_AT):
        _mark(state, "expiry", now)
        from .expiry import remind
        if remind(only_days=EXPIRY_DAYS):
            done.append("lembrete de ligações a expirar enviado")
    if _due(state, "weekly", now, MORNING_AT, "week"):
        _mark(state, "weekly", now, "week")
        weekly_summary(now)
        done.append("resumo semanal enviado")
    return done


def remind_pending(now: datetime) -> int:
    """Publicações com data nas próximas 24 h que ainda não foram aprovadas (com link para o dashboard)."""
    from . import notify
    from .config import accounts
    from .db import connect
    from .scheduler import parse_dt
    limit = now + timedelta(hours=24)
    with connect() as conn:
        rows = [r for r in conn.execute("SELECT * FROM posts WHERE status IN ('idea','draft')").fetchall()
                if r["scheduled_at"] and parse_dt(r["scheduled_at"]) <= limit]
    if rows:
        accs = accounts()
        lines = [f"• #{r['id']} {parse_dt(r['scheduled_at']).strftime('%d/%m %H:%M')} · "
                 f"{accs[r['account_id']].name if r['account_id'] in accs else r['account_id']} · "
                 f"{r['title'] or r['pillar'] or ''}" for r in rows]
        notify.send("📝 Por aprovar nas próximas 24h:\n" + "\n".join(lines) +
                    f"\n\nAprovar no dashboard: {dashboard_url('/aprovar')}")
    return len(rows)


def weekly_summary(now: datetime) -> None:
    """Segunda-feira: o que saiu na semana passada, o que falhou, o que está por publicar à mão e o que vem aí."""
    from . import notify
    from .db import connect
    from .scheduler import parse_dt
    week_ago, next_week = now - timedelta(days=7), now + timedelta(days=7)
    with connect() as conn:
        rows = conn.execute("SELECT status, scheduled_at, updated_at FROM posts").fetchall()

    def when(r, key):
        try:
            return parse_dt(r[key]) if r[key] else None
        except Exception:  # noqa: BLE001
            return None
    last = [r for r in rows if (when(r, "scheduled_at") or when(r, "updated_at") or now) >= week_ago
            and (when(r, "scheduled_at") or now) <= now]
    count = lambda st, rs: sum(1 for r in rs if r["status"] == st)  # noqa: E731
    upcoming = [r for r in rows if when(r, "scheduled_at") and now < when(r, "scheduled_at") <= next_week]
    manual = sum(1 for r in rows if r["status"] in ("assist_sent", "tiktok_draft"))
    text = ("🗓 Resumo semanal\n"
            f"Semana passada: {count('published', last)} publicada(s), {count('tiktok_draft', last)} enviada(s) para o "
            f"TikTok, {count('assist_sent', last)} para publicar à mão, {count('failed', last)} falhada(s).\n"
            f"Por publicar à mão (inclui rascunhos do TikTok): {manual}.\n"
            f"Próximos 7 dias: {len(upcoming)} agendada(s), das quais {count('approved', upcoming)} aprovada(s) e "
            f"{sum(1 for r in upcoming if r['status'] in ('idea', 'draft'))} por aprovar.\n"
            f"Dashboard: {dashboard_url('/')}")
    try:
        from .duplicates import find, total
        n = total(find())
        text += f"\nDuplicados: {'nenhum ✓' if not n else str(n) + ' a rever em ' + dashboard_url('/verificacao')}"
    except Exception:  # noqa: BLE001
        pass
    notify.send(text)
