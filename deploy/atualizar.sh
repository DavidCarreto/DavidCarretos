#!/usr/bin/env bash
# Atualiza o Carretos Social no servidor: código, dependências e reinício dos serviços.
# Uso (por SSH como "carretos", ou na consola como root):
#   bash /opt/carretos/deploy/atualizar.sh
set -euo pipefail

APP=/opt/carretos
APP_USER=carretos
BRANCH="claude/social-media-management-system-goj30w"

# se for corrido como root, volta a correr-se como o utilizador da app
if [ "$(id -un)" != "$APP_USER" ]; then
  exec sudo -u "$APP_USER" -H bash "$APP/deploy/atualizar.sh" "$@"
fi

cd "$APP"
echo "==> Código (git pull)"
ANTES=$(git rev-parse --short HEAD)
if ! git diff --quiet || ! git diff --cached --quiet; then
  # alterações feitas à mão no servidor: ficam guardadas (git stash list) em vez de bloquear a atualização
  echo "Havia alterações locais em ficheiros do repositório; guardadas com git stash:"
  git --no-pager diff --stat
  git stash push --quiet -m "alteracoes-locais-$(date +%Y%m%d-%H%M%S)"
fi
git fetch --quiet origin "$BRANCH"
git checkout --quiet "$BRANCH"
git pull --ff-only --quiet origin "$BRANCH"
DEPOIS=$(git rev-parse --short HEAD)
if [ "$ANTES" = "$DEPOIS" ]; then
  echo "Já estava atualizado ($DEPOIS)."
else
  echo "Atualizado: $ANTES → $DEPOIS"
  git --no-pager log --oneline "$ANTES..$DEPOIS" | head -20
fi

echo "==> Dependências (pip install -e .)"
.venv/bin/pip install --quiet -U pip wheel
.venv/bin/pip install --quiet -e .

# depois do pip install: o comando 'backup' pode ser novo nesta atualização
echo "==> Cópia de segurança da base de dados (data/backups/, guarda as últimas 30)"
.venv/bin/carretos backup antes-atualizar || echo "(sem cópia: $?)"

echo "==> Músicas (descarrega só as que faltam)"
[ -f config/drive/musicas.csv ] && .venv/bin/carretos importar-drive musicas config/drive/musicas.csv || true

echo "==> Reiniciar serviços"
sudo /usr/bin/systemctl restart carretos-web carretos-agendador
sleep 3

echo "==> Estado"
sudo /usr/bin/systemctl --no-pager status carretos-web carretos-agendador caddy || true
echo
if curl -fsS -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/login | grep -q 200; then
  echo "✔ Dashboard a responder em $(cat ENDERECO_DASHBOARD.txt 2>/dev/null || echo 'http://127.0.0.1:8000')"
else
  echo "✘ O dashboard não respondeu. Ver os erros: journalctl -u carretos-web -n 50 --no-pager"
fi
