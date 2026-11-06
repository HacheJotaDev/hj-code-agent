#!/usr/bin/env bash
# Actualizacion in-place del codigo. No toca .env, datos ni otros servicios.
set -euo pipefail
BASE_DIR="/opt/hj-code-agent"
SERVICE="hj-code-agent"
REPO_SRC="$(cd "$(dirname "$0")/.." && pwd)"
[ "$(id -u)" -eq 0 ] || { echo "Ejecuta como root (sudo)."; exit 1; }

echo "== Copiando codigo nuevo =="
rsync -a --delete --exclude '.git' --exclude '__pycache__' --exclude '.venv' \
      --exclude '.env' --exclude 'data' --exclude 'workspaces' --exclude 'backups' \
      "$REPO_SRC"/ "$BASE_DIR/app"/
echo "== Actualizando dependencias =="
"$BASE_DIR/venv/bin/pip" install -e "$BASE_DIR/app" --quiet
echo "== Reiniciando SOLO el servicio $SERVICE =="
systemctl restart "$SERVICE"
systemctl --no-pager status "$SERVICE" | head -5
echo "Hecho. Las migraciones de BD se aplican solas al arrancar."
