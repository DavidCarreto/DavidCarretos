"""Utilizadores, palavras-passe e permissões por conta.

Nível por conta (cada um inclui os anteriores):
  nenhum   sem acesso (não vê a conta em lado nenhum)
  ver      agenda e métricas
  criar    criar e editar rascunhos, enviar para aprovação
  aprovar  aprovar/rejeitar e agendar publicações
O administrador (utilizador "david") tem sempre acesso total e é o único que gere a equipa.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from dataclasses import dataclass, field

from ..config import accounts
from ..db import connect, now

LEVELS = ["nenhum", "ver", "criar", "aprovar"]
LEVEL_LABELS = {"nenhum": "Sem acesso", "ver": "Ver", "criar": "Criar", "aprovar": "Aprovar"}
MAX_USERS = 5  # total de utilizadores ativos, incluindo o administrador


class LimitError(Exception):
    pass


def hash_pw(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1)
    return f"scrypt${salt}${dk.hex()}"


def check_pw(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1)
        return hmac.compare_digest(dk.hex(), digest)
    except ValueError:
        return False


def _rank(level: str | None) -> int:
    return LEVELS.index(level) if level in LEVELS else 0


@dataclass
class User:
    id: int
    username: str
    name: str
    is_admin: bool
    levels: dict = field(default_factory=dict)   # account_id -> nível
    must_change: bool = False
    email: str = ""

    def level(self, account_id: str) -> str:
        return "aprovar" if self.is_admin else self.levels.get(account_id, "nenhum")

    def can_view(self, account_id: str) -> bool:
        return _rank(self.level(account_id)) >= 1

    def can_create(self, account_id: str) -> bool:
        return _rank(self.level(account_id)) >= 2

    def can_approve(self, account_id: str) -> bool:
        return _rank(self.level(account_id)) >= 3

    can_see = can_view  # nome antigo

    @property
    def perms(self) -> dict:  # compatibilidade com código/testes antigos
        return {a: {"create": self.can_create(a), "approve": self.can_approve(a)} for a in self.levels}

    @property
    def visible_accounts(self) -> list[str]:
        return [a for a in accounts() if self.can_view(a)]

    @property
    def creatable_accounts(self) -> list[str]:
        return [a for a in accounts() if self.can_create(a)]


def load(user_id: int) -> User | None:
    with connect() as conn:
        r = conn.execute("SELECT * FROM users WHERE id=? AND active=1", (user_id,)).fetchone()
        if not r:
            return None
        levels = {p["account_id"]: (p["level"] or "nenhum")
                  for p in conn.execute("SELECT * FROM user_accounts WHERE user_id=?", (user_id,))}
    return User(r["id"], r["username"], r["name"] or r["username"], bool(r["is_admin"]), levels,
                bool(r["must_change"]), r["email"] or "")


def authenticate(username: str, password: str) -> User | None:
    with connect() as conn:
        r = conn.execute("SELECT * FROM users WHERE username=? AND active=1",
                         (username.strip().lower(),)).fetchone()
    if r and check_pw(password, r["pw_hash"]):
        return load(r["id"])
    return None


def count(active_only: bool = False) -> int:
    with connect() as conn:
        q = "SELECT COUNT(*) FROM users" + (" WHERE active=1" if active_only else "")
        return conn.execute(q).fetchone()[0]


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(normalize_email(email)))


def create(username: str, name: str, password: str, is_admin: bool = False, must_change: bool = False,
           email: str = "") -> int:
    """Cria um utilizador SEM acesso a nenhuma conta (o administrador dá as permissões depois)."""
    if count(active_only=True) >= MAX_USERS:
        raise LimitError(f"Limite de {MAX_USERS} utilizadores ativos atingido (incluindo o administrador).")
    email = normalize_email(email)
    if email and find_by_email(email):
        raise ValueError("Já existe um utilizador com este email.")
    with connect() as conn:
        return conn.execute(
            "INSERT INTO users(username, name, pw_hash, is_admin, created_at, must_change, email) "
            "VALUES (?,?,?,?,?,?,?)",
            (username.strip().lower(), name, hash_pw(password), int(is_admin), now(), int(must_change),
             email or None)).lastrowid


def set_email(user_id: int, email: str) -> None:
    email = normalize_email(email)
    other = find_by_email(email)
    if other and other != user_id:
        raise ValueError("Já existe um utilizador com este email.")
    with connect() as conn:
        conn.execute("UPDATE users SET email=? WHERE id=?", (email or None, user_id))


def find_by_email(email: str) -> int | None:
    email = normalize_email(email)
    if not email:
        return None
    with connect() as conn:
        r = conn.execute("SELECT id FROM users WHERE lower(email)=? AND active=1", (email,)).fetchone()
    return r["id"] if r else None


# ---------------------------------------------------------------- reposição da palavra-passe
RESET_MINUTES = 60


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_reset_token(user_id: int) -> str:
    """Código de uso único (só o hash fica na base de dados), válido durante RESET_MINUTES."""
    from datetime import datetime, timedelta
    token = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(minutes=RESET_MINUTES)).isoformat(timespec="seconds")
    with connect() as conn:
        conn.execute("DELETE FROM password_resets WHERE user_id=? OR expires_at < ?", (user_id, now()))
        conn.execute("INSERT INTO password_resets(token_hash, user_id, expires_at) VALUES (?,?,?)",
                     (_token_hash(token), user_id, expires))
    return token


def reset_user_for(token: str) -> int | None:
    with connect() as conn:
        r = conn.execute("SELECT user_id FROM password_resets WHERE token_hash=? AND used=0 AND expires_at >= ?",
                         (_token_hash(token), now())).fetchone()
    return r["user_id"] if r else None


def use_reset_token(token: str, new_password: str) -> bool:
    uid = reset_user_for(token)
    if not uid or len(new_password) < 8:
        return False
    set_password(uid, new_password, must_change=False)
    with connect() as conn:
        conn.execute("UPDATE password_resets SET used=1 WHERE token_hash=?", (_token_hash(token),))
    return True


def set_password(user_id: int, password: str, must_change: bool = False) -> None:
    with connect() as conn:
        conn.execute("UPDATE users SET pw_hash=?, must_change=? WHERE id=?",
                     (hash_pw(password), int(must_change), user_id))


def set_active(user_id: int, active: bool) -> None:
    if active and count(active_only=True) >= MAX_USERS:
        raise LimitError(f"Limite de {MAX_USERS} utilizadores ativos atingido (incluindo o administrador).")
    with connect() as conn:
        conn.execute("UPDATE users SET active=? WHERE id=?", (int(active), user_id))


def set_levels(user_id: int, levels: dict[str, str], only_accounts: list[str] | None = None) -> None:
    """Grava o nível por conta. only_accounts limita a alteração (ex.: só as contas de um grupo)."""
    scope = only_accounts if only_accounts is not None else list(accounts())
    with connect() as conn:
        for acc in scope:
            lvl = levels.get(acc, "nenhum")
            lvl = lvl if lvl in LEVELS else "nenhum"
            conn.execute("DELETE FROM user_accounts WHERE user_id=? AND account_id=?", (user_id, acc))
            if lvl != "nenhum":
                conn.execute("INSERT INTO user_accounts(user_id, account_id, can_create, can_approve, level) "
                             "VALUES (?,?,?,?,?)", (user_id, acc, int(_rank(lvl) >= 2), int(lvl == "aprovar"), lvl))


def set_perms(user_id: int, perms: dict[str, dict]) -> None:
    """Formato antigo ({conta: {"create": bool, "approve": bool}}) → níveis."""
    set_levels(user_id, {a: ("aprovar" if p.get("approve") else "criar" if p.get("create") else
                             "ver" if p.get("view") else "nenhum") for a, p in perms.items()})


def bootstrap_admin() -> None:
    """Uso local: na 1.ª vez cria o administrador 'david' com a DASHBOARD_PASSWORD, se definida."""
    if count() == 0 and os.environ.get("DASHBOARD_PASSWORD"):
        create("david", "David Carreto", os.environ["DASHBOARD_PASSWORD"], is_admin=True,
               email=os.environ.get("ADMIN_EMAIL", ""))
