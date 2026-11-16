"""Utilizadores, palavras-passe e permissões por conta (criar e/ou aprovar; administrador = tudo)."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass, field

from ..config import accounts
from ..db import connect, now


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


@dataclass
class User:
    id: int
    username: str
    name: str
    is_admin: bool
    perms: dict = field(default_factory=dict)   # account_id -> {"create": bool, "approve": bool}

    def can_create(self, account_id: str) -> bool:
        return self.is_admin or self.perms.get(account_id, {}).get("create", False)

    def can_approve(self, account_id: str) -> bool:
        return self.is_admin or self.perms.get(account_id, {}).get("approve", False)

    def can_see(self, account_id: str) -> bool:
        return self.can_create(account_id) or self.can_approve(account_id)

    @property
    def visible_accounts(self) -> list[str]:
        return [a for a in accounts() if self.can_see(a)]

    @property
    def creatable_accounts(self) -> list[str]:
        return [a for a in accounts() if self.can_create(a)]


def load(user_id: int) -> User | None:
    with connect() as conn:
        r = conn.execute("SELECT * FROM users WHERE id=? AND active=1", (user_id,)).fetchone()
        if not r:
            return None
        perms = {p["account_id"]: {"create": bool(p["can_create"]), "approve": bool(p["can_approve"])}
                 for p in conn.execute("SELECT * FROM user_accounts WHERE user_id=?", (user_id,))}
    return User(r["id"], r["username"], r["name"] or r["username"], bool(r["is_admin"]), perms)


def authenticate(username: str, password: str) -> User | None:
    with connect() as conn:
        r = conn.execute("SELECT * FROM users WHERE username=? AND active=1",
                         (username.strip().lower(),)).fetchone()
    if r and check_pw(password, r["pw_hash"]):
        return load(r["id"])
    return None


def count() -> int:
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def create(username: str, name: str, password: str, is_admin: bool = False) -> int:
    with connect() as conn:
        return conn.execute("INSERT INTO users(username, name, pw_hash, is_admin, created_at) VALUES (?,?,?,?,?)",
                            (username.strip().lower(), name, hash_pw(password), int(is_admin), now())).lastrowid


def set_password(user_id: int, password: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE users SET pw_hash=? WHERE id=?", (hash_pw(password), user_id))


def set_perms(user_id: int, perms: dict[str, dict]) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM user_accounts WHERE user_id=?", (user_id,))
        for acc, p in perms.items():
            if p.get("create") or p.get("approve"):
                conn.execute("INSERT INTO user_accounts VALUES (?,?,?,?)",
                             (user_id, acc, int(bool(p.get("create"))), int(bool(p.get("approve")))))


def bootstrap_admin() -> None:
    """Na 1.ª vez cria o administrador 'david' com a DASHBOARD_PASSWORD (compatibilidade)."""
    if count() == 0 and os.environ.get("DASHBOARD_PASSWORD"):
        create("david", "David Carreto", os.environ["DASHBOARD_PASSWORD"], is_admin=True)
