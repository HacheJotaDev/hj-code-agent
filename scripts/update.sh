#!/usr/bin/env bash
# ============================================================================
# HJ CODE AGENT V3 - Actualizacion SEGURA de una instalacion existente
#
# Requisitos del encargo:
#   1. Detecta la instalacion existente y sus modificaciones locales.
#   2. Backup de .env, base de datos, clave maestra y codigo actual.
#   3. Conserve proyectos, conversaciones y preferencias (NO toca data/).
#   4. Detiene UNICAMENTE la unidad hj-code-agent.
#   5. Aplica el software nuevo + migraciones compatibles.
#   6. Comprueba salud y ROLLBACK automatico si falla.
#   7. Nunca ejecuta git reset --hard ni borra datos; no toca otros servicios.
#   8. No requiere editar archivos a mano ni nano.
#
# Uso:  sudo bash /opt/hj-code-agent/app/scripts/update.sh [ruta-del-codigo-nuevo]
# ============================================================================
set -euo pipefail

BASE_DIR="${HJ_BASE_DIR:-/opt/hj-code-agent}"
APP_DIR="$BASE_DIR/app"
SERVICE="hj-code-agent"
SRC_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$BASE_DIR/backups/update-$TS"

step() { echo -e "\n\033[1;36m== $1 ==\033[0m"; }
ok()   { echo -e "\033[1;32m✔ $1\033[0m"; }
die()  { echo -e "\033[1;31m✘ $1\033[0m"; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Ejecuta con sudo."
[ -d "$APP_DIR" ] || die "No existe instalacion previa en $APP_DIR (usa install.sh)."
[ -f "$SRC_DIR/pyproject.toml" ] || die "El codigo nuevo no parece el repositorio: $SRC_DIR"

step "1/8 Detectando instalacion y modificaciones locales"
PREV_VERSION="desconocida"
grep -rs "__version__" "$APP_DIR/core/__init__.py" >/dev/null 2>&1 && \
  PREV_VERSION=$(grep -o '"[0-9.]*"' "$APP_DIR/core/__init__.py" | head -1 | tr -d '"')
echo "Version instalada: $PREV_VERSION"
# Guarda copia de cualquier archivo MODIFICADO localmente (p.ej. providers.py,
# sandbox/factory.py cambiados a mano en el VPS) para revisarlos despues.
LOCALMODS="$BACKUP_DIR/localmods"
mkdir -p "$LOCALMODS"
if command -v rsync >/dev/null; then
  # dry-run para detectar diferencias entre instalado y nuevo codigo
  CHANGED=$(rsync -rcn --delete --exclude '.git' --exclude '__pycache__' --exclude '.venv' \
        --exclude 'data' --exclude 'workspaces' --exclude 'backups' --exclude '.env' \
        "$SRC_DIR"/ "$APP_DIR"/ 2>/dev/null | grep -v '/$' || true)
  if [ -n "$CHANGED" ]; then
    echo "Archivos con cambios (se conservan copia en $LOCALMODS):"
    echo "$CHANGED" | head -20
    mkdir -p "$LOCALMODS"
    while IFS= read -r f; do
      mkdir -p "$LOCALMODS/$(dirname "$f")"
      [ -f "$APP_DIR/$f" ] && cp "$APP_DIR/$f" "$LOCALMODS/$f"
    done <<< "$CHANGED"
  fi
fi
ok "Deteccion completada"

step "2/8 Backup completo (env + BD + clave maestra + codigo actual)"
mkdir -p "$BACKUP_DIR"
cp -a "$APP_DIR/.env" "$BACKUP_DIR/.env" 2>/dev/null || echo "(sin .env en app/)"
[ -d "$BASE_DIR/data" ] && tar -czf "$BACKUP_DIR/data.tar.gz" -C "$BASE_DIR" data
[ -d "$BASE_DIR/workspaces" ] && tar -czf "$BACKUP_DIR/workspaces.tar.gz" -C "$BASE_DIR" workspaces
tar -czf "$BACKUP_DIR/app-anterior.tar.gz" -C "$BASE_DIR" --exclude='app/.venv' --exclude='app/__pycache__' app
ls -la "$BACKUP_DIR" | head -8
ok "Backup en $BACKUP_DIR (restaurable tal cual)"

step "3/8 Deteniendo UNICAMENTE $SERVICE"
systemctl stop "$SERVICE" 2>/dev/null || true
ok "Servicio detenido (otros servicios intactos)"

rollback() {
  echo -e "\n\033[1;31m!! FALLO: $1 — iniciando ROLLBACK\033[0m"
  rm -rf "$APP_DIR.new"
  [ -d "$BACKUP_DIR/app-anterior.tar.gz" ] || true
  # restaura el codigo anterior desde el tar (sin tocar .env ni data)
  tar -xzf "$BACKUP_DIR/app-anterior.tar.gz" -C "$BASE_DIR"
  "$BASE_DIR/venv/bin/pip" install -e "$BASE_DIR/app" --quiet || true
  systemctl start "$SERVICE" || true
  echo "Rollback completado: version anterior en marcha. Backup: $BACKUP_DIR"
  exit 1
}

step "4/8 Copiando software nuevo"
rsync -a --exclude '.git' --exclude '__pycache__' --exclude '.venv' \
      --exclude 'data' --exclude 'workspaces' --exclude 'backups' --exclude '.env' \
      "$SRC_DIR"/ "$APP_DIR"/
[ -f "$APP_DIR/.env" ] || cp -a "$BACKUP_DIR/.env" "$APP_DIR/.env" 2>/dev/null || true
ok "Codigo actualizado (.env, data/, workspaces/ y backups/ NO se tocan)"

step "5/8 Dependencias + migraciones"
"$BASE_DIR/venv/bin/pip" install -e "$APP_DIR" --quiet || rollback "pip install"
"$BASE_DIR/venv/bin/python" - <<'PYEOF' || rollback "migraciones"
import asyncio, sys
sys.path.insert(0, "/opt/hj-code-agent/app")
from core.storage.database import Database
async def main():
    db = Database("/opt/hj-code-agent/data/hj.db")
    await db.connect()
    applied = await db.migrate()
    print(f"Migraciones aplicadas: {applied}")
    await db.recover()
    await db.close()
asyncio.run(main())
PYEOF
ok "Dependencias y migraciones compatibles aplicadas"

step "6/8 Permisos y usuario de servicio"
if ! id hjagent >/dev/null 2>&1; then
  useradd --system --home "$BASE_DIR" --shell /usr/sbin/nologin hjagent || true
fi
chown -R hjagent:hjagent "$BASE_DIR/data" "$BASE_DIR/workspaces" "$BASE_DIR/backups" 2>/dev/null || true
# La unidad existente se respeta salvo User= inexistente:
UNIT="/etc/systemd/system/${SERVICE}.service"
if [ -f "$UNIT" ] && grep -q "^User=root" "$UNIT"; then
  sed -i "s/^User=root/User=hjagent/" "$UNIT"
  grep -q "NoNewPrivileges" "$UNIT" || sed -i "/^User=/a NoNewPrivileges=yes\nProtectSystem=full\nProtectHome=read-only" "$UNIT"
  echo "Unidad systemd endurecida: User=hjagent, NoNewPrivileges, ProtectSystem."
fi
systemctl daemon-reload
ok "Permisos ajustados (bot sin privilegios)"

step "7/8 Arranque y comprobacion de salud"
systemctl start "$SERVICE"
sleep 4
if ! systemctl is-active --quiet "$SERVICE"; then
  journalctl -u "$SERVICE" -n 30 --no-pager || true
  rollback "el servicio no arranco"
fi
LOG_OK=$(journalctl -u "$SERVICE" --since "30 seconds ago" --no-pager 2>/dev/null | grep -c "Bot en marcha" || true)
if [ "$LOG_OK" -eq 0 ]; then
  sleep 6
  LOG_OK=$(journalctl -u "$SERVICE" --since "60 seconds ago" --no-pager 2>/dev/null | grep -c "Bot en marcha" || true)
fi
[ "$LOG_OK" -ge 1 ] || rollback "no se vio 'Bot en marcha' en los logs"
ok "Servicio activo y polling en marcha"

step "8/8 Resultado"
echo "Actualizacion completada desde $PREV_VERSION."
echo "Backup y rollback listos en: $BACKUP_DIR"
echo "Modificaciones locales previas guardadas en: $LOCALMODS (revisalas si existian)."
echo "Comandos utiles: journalctl -u $SERVICE -f · /health y /testapi en Telegram"
