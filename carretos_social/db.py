"""Base de dados SQLite: publicações (plano/agenda), media e métricas."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .config import DATA_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                 -- raw_video | video | image | cover
    path TEXT NOT NULL,
    source_id INTEGER,                  -- media original de onde foi gerado
    meta TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    pillar TEXT,
    format TEXT,                        -- reel | video | carousel | image | text_image
    title TEXT,
    hook TEXT,
    caption TEXT,
    script TEXT,
    hashtags TEXT DEFAULT '[]',
    media_ids TEXT DEFAULT '[]',
    cover_id INTEGER,
    scheduled_at TEXT,                  -- ISO, fuso horário da estratégia
    status TEXT NOT NULL DEFAULT 'idea',-- idea | draft | approved | published | failed | assist_sent
    remote_id TEXT,
    remote_url TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_posts_due ON posts(status, scheduled_at);

CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    remote_id TEXT NOT NULL,
    post_id INTEGER,
    published_at TEXT,
    format TEXT,
    pillar TEXT,
    caption TEXT,
    views INTEGER DEFAULT 0,
    reach INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    shares INTEGER DEFAULT 0,
    saves INTEGER DEFAULT 0,
    followers_at_time INTEGER,
    collected_at TEXT NOT NULL,
    UNIQUE(account_id, remote_id)
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                 -- comando carretos (create-video, montage, ...)
    args TEXT NOT NULL,                 -- JSON (lista de argumentos)
    label TEXT,
    status TEXT NOT NULL DEFAULT 'queued',  -- queued | running | done | failed
    log TEXT DEFAULT '',
    post_id INTEGER,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS chat (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,                 -- user | assistant
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    name TEXT,
    pw_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

-- permissões por conta, combináveis: criar e/ou aprovar
CREATE TABLE IF NOT EXISTS user_accounts (
    user_id INTEGER NOT NULL,
    account_id TEXT NOT NULL,
    can_create INTEGER NOT NULL DEFAULT 0,
    can_approve INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, account_id)
);

-- pedidos de reposição de palavra-passe (só se guarda o hash do código; uso único; expira)
CREATE TABLE IF NOT EXISTS password_resets (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS account_stats (
    account_id TEXT NOT NULL,
    day TEXT NOT NULL,
    followers INTEGER,
    impressions INTEGER,
    profile_views INTEGER,
    PRIMARY KEY (account_id, day)
);
"""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def db_path() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / "carretos.db"


MIGRATIONS = [  # colunas acrescentadas depois (ALTER TABLE é ignorado se já existirem)
    "ALTER TABLE posts ADD COLUMN created_by INTEGER",
    "ALTER TABLE posts ADD COLUMN approved_by INTEGER",
    "ALTER TABLE jobs ADD COLUMN created_by INTEGER",
    "ALTER TABLE chat ADD COLUMN user_id INTEGER",
    "ALTER TABLE users ADD COLUMN must_change INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE user_accounts ADD COLUMN level TEXT",
    "ALTER TABLE users ADD COLUMN email TEXT",
]


def _migrate(conn) -> None:
    tables = ("posts", "jobs", "chat", "users", "user_accounts")
    cols = {t: {r[1] for r in conn.execute(f"PRAGMA table_info({t})")} for t in tables}
    for sql in MIGRATIONS:
        table, col = sql.split()[2], sql.split()[5]
        if col not in cols[table]:
            conn.execute(sql)
    # permissões antigas (criar/aprovar) → nível por conta, sem perder nada
    conn.execute("UPDATE user_accounts SET level = CASE WHEN can_approve=1 THEN 'aprovar' "
                 "WHEN can_create=1 THEN 'criar' ELSE 'ver' END WHERE level IS NULL")


@contextmanager
def connect(path: Path | None = None):
    conn = sqlite3.connect(path or db_path())
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def add_media(conn, kind: str, path: str, source_id: int | None = None, meta: dict | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO media(kind, path, source_id, meta, created_at) VALUES (?,?,?,?,?)",
        (kind, str(path), source_id, json.dumps(meta or {}), now()),
    )
    return cur.lastrowid


def add_post(conn, **fields) -> int:
    for key in ("hashtags", "media_ids"):
        if key in fields and not isinstance(fields[key], str):
            fields[key] = json.dumps(fields[key], ensure_ascii=False)
    fields.setdefault("status", "idea")
    import os
    if os.environ.get("CARRETOS_USER_ID", "").isdigit():  # quem pediu (tarefas do dashboard)
        fields.setdefault("created_by", int(os.environ["CARRETOS_USER_ID"]))
    fields["created_at"] = fields["updated_at"] = now()
    cols = ",".join(fields)
    marks = ",".join("?" * len(fields))
    return conn.execute(f"INSERT INTO posts({cols}) VALUES ({marks})", list(fields.values())).lastrowid


def update_post(conn, post_id: int, **fields) -> None:
    for key in ("hashtags", "media_ids"):
        if key in fields and not isinstance(fields[key], str):
            fields[key] = json.dumps(fields[key], ensure_ascii=False)
    fields["updated_at"] = now()
    sets = ",".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE posts SET {sets} WHERE id=?", [*fields.values(), post_id])


def get_post(conn, post_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if not row:
        raise SystemExit(f"Publicação {post_id} não existe.")
    return row


def media_paths(conn, ids: list[int]) -> list[str]:
    if not ids:
        return []
    rows = {r["id"]: r["path"] for r in conn.execute(
        f"SELECT id, path FROM media WHERE id IN ({','.join('?' * len(ids))})", ids)}
    return [rows[i] for i in ids if i in rows]


def upsert_metric(conn, **m) -> None:
    m["collected_at"] = now()
    cols = ",".join(m)
    marks = ",".join("?" * len(m))
    updates = ",".join(f"{k}=excluded.{k}" for k in m if k not in ("account_id", "remote_id"))
    conn.execute(
        f"INSERT INTO metrics({cols}) VALUES ({marks}) "
        f"ON CONFLICT(account_id, remote_id) DO UPDATE SET {updates}",
        list(m.values()),
    )
