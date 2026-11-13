"""Plano e agenda de conteúdos: distribui temas, formatos e horários pela estrutura acordada."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from ..analytics.analyzer import WEEKDAYS, best_times
from ..config import accounts, strategy


def _weighted_sequence(weights: dict[str, float], n: int) -> list[str]:
    """Sequência de n itens respeitando os pesos e intercalando (sem 3 iguais seguidos se possível)."""
    if not weights or n <= 0:
        return []
    total = sum(weights.values())
    credit = {k: 0.0 for k in weights}
    out = []
    for _ in range(n):
        for k, w in weights.items():
            credit[k] += w / total
        pick = max(credit, key=lambda k: credit[k])
        credit[pick] -= 1
        out.append(pick)
    return out


def _times_for(conn, account_id: str, cfg: dict) -> list[str]:
    times = []
    if cfg.get("best_times") == "auto" and conn is not None:
        times = best_times(conn, account_id)
    return times or cfg.get("default_times", ["12:00"])


def slots_for_account(conn, account_id: str, start: date, days: int) -> list[dict]:
    cfg = strategy()["accounts"][account_id]
    tz = ZoneInfo(strategy().get("timezone", "Europe/Lisbon"))
    allowed = cfg.get("days", WEEKDAYS)
    per_week = cfg["posts_per_week"]
    times = _times_for(conn, account_id, cfg)

    # dias candidatos no período
    candidates = [start + timedelta(d) for d in range(days)
                  if WEEKDAYS[(start + timedelta(d)).weekday()] in allowed]
    target = round(per_week * days / 7)
    # se houver mais publicações do que dias, usa várias horas por dia
    per_day = max(1, -(-target // max(1, len(candidates))))
    datetimes = []
    for day in candidates:
        for i in range(per_day):
            hhmm = times[(day.toordinal() + i) % len(times)] if per_day == 1 else times[i % len(times)]
            h, m = map(int, hhmm.split(":"))
            datetimes.append(datetime.combine(day, time(h, m), tzinfo=tz))
    # distribui uniformemente se houver mais candidatos do que o alvo
    if len(datetimes) > target and target > 0:
        step = len(datetimes) / target
        datetimes = [datetimes[int(i * step)] for i in range(target)]
    datetimes = datetimes[:target]

    pillars = _weighted_sequence(cfg["pillar_mix"], len(datetimes))
    formats = _weighted_sequence(cfg["formats"], len(datetimes))
    return [{"account_id": account_id, "scheduled_at": dt.isoformat(), "pillar": p, "format": f}
            for dt, p, f in zip(datetimes, pillars, formats)]


def build_plan(conn, start: date, days: int = 7, account_ids: list[str] | None = None,
               persist: bool = True) -> list[dict]:
    """Cria os slots do período para todas as contas (estado 'idea'). Não duplica slots existentes."""
    from ..db import add_post

    plan = []
    for acc_id in accounts():
        if account_ids and acc_id not in account_ids:
            continue
        if acc_id not in strategy()["accounts"]:
            continue
        for slot in slots_for_account(conn, acc_id, start, days):
            if persist:
                exists = conn.execute("SELECT 1 FROM posts WHERE account_id=? AND scheduled_at=?",
                                      (acc_id, slot["scheduled_at"])).fetchone()
                if exists:
                    continue
                slot["id"] = add_post(conn, **slot, status="idea")
            plan.append(slot)
    return sorted(plan, key=lambda s: s["scheduled_at"])


def calendar(conn, start: date, days: int = 14) -> list[dict]:
    end = start + timedelta(days)
    rows = conn.execute(
        "SELECT * FROM posts WHERE substr(scheduled_at,1,10) >= ? AND substr(scheduled_at,1,10) < ? "
        "ORDER BY scheduled_at", (start.isoformat(), end.isoformat())).fetchall()
    return [dict(r) for r in rows]
