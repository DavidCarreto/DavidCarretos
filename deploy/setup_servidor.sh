#!/usr/bin/env bash
# Instala o Carretos Social num servidor Ubuntu 24.04 novo (ex.: Hetzner CPX31 / DigitalOcean 4 vCPU 8 GB).
# Uso (como root):  curl -fsSL <este ficheiro> | bash   — ou copiar e correr: bash setup_servidor.sh
# Depois: preencher /opt/carretos/.env e reiniciar:  systemctl restart carretos-web carretos-agendador
set -euo pipefail
REPO="https://github.com/DavidCarreto/DavidCarretos.git"
BRANCH="claude/social-media-management-system-goj30w"
DOMINIO="${DOMINIO:-}"   # opcional: ex. redes.davidcarreto.pt (aponta o DNS para o IP do servidor)

apt-get update -y
apt-get install -y git ffmpeg python3-venv python3-pip fonts-inter caddy

id carretos &>/dev/null || useradd -m -s /bin/bash carretos
if [ ! -d /opt/carretos ]; then git clone -b "$BRANCH" "$REPO" /opt/carretos; fi
chown -R carretos:carretos /opt/carretos
sudo -u carretos bash -c "cd /opt/carretos && python3 -m venv .venv && .venv/bin/pip install -q -U pip && .venv/bin/pip install -q -e . chatterbox-tts fastapi 'uvicorn[standard]' python-multipart jinja2"
[ -f /opt/carretos/.env ] || sudo -u carretos cp /opt/carretos/.env.example /opt/carretos/.env

cat > /etc/systemd/system/carretos-web.service <<UNIT
[Unit]
Description=Carretos Social - dashboard
After=network.target
[Service]
User=carretos
WorkingDirectory=/opt/carretos
ExecStart=/opt/carretos/.venv/bin/carretos web --host 127.0.0.1 --port 8000
Restart=always
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/carretos-agendador.service <<UNIT
[Unit]
Description=Carretos Social - publicação automática, métricas e lembretes
After=network.target
[Service]
User=carretos
WorkingDirectory=/opt/carretos
ExecStart=/opt/carretos/.venv/bin/carretos run
Restart=always
[Install]
WantedBy=multi-user.target
UNIT

# HTTPS automático (com domínio) ou acesso pelo IP
if [ -n "$DOMINIO" ]; then
  printf '%s {\n  reverse_proxy 127.0.0.1:8000\n}\n' "$DOMINIO" > /etc/caddy/Caddyfile
else
  printf ':80 {\n  reverse_proxy 127.0.0.1:8000\n}\n' > /etc/caddy/Caddyfile
fi
systemctl daemon-reload
systemctl enable --now carretos-web carretos-agendador
systemctl restart caddy
echo "Pronto. Falta: editar /opt/carretos/.env (DASHBOARD_PASSWORD, SOCIAL_ANTHROPIC_API_KEY, ...) e"
echo "  systemctl restart carretos-web carretos-agendador"
