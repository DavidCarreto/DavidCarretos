"""Linha de comandos: `carretos <comando>` (ou `python -m carretos_social <comando>`)."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from . import config
from .config import DATA_DIR, account, accounts, strategy
from .db import add_media, add_post, connect, get_post, update_post

PLATFORM_KEY = {"instagram": "instagram", "tiktok": "tiktok", "facebook_profile": "facebook_profile",
                "linkedin_member": "linkedin_member", "linkedin_org": "linkedin_org"}


def _render_size(acc, kind: str = "video") -> tuple[int, int]:
    r = strategy()["render"].get(acc.platform, {})
    w, h = r.get(kind) or r.get("video") or [1080, 1920]
    return int(w), int(h)


def _narrator_ready(name: str) -> bool:
    """Há narração? 'nenhum' nunca; a voz da ElevenLabs só quando a chave e o Voice ID estão configurados
    (até lá, as contas pessoais saem sem narração, em vez de uma voz que não é a do David)."""
    import os
    if name == "nenhum":
        return False
    cfg = config.brand().get("narrators", {}).get(name, {})
    if cfg.get("engine") == "elevenlabs":
        return bool(os.environ.get("ELEVENLABS_API_KEY") and (cfg.get("voice_id") or os.environ.get("ELEVENLABS_VOICE_ID")))
    return True


def _when(conn, account_id: str, schedule: str | None) -> str | None:
    """Data pedida, ou o próximo horário livre da conta (nenhuma publicação fica sem data)."""
    if schedule:
        return _aware(schedule)
    from .content.planner import next_free_slot
    return next_free_slot(conn, account_id)


def _aware(value: str) -> str:
    from .scheduler import parse_dt
    return parse_dt(value).isoformat()


def _out_dir(*parts) -> Path:
    p = DATA_DIR.joinpath("media", *parts)
    p.mkdir(parents=True, exist_ok=True)
    return p


# ------------------------------------------------------------------ comandos
def cmd_init(a):
    with connect():
        pass
    env = config.ROOT / ".env"
    if not env.exists():
        (config.ROOT / ".env.example").exists() and env.write_text(
            (config.ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
        print("Criei .env a partir de .env.example — preenche as credenciais.")
    print(f"Base de dados pronta em {DATA_DIR / 'carretos.db'}")
    cmd_status(a)


def cmd_status(a):
    print(f"{'conta':22} {'plataforma':17} {'modo':7} {'credenciais'}")
    for acc in accounts().values():
        creds = acc.credentials
        ok = all(acc.secret(k) for k in creds) if creds else None
        state = "n/a (assistido)" if ok is None else ("✔ ok" if ok else "✘ em falta: " + ", ".join(
            v for k, v in creds.items() if not acc.secret(k)))
        print(f"{acc.id:22} {acc.platform:17} {acc.publish_mode:7} {state}")
    import os
    print("\nIA (SOCIAL_ANTHROPIC_API_KEY):", "✔" if os.environ.get("SOCIAL_ANTHROPIC_API_KEY") else "✘ em falta")
    from . import notify
    print("Telegram:", "✔" if notify.enabled() else "— (opcional)")


def cmd_sync(a):
    from .analytics.analyzer import sync
    with connect() as conn:
        for acc, st in sync(conn, a.accounts).items():
            print(f"{acc:22} {st}")


def cmd_import_csv(a):
    from .analytics.analyzer import import_metrics
    account(a.account)
    with connect() as conn:
        n = import_metrics(conn, a.account, Path(a.file))
    print(f"Importadas {n} linhas para {a.account}")


def cmd_report(a):
    from .analytics.analyzer import full_report
    with connect() as conn:
        report = full_report(conn, a.days)
    for r in report:
        print(f"\n== {accounts()[r['account_id']].name} ==")
        if not r["posts"]:
            print("  sem dados (corre `carretos sync` ou `carretos import-csv`)")
            continue
        print(f"  publicações: {r['posts']} | média views {r['avg_views']} | envolvimento {r['avg_engagement_pct']}%")
        print(f"  melhores horas: {', '.join(r['best_times']) or '—'} | melhores dias: {', '.join(r['best_weekdays'])}")
        print(f"  por formato: {r['engagement_by_format_pct']}")
        print(f"  por tema:    {r['engagement_by_pillar_pct']}")
        for t in r["top_posts"][:3]:
            print(f"   ★ {t['engagement_pct']}% · {t['views']} views · {t['caption']}")
    rec = None
    if a.ai:
        from .content.ai import recommendations
        rec = recommendations(report)
        print("\n### Recomendações\n" + rec["headline"])
        for acc in rec["per_account"]:
            print(f"\n[{acc['account_id']}] {acc['diagnosis']}")
            for c in acc["change"]:
                print(f"  → {c}")
            for i in acc["next_content_ideas"]:
                print(f"  💡 {i}")
    out = DATA_DIR / "relatorio.json"
    out.write_text(json.dumps({"report": report, "recommendations": rec}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"\nRelatório guardado em {out}")


def cmd_plan(a):
    from .content.planner import build_plan
    start = date.fromisoformat(a.start) if a.start else date.today() + timedelta(1)
    with connect() as conn:
        plan = build_plan(conn, start, a.days, a.accounts)
    for s in plan:
        print(f"#{s.get('id', '-'):<5} {s['scheduled_at'][:16].replace('T', ' ')}  {s['account_id']:18} "
              f"{s['format']:10} {s['pillar']}")
    print(f"\n{len(plan)} slots criados de {start} a {start + timedelta(a.days - 1)}. "
          f"Gera o conteúdo com: carretos generate")


def cmd_generate(a):
    from .analytics.analyzer import summary
    from .content.ai import generate_posts
    with connect() as conn:
        q = "SELECT * FROM posts WHERE status='idea'"
        params: list = []
        if a.ids:
            q += f" AND id IN ({','.join('?' * len(a.ids))})"
            params += a.ids
        if a.accounts:
            q += f" AND account_id IN ({','.join('?' * len(a.accounts))})"
            params += a.accounts
        rows = conn.execute(q + " ORDER BY scheduled_at", params).fetchall()
        by_acc: dict[str, list] = {}
        for r in rows:
            by_acc.setdefault(r["account_id"], []).append(r)
        for acc_id, items in by_acc.items():
            acc = account(acc_id)
            insights = summary(conn, acc_id)
            for i in range(0, len(items), 5):  # lotes de 5
                batch = items[i:i + 5]
                slots = [{"pillar": r["pillar"], "format": r["format"], "scheduled_at": r["scheduled_at"]}
                         for r in batch]
                print(f"A criar {len(batch)} publicações para {acc.name}...")
                posts = generate_posts(acc, slots, insights, a.context or "")
                for r, p in zip(batch, posts):
                    update_post(conn, r["id"], title=p["title"], hook=p["hook"], caption=_safe(r["account_id"], p["caption"]),
                                script=json.dumps({k: p[k] for k in ("script", "on_screen_texts", "slides",
                                                                     "cover_text", "filming_notes")},
                                                  ensure_ascii=False),
                                hashtags=p["hashtags"], status="draft")
                    print(f"  #{r['id']} {p['title']}")
    print("Rascunhos prontos. Vê-os com `carretos show <id>` ou no painel (`carretos dashboard`).")


def cmd_show(a):
    with connect() as conn:
        r = dict(get_post(conn, a.id))
    extra = json.loads(r.pop("script") or "{}")
    for k, v in r.items():
        if v not in (None, "", "[]"):
            print(f"{k:13}: {v}")
    if extra:
        print("\n--- guião ---")
        for scene in extra.get("script", []):
            print(f"[{scene['seconds']}] 🎥 {scene['visual']}\n        🗣 {scene['voice_or_text']}")
        for k in ("on_screen_texts", "slides", "cover_text", "filming_notes"):
            if extra.get(k):
                print(f"{k}: {extra[k]}")


def _post_meta(conn, post_id):
    r = get_post(conn, post_id)
    extra = json.loads(r["script"] or "{}")
    return r, extra


def cmd_edit_video(a):
    from .media import image_gen
    from .media.video_editor import auto_edit
    acc = account(a.account)
    w, h = _render_size(acc)
    max_s = strategy()["render"].get(acc.platform, {}).get("max_seconds")
    hook, goal, cover_text = a.hook or "", a.goal or "", a.cover_text
    with connect() as conn:
        if a.post:
            r, extra = _post_meta(conn, a.post)
            hook = hook or (r["hook"] or "")
            cover_text = cover_text or extra.get("cover_text")
            goal = goal or f"Tema: {r['title']}. {r['hook']}"
        out_dir = _out_dir(acc.id)
        res = auto_edit(a.file, out_dir, width=w, height=h, target_seconds=a.seconds, max_seconds=max_s,
                        hook_text=hook, use_transcription=not a.no_subs, use_ai=not a.no_ai, goal=goal,
                        fill=a.fill, music=None if a.no_music else "auto", speed=a.speed)
        cover_text = cover_text or res.get("cover_text") or hook or acc.name
        cover_path = image_gen.cover(res["cover_frame"], cover_text, out_dir / f"{Path(a.file).stem}_capa.jpg",
                                     size=(w, h))
        raw_id = add_media(conn, "raw_video", a.file)
        vid_id = add_media(conn, "video", res["video"], raw_id, {"account": acc.id, **res})
        cov_id = add_media(conn, "cover", cover_path, vid_id)
        if a.post:
            update_post(conn, a.post, media_ids=[vid_id], cover_id=cov_id)
        else:  # cria a publicação (na data pedida ou no próximo horário livre da conta)
            post_id = add_post(conn, account_id=acc.id, format="reel" if acc.platform == "instagram" else "video",
                               title=res.get("title") or Path(a.file).stem, hook=hook,
                               caption=res.get("caption") or "", hashtags=res.get("hashtags") or [],
                               media_ids=[vid_id], cover_id=cov_id, scheduled_at=_when(conn, acc.id, a.schedule),
                               status="draft")
            print(f"Criada publicação #{post_id}")
    for s in res["steps"]:
        print(" •", s)
    print(f"Vídeo: {res['video']} ({res['duration']} s)\nCapa:  {cover_path}")


def cmd_repurpose(a):
    """Um vídeo → versões para todas as contas de vídeo, nos próximos slots livres de cada uma."""
    from .media import image_gen
    from .media.video_editor import auto_edit
    targets = a.accounts or [i for i, acc in accounts().items()
                             if "video" in strategy()["accounts"].get(i, {}).get("formats", {})
                             or "reel" in strategy()["accounts"].get(i, {}).get("formats", {})]
    done: dict[tuple[int, int], dict] = {}
    with connect() as conn:
        raw_id = add_media(conn, "raw_video", a.file)
        for acc_id in targets:
            acc = account(acc_id)
            w, h = _render_size(acc)
            if (w, h) not in done:  # renderiza cada formato só uma vez
                res = auto_edit(a.file, _out_dir("repurpose"), width=w, height=h, target_seconds=a.seconds,
                                max_seconds=strategy()["render"].get(acc.platform, {}).get("max_seconds"),
                                goal=a.goal or "", use_ai=not a.no_ai, use_transcription=not a.no_subs)
                cover = image_gen.cover(res["cover_frame"], res.get("cover_text") or res.get("hook_text") or "VÊ ISTO",
                                        _out_dir("repurpose") / f"{Path(a.file).stem}_{w}x{h}_capa.jpg", size=(w, h))
                res["vid_id"] = add_media(conn, "video", res["video"], raw_id)
                res["cov_id"] = add_media(conn, "cover", cover, res["vid_id"])
                done[(w, h)] = res
            res = done[(w, h)]
            slot = conn.execute(
                "SELECT * FROM posts WHERE account_id=? AND status IN ('idea','draft') AND media_ids='[]' "
                "AND format IN ('reel','video') AND scheduled_at > ? ORDER BY scheduled_at LIMIT 1",
                (acc_id, datetime.now().isoformat())).fetchone()
            caption = res.get("caption") or ""
            if not a.no_ai and caption:
                try:
                    from .content.ai import rewrite_for_account
                    adapted = rewrite_for_account({"title": res.get("title"), "caption": caption,
                                                   "hashtags": res.get("hashtags")}, acc)
                    caption, tags = adapted["caption"], adapted["hashtags"]
                except Exception as exc:  # noqa: BLE001
                    print(f"  (sem adaptação IA para {acc_id}: {exc})")
                    tags = res.get("hashtags") or []
            else:
                tags = res.get("hashtags") or []
            fields = dict(media_ids=[res["vid_id"]], cover_id=res["cov_id"], caption=caption, hashtags=tags,
                          title=res.get("title") or Path(a.file).stem, status="draft")
            if slot:
                update_post(conn, slot["id"], **fields)
                print(f"{acc_id:20} → slot #{slot['id']} {slot['scheduled_at'][:16]}")
            else:
                pid = add_post(conn, account_id=acc_id, format="reel" if acc.platform == "instagram" else "video",
                               **fields)
                print(f"{acc_id:20} → publicação #{pid} sem data (usa `carretos schedule {pid} <data>`)")


def cmd_cover(a):
    from .media import image_gen
    from .media.video_editor import best_frame
    frame = a.image
    if a.video:
        frame = best_frame(a.video, _out_dir("covers") / f"{Path(a.video).stem}_frame.jpg")
    w, h = map(int, a.size.split("x"))
    out = a.out or _out_dir("covers") / f"capa_{datetime.now():%Y%m%d_%H%M%S}.jpg"
    p = image_gen.cover(frame, a.text, out, size=(w, h), subtitle=a.subtitle or "",
                        highlight=a.highlight.split(",") if a.highlight else None)
    _maybe_attach(a, [p], cover=True)
    print(p)


def cmd_image(a):
    from .media import image_gen
    if a.account:
        account(a.account)  # aplica a identidade visual da conta (ex.: preto e dourado nas pessoais)
    w, h = map(int, a.size.split("x"))
    out_dir = _out_dir("images")
    stamp = f"{datetime.now():%Y%m%d_%H%M%S}"
    if a.kind == "quote":
        paths = [image_gen.quote_card(a.text, out_dir / f"frase_{stamp}.jpg", size=(w, h), photo=a.photo)]
    elif a.kind == "photo":
        paths = [image_gen.photo_post(a.photo, a.text, out_dir / f"foto_{stamp}.jpg", size=(w, h), tag=a.tag or "")]
    else:  # carousel
        slides = a.slides
        if a.post and not slides:
            with connect() as conn:
                _, extra = _post_meta(conn, a.post)
            slides = extra.get("slides") or []
        if not slides:
            raise SystemExit("Indica --slides 'Título' 'Ponto 1\\ndetalhe' ... ou --post <id> com slides gerados.")
        handle = account(a.account).handle if a.account else ""
        paths = image_gen.carousel(slides, out_dir / f"carrossel_{stamp}", size=(w, h), cover_photo=a.photo,
                                   handle=handle)
    _maybe_attach(a, paths)
    for p in paths:
        print(p)


def _maybe_attach(a, paths, cover=False):
    if not getattr(a, "post", None):
        acc_id = getattr(a, "account", None)
        if acc_id and not cover:  # imagem feita para uma conta: fica como publicação a aprovar
            with connect() as conn:
                ids = [add_media(conn, "image", p) for p in paths]
                fmt = "carousel" if len(paths) > 1 else "image"
                pid = add_post(conn, account_id=acc_id, format=fmt, title=(getattr(a, "text", "") or fmt)[:60],
                               caption=getattr(a, "text", "") or "", media_ids=ids,
                               scheduled_at=_when(conn, acc_id, None), status="draft")
            print(f"Criada publicação #{pid}")
        return
    with connect() as conn:
        ids = [add_media(conn, "cover" if cover else "image", p) for p in paths]
        if cover:
            update_post(conn, a.post, cover_id=ids[0])
        else:
            update_post(conn, a.post, media_ids=ids)
    print(f"Associado à publicação #{a.post}")


def cmd_attach(a):
    with connect() as conn:
        ids = [add_media(conn, "video" if f.endswith(".mp4") else "image", str(Path(f).resolve())) for f in a.files]
        fields = {"media_ids": ids}
        if a.cover:
            fields["cover_id"] = add_media(conn, "cover", str(Path(a.cover).resolve()))
        update_post(conn, a.post, **fields)
    print(f"#{a.post}: {len(ids)} ficheiro(s) associados")


def cmd_edit(a):
    fields = {k: v for k, v in (("caption", a.caption), ("title", a.title),
                                ("scheduled_at", a.when and _aware(a.when))) if v}
    if a.caption_file:
        fields["caption"] = Path(a.caption_file).read_text(encoding="utf-8")
    with connect() as conn:
        update_post(conn, a.id, **fields)
    print(f"#{a.id} atualizado")


def cmd_schedule(a):
    from .scheduler import parse_dt
    dt = parse_dt(a.when)
    with connect() as conn:
        update_post(conn, a.id, scheduled_at=dt.isoformat())
    print(f"#{a.id} agendado para {dt:%Y-%m-%d %H:%M}")


def cmd_approve(a):
    from .scheduler import all_problems
    with connect() as conn:
        for pid in a.ids:
            problems = all_problems(conn, get_post(conn, pid))
            if problems and not a.force:
                print(f"#{pid} não aprovado: {', '.join(problems)} (usa --force para ignorar)")
                continue
            update_post(conn, pid, status="approved", error=None)
            print(f"#{pid} aprovado ✔")


def cmd_fit_format(a):
    """Cria versões dos ficheiros no tamanho certo para a rede, sem cortar nada (fundo desfocado)."""
    from .db import media_paths
    from .media import formats
    from .scheduler import format_report
    with connect() as conn:
        row = get_post(conn, a.post)
        rep = format_report(conn, row)
        if not rep.spec.get("size"):
            print(f"#{a.post}: nada a ajustar ({'; '.join(rep.problems) or 'sem tamanho definido'})")
            return
        ids = json.loads(row["media_ids"] or "[]")
        out_dir = DATA_DIR / "renders" / "ajustados"
        out_dir.mkdir(parents=True, exist_ok=True)
        new_ids = []
        for mid, path, item in zip(ids, media_paths(conn, ids), rep.items):
            fixable = item.width and any(k in " ".join(item.notes) for k in (
                "proporção", "resolução", "pequeno", "largura", "imagens por segundo", "fora do aceite"))
            if item.verdict == "ok" or not fixable:
                new_ids.append(mid)
                continue
            spec = rep.spec if not item.video or rep.kind == "video" else \
                (formats.spec_for(rep.platform, "video") or rep.spec)
            size = tuple(spec["size"])
            stem = f"post{a.post}_{mid}_{size[0]}x{size[1]}"
            if item.video:
                lo, hi = spec.get("fps", (0, 999))
                fps = 30 if item.fps and not (lo - 0.5 <= item.fps <= hi + 0.5) else None
                out = formats.fit_video(path, str(out_dir / f"{stem}.mp4"), size, fps=fps)
            else:
                out = formats.fit_image(path, str(out_dir / f"{stem}.jpg"), size)
            old = conn.execute("SELECT kind, meta FROM media WHERE id=?", (mid,)).fetchone()
            meta = {**json.loads(old["meta"] or "{}"), "ajustado_de": mid}
            new_ids.append(add_media(conn, old["kind"], out, meta=meta))
            print(f"✔ ficheiro {len(new_ids)}: {item.size} → {size[0]}×{size[1]}")
        if new_ids != ids:
            update_post(conn, a.post, media_ids=new_ids, error=None)
        print(f"#{a.post}: {format_report(conn, get_post(conn, a.post)).verdict_label}")


def make_quote_carousel(conn, acc_id: str, frases: list[str], *, title: str = "", caption: str = "",
                        scheduled_at: str | None = None, auto_date: bool = False, use_ai: bool = True) -> int:
    """Uma imagem de frase por linha (estilo da 'Imagem com frase') e UM post do tipo carrossel, 'Para aprovar'."""
    from .media import image_gen
    from .media.formats import spec_for
    frases = [f.strip() for f in frases if f.strip()]
    acc = account(acc_id)                      # aplica a identidade visual da conta (preto e dourado nas pessoais)
    mn, mx = spec_for(acc.platform, "carousel").get("count", (2, 10))
    if not mn <= len(frases) <= mx:
        raise SystemExit(f"Um carrossel em {acc.name} leva {mn} a {mx} frases (recebi {len(frases)}).")
    size = _render_size(acc, "image")
    out = _out_dir("images", f"carrossel_frases_{datetime.now():%Y%m%d_%H%M%S}")
    paths = [image_gen.quote_card(f, out / f"{i:02d}.jpg", size=size) for i, f in enumerate(frases, 1)]
    ids = [add_media(conn, "image", str(p), None, {"frase": f}) for p, f in zip(paths, frases)]
    when = scheduled_at if scheduled_at is not None else (_when(conn, acc_id, None) if auto_date else None)
    hashtags: list[str] = []
    if not caption and use_ai:
        caption, hashtags = _ai_caption(acc, "carrossel", "Uma imagem por frase, por esta ordem:\n"
                                        + "\n".join(f"{i}. {f}" for i, f in enumerate(frases, 1)))
    return add_post(conn, account_id=acc_id, format="carousel", title=(title or frases[0])[:80],
                    caption=caption, hashtags=hashtags, media_ids=ids, scheduled_at=when, status="draft")


def _safe(account_id: str, caption: str) -> str:
    """Legenda escrita pela IA → sem termos proibidos (ex.: AURON nas contas da Carretos), ver content/guard.py."""
    from .content.guard import sanitize
    return sanitize(account_id, caption or "")


def _ai_caption(acc, fmt: str, brief: str) -> tuple[str, list[str]]:
    """Legenda pela IA; sem chave ou com erro devolve vazio (a página pede para escrever ou pedir à IA)."""
    import os
    if not os.environ.get("SOCIAL_ANTHROPIC_API_KEY"):
        print("(sem chave da IA: a legenda fica por escrever)")
        return "", []
    try:
        from .content.ai import write_caption
        from .content.guard import sanitize
        res = write_caption(acc, fmt, brief)
        return sanitize(acc.id, res.get("caption", "").strip()), res.get("hashtags") or []
    except Exception as exc:  # noqa: BLE001
        print(f"(a IA não escreveu a legenda: {exc})")
        return "", []


def cmd_caption_ai(a):
    """Pede à IA a legenda de uma publicação que ainda não a tem (a partir do título, gancho e frases)."""
    with connect() as conn:
        row, extra = _post_meta(conn, a.post)
        acc = account(row["account_id"])
        ids = json.loads(row["media_ids"] or "[]")
        frases = [json.loads(m["meta"] or "{}").get("frase") for m in conn.execute(
            f"SELECT meta FROM media WHERE id IN ({','.join('?' * len(ids)) or 'NULL'})", ids)]
        brief = "\n".join(x for x in [f"Título: {row['title'] or ''}", f"Gancho: {row['hook'] or ''}",
                                       *[f"Frase: {f}" for f in frases if f],
                                       *[f"Slide: {s}" for s in extra.get("slides") or []]] if x.split(": ", 1)[1])
        caption, tags = _ai_caption(acc, row["format"] or "imagem", brief or "(sem descrição)")
        if not caption:
            raise SystemExit("Não foi possível gerar a legenda.")
        if (row["title"] or "").startswith("[TESTE]") or (row["caption"] or "").startswith("[TESTE]"):
            caption = "[TESTE] " + caption.removeprefix("[TESTE]").lstrip()   # nunca parecer um post real
        update_post(conn, a.post, caption=caption, hashtags=tags)
    print(f"#{a.post}: legenda escrita pela IA")


def cmd_quote_carousel(a):
    frases = list(a.frase or [])
    if a.ficheiro:
        frases += Path(a.ficheiro).read_text(encoding="utf-8").splitlines()
    with connect() as conn:
        pid = make_quote_carousel(conn, a.account, frases, caption=a.legenda or "",
                                  scheduled_at=_aware(a.schedule) if a.schedule else None)
    print(f"Criada publicação #{pid} (carrossel com {len([f for f in frases if f.strip()])} imagens, Para aprovar)")


EXEMPLO_FRASES = ["A consistência vence o talento quando o talento não aparece.",
                  "Cada carro que sai bem reparado é a melhor publicidade.",
                  "Não vendemos peças. Vendemos confiança."]


def cmd_example_carousel(a):
    """Post de TESTE (Instagram pessoal), carrossel de 3 frases, Para aprovar e SEM data (nunca sai sozinho)."""
    with connect() as conn:
        pid = make_quote_carousel(conn, "ig_davidcarreto", EXEMPLO_FRASES,
                                  title="[TESTE] Carrossel de exemplo (não publicar)",
                                  caption="[TESTE] Carrossel de exemplo: não publicar.", use_ai=False)
    print(f"Criada publicação de teste #{pid}: carrossel com 3 imagens, Para aprovar, sem data.")


def cmd_tiktok_test(a):
    """Envia para os rascunhos do TikTok um vídeo curto e um carrossel de 2 fotos de TESTE (nada é publicado)."""
    import subprocess
    from PIL import Image, ImageDraw
    from .media import image_gen
    from .publishers.base import PublishRequest
    from .publishers.tiktok import PRIVACY, TikTokPublisher, _send_caption
    from .tiktok_connect import ensure_fresh
    acc = account(a.account)
    out = _out_dir("teste_tiktok", acc.id)
    video = out / "teste_tiktok.mp4"
    photos = []
    for i in (1, 2):                                   # com texto, no tipo de letra das imagens reais
        im = Image.new("RGB", (1080, 1920), (17, 17, 17))
        d = ImageDraw.Draw(im)
        d.rectangle([60, 60, 1020, 1860], outline=(212, 175, 55), width=12)
        big, small = image_gen._font(True, 120), image_gen._font(False, 52)
        for text, font, y, fill in ((f"[TESTE] {i}/2", big, 820, (255, 255, 255)),
                                    ("Carretos Studio", small, 1000, (212, 175, 55))):
            w = d.textlength(text, font=font)
            d.text(((1080 - w) / 2, y), text, font=font, fill=fill)
        p = out / f"teste_tiktok_{i}.jpg"
        im.save(p, quality=92)
        photos.append(str(p))
    print(f"Tipo de letra usado: {getattr(big, 'path', '?')}")
    # vídeo de teste a partir das mesmas imagens (2,5 s cada), com som silencioso
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-t", "2.5", "-i", photos[0], "-loop", "1", "-t", "2.5",
                    "-i", photos[1], "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                    "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0,scale=1080:1920,fps=30,format=yuv420p[v]",
                    "-map", "[v]", "-map", "2:a", "-shortest", "-c:v", "libx264", "-c:a", "aac", str(video)], check=True)
    from .media.formats import is_blank_video
    if is_blank_video(str(video)):
        raise SystemExit(f"✘ Vídeo de teste: saiu vazio (uma só cor, {video.stat().st_size // 1024} KB). Não enviado.")
    print(f"Vídeo de teste: com texto ✓ ({video.stat().st_size // 1024} KB, 5 s, 1080×1920)")
    # pré-visualização no dashboard: uma publicação [TESTE] com o que foi enviado (sem data: nunca é publicada)
    with connect() as conn:
        ids = [add_media(conn, "image", p) for p in photos]
        vid = add_media(conn, "video", str(video))
        pv_photos = add_post(conn, account_id=acc.id, format="carousel", status="tiktok_draft", media_ids=ids,
                             title="[TESTE] Carrossel enviado para os rascunhos do TikTok",
                             caption="[TESTE] Carrossel de teste do Carretos Studio.")
        pv_video = add_post(conn, account_id=acc.id, format="video", status="tiktok_draft", media_ids=[vid],
                            title="[TESTE] Vídeo enviado para os rascunhos do TikTok",
                            caption="[TESTE] Legenda de teste do vídeo do Carretos Studio.")
    pub = TikTokPublisher()
    pub.h = {"Authorization": f"Bearer {ensure_fresh(acc)}", "Content-Type": "application/json; charset=UTF-8"}
    ok = True
    for label, pv, run in (("Vídeo", pv_video, lambda: pub._video(video)),
                           ("Carrossel de 2 fotos", pv_photos, lambda: pub._photos(photos, PublishRequest(
                               account=acc, format="carousel", caption="[TESTE] Carrossel de teste do Carretos Studio.",
                               media=photos, title="[TESTE] Carrossel de teste")))):
        try:
            pid = run()
            st = pub._wait(pid)
            print(f"✔ {label}: a TikTok confirmou ({' → '.join(st['trace'])}; publish_id {pid}) – está nos rascunhos "
                  f"de @{acc.handle}; pode demorar alguns minutos a aparecer completo na app. Pré-visualização: /post/{pv}")
            if label == "Vídeo":
                for line in _send_caption(PublishRequest(account=acc, format="video", media=[str(video)],
                                                         caption="[TESTE] Legenda de teste do vídeo do Carretos Studio."),
                                          test=True):
                    print(line)
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"✘ {label}: {exc}")
    print(PRIVACY)
    if not ok:
        raise SystemExit("Pelo menos um envio foi recusado (ver acima). Os posts desta conta seguem em modo assistido.")


def cmd_restore(a):
    """Repõe a imagem/vídeo de uma publicação: um ficheiro indicado, ou a última versão do histórico."""
    from .db import post_history
    with connect() as conn:
        row = get_post(conn, a.post)
        if a.ficheiro:
            path = str(Path(a.ficheiro).resolve())
            if not Path(path).exists():
                raise SystemExit(f"O ficheiro não existe: {path}")
            found = conn.execute("SELECT id FROM media WHERE path=? ORDER BY id DESC LIMIT 1", (path,)).fetchone()
            kind = "video" if path.lower().endswith((".mp4", ".mov")) else "image"
            ids = [found["id"] if found else add_media(conn, kind, path)]
        else:
            prev = next((h for h in post_history(conn, a.post)
                         if h["field"] == "media_ids" and json.loads(h["old"] or "[]")), None)
            if not prev:
                raise SystemExit("Sem versão anterior no histórico. Indica o ficheiro: --ficheiro CAMINHO")
            ids = json.loads(prev["old"])
        fields = {"media_ids": ids, "error": None}
        if a.estado:
            fields["status"] = a.estado
        elif row["status"] == "idea":
            fields["status"] = "draft"
        update_post(conn, a.post, **fields)
        row = get_post(conn, a.post)
    print(f"#{a.post}: media {json.loads(row['media_ids'])} · estado {row['status']}")


def cmd_backup(a):
    from .db import backup
    dest = backup(a.motivo)
    print(f"Cópia da base de dados: {dest}" if dest else "Ainda não há base de dados.")


def cmd_reject(a):
    with connect() as conn:
        for pid in a.ids:
            update_post(conn, pid, status="idea" if a.regenerate else "rejected")
            print(f"#{pid} {'volta a ideia (será regenerado)' if a.regenerate else 'rejeitado'}")


def cmd_calendar(a):
    from .content.planner import calendar
    start = date.fromisoformat(a.start) if a.start else date.today()
    with connect() as conn:
        rows = calendar(conn, start, a.days)
    icons = {"idea": "💭", "draft": "📝", "approved": "✅", "published": "🚀", "failed": "⚠️",
             "assist_sent": "📲", "rejected": "✖"}
    day = None
    for r in rows:
        d = r["scheduled_at"][:10]
        if d != day:
            day = d
            print(f"\n{datetime.fromisoformat(d):%a %d/%m}")
        media = "🎬" if json.loads(r["media_ids"] or "[]") else "  "
        print(f"  {r['scheduled_at'][11:16]} {icons.get(r['status'], '?')} {media} #{r['id']:<4} "
              f"{r['account_id']:18} {r['format']:9} {r['title'] or r['pillar']}")


def cmd_publish_due(a):
    from .scheduler import tick
    lines = tick(dry_run=a.dry_run)
    print("\n".join(lines) if lines else "Nada para publicar agora.")


def cmd_publish(a):
    from .scheduler import publish_post
    with connect() as conn:
        print(publish_post(conn, a.id, a.dry_run))


def cmd_run(a):
    from .scheduler import run_forever
    run_forever(a.interval)


def cmd_correio(a):
    from .mail_receiver import run
    run(port=a.porta)


def cmd_dashboard(a):
    from .dashboard import build
    p = build(a.days)
    print(f"Painel: {p}")



def _library_names(limit: int = 60) -> list[str]:
    from .media.stock import LIBRARY
    if not LIBRARY.exists():
        return []
    import yaml
    tags_file = LIBRARY / "etiquetas.yaml"
    tags = (yaml.safe_load(tags_file.read_text(encoding="utf-8")) or {}) if tags_file.exists() else {}
    names = sorted(p.name for p in LIBRARY.rglob("*") if p.is_file() and p.suffix.lower() in
                   {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov"})[:limit]
    # a IA recebe o ficheiro + o que mostra, para escolher o fundo certo em "visual"
    return [f"{n} ({', '.join(tags[n][:8])})" if n in tags else n for n in names]


def _create_for(conn, acc, *, topic: str = "", post_id: int | None = None, storyboard_file: str | None = None,
                seconds: int = 35, narration: bool = True, music: bool = True, schedule: str | None = None,
                use_ai: bool = True) -> dict:
    from .media import image_gen
    from .media.creator import create_video, storyboard_from_post
    post = extra = None
    if post_id:
        row, extra = _post_meta(conn, post_id)
        post = dict(row)
    if storyboard_file:
        sb = json.loads(Path(storyboard_file).read_text(encoding="utf-8"))
    elif use_ai:
        from .content.ai import storyboard
        brief = None
        if post:
            brief = {k: post[k] for k in ("title", "hook", "caption", "pillar")} | {
                "guiao": extra.get("script"), "textos_ecra": extra.get("on_screen_texts")}
        sb = storyboard(acc, topic or (post or {}).get("title") or "", seconds, (post or {}).get("pillar") or "",
                        brief, _library_names())
    elif post:
        sb = storyboard_from_post(post, extra)
    else:
        raise SystemExit("Sem IA: indica --storyboard ficheiro.json ou --post <id> com guião gerado.")
    w, h = _render_size(acc)
    out_dir = _out_dir(acc.id, "criados")
    (out_dir / "storyboards").mkdir(exist_ok=True)
    res = create_video(sb, out_dir, size=(w, h), handle=acc.handle,
                       narration=narration and _narrator_ready(acc.narrator), narrator=acc.narrator,
                       music="auto" if music else None,
                       max_seconds=strategy()["render"].get(acc.platform, {}).get("max_seconds"))
    stem = Path(res["video"]).stem
    (out_dir / "storyboards" / f"{stem}.json").write_text(json.dumps(sb, ensure_ascii=False, indent=1),
                                                          encoding="utf-8")
    cover = image_gen.cover(res["cover_frame"], res.get("cover_text") or sb.get("title") or acc.name,
                            out_dir / f"{stem}_capa.jpg", size=(w, h))
    vid_id = add_media(conn, "video", res["video"], None, {"account": acc.id, "created_from_zero": True,
                                                         "stock": res.get("stock_sources", [])})
    cov_id = add_media(conn, "cover", cover, vid_id)
    res["cover"] = str(cover)
    if post_id:
        fields = {"media_ids": [vid_id], "cover_id": cov_id}
        if not post.get("caption") and res.get("caption"):
            fields.update(caption=_safe(acc.id, res["caption"]), hashtags=res.get("hashtags") or [])
        if post["status"] == "idea":
            fields["status"] = "draft"
        update_post(conn, post_id, **fields)
        res["post_id"] = post_id
    else:
        res["post_id"] = add_post(conn, account_id=acc.id, format="reel" if acc.platform == "instagram" else "video",
                                  title=res.get("title") or stem, hook=sb["scenes"][0].get("title", ""),
                                  caption=_safe(acc.id, res.get("caption") or ""), hashtags=res.get("hashtags") or [],
                                  media_ids=[vid_id], cover_id=cov_id,
                                  scheduled_at=_when(conn, acc.id, schedule), status="draft")
    return res


def cmd_create_video(a):
    acc = account(a.account)
    if not (a.topic or a.post or a.storyboard):
        raise SystemExit("Indica --topic \"tema\", --post <id> ou --storyboard ficheiro.json")
    with connect() as conn:
        res = _create_for(conn, acc, topic=a.topic or "", post_id=a.post, storyboard_file=a.storyboard,
                          seconds=a.seconds, narration=not a.no_voice, music=not a.no_music, schedule=a.schedule,
                          use_ai=not a.no_ai)
    for s in res["steps"]:
        print(" •", s)
    print(f"Vídeo: {res['video']} ({res['duration']} s)\nCapa:  {res['cover']}\nPublicação #{res['post_id']}")


def cmd_produce(a):
    """Piloto automático: cria o vídeo/imagem de todas as publicações planeadas que ainda não têm media."""
    from .media import image_gen
    start = datetime.now().isoformat()
    end = (datetime.now() + timedelta(days=a.days)).isoformat()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM posts WHERE status IN ('idea','draft') AND media_ids='[]' AND scheduled_at BETWEEN ? AND ? "
            "ORDER BY scheduled_at", (start, end)).fetchall()
        if a.accounts:
            rows = [r for r in rows if r["account_id"] in a.accounts]
        print(f"{len(rows)} publicações sem media nos próximos {a.days} dias.")
        for r in rows:
            acc = account(r["account_id"])
            label = f"#{r['id']} {r['scheduled_at'][:16]} {acc.id} {r['format']}"
            try:
                if r["format"] in ("reel", "video"):
                    if a.only_images:
                        continue
                    res = _create_for(conn, acc, post_id=r["id"], seconds=a.seconds, use_ai=not a.no_ai)
                    print(f"{label} → 🎬 {Path(res['video']).name} ({res['duration']} s)")
                else:
                    _, extra = _post_meta(conn, r["id"])
                    size = _render_size(acc, "image")
                    out = _out_dir(acc.id, "criados")
                    title = extra.get("cover_text") or r["hook"] or r["title"] or r["pillar"]
                    photo_src = None
                    if r["format"] == "carousel" and extra.get("slides"):
                        paths = image_gen.carousel(extra["slides"], out / f"carrossel_{r['id']}", size=size,
                                                   handle=acc.handle)
                    elif r["pillar"] in ("lideranca", "dificuldades") and r["hook"]:
                        paths = [image_gen.quote_card(r["hook"], out / f"frase_{r['id']}.jpg", size=size)]
                    else:
                        from .media.stock import find_visual
                        from .media.stock import source_of
                        photo = find_visual(r["title"] or r["pillar"] or "mercedes workshop", "image")
                        photo_src = source_of(photo) if photo else None
                        paths = [image_gen.photo_post(photo, title, out / f"imagem_{r['id']}.jpg", size=size,
                                                      tag=(r["pillar"] or "").replace("_", " "))]
                    meta = {"stock": [photo_src]} if photo_src else None
                    ids = [add_media(conn, "image", p, None, meta) for p in paths]
                    update_post(conn, r["id"], media_ids=ids, status="draft" if r["status"] == "idea" else r["status"])
                    print(f"{label} → 🖼  {len(paths)} imagem(ns)")
            except Exception as exc:  # noqa: BLE001
                print(f"{label} → ⚠️ {exc}")



def cmd_voice_setup(a):
    from .config import ROOT, brand
    from .media.voice import prepare_sample
    cfg = brand().get("narrators", {}).get(a.narrator)
    if not cfg or cfg.get("engine") not in ("chatterbox", "conversion"):
        raise SystemExit(f"O narrador '{a.narrator}' não é um clone (ver narrators em config/brand.yaml)")
    out = ROOT / cfg["sample"]
    info = prepare_sample(a.file, out, a.seconds)
    print(f"Referência pronta: {info['sample']} ({info['speech_seconds']} s de fala limpa)")
    if info.get("representativeness"):
        print(f"Escolhido o trecho mais representativo de {info['total_speech_seconds']} s de fala "
              f"(semelhança {info['representativeness']})")
    if info["speech_seconds"] < 8:
        print("⚠️  Pouca fala aproveitável; grava 1–2 minutos num sítio silencioso.")
    print('Testa com: carretos voice-test "Olá, sou o David Carreto."')


def cmd_voice_collect(a):
    from .config import ROOT
    from .media.voice import collect_voice
    rep = collect_voice(a.folder, a.reference, a.out or ROOT / "assets" / "voz" / "dataset", a.threshold)
    total = 0.0
    for name, r in rep.items():
        total += r.get("fala_tua_s", 0) or 0
        print(f"{name[:45]:45} {r}")
    print(f"\nTotal de fala verificada como tua: {total / 60:.1f} min")


def cmd_voice_test(a):
    from .media.voice import speak
    out = Path(a.out or DATA_DIR / f"teste_voz_{a.narrator}.wav")
    secs = speak(a.text, out, a.speed, a.narrator)
    print(f"{out} ({secs:.1f} s)")



def cmd_montage(a):
    """Vários vídeos teus → um vídeo: melhores trechos, imagens a meio, legendas, música, capa."""
    from .media import image_gen
    from .media.montage import montage
    acc = account(a.account)
    w, h = _render_size(acc)
    out_dir = _out_dir(acc.id, "montagens")
    res = montage(a.files, out_dir, acc=acc, width=w, height=h, target_seconds=a.seconds, goal=a.goal or "",
                  use_ai=not a.no_ai, broll=not a.no_broll, fill=a.fill, music=None if a.no_music else "auto",
                  max_seconds=strategy()["render"].get(acc.platform, {}).get("max_seconds"),
                  library=_library_names())
    stem = Path(res["video"]).stem
    cover = image_gen.cover(res["cover_frame"], res.get("cover_text") or res.get("hook_text") or acc.name,
                            out_dir / f"{stem}_capa.jpg", size=(w, h))
    with connect() as conn:
        vid_id = add_media(conn, "video", res["video"], None, {"account": acc.id, "montage": res.get("pieces"),
                                                         "stock": res.get("stock_sources", [])})
        cov_id = add_media(conn, "cover", cover, vid_id)
        pid = add_post(conn, account_id=acc.id, format="reel" if acc.platform == "instagram" else "video",
                       title=res.get("title") or stem, hook=res.get("hook_text") or "",
                       caption=res.get("caption") or "", hashtags=res.get("hashtags") or [], media_ids=[vid_id],
                       cover_id=cov_id, scheduled_at=_when(conn, acc.id, a.schedule), status="draft")
    for s in res["steps"]:
        print(" •", s)
    print(f"Vídeo: {res['video']} ({res['duration']} s)\nCapa:  {cover}\nPublicação #{pid}")



def cmd_avatar_video(a):
    """Vídeo com o teu avatar a falar (HeyGen, pago) + acabamento do sistema (legendas, música, capa)."""
    from .media import avatar, image_gen
    from .media.video_editor import auto_edit
    acc = account(a.account)
    if not avatar.configured():
        raise SystemExit("O avatar usa o HeyGen (pago) e ainda não está configurado. "
                         "Preenche HEYGEN_API_KEY, HEYGEN_AVATAR_ID e HEYGEN_VOICE_ID no .env depois de aprovares o plano.")
    script = a.text
    if not script:
        from .content.ai import storyboard
        sb = storyboard(acc, a.topic, a.seconds)
        script = " ".join(s["voiceover"] for s in sb["scenes"])
    w, h = _render_size(acc)
    out_dir = _out_dir(acc.id, "avatar")
    raw = avatar.generate(script, out_dir / f"avatar_{datetime.now():%Y%m%d_%H%M%S}.mp4", w, h)
    res = auto_edit(raw, out_dir, width=w, height=h, target_seconds=None, use_ai=False, fill="crop")
    cover = image_gen.cover(res["cover_frame"], a.cover_text or (a.topic or script)[:40], out_dir / f"{raw.stem}_capa.jpg",
                            size=(w, h))
    print(f"Vídeo: {res['video']}\nCapa:  {cover}\n⚠️  Vídeo feito com IA: marca 'conteúdo gerado por IA' ao publicar.")



def cmd_web(a):
    """Arranca o dashboard (e a fila de tarefas)."""
    import uvicorn
    uvicorn.run("carretos_social.web.app:app", host=a.host, port=a.port, log_level="warning")



CONFIG_KEYS = [
    ("DASHBOARD_PASSWORD", "Palavra-passe para entrar no dashboard (escolhe uma forte)", True),
    ("SOCIAL_ANTHROPIC_API_KEY", "Chave da IA (Claude Console)", True),
    ("ELEVENLABS_API_KEY", "Chave da ElevenLabs", True),
    ("ELEVENLABS_VOICE_ID", "Voice ID da voz 'David Carreto' na ElevenLabs (não é secreto)", False),
    ("PIXABAY_API_KEY", "Chave da Pixabay (imagens e vídeos de stock)", True),
    ("PEXELS_API_KEY", "Chave do Pexels (opcional; tem prioridade sobre a Pixabay)", True),
]


def cmd_configurar(a):
    """Pergunta as chaves uma a uma (sem as mostrar) e grava-as no .env. Enter = manter o valor atual."""
    import getpass
    env = config.ROOT / ".env"
    if not env.exists() and (config.ROOT / ".env.example").exists():
        env.write_text((config.ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    current = {l.split("=", 1)[0].strip(): l.split("=", 1)[1] for l in lines if "=" in l and not l.startswith("#")}
    for key, label, secret in CONFIG_KEYS:
        has = "já definida" if current.get(key) else "vazia"
        prompt = f"{label} [{has}]: "
        value = (getpass.getpass(prompt) if secret else input(prompt)).strip()
        if not value:
            continue
        found = False
        for i, l in enumerate(lines):
            if l.split("=", 1)[0].strip() == key and not l.startswith("#"):
                lines[i] = f"{key}={value}"
                found = True
        if not found:
            lines.append(f"{key}={value}")
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env.chmod(0o600)
    print("Guardado. Reinicia os serviços: sudo systemctl restart carretos-web carretos-agendador")


def cmd_importar_drive(a):
    """Descarrega ficheiros públicos do Google Drive a partir de um CSV (nome,...,download)."""
    import csv
    import io
    import requests as rq
    dest = {"fotos": config.ROOT / "assets" / "library" / "david", "musicas": config.ROOT / "assets" / "music",
            "voz": config.ROOT / "assets" / "voz" / "elevenlabs"}[a.destino]
    dest.mkdir(parents=True, exist_ok=True)
    text = Path(a.csv).read_text(encoding="utf-8-sig") if Path(a.csv).exists() else rq.get(a.csv, timeout=60).text
    ok = 0
    for row in csv.DictReader(io.StringIO(text)):
        name, url = (row.get("nome") or "").strip(), (row.get("download") or "").strip()
        if not name or not url:
            continue
        target = dest / Path(name).name
        if target.exists() and target.stat().st_size > 0:
            continue
        r = rq.get(url, timeout=600)
        if r.ok and not r.content[:200].lstrip().lower().startswith(b"<!doctype html"):
            target.write_bytes(r.content)
            ok += 1
            print(f"✔ {name}")
        else:
            print(f"✘ {name} (não está partilhado com 'Qualquer pessoa com o link'?)")
    print(f"{ok} ficheiro(s) novos em {dest}")


# ------------------------------------------------------------------ parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="carretos", description="Gestão automática das redes sociais Carretos")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_)
        sp.set_defaults(fn=fn)
        return sp

    add("init", cmd_init, "prepara a base de dados e o .env")
    add("status", cmd_status, "estado das contas e credenciais")
    s = add("sync", cmd_sync, "recolhe métricas de todas as contas")
    s.add_argument("--accounts", nargs="*")
    s = add("import-csv", cmd_import_csv, "importa métricas de um CSV exportado")
    s.add_argument("account"); s.add_argument("file")
    s = add("report", cmd_report, "relatório de desempenho (+ recomendações IA com --ai)")
    s.add_argument("--days", type=int, default=30); s.add_argument("--ai", action="store_true")
    s = add("plan", cmd_plan, "cria a agenda de slots para o período")
    s.add_argument("--start"); s.add_argument("--days", type=int, default=7); s.add_argument("--accounts", nargs="*")
    s = add("generate", cmd_generate, "a IA cria guiões e legendas para os slots")
    s.add_argument("--ids", nargs="*", type=int); s.add_argument("--accounts", nargs="*")
    s.add_argument("--context", help="novidades da semana: carros, conquistas, problemas...")
    s = add("show", cmd_show, "mostra uma publicação"); s.add_argument("id", type=int)

    s = add("edit-video", cmd_edit_video, "edita automaticamente um vídeo teu")
    s.add_argument("file"); s.add_argument("--account", required=True)
    s.add_argument("--post", type=int, help="associa à publicação planeada")
    s.add_argument("--schedule", help="cria nova publicação nesta data (AAAA-MM-DDTHH:MM)")
    s.add_argument("--seconds", type=int, default=45, help="duração alvo")
    s.add_argument("--hook"); s.add_argument("--goal"); s.add_argument("--cover-text")
    s.add_argument("--fill", choices=["blur", "crop"], default="blur")
    s.add_argument("--speed", type=float, default=1.0)
    s.add_argument("--no-ai", action="store_true"); s.add_argument("--no-subs", action="store_true")
    s.add_argument("--no-music", action="store_true")

    s = add("repurpose", cmd_repurpose, "um vídeo → versões para todas as contas de vídeo")
    s.add_argument("file"); s.add_argument("--accounts", nargs="*"); s.add_argument("--seconds", type=int, default=45)
    s.add_argument("--goal"); s.add_argument("--no-ai", action="store_true"); s.add_argument("--no-subs", action="store_true")

    s = add("cover", cmd_cover, "cria uma capa (de um vídeo ou imagem)")
    s.add_argument("text"); s.add_argument("--video"); s.add_argument("--image"); s.add_argument("--subtitle")
    s.add_argument("--highlight", help="palavras a destacar, separadas por vírgula")
    s.add_argument("--size", default="1080x1920"); s.add_argument("--out"); s.add_argument("--post", type=int)

    s = add("image", cmd_image, "cria imagem: quote | photo | carousel")
    s.add_argument("kind", choices=["quote", "photo", "carousel"]); s.add_argument("--text", default="")
    s.add_argument("--photo"); s.add_argument("--tag"); s.add_argument("--slides", nargs="*")
    s.add_argument("--account"); s.add_argument("--size", default="1080x1350"); s.add_argument("--post", type=int)

    s = add("attach", cmd_attach, "associa ficheiros a uma publicação")
    s.add_argument("post", type=int); s.add_argument("files", nargs="+"); s.add_argument("--cover")
    s = add("edit", cmd_edit, "altera legenda/título/data de uma publicação")
    s.add_argument("id", type=int); s.add_argument("--caption"); s.add_argument("--caption-file")
    s.add_argument("--title"); s.add_argument("--when")
    s = add("schedule", cmd_schedule, "agenda uma publicação"); s.add_argument("id", type=int); s.add_argument("when")
    s = add("approve", cmd_approve, "aprova publicações para saírem automaticamente")
    s.add_argument("ids", nargs="+", type=int); s.add_argument("--force", action="store_true")
    s = add("ajustar-formato", cmd_fit_format, "ajusta imagens/vídeos ao tamanho da rede, sem cortar")
    s.add_argument("post", type=int)
    s = add("carrossel-frases", cmd_quote_carousel, "uma imagem por frase → um post carrossel (Para aprovar)")
    s.add_argument("--account", required=True); s.add_argument("--frase", action="append")
    s.add_argument("--ficheiro", help="ficheiro de texto com uma frase por linha")
    s.add_argument("--legenda"); s.add_argument("--schedule")
    s = add("legenda-ia", cmd_caption_ai, "a IA escreve a legenda de uma publicação"); s.add_argument("post", type=int)
    add("exemplo-carrossel", cmd_example_carousel, "cria um carrossel de TESTE (sem data) para experimentar")
    s = add("tiktok-teste", cmd_tiktok_test, "envia um vídeo e um carrossel de TESTE para os rascunhos do TikTok")
    s.add_argument("--account", required=True)
    s = add("repor", cmd_restore, "repõe a imagem/vídeo de uma publicação (ficheiro ou histórico)")
    s.add_argument("post", type=int); s.add_argument("--ficheiro")
    s.add_argument("--estado", choices=["idea", "draft", "approved"], help="por defeito: 'draft' (Para aprovar)")
    s = add("backup", cmd_backup, "cópia de segurança da base de dados (data/backups/)")
    s.add_argument("motivo", nargs="?", default="manual")
    s = add("reject", cmd_reject, "rejeita publicações"); s.add_argument("ids", nargs="+", type=int)
    s.add_argument("--regenerate", action="store_true")
    s = add("calendar", cmd_calendar, "agenda de conteúdos")
    s.add_argument("--start"); s.add_argument("--days", type=int, default=14)
    s = add("publish-due", cmd_publish_due, "publica o que está aprovado e na hora (para cron)")
    s.add_argument("--dry-run", action="store_true")
    s = add("publish", cmd_publish, "publica já uma publicação"); s.add_argument("id", type=int)
    s.add_argument("--dry-run", action="store_true")
    s = add("correio", cmd_correio, "recetor de email (porta 25) só para os avisos de mensagens do LinkedIn")
    s.add_argument("--porta", type=int, default=None)
    s = add("run", cmd_run, "agendador contínuo (publica, recolhe métricas, lembra aprovações)")
    s.add_argument("--interval", type=int, default=60)
    s = add("dashboard", cmd_dashboard, "gera o painel HTML (agenda + métricas)")
    s.add_argument("--days", type=int, default=30)
    s = add("create-video", cmd_create_video, "cria um vídeo do zero (guião IA + voz + grafismo + imagens)")
    s.add_argument("--account", required=True); s.add_argument("--topic"); s.add_argument("--post", type=int)
    s.add_argument("--storyboard", help="JSON de cenas escrito à mão (ver exemplos/)")
    s.add_argument("--seconds", type=int, default=35); s.add_argument("--schedule")
    s.add_argument("--no-voice", action="store_true"); s.add_argument("--no-music", action="store_true")
    s.add_argument("--no-ai", action="store_true")
    s = add("produce", cmd_produce, "piloto automático: cria vídeos/imagens para as publicações planeadas")
    s.add_argument("--days", type=int, default=7); s.add_argument("--accounts", nargs="*")
    s.add_argument("--seconds", type=int, default=35); s.add_argument("--no-ai", action="store_true")
    s.add_argument("--only-images", action="store_true")
    s = add("montage", cmd_montage, "junta vários vídeos teus num só (trechos, imagens a meio, legendas, música)")
    s.add_argument("files", nargs="+"); s.add_argument("--account", required=True)
    s.add_argument("--seconds", type=int, default=45); s.add_argument("--goal"); s.add_argument("--schedule")
    s.add_argument("--fill", choices=["blur", "crop"], default="crop")
    s.add_argument("--no-ai", action="store_true"); s.add_argument("--no-broll", action="store_true")
    s.add_argument("--no-music", action="store_true")
    s = add("avatar-video", cmd_avatar_video, "vídeo com o teu avatar a falar (HeyGen, pago)")
    s.add_argument("--account", required=True); s.add_argument("--text"); s.add_argument("--topic", default="")
    s.add_argument("--seconds", type=int, default=30); s.add_argument("--cover-text")
    s = add("web", cmd_web, "arranca o dashboard no browser (http://localhost:8000)")
    s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8000)
    add("configurar", cmd_configurar, "pede as chaves (sem as mostrar) e grava-as no .env")
    s = add("importar-drive", cmd_importar_drive, "descarrega fotos/músicas/voz do Drive a partir de um CSV")
    s.add_argument("destino", choices=["fotos", "musicas", "voz"]); s.add_argument("csv")
    s = add("voice-setup", cmd_voice_setup, "prepara a tua gravação para o clone de voz")
    s.add_argument("file"); s.add_argument("--narrator", default="david"); s.add_argument("--seconds", type=float, default=10)
    s = add("voice-collect", cmd_voice_collect, "extrai de uma pasta de vídeos só os trechos com a tua voz")
    s.add_argument("folder"); s.add_argument("--reference", default="assets/voz/david_referencia.wav")
    s.add_argument("--out"); s.add_argument("--threshold", type=float, default=0.82)
    s = add("voice-test", cmd_voice_test, "gera uma frase de teste com um narrador")
    s.add_argument("text"); s.add_argument("--narrator", default="david"); s.add_argument("--speed", type=float, default=1.0)
    s.add_argument("--out")
    return p


def main(argv=None):
    config.load_env()
    args = build_parser().parse_args(argv)
    try:
        args.fn(args)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
