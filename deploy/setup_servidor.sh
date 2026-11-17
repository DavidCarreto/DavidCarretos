#!/usr/bin/env bash
# Instala (ou volta a instalar) o Carretos Social num servidor Ubuntu 24.04.
# É idempotente: pode correr-se mais de uma vez sem estragar nada.
#   - 1.ª vez: clona o repositório, cria o venv, o .env, os serviços e o Caddy (HTTPS).
#   - Vezes seguintes: atualiza o código (git pull), as dependências e reinicia os serviços.
# Uso (como root):  SETUP_CODE=meu-codigo bash setup_servidor.sh
#   (pela Hetzner: deploy/cloud-config.yaml faz isto ao criar o servidor)
# Para atualizações do dia a dia usar antes: deploy/atualizar.sh
set -euo pipefail

REPO_HTTPS="https://github.com/DavidCarreto/DavidCarretos.git"
REPO_SSH="git@github.com:DavidCarreto/DavidCarretos.git"
BRANCH="claude/social-media-management-system-goj30w"
APP=/opt/carretos
APP_USER=carretos
DOMINIO="${DOMINIO:-}"        # opcional: domínio próprio (o DNS tem de apontar para o IP do servidor)
SETUP_CODE="${SETUP_CODE:-}"  # código escolhido pelo David para a 1.ª configuração no dashboard

log() { echo -e "\n==> $*"; }
as_app() { sudo -u "$APP_USER" -H bash -c "$*"; }

log "Pacotes do sistema"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y git ffmpeg python3-venv python3-pip python3-dev build-essential \
                   fonts-inter fonts-dejavu-core fontconfig caddy curl

log "Desligar o Ctrl+Alt+Del (evita reinícios sem querer pela consola web da Hetzner)"
systemctl mask ctrl-alt-del.target >/dev/null 2>&1 || true

log "Utilizador da aplicação"
id "$APP_USER" &>/dev/null || useradd -m -s /bin/bash "$APP_USER"
usermod -aG systemd-journal "$APP_USER"   # pode ler os registos (journalctl) dos serviços

log "Código (clone na 1.ª vez, git pull nas seguintes)"
if [ -d "$APP/.git" ]; then
  chown -R "$APP_USER:$APP_USER" "$APP"
  as_app "cd $APP && { git diff --quiet && git diff --cached --quiet || git stash push --quiet -m alteracoes-locais-\$(date +%Y%m%d-%H%M%S); } && git fetch --quiet origin $BRANCH && git checkout --quiet $BRANCH && git pull --ff-only --quiet origin $BRANCH"
else
  mkdir -p "$APP" && chown "$APP_USER:$APP_USER" "$APP"
  if git ls-remote "$REPO_HTTPS" &>/dev/null; then
    as_app "git clone --quiet -b $BRANCH $REPO_HTTPS $APP"                 # repositório público
  else
    # repositório privado: chave só de leitura ("Deploy key") para este servidor
    as_app 'mkdir -p ~/.ssh && chmod 700 ~/.ssh && { [ -f ~/.ssh/id_ed25519 ] || ssh-keygen -q -t ed25519 -N "" -f ~/.ssh/id_ed25519 -C carretos-servidor; } && ssh-keyscan -q github.com >> ~/.ssh/known_hosts'
    if ! as_app "git clone --quiet -b $BRANCH $REPO_SSH $APP"; then
      echo "=================================================================="
      echo "Repositório privado. Adiciona esta chave em GitHub → DavidCarretos →"
      echo "Settings → Deploy keys → Add deploy key (só leitura) e volta a correr o script:"
      cat "/home/$APP_USER/.ssh/id_ed25519.pub"
      echo "=================================================================="
      exit 1
    fi
  fi
fi

log "Ambiente Python e dependências (pyproject.toml)"
as_app "cd $APP && { [ -x .venv/bin/python ] || python3 -m venv .venv; } && .venv/bin/pip install --quiet -U pip wheel && .venv/bin/pip install --quiet -e ."
# Nota: NÃO instalar 'chatterbox-tts' (extra voz-local) no servidor: falha a compilar 'pkuseg' e não é
# preciso, porque a voz é gerada pela ElevenLabs.

