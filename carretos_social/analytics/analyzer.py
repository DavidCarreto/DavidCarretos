"""Análise de desempenho: taxa de envolvimento, melhores horas, melhores temas e formatos."""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from ..config import accounts, strategy
from ..db import upsert_metric
from . import connectors

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def engagement(m: dict) -> float:
    """Envolvimento ponderado: partilhas e guardados valem mais que gostos."""
    interactions = m["likes"] + 2 * m["comments"] + 3 * m["shares"] + 3 * m["saves"]
    base = m["reach"] or m["views"] or 0
    return interactions / base if base else 0.0


def sync(conn, account_ids: list[str] | None = None) -> dict[str, str]:
    """Recolhe métricas de todas as contas configuradas. Devolve o estado por conta."""
    result = {}
    conn.commit()
    for acc in accounts().values():
        if account_ids and acc.id not in account_ids:
            continue
        try:
            data = connectors.fetch(acc)
        except connectors.NotConfigured as exc:
            result[acc.id] = f"ignorada — {exc}"
            continue
        except Exception as exc:  # noqa: BLE001 — uma conta com erro não pára as outras
            result[acc.id] = f"erro — {exc}"
            continue
        for p in data["posts"]:
            pillar = _guess_pillar(conn, acc.id, p["remote_id"])
            upsert_metric(conn, account_id=acc.id, followers_at_time=data.get("followers"), pillar=pillar, **p)
        if data.get("followers") is not None:
            conn.execute("INSERT OR REPLACE INTO account_stats(account_id, day, followers) VALUES (?,?,?)",
                         (acc.id, datetime.now().date().isoformat(), data["followers"]))
        result[acc.id] = f"ok — {len(data['posts'])} publicações, {data.get('followers') or '?'} seguidores"
        conn.commit()     # grava conta a conta: a base de dados não fica bloqueada enquanto se espera pelas redes
    return result


def import_metrics(conn, account_id: str, path) -> int:
    rows = connectors.import_csv(path)
    for r in rows:
        upsert_metric(conn, account_id=account_id, **r)
    return len(rows)


def _guess_pillar(conn, account_id: str, remote_id: str) -> str | None:
    row = conn.execute("SELECT pillar FROM posts WHERE account_id=? AND remote_id=?",
                       (account_id, remote_id)).fetchone()
    return row["pillar"] if row else None


def _rows(conn, account_id: str) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM metrics WHERE account_id=?", (account_id,))]


def _local(ts: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00").replace("+0000", "+00:00"))
    except (ValueError, AttributeError):
        return None
    tz = ZoneInfo(strategy().get("timezone", "Europe/Lisbon"))
    return dt.astimezone(tz) if dt.tzinfo else dt.replace(tzinfo=tz)


def best_times(conn, account_id: str, top: int = 3, min_posts: int = 8) -> list[str]:
    """Horas (HH:MM) com maior envolvimento médio. Vazio se ainda não houver dados suficientes."""
    rows = _rows(conn, account_id)
    if len(rows) < min_posts:
        return []
    by_hour: dict[int, list[float]] = defaultdict(list)
    for r in rows:
        dt = _local(r["published_at"])
        if dt:
            by_hour[dt.hour].append(engagement(r))
    ranked = sorted(by_hour.items(), key=lambda kv: (statistics.mean(kv[1]), len(kv[1])), reverse=True)
    return [f"{h:02d}:00" for h, _ in ranked[:top]]


def best_weekdays(conn, account_id: str) -> list[str]:
    by_day: dict[int, list[float]] = defaultdict(list)
    for r in _rows(conn, account_id):
        dt = _local(r["published_at"])
        if dt:
            by_day[dt.weekday()].append(engagement(r))
    ranked = sorted(by_day.items(), key=lambda kv: statistics.mean(kv[1]), reverse=True)
    return [WEEKDAYS[d] for d, _ in ranked]


def summary(conn, account_id: str, days: int = 30) -> dict:
    rows = _rows(conn, account_id)
    cutoff = datetime.now().astimezone().timestamp() - days * 86400
    recent = [r for r in rows if (dt := _local(r["published_at"])) and dt.timestamp() >= cutoff]
    if not recent:
        return {"account_id": account_id, "posts": 0}

    def avg(key):
        return round(statistics.mean(r[key] or 0 for r in recent), 1)

    def group(key):
        g = defaultdict(list)
        for r in recent:
            g[r[key] or "—"].append(engagement(r))
        return {k: round(statistics.mean(v) * 100, 2) for k, v in sorted(g.items(), key=lambda kv: -statistics.mean(kv[1]))}

    top = sorted(recent, key=engagement, reverse=True)[:5]
    followers = conn.execute(
        "SELECT day, followers FROM account_stats WHERE account_id=? ORDER BY day", (account_id,)).fetchall()
    growth = (followers[-1]["followers"] - followers[0]["followers"]) if len(followers) > 1 else None
    return {
        "account_id": account_id,
        "posts": len(recent),
        "avg_views": avg("views"),
        "avg_reach": avg("reach"),
        "avg_likes": avg("likes"),
        "avg_comments": avg("comments"),
        "avg_shares": avg("shares"),
        "avg_engagement_pct": round(statistics.mean(engagement(r) for r in recent) * 100, 2),
        "engagement_by_format_pct": group("format"),
        "engagement_by_pillar_pct": group("pillar"),
        "best_times": best_times(conn, account_id),
        "best_weekdays": best_weekdays(conn, account_id)[:3],
        "followers_growth": growth,
        "top_posts": [{"caption": (r["caption"] or "")[:90], "views": r["views"],
                       "engagement_pct": round(engagement(r) * 100, 2)} for r in top],
    }


def full_report(conn, days: int = 30) -> list[dict]:
    return [summary(conn, a, days) for a in accounts()]
