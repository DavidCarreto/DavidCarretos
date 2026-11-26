#!/usr/bin/env bash
# Ativa o recetor de email do Carretos Studio (porta 25), só para os avisos de mensagens do LinkedIn.
# Corre-se UMA vez, como root (consola da Hetzner):   bash /opt/carretos/deploy/ativar_correio.sh
# Cria o serviço carretos-correio (utilizador "carretos", com permissão só para usar a porta 25) e deixa o
# dashboard reiniciá-lo nas atualizações. Não instala nada da internet.
set -euo pipefail
APP=/opt/carretos
APP_USER=carretos
[ "$(id -u)" = 0 ] || { echo "Correr como root."; exit 1; }

cat > /etc/systemd/system/carretos-correio.service <<UNIT
[Unit]
Description=Carretos Studio - recetor de email (avisos de mensagens do LinkedIn)
After=network.target
[Service]
User=$APP_USER
WorkingDirectory=$APP
ExecStart=$APP/.venv/bin/carretos correio
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=yes
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT

# o dashboard pode reiniciar este serviço nas atualizações (acrescenta só esta linha)
SUDO=/etc/sudoers.d/carretos-correio
echo "$APP_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart carretos-correio" > "$SUDO"
chmod 440 "$SUDO"
visudo -cf "$SUDO" >/dev/null

# firewall: só se o ufw estiver ativo (por omissão não está)
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then ufw allow 25/tcp; fi

systemctl daemon-reload
systemctl enable --now carretos-correio
sleep 2
systemctl --no-pager --lines=5 status carretos-correio || true
echo
echo "✔ Recetor de email ativo na porta 25. No dashboard: Mensagens mostra o endereço para a regra do Hotmail."
