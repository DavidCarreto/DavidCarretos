"""Verificação automática das ligações (uma vez por dia, no agendador; ou em Contas → "Verificar todas agora").

Faz o mesmo que o botão "Testar" em cada conta ligada (Meta, LinkedIn, TikTok). Guarda o resultado em
data/saude.json; quando uma conta passa de "a funcionar" para "com problema", avisa no dashboard e manda um
alerta por email aos administradores e pelo Telegram (uma vez por mudança, sem repetir todos os dias).
Cobre o que não tem data de validade (tokens das Páginas/Instagram da Meta) e pode cair sem aviso.
"""
from __future__ import annotations

import json
from datetime import datetime

from . import config as _cfg
from .config import Account, accounts


def _path():
    return _cfg.DATA_DIR / "saude.json"


def results() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8")) if _path().exists() else {}
    except (OSError, ValueError):
        return {}


def tester(acc: Account):
    from . import linkedin_connect, meta_connect, tiktok_connect
    if acc.platform == "tiktok":
        return tiktok_connect.test
    if acc.platform in ("linkedin_member", "linkedin_org"):
        return linkedin_connect.test
    if acc.platform in ("instagram", "facebook_page"):
        return meta_connect.test
    return None


def test_account(acc: Account) -> tuple[bool, str]:
    t = tester(acc)
    return t(acc) if t else (False, "esta rede ainda não se liga")


def check_all(alert: bool = True) -> dict:
    """Testa todas as contas ligadas. Devolve {conta: {ok, text, at}} e alerta as que passaram a falhar."""
    previous = results()
    now = datetime.now().isoformat(timespec="minutes")
    out: dict[str, dict] = {}
    for acc in accounts().values():
        if not acc.has_credentials or not tester(acc):
            continue
        try:
            ok, text = test_account(acc)
        except Exception as exc:  # noqa: BLE001
            ok, text = False, f"a verificação falhou: {exc}"
        out[acc.id] = {"ok": ok, "text": text, "at": now, "name": acc.name}
    _cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _path().write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    newly = [r for k, r in out.items() if not r["ok"] and (previous.get(k) or {}).get("ok", True)]
    if alert and newly:
        _alert(newly)
    return out


def failing() -> list[dict]:
    return [{"account": k, **r} for k, r in results().items() if not r.get("ok")]


def _alert(items: list[dict]) -> None:
    text = ("Ligações com problemas:\n" + "\n".join(f"• {r['name']}: {r['text']}" for r in items) +
            "\nVolte a ligar em Contas (carretosstudio.duckdns.org/contas).")
    from . import notify
    try:
        notify.send(text)
    except Exception:  # noqa: BLE001
        pass
    try:
        from .web import mailer
        if mailer.configured():
            from .db import connect
            with connect() as conn:
                to = ",".join(r["email"] for r in conn.execute(
                    "SELECT email FROM users WHERE is_admin=1 AND active=1 AND email IS NOT NULL") if r["email"])
            if to:
                mailer.send(to, "Ligações com problemas", text)
    except Exception:  # noqa: BLE001
        pass
