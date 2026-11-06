#!/usr/bin/env bash
# Restauracion desde un backup full-*.tar.gz. DETIENE solo este servicio.
set -euo pipefail
BASE_DIR="/opt/hj-code-agent"
SERVICE="hj-code-agent"
[ "$(id -u)" -eq 0 ] || { echo "Ejecuta como root (sudo)."; exit 1; }
[ -f "$1" ] || { echo "Uso: restore.sh <backup.tar.gz>"; exit 1; }

echo "Deteniendo $SERVICE (solo este servicio)..."
systemctl stop "$SERVICE" || true
tar -xzf "$1" -C /
chown -R root:root "$BASE_DIR/data" 2>/dev/null || true
systemctl start "$SERVICE"
echo "Restaurado desde $1. Comprueba: journalctl -u $SERVICE -f"
