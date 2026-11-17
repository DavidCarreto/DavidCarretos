"""Manutenção a partir do dashboard (só administrador): atualizar o Carretos Studio, estado dos serviços e
aviso quando o servidor reinicia (com a causa provável). Assim não é preciso a consola da Hetzner."""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from ..config import DATA_DIR, ROOT

STARTED_AT = datetime.now()          # quando este processo do dashboard arrancou
LOG = "atualizacao.log"
STATE = "atualizacao.json"
SERVER = "servidor.json"


def _run(cmd: list[str], timeout: int = 10) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def git_rev() -> str:
    return _run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"]) or "?"


# ------------------------------------------------------------------ atualizar
def start_update(by: str) -> bool:
    """Corre deploy/atualizar.sh em segundo plano. Ao reiniciar o dashboard, o script é terminado com ele
    (systemd); o resultado (serviços, versão, cópia de segurança) é verificado depois pelo dashboard novo."""
    script = ROOT / "deploy" / "atualizar.sh"
    if not script.exists() or update_running():
        return False
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / STATE).write_text(json.dumps({"started": datetime.now().isoformat(timespec="seconds"),
                                              "by": by, "before": git_rev()}), encoding="utf-8")
    log = open(DATA_DIR / LOG, "w", encoding="utf-8")  # noqa: SIM115 (fica aberto pelo processo filho)
    subprocess.Popen(["bash", str(script)], stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT),
                     start_new_session=True)
    return True


def update_running() -> bool:
    st = update_state()
    if not st:
        return False
    started = datetime.fromisoformat(st["started"])
    if STARTED_AT > started:            # o dashboard já reiniciou depois de começar
        return False
    log = (DATA_DIR / LOG).read_text(encoding="utf-8", errors="replace") if (DATA_DIR / LOG).exists() else ""
    return "✔ Dashboard a responder" not in log and "✘" not in log and \
        (datetime.now() - started).total_seconds() < 900


def update_state() -> dict:
    p = DATA_DIR / STATE
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        return {}


def services() -> dict[str, str]:
    if not shutil.which("systemctl"):
        return {}
    out = {}
    for s in ("carretos-web", "carretos-agendador", "caddy"):
        out[s] = _run(["systemctl", "is-active", s]) or "desconhecido"
    return out


def last_backup() -> dict | None:
    files = sorted((DATA_DIR / "backups").glob("carretos-*.db")) if (DATA_DIR / "backups").exists() else []
    if not files:
        return None
    f = files[-1]
    return {"name": f.name, "size_kb": f.stat().st_size // 1024,
            "at": datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m %H:%M")}


def update_report() -> dict:
    st = update_state()
    log = (DATA_DIR / LOG).read_text(encoding="utf-8", errors="replace")[-12000:] if (DATA_DIR / LOG).exists() else ""
    started = datetime.fromisoformat(st["started"]) if st.get("started") else None
    restarted = bool(started and STARTED_AT > started)
    backup = last_backup()
    return {
        "state": st, "log": log, "running": update_running(), "restarted": restarted,
        "rev": git_rev(), "before": st.get("before"), "services": services(), "backup": backup,
        "backup_ok": bool(backup and started and "Cópia de segurança" in log and "sem cópia" not in log),
        "started_at": STARTED_AT.strftime("%d/%m %H:%M:%S"),
    }


# ------------------------------------------------------------------ reinícios do servidor
def boot_time() -> datetime | None:
    try:
        for line in Path("/proc/stat").read_text().splitlines():
            if line.startswith("btime "):
                return datetime.fromtimestamp(int(line.split()[1]))
    except OSError:
        pass
    return None


def _previous_boot_tail(lines: int = 60) -> str:
    """Últimas linhas do registo ANTES do reinício (o utilizador da app está no grupo systemd-journal)."""
    if not shutil.which("journalctl"):
        return ""
    return _run(["journalctl", "-b", "-1", "-n", str(lines), "--no-pager", "-o", "short-iso"], timeout=15)


def guess_cause(tail: str) -> str:
    t = tail.lower()
    if not t:
        return "sem registo do arranque anterior (não foi possível ler o journal)"
    if "unattended-upgrade" in t and ("reboot" in t or "rebooting" in t):
        return "atualizações automáticas do Ubuntu (unattended-upgrades) pediram o reinício"
    if "power key" in t or "power button" in t:
        return "botão de energia: reinício pela consola/painel da Hetzner (por alguém ou por manutenção)"
    if "system is rebooting" in t or "system is powering down" in t or "reached target" in t and "reboot" in t:
        return "reinício pedido no próprio sistema (comando reboot ou atualização)"
    if "shutting down" in t or "systemd-shutdown" in t:
        return "encerramento normal do sistema"
    return "o registo acaba sem encerramento normal: provável corte de energia/falha ou manutenção do " \
           "servidor físico na Hetzner (ver avisos no painel da Hetzner)"


def check_reboot() -> dict | None:
    """Se o servidor arrancou de novo desde a última vez que o dashboard viu, guarda e devolve o aviso."""
    bt = boot_time()
    if not bt:
        return None
    p = DATA_DIR / SERVER
    try:
        st = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        st = {}
    known = st.get("boot")
    if known and abs((datetime.fromisoformat(known) - bt).total_seconds()) > 60:
        tail = _previous_boot_tail()
        st["reboot"] = {"at": bt.isoformat(timespec="minutes"), "cause": guess_cause(tail), "tail": tail[-6000:],
                        "seen": False}
    st["boot"] = bt.isoformat(timespec="seconds")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    return st.get("reboot")


def reboot_notice() -> dict | None:
    p = DATA_DIR / SERVER
    try:
        st = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        return None
    r = st.get("reboot")
    return r if r and not r.get("seen") else None


def dismiss_reboot() -> None:
    p = DATA_DIR / SERVER
    try:
        st = json.loads(p.read_text(encoding="utf-8"))
        if st.get("reboot"):
            st["reboot"]["seen"] = True
            p.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    except (OSError, ValueError):
        pass
