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

-- histórico de alterações às publicações (para saber quem mudou o quê e poder repor)
CREATE TABLE IF NOT EXISTS post_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL,
    at TEXT NOT NULL,
    user_id INTEGER,
    field TEXT NOT NULL,
    old TEXT,
    new TEXT,
    note TEXT
);
CREATE INDEX IF NOT EXISTS idx_post_history ON post_history(post_id, id);

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
    "ALTER TABLE post_history ADD COLUMN note TEXT",
]


def _migrate(conn) -> None:
    """Só ACRESCENTA colunas (nunca apaga nem altera media/estados). Antes de mudar, faz uma cópia da base."""
    tables = ("posts", "jobs", "chat", "users", "user_accounts", "post_history")
    cols = {t: {r[1] for r in conn.execute(f"PRAGMA table_info({t})")} for t in tables}
    pending = [sql for sql in MIGRATIONS if sql.split()[5] not in cols[sql.split()[2]]]
    if pending:
        _snapshot(conn, "antes-migracao")
    before = conn.execute("SELECT COUNT(*), COALESCE(GROUP_CONCAT(id || ':' || status || ':' || media_ids), '') "
                          "FROM posts").fetchone()
    for sql in pending:
        assert sql.startswith("ALTER TABLE") and " ADD COLUMN " in sql, "migrações só podem acrescentar colunas"
        conn.execute(sql)
    after = conn.execute("SELECT COUNT(*), COALESCE(GROUP_CONCAT(id || ':' || status || ':' || media_ids), '') "
                         "FROM posts").fetchone()
    if tuple(before) != tuple(after):
        conn.rollback()
        raise RuntimeError("migração alteraria publicações: cancelada")
    # permissões antigas (criar/aprovar) → nível por conta, sem perder nada
    conn.execute("UPDATE user_accounts SET level = CASE WHEN can_approve=1 THEN 'aprovar' "
                 "WHEN can_create=1 THEN 'criar' ELSE 'ver' END WHERE level IS NULL")


def _snapshot(conn, reason: str) -> None:
    """Cópia de segurança a partir da ligação aberta (só se houver dados)."""
    try:
        if not conn.execute("SELECT 1 FROM posts LIMIT 1").fetchone():
            return
        dest_dir = DATA_DIR / "backups"
        dest_dir.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(dest_dir / f"carretos-{datetime.now():%Y%m%d-%H%M%S}-{reason}.db") as dest:
            conn.backup(dest)
    except sqlite3.Error:
        pass


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


TRACKED = ("status", "media_ids", "cover_id", "format", "scheduled_at", "caption")


class MediaLossError(ValueError):
    """Tentativa de deixar sem imagem/vídeo uma publicação que já os tem."""


def update_post(conn, post_id: int, _by: int | None = None, _allow_clear_media: bool = False,
                _note: str | None = None, **fields) -> None:
    """Atualiza uma publicação e regista no histórico o que mudou (estado, media, tipo, data, legenda).

    Nunca deixa sem media uma publicação que já tem imagem/vídeo, a não ser com _allow_clear_media=True.
    """
    import os
    for key in ("hashtags", "media_ids"):
        if key in fields and not isinstance(fields[key], str):
            fields[key] = json.dumps(fields[key], ensure_ascii=False)
    old = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if old is not None:
        if (fields.get("media_ids") in ("[]", "", None) and "media_ids" in fields
                and json.loads(old["media_ids"] or "[]") and not _allow_clear_media):
            raise MediaLossError(f"publicação #{post_id}: não se apaga a imagem/vídeo de uma publicação")
        if _by is None and os.environ.get("CARRETOS_USER_ID", "").isdigit():
            _by = int(os.environ["CARRETOS_USER_ID"])
        for key in TRACKED:
            if key in fields and str(fields[key] if fields[key] is not None else "") != \
                    str(old[key] if old[key] is not None else ""):
                conn.execute("INSERT INTO post_history(post_id, at, user_id, field, old, new, note) "
                             "VALUES (?,?,?,?,?,?,?)", (post_id, now(), _by, key, old[key], fields[key],
                                                        _note if key == "media_ids" else None))
    fields["updated_at"] = now()
    sets = ",".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE posts SET {sets} WHERE id=?", [*fields.values(), post_id])


def post_history(conn, post_id: int, limit: int = 30) -> list[sqlite3.Row]:
    return conn.execute("SELECT h.*, u.name AS user_name FROM post_history h LEFT JOIN users u ON u.id = h.user_id "
                        "WHERE post_id=? ORDER BY h.id DESC LIMIT ?", (post_id, limit)).fetchall()


def backup(reason: str = "manual", keep: int = 30) -> Path | None:
    """Cópia da base de dados (sqlite backup, segura com os serviços a correr); guarda as últimas `keep`."""
    src = db_path()
    if not src.exists():
        return None
    dest_dir = DATA_DIR / "backups"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"carretos-{datetime.now():%Y%m%d-%H%M%S}-{reason}.db"
    with sqlite3.connect(src) as a, sqlite3.connect(dest) as b:
        a.backup(b)
    for old in sorted(dest_dir.glob("carretos-*.db"))[:-keep]:
        old.unlink()
    return dest


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
