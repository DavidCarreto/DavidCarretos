#!/usr/bin/env bash
# Muda o endereço do dashboard para um domínio próprio (ex.: studio.carretos.pt), mantendo o antigo.
# Uso (como root):  bash /opt/carretos/deploy/mudar_endereco.sh studio.carretos.pt
# Antes: no DNS do domínio, criar um registo A com o nome (ex.: "studio") a apontar para o IP do servidor.
set -euo pipefail
APP=/opt/carretos
NOVO="${1:-}"
[ "$(id -u)" = "0" ] || { echo "Corre como root."; exit 1; }
[[ "$NOVO" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$ ]] || { echo "Indica o endereço, ex.: studio.carretos.pt"; exit 1; }

IP=$(curl -4 -fsS https://api.ipify.org || hostname -I | awk '{print $1}')
DNS=$(getent ahostsv4 "$NOVO" | awk 'NR==1{print $1}' || true)
if [ "$DNS" != "$IP" ]; then
  echo "✘ $NOVO ainda não aponta para este servidor ($IP); o DNS responde: ${DNS:-nada}."
  echo "  Cria/corrige o registo A no DNS e espera uns minutos (pode demorar algumas horas). Nada foi alterado."
  exit 1
fi
echo "$NOVO" > "$APP/DOMINIO.txt"
SSLIP="$(echo "$IP" | tr . -).sslip.io"
printf '%s, %s {\n  reverse_proxy 127.0.0.1:8000\n}\n' "$NOVO" "$SSLIP" > /etc/caddy/Caddyfile
systemctl reload caddy || systemctl restart caddy
echo "https://$NOVO" > "$APP/ENDERECO_DASHBOARD.txt"
chown carretos:carretos "$APP/DOMINIO.txt" "$APP/ENDERECO_DASHBOARD.txt"
systemctl restart carretos-web
sleep 8
if curl -fsS -o /dev/null "https://$NOVO/login"; then
  echo "✔ Dashboard disponível em https://$NOVO (o endereço https://$SSLIP continua a funcionar)."
else
  echo "… O certificado HTTPS pode demorar 1-2 minutos. Abre https://$NOVO daqui a pouco."
fi
