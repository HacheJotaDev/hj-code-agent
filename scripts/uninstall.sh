#!/usr/bin/env bash
# Desinstalacion: SOLO toca la unidad hj-code-agent y /opt/hj-code-agent.
# Nunca detiene otros servicios de Docker ni del sistema.
set -euo pipefail
SERVICE="hj-code-agent"
BASE_DIR="/opt/hj-code-agent"
[ "$(id -u)" -eq 0 ] || { echo "Ejecuta como root (sudo)."; exit 1; }

echo "Esto detendra y deshabilitara el bot y (opcionalmente) borrara $BASE_DIR."
systemctl stop "$SERVICE" 2>/dev/null || true
systemctl disable "$SERVICE" 2>/dev/null || true
rm -f "/etc/systemd/system/${SERVICE}.service"
systemctl daemon-reload
echo "Servicio detenido y eliminado."
read -r -p "¿Borrar tambien $BASE_DIR (codigo, datos, workspaces)? [y/N] " ans
if [ "${ans:-n}" = "y" ]; then
  rm -rf "$BASE_DIR"
  echo "Directorios eliminados."
else
  echo "Datos conservados en $BASE_DIR."
fi
echo "Desinstalacion completada."
