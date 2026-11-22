"""Escrever chaves no .env do servidor (valores nunca mostrados) e aplicá-las já ao processo atual."""
from __future__ import annotations

import os

from .config import ROOT


def set_env(updates: dict[str, str], root=None) -> None:
    env = (root or ROOT) / ".env"
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    for key, value in updates.items():
        os.environ[key] = value
        for i, line in enumerate(lines):
            if line.split("=", 1)[0].strip() == key and not line.startswith("#"):
                lines[i] = f"{key}={value}"
                break
        else:
            lines.append(f"{key}={value}")
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env.chmod(0o600)


def reload_env(root=None) -> None:
    """Relê o .env (ex.: o agendador apanha contas ligadas no dashboard sem reiniciar)."""
    env = (root or ROOT) / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if not k:
                continue
            if v:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)          # chave apagada (ex.: conta desligada)
