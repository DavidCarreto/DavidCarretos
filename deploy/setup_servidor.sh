#!/usr/bin/env bash
# Instala o Carretos Social num servidor Ubuntu 24.04 novo (ex.: Hetzner CPX31 / DigitalOcean 4 vCPU 8 GB).
# Uso (como root):  curl -fsSL <este ficheiro> | bash   — ou copiar e correr: bash setup_servidor.sh
# Depois: preencher /opt/carretos/.env e reiniciar:  systemctl restart carretos-web carretos-agendador
set -euo pipefail
REPO_HTTPS="https://github.com/DavidCarreto/DavidCarretos.git"
REPO_SSH="git@github.com:DavidCarreto/DavidCarretos.git"
BRANCH="claude/social-media-management-system-goj30w"
DOMINIO="${DOMINIO:-}"   # opcional: ex. redes.davidcarreto.pt (aponta o DNS para o IP do servidor)
SETUP_CODE="${SETUP_CODE:-}"  # código escolhido pelo David para a 1.ª configuração no dashboard

apt-get update -y
apt-get install -y git ffmpeg python3-venv python3-pip fonts-inter caddy

id carretos &>/dev/null || useradd -m -s /bin/bash carretos
if [ ! -d /opt/carretos ]; then
  if git ls-remote "$REPO_HTTPS" &>/dev/null; then
    git clone -b "$BRANCH" "$REPO_HTTPS" /opt/carretos            # repositório público
  else
    # repositório privado: chave de leitura ("Deploy key") só para este servidor
    sudo -u carretos bash -c 'mkdir -p ~/.ssh && [ -f ~/.ssh/id_ed25519 ] || ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519 -C carretos-servidor >/dev/null; ssh-keyscan github.com >> ~/.ssh/known_hosts 2>/dev/null'
    echo "=================================================================="
    echo "Repositório privado. Adiciona esta chave em GitHub → DavidCarretos →"
    echo "Settings → Deploy keys → Add deploy key (só leitura, sem 'Allow write'):"
    cat /home/carretos/.ssh/id_ed25519.pub
    echo "Depois volta a correr este script."
    echo "=================================================================="
    sudo -u carretos git clone -b "$BRANCH" "$REPO_SSH" /opt/carretos || exit 1
  fi
fi
chown -R carretos:carretos /opt/carretos
sudo -u carretos bash -c "cd /opt/carretos && python3 -m venv .venv && .venv/bin/pip install -q -U pip && .venv/bin/pip install -q -e . chatterbox-tts fastapi 'uvicorn[standard]' python-multipart jinja2"
[ -f /opt/carretos/.env ] || sudo -u carretos cp /opt/carretos/.env.example /opt/carretos/.env
if [ -n "$SETUP_CODE" ] && ! grep -q '^SETUP_CODE=' /opt/carretos/.env; then
  echo "SETUP_CODE=$SETUP_CODE" >> /opt/carretos/.env
fi
chmod 600 /opt/carretos/.env && chown carretos:carretos /opt/carretos/.env

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

# HTTPS automático: domínio próprio ou, sem domínio, <ip-com-traços>.sslip.io (certificado grátis)
if [ -z "$DOMINIO" ]; then
  IP=$(curl -fsS https://api.ipify.org || hostname -I | awk '{print $1}')
  DOMINIO="$(echo "$IP" | tr . -).sslip.io"
fi
printf '%s {\n  reverse_proxy 127.0.0.1:8000\n}\n' "$DOMINIO" > /etc/caddy/Caddyfile
echo "https://$DOMINIO" > /opt/carretos/ENDERECO_DASHBOARD.txt
systemctl daemon-reload
systemctl enable --now carretos-web carretos-agendador
systemctl restart caddy
# fotos e músicas a partir do Drive (se os CSV estiverem em config/drive/)
for d in fotos musicas; do
  [ -f /opt/carretos/config/drive/$d.csv ] && sudo -u carretos /opt/carretos/.venv/bin/carretos importar-drive $d /opt/carretos/config/drive/$d.csv || true
done
echo "Dashboard: https://$DOMINIO  (1.ª vez: página de configuração com o código escolhido)"
echo "Alternativa no terminal para guardar as chaves (pergunta uma a uma, sem as mostrar):"
echo "  cd /opt/carretos && sudo -u carretos .venv/bin/carretos configurar"
echo "  systemctl restart carretos-web carretos-agendador"
