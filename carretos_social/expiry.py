"""Ligações que expiram (LinkedIn ~60 dias, token de utilizador da Meta ~60 dias, renovação da TikTok ~1 ano):
aviso no dashboard e lembrete pelo Telegram, para voltar a ligar a tempo."""
from __future__ import annotations

from datetime import date

from .config import account_overrides, accounts

WARN_DAYS = 14


def expiring(today: date | None = None, warn_days: int = WARN_DAYS) -> list[dict]:
    """[{account, name, until, days}] das ligações que expiram em ≤ warn_days (ou já expiraram)."""
    today = today or date.today()
    out = []
    accs = accounts()
    for acc_id, o in account_overrides().items():
        acc = accs.get(acc_id)
        if not acc or not acc.has_credentials:
            continue
        for key in ("token_expires", "refresh_expires"):
            until = (o.get(key) or "")[:10]
            if not until:
                continue
            days = (date.fromisoformat(until) - today).days
            if days <= warn_days:
                out.append({"account": acc_id, "name": acc.name, "until": until, "days": days})
    return sorted(out, key=lambda e: e["days"])


def reminder_text(items: list[dict]) -> str:
    lines = [f"• {e['name']}: " + (f"expirou a {e['until']}" if e["days"] < 0 else
                                   f"expira a {e['until']} (faltam {e['days']} dias)") for e in items]
    return "📣 Carretos Studio · Ligações a renovar\n" + "\n".join(lines) + \
        "\nVolte a ligar em Contas (carretosstudio.duckdns.org/contas)."


def remind(only_days: set[int] | None = None) -> bool:
    """Envia o lembrete pelo Telegram (se estiver configurado). Devolve True se enviou.
    only_days: só nesses dias antes de expirar (ex.: {14, 7, 3, 1, 0}); depois de expirar, todos os dias."""
    from . import notify
    items = [e for e in expiring() if only_days is None or e["days"] < 0 or e["days"] in only_days]
    if not items or not notify.enabled():
        return False
    notify.send(reminder_text(items))
    return True
