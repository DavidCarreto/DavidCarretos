#!/usr/bin/env bash
# Autoriza as chaves SSH PÚBLICAS de deploy/ssh_keys/*.pub a entrar no servidor.
# Corre-se À MÃO, como root: bash /opt/carretos/deploy/autorizar_ssh.sh
# Não é chamado por nenhum outro script (de propósito).
set -euo pipefail
[ "$(id -u)" = "0" ] || { echo "Corre como root."; exit 1; }
DIR=/opt/carretos/deploy/ssh_keys
shopt -s nullglob
keys=("$DIR"/*.pub)
[ ${#keys[@]} -gt 0 ] || { echo "Não há chaves em $DIR"; exit 1; }
for user in root carretos; do
  home=$(getent passwd "$user" | cut -d: -f6)
  install -d -m 700 -o "$user" -g "$user" "$home/.ssh"
  touch "$home/.ssh/authorized_keys"
  for k in "${keys[@]}"; do
    line=$(head -n1 "$k")
    case "$line" in ssh-ed25519\ *|ssh-rsa\ *|ecdsa-sha2-*) ;; *) echo "Ignorada (não é chave pública): $k"; continue;; esac
    grep -qxF "$line" "$home/.ssh/authorized_keys" || { echo "$line" >> "$home/.ssh/authorized_keys"; echo "✔ $(basename "$k") → $user"; }
  done
  chown "$user:$user" "$home/.ssh/authorized_keys" && chmod 600 "$home/.ssh/authorized_keys"
done
echo "Feito. Testa a partir do teu computador: ssh carretos@$(curl -4 -fsS https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')"
