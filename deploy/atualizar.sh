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

# tudo dentro de main(): o bash lê o script todo antes de começar (o git pull muda este ficheiro a meio)
main() {
cd "$APP"
# pedido pelo dashboard: o próprio script escreve o registo (linha a linha), para a página o mostrar
if [ -n "${CARRETOS_UPDATE_LOG:-}" ]; then
  exec >>"$CARRETOS_UPDATE_LOG" 2>&1
fi
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
if ! .venv/bin/carretos backup antes-atualizar; then
  # alternativa sem depender do comando 'backup' (cópia segura do SQLite)
  mkdir -p data/backups
  .venv/bin/python -c "import sqlite3,sys; s=sqlite3.connect('data/carretos.db'); d=sqlite3.connect(sys.argv[1]); s.backup(d)" \
    "data/backups/carretos-$(date +%Y%m%d-%H%M%S)-antes-atualizar.db" && echo "Cópia feita (alternativa)." \
    || echo "(sem cópia de segurança)"
fi

echo "==> Músicas (descarrega só as que faltam)"
[ -f config/drive/musicas.csv ] && .venv/bin/carretos importar-drive musicas config/drive/musicas.csv || true

echo "==> Reiniciar serviços"
# o agendador PRIMEIRO: quando a atualização é pedida pelo dashboard, reiniciar o carretos-web termina também
# este script (e o systemctl), por isso o que vier depois dele pode não chegar a correr
sudo /usr/bin/systemctl restart carretos-agendador
echo "Agendador reiniciado."
if systemctl list-unit-files carretos-correio.service >/dev/null 2>&1 && systemctl cat carretos-correio >/dev/null 2>&1; then
  sudo /usr/bin/systemctl restart carretos-correio && echo "Recetor de email reiniciado." || true
fi
sudo /usr/bin/systemctl restart carretos-web
sleep 3

echo "==> Estado"
sudo /usr/bin/systemctl --no-pager status carretos-web carretos-agendador caddy || true
echo
if curl -fsS -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/login | grep -q 200; then
  echo "✔ Dashboard a responder em $(cat ENDERECO_DASHBOARD.txt 2>/dev/null || echo 'http://127.0.0.1:8000')"
else
  echo "✘ O dashboard não respondeu. Ver os erros: journalctl -u carretos-web -n 50 --no-pager"
fi
}
main "$@"
exit
