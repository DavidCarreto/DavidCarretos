"""Fila de tarefas do dashboard: cada tarefa corre um comando `carretos` em segundo plano (uma de cada vez,
porque criar vídeos usa muito processador)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
from datetime import datetime

from ..db import connect, now

_lock = threading.Lock()
_started = False


def enqueue(kind: str, args: list[str], label: str = "", user_id: int | None = None) -> int:
    with connect() as conn:
        return conn.execute("INSERT INTO jobs(kind, args, label, created_at, created_by) VALUES (?,?,?,?,?)",
                            (kind, json.dumps(args, ensure_ascii=False), label or kind, now(), user_id)).lastrowid


def _run(job) -> None:
    args = json.loads(job["args"])
    with connect() as conn:
        conn.execute("UPDATE jobs SET status='running' WHERE id=?", (job["id"],))
    import os
    env = {**os.environ, "CARRETOS_USER_ID": str(job["created_by"] or "")}
    proc = subprocess.run([sys.executable, "-m", "carretos_social", job["kind"], *args],
                          capture_output=True, text=True, env=env)
    log = (proc.stdout + "\n" + "\n".join(l for l in proc.stderr.splitlines()
                                         if "warn" not in l.lower()))[-6000:]
    post = re.findall(r"[Pp]ublica[çc][ãa]o #(\d+)", proc.stdout)
    with connect() as conn:
        conn.execute("UPDATE jobs SET status=?, log=?, post_id=?, finished_at=? WHERE id=?",
                     ("done" if proc.returncode == 0 else "failed", log, int(post[-1]) if post else None,
                      datetime.now().isoformat(timespec="seconds"), job["id"]))


def _worker() -> None:
    while True:
        with connect() as conn:
            job = conn.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if job:
            try:
                _run(job)
            except Exception as exc:  # noqa: BLE001
                with connect() as conn:
                    conn.execute("UPDATE jobs SET status='failed', log=? WHERE id=?", (str(exc), job["id"]))
        else:
            time.sleep(2)


def start_worker() -> None:
    global _started
    with _lock:
        if not _started:
            with connect() as conn:  # tarefas interrompidas por um reinício voltam à fila
                conn.execute("UPDATE jobs SET status='queued' WHERE status='running'")
            threading.Thread(target=_worker, daemon=True).start()
            _started = True
