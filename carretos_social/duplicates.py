"""Verificação de duplicados (dashboard → ⚙ Configurar → Manutenção → "Verificar duplicados").

Procura: publicações da mesma conta à mesma hora, com a mesma legenda ou com os mesmos ficheiros; fichas
repetidas na base de conhecimento; respostas automáticas repetidas à mesma pessoa; tarefas repetidas na fila.
Só lê: não apaga nem altera nada.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta

from .config import accounts
from .db import connect

ACTIVE = ("idea", "draft", "approved", "published", "assist_sent", "tiktok_draft", "failed")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", (text or "").lower())).strip()


def find() -> dict[str, list[dict]]:
    names = {a.id: a.name for a in accounts().values()}
    out: dict[str, list[dict]] = {"agenda": [], "legendas": [], "ficheiros": [], "conhecimento": [], "respostas": [],
                                  "tarefas": []}
    with connect() as conn:
        posts = [dict(r) for r in conn.execute(
            f"SELECT id, account_id, scheduled_at, caption, media_ids, status, title FROM posts "
            f"WHERE status IN ({','.join('?' * len(ACTIVE))})", ACTIVE)]
        groups: dict[tuple, list] = defaultdict(list)
        for p in posts:
            if p["scheduled_at"]:
                groups[("agenda", p["account_id"], p["scheduled_at"][:16])].append(p)
            cap = _norm(p["caption"])
            if len(cap) > 20 and not cap.startswith("teste"):
                groups[("legendas", p["account_id"], cap)].append(p)
            media = tuple(sorted(json.loads(p["media_ids"] or "[]")))
            if media:
                groups[("ficheiros", p["account_id"], media)].append(p)
        for (kind, acc, key), ps in groups.items():
            if len(ps) > 1:
                what = (f"à mesma hora ({key.replace('T', ' ')})" if kind == "agenda" else
                        "com a mesma legenda" if kind == "legendas" else "com os mesmos ficheiros")
                out[kind].append({"account": names.get(acc, acc), "what": what,
                                  "posts": [{"id": p["id"], "status": p["status"], "title": p["title"] or ""} for p in ps]})
        from . import knowledge
        seen: dict[tuple, list] = defaultdict(list)
        for i in knowledge.items(conn):
            seen[(i["brand"], _norm(i["text"]))].append(i)
        for (brand, _), its in seen.items():
            if len(its) > 1:
                out["conhecimento"].append({"brand": brand, "text": its[0]["text"], "ids": [i["id"] for i in its]})
        limit = (datetime.now() - timedelta(days=7)).isoformat(timespec="seconds")
        rows = conn.execute("SELECT account_id, author_id, author, kind, replied_at FROM inbox "
                            "WHERE status='respondido' AND created_at >= ? ORDER BY replied_at", (limit,)).fetchall()
        by: dict[tuple, list] = defaultdict(list)
        for r in rows:
            by[(r["account_id"], r["author_id"], r["kind"])].append(r)
        for (acc, author_id, kind), rs in by.items():
            if kind == "message":
                close = [b for a, b in zip(rs, rs[1:]) if (datetime.fromisoformat(b["replied_at"]) -
                                                          datetime.fromisoformat(a["replied_at"])) < timedelta(hours=24)]
                if close:
                    out["respostas"].append({"account": names.get(acc, acc), "author": rs[0]["author"] or author_id,
                                             "what": f"{len(close) + 1} respostas automáticas a mensagens em menos de 24 h"})
            elif len(rs) > 3:
                out["respostas"].append({"account": names.get(acc, acc), "author": rs[0]["author"] or author_id,
                                         "what": f"{len(rs)} respostas a comentários desta pessoa em 7 dias"})
        jobs: dict[tuple, list] = defaultdict(list)
        for j in conn.execute("SELECT id, kind, args, label FROM jobs WHERE status IN ('queued','running')"):
            jobs[(j["kind"], j["args"])].append(j)
        for (_, _), js in jobs.items():
            if len(js) > 1:
                out["tarefas"].append({"label": js[0]["label"], "ids": [j["id"] for j in js]})
    return out


def total(found: dict) -> int:
    return sum(len(v) for v in found.values())
