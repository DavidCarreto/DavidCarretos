"""Painel HTML estático: métricas por conta + agenda de conteúdos (abre no browser)."""
from __future__ import annotations

import html
import json
from datetime import date, datetime, timedelta

from .analytics.analyzer import full_report
from .config import DATA_DIR, accounts, brand
from .content.planner import calendar
from .db import connect

STATUS = {"idea": ("Ideia", "#8a8f98"), "draft": ("Rascunho", "#d29922"), "approved": ("Aprovado", "#2f81f7"),
          "published": ("Publicado", "#3fb950"), "failed": ("Falhou", "#f85149"), "publishing": ("A publicar…", "#58a6ff"),
          "assist_sent": ("Enviado p/ telemóvel", "#a371f7"), "rejected": ("Rejeitado", "#6e7681")}
PLATFORM_ICON = {"instagram": "IG", "tiktok": "TT", "facebook_profile": "FB", "linkedin_member": "in",
                 "linkedin_org": "in"}


def _e(x) -> str:
    return html.escape(str(x if x is not None else ""))


def build(days: int = 30):
    with connect() as conn:
        report = full_report(conn, days)
        start = date.today() - timedelta(days=date.today().weekday())
        posts = calendar(conn, start, 28)
    accs = accounts()
    b = brand()

    cards = []
    for r in report:
        acc = accs[r["account_id"]]
        if r["posts"]:
            pillars = "".join(f"<li><span>{_e(k)}</span><b>{v}%</b></li>"
                              for k, v in list(r["engagement_by_pillar_pct"].items())[:4])
            body = f"""<div class="kpis"><div><b>{r['posts']}</b><span>posts</span></div>
            <div><b>{int(r['avg_views']):,}</b><span>views méd.</span></div>
            <div><b>{r['avg_engagement_pct']}%</b><span>envolvimento</span></div></div>
            <p class="muted">Melhores horas: {_e(', '.join(r['best_times']) or '—')}</p>
            <ul class="bars">{pillars}</ul>"""
        else:
            body = '<p class="muted">Sem métricas ainda.</p>'
        cards.append(f"""<section class="card"><header><i>{PLATFORM_ICON.get(acc.platform, '?')}</i>
        <div><h3>{_e(acc.name)}</h3><small>@{_e(acc.handle)} · {_e(acc.publish_mode)}</small></div></header>{body}</section>""")

    weeks = []
    for w in range(4):
        cols = []
        for d in range(7):
            day = start + timedelta(w * 7 + d)
            items = [p for p in posts if p["scheduled_at"][:10] == day.isoformat()]
            chips = "".join(
                f"""<div class="chip" style="border-color:{STATUS.get(p['status'], ('', '#888'))[1]}"
                title="{_e(p['caption'] or '')[:300]}"><span>{p['scheduled_at'][11:16]} ·
                {PLATFORM_ICON.get(accs[p['account_id']].platform, '?')} {_e(accs[p['account_id']].handle)}</span>
                {_e(p['title'] or p['pillar'])}<em>#{p['id']} {STATUS.get(p['status'], (p['status'],))[0]}
                {'· 🎬' if json.loads(p['media_ids'] or '[]') else ''}</em></div>""" for p in items)
            today = " today" if day == date.today() else ""
            cols.append(f'<div class="day{today}"><h4>{day:%d/%m}</h4>{chips}</div>')
        weeks.append("".join(cols))

    legend = "".join(f'<span><i style="background:{c}"></i>{n}</span>' for n, c in STATUS.values())
    page = f"""<!doctype html><html lang="pt-PT"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Painel Carretos</title>
<style>
:root{{--bg:#0b0b0d;--card:#16171b;--line:#2a2c33;--text:#f2f3f5;--muted:#9aa0aa;--accent:{b['visual']['colors']['accent']}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 Inter,system-ui,sans-serif;padding:24px 16px}}
h1{{margin:0 0 4px;font-size:26px}}h2{{margin:32px 0 12px;font-size:18px}}.muted{{color:var(--muted)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px}}
.card header{{display:flex;gap:10px;align-items:center;margin-bottom:10px}}.card h3{{margin:0;font-size:15px}}
.card i{{width:34px;height:34px;border-radius:10px;background:var(--accent);display:grid;place-items:center;font-style:normal;font-weight:800;color:#fff}}
.kpis{{display:flex;gap:16px}}.kpis b{{display:block;font-size:20px}}.kpis span{{color:var(--muted);font-size:12px}}
.bars{{list-style:none;padding:0;margin:8px 0 0}}.bars li{{display:flex;justify-content:space-between;border-top:1px solid var(--line);padding:4px 0}}
.cal{{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:6px;margin-bottom:6px}}
.day{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:6px;min-height:90px}}
.day.today{{border-color:var(--accent)}}.day h4{{margin:0 0 4px;font-size:12px;color:var(--muted)}}
.chip{{border-left:3px solid;background:#1f2127;border-radius:6px;padding:4px 6px;margin-bottom:4px;font-size:12px;overflow-wrap:anywhere}}
.chip span{{display:block;color:var(--muted);font-size:11px}}.chip em{{display:block;font-style:normal;color:var(--muted);font-size:10px}}
.legend{{display:flex;flex-wrap:wrap;gap:12px;color:var(--muted);font-size:12px}}.legend i{{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:4px}}
@media(max-width:760px){{.cal{{grid-template-columns:1fr}}.day{{min-height:0}}}}
</style></head><body>
<h1>{_e(b['company'])} · Redes sociais</h1><p class="muted">Atualizado {datetime.now():%d/%m/%Y %H:%M} · últimos {days} dias</p>
<h2>Desempenho por conta</h2><div class="grid">{''.join(cards)}</div>
<h2>Agenda (4 semanas)</h2><div class="legend">{legend}</div><br>
{''.join(f'<div class="cal">{w}</div>' for w in weeks)}
</body></html>"""
    out = DATA_DIR / "painel.html"
    out.write_text(page, encoding="utf-8")
    return out