log "Configuração (.env)"
if [ ! -f "$APP/.env" ]; then
  cp "$APP/.env.example" "$APP/.env"
fi
if [ -n "$SETUP_CODE" ] && ! grep -q '^SETUP_CODE=' "$APP/.env"; then
  echo "SETUP_CODE=$SETUP_CODE" >> "$APP/.env"                  # nunca duplicado
fi
grep -q '^DASHBOARD_HTTPS=' "$APP/.env" || echo "DASHBOARD_HTTPS=1" >> "$APP/.env"
chown "$APP_USER:$APP_USER" "$APP/.env" && chmod 600 "$APP/.env"
mkdir -p "$APP/data" && chown -R "$APP_USER:$APP_USER" "$APP/data"

log "Serviços (systemd)"
cat > /etc/systemd/system/carretos-web.service <<UNIT
[Unit]
Description=Carretos Social - dashboard
After=network.target
[Service]
User=$APP_USER
WorkingDirectory=$APP
ExecStart=$APP/.venv/bin/carretos web --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/carretos-agendador.service <<UNIT
[Unit]
Description=Carretos Social - publicação automática, métricas e lembretes
After=network.target
[Service]
User=$APP_USER
WorkingDirectory=$APP
ExecStart=$APP/.venv/bin/carretos run
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT

# o utilizador da app pode reiniciar/ver os SEUS serviços sem palavra-passe (usado por deploy/atualizar.sh)
cat > /etc/sudoers.d/carretos <<SUDO
$APP_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart carretos-web carretos-agendador, /usr/bin/systemctl restart carretos-web, /usr/bin/systemctl restart carretos-agendador, /usr/bin/systemctl --no-pager status carretos-web carretos-agendador caddy
SUDO
chmod 440 /etc/sudoers.d/carretos
visudo -cf /etc/sudoers.d/carretos >/dev/null

log "HTTPS (Caddy)"
IP=$(curl -4 -fsS https://api.ipify.org || hostname -I | awk '{print $1}')
SSLIP="$(echo "$IP" | tr . -).sslip.io"                         # 2.29.177.117 → 2-29-177-117.sslip.io
# domínio próprio: o que vier em DOMINIO, ou o guardado por deploy/mudar_endereco.sh
[ -z "$DOMINIO" ] && [ -f "$APP/DOMINIO.txt" ] && DOMINIO=$(tr -d ' \n' < "$APP/DOMINIO.txt")
if [ -n "$DOMINIO" ]; then
  echo "$DOMINIO" > "$APP/DOMINIO.txt"
  SITES="$DOMINIO, $SSLIP"                                       # o endereço antigo continua a funcionar
  PRINCIPAL="$DOMINIO"
else
  SITES="$SSLIP"
  PRINCIPAL="$SSLIP"
fi
NOVO_CADDY=$(printf '%s {\n  reverse_proxy 127.0.0.1:8000\n}\n' "$SITES")
if [ "$(cat /etc/caddy/Caddyfile 2>/dev/null)" != "$NOVO_CADDY" ]; then
  echo "$NOVO_CADDY" > /etc/caddy/Caddyfile
  systemctl reload caddy || systemctl restart caddy
fi
echo "https://$PRINCIPAL" > "$APP/ENDERECO_DASHBOARD.txt"
DOMINIO="$PRINCIPAL"

log "Fotos e músicas do Drive (se houver CSV em config/drive/)"
for d in fotos musicas; do
  if [ -f "$APP/config/drive/$d.csv" ]; then
    as_app "$APP/.venv/bin/carretos importar-drive $d $APP/config/drive/$d.csv" || true
  fi
done

log "Arrancar"
systemctl daemon-reload
systemctl enable --quiet carretos-web carretos-agendador caddy
systemctl restart carretos-web carretos-agendador
sleep 3
systemctl --no-pager --lines=0 status carretos-web carretos-agendador caddy || true
echo
echo "Pronto. Dashboard: https://$DOMINIO"
echo "Atualizações futuras: sudo -u $APP_USER bash $APP/deploy/atualizar.sh"
