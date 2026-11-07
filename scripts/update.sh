#!/usr/bin/env bash
# ============================================================================
# HJ CODE AGENT V3 - Actualizacion SEGURA de una instalacion existente
#
# Requisitos del encargo (corregidos tras revision con VPS real):
#   1. Detecta la instalacion, sus modificaciones locales y el USUARIO
#      EFECTIVO del servicio systemd (p. ej. "hjcode"). NO inventa usuarios,
#      NO crea "hjagent", NO cambia propietarios salvo divergencia real.
#   2. Backup COHERENTE: detiene PRIMERO el servicio y hace checkpoint WAL de
#      SQLite antes de tar (evita copias con transacciones a medias).
#   3. Conserva .env, base de datos, clave maestra, vault y proyectos.
#   4. Detiene UNICAMENTE la unidad hj-code-agent (otros servicios intactos).
#   5. Software nuevo + migraciones compatibles.
#   6. Salud y ROLLBACK COMPLETO: codigo, dependencias, DATOS y permisos.
#   7. Nunca git reset --hard; no toca otros servicios ni configs ajenas.
#   8. No requiere nano ni ediciones a mano.
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
PY="$BASE_DIR/venv/bin/python"
DB_PATH="$BASE_DIR/data/hj.db"

step() { echo -e "\n\033[1;36m== $1 ==\033[0m"; }
ok()   { echo -e "\033[1;32m✔ $1\033[0m"; }
die()  { echo -e "\033[1;31m✘ $1\033[0m"; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Ejecuta con sudo."
[ -d "$APP_DIR" ] || die "No existe instalacion previa en $APP_DIR (usa install.sh)."
[ -f "$SRC_DIR/pyproject.toml" ] || die "El codigo nuevo no parece el repositorio: $SRC_DIR"
command -v rsync >/dev/null || die "Necesitas rsync (apt install rsync)."

# ----------------------------------------------------------------------------
step "1/8 Instalacion, usuario efectivo del servicio y modificaciones locales"
# ----------------------------------------------------------------------------
PREV_VERSION="desconocida"
grep -rs "__version__" "$APP_DIR/core/__init__.py" >/dev/null 2>&1 && \
  PREV_VERSION=$(grep -o '"[0-9.]*"' "$APP_DIR/core/__init__.py" | head -1 | tr -d '"')
echo "Version instalada: $PREV_VERSION"

# USUARIO EFECTIVO del servicio tal y como lo ve systemd (respeta User= de la
# unidad y sus drop-ins). Bug corregido: antes se forzaba "hjagent" y podia
# dejar a SQLite/boveda/proyectos sin duenio cuando el servicio corre como
# otro usuario (p. ej. "hjcode").
SERVICE_USER="$(systemctl show "$SERVICE" -p User --value 2>/dev/null | tr -d '[:space:]')"
if [ -z "$SERVICE_USER" ] || [ "$SERVICE_USER" = "root" ]; then
  # Sin User= no-root en la unidad: usa el propietario ACTUAL de data/ si es
  # un usuario real (no root) y no toques nada mas.
  OWNER_DATA_USER="$(stat -c '%U' "$BASE_DIR/data" 2>/dev/null || echo "")"
  if [ -n "$OWNER_DATA_USER" ] && [ "$OWNER_DATA_USER" != "root" ]; then
    SERVICE_USER="$OWNER_DATA_USER"
  else
    SERVICE_USER=""
  fi
fi
if [ -n "$SERVICE_USER" ] && id "$SERVICE_USER" >/dev/null 2>&1; then
  echo "El servicio ejecuta como usuario: $SERVICE_USER (se conserva tal cual)"
  if [ -f "/etc/systemd/system/${SERVICE}.service" ] && \
     grep -Eq "^User=root" "/etc/systemd/system/${SERVICE}.service"; then
    echo "AVISO: la unidad corre como root. No se modifica nada automaticamente;"
    echo "       revisa la unidad manualmente si quieres ejecutar como $SERVICE_USER."
  fi
else
  SERVICE_USER=""
  echo "AVISO: no se detecto usuario de servicio no-root; NO se alteraran permisos."
fi

# Propietarios REALES de los directorios de datos (para rollback exacto).
OWNER_DATA="$(stat -c '%u:%g' "$BASE_DIR/data" 2>/dev/null || echo "")"
OWNER_WS="$(stat -c '%u:%g' "$BASE_DIR/workspaces" 2>/dev/null || echo "")"
OWNER_BK="$(stat -c '%u:%g' "$BASE_DIR/backups" 2>/dev/null || echo "")"
echo "Propietarios actuales: data=$OWNER_DATA workspaces=$OWNER_WS backups=$OWNER_BK"

# Copia de los archivos MODIFICADOS localmente (p. ej. providers.py,
# sandbox/factory.py cambiados a mano) para poder revisarlos despues.
LOCALMODS="$BACKUP_DIR/localmods"
mkdir -p "$LOCALMODS"
CHANGED=$(rsync -rcn --delete --exclude '.git' --exclude '__pycache__' --exclude '.venv' \
      --exclude 'data' --exclude 'workspaces' --exclude 'backups' --exclude '.env' \
      "$SRC_DIR"/ "$APP_DIR"/ 2>/dev/null | grep -v '/$' | grep -v '^\*deleting' || true)
if [ -n "$CHANGED" ]; then
  echo "Archivos con cambios (copia previa en $LOCALMODS):"
  echo "$CHANGED" | head -20
  while IFS= read -r f; do
    mkdir -p "$LOCALMODS/$(dirname "$f")"
    [ -f "$APP_DIR/$f" ] && cp "$APP_DIR/$f" "$LOCALMODS/$f"
  done <<< "$CHANGED"
fi
ok "Deteccion completada (usuario: ${SERVICE_USER:-sin usuario no-root})"

# ----------------------------------------------------------------------------
step "2/8 Deteniendo UNICAMENTE $SERVICE (antes del backup)"
# ----------------------------------------------------------------------------
# El backup de SQLite se hace con el servicio PARADO: sin escritores
# concurrentes + checkpoint WAL = copia coherente garantizada.
systemctl stop "$SERVICE" 2>/dev/null || true
ok "Servicio detenido (otros servicios intactos)"

# Rollback COMPLETO: codigo anterior, dependencias, DATOS, .env y permisos.
rollback() {
  echo -e "\n\033[1;31m!! FALLO: $1 — iniciando ROLLBACK COMPLETO\033[0m"
  # 1) codigo anterior (rm + untar: deja la instalacion EXACTAMENTE como estaba;
  #    .env se restaura desde el backup porque vive dentro de app/)
  if [ -f "$BACKUP_DIR/app-anterior.tar.gz" ]; then
    rm -rf "$APP_DIR"
    tar -xzf "$BACKUP_DIR/app-anterior.tar.gz" -C "$BASE_DIR"
    [ -f "$BACKUP_DIR/.env" ] && cp -a "$BACKUP_DIR/.env" "$APP_DIR/.env"
    "$PY" -m pip install -e "$BASE_DIR/app" --quiet || true
  else
    echo "  (sin backup de codigo: no se habia modificado nada todavia)"
  fi
  # 2) datos anteriores solo si las migraciones llegaron a escribir
  if [ "${MIGRATED:-0}" = "1" ] && [ -f "$BACKUP_DIR/data.tar.gz" ]; then
    tar -xzf "$BACKUP_DIR/data.tar.gz" -C "$BASE_DIR"
    echo "  data/ restaurada desde backup (migraciones revertidas)"
  fi
  # 3) propietarios originales de los directorios de datos
  [ -n "$OWNER_DATA" ] && chown -R "$OWNER_DATA" "$BASE_DIR/data" 2>/dev/null || true
  [ -n "$OWNER_WS" ]   && chown -R "$OWNER_WS" "$BASE_DIR/workspaces" 2>/dev/null || true
  [ -n "$OWNER_BK" ]   && chown -R "$OWNER_BK" "$BASE_DIR/backups" 2>/dev/null || true
  # 4) servicio en marcha con la version anterior
  systemctl start "$SERVICE" || true
  echo "Rollback completado: version anterior en marcha. Backup: $BACKUP_DIR"
  exit 1
}

# ----------------------------------------------------------------------------
step "3/8 Backup coherente (env + SQLite con WAL + workspaces + codigo)"
# ----------------------------------------------------------------------------
mkdir -p "$BACKUP_DIR"
cp -a "$APP_DIR/.env" "$BACKUP_DIR/.env" 2>/dev/null || echo "(sin .env en app/)"

# Checkpoint WAL: todo lo comprometido pasa de hj.db-wal a hj.db y el -wal
# queda a 0 bytes. Con el servicio parado, el tar posterior es coherente.
if [ -f "$DB_PATH" ]; then
  [ -x "$PY" ] || PY="$(command -v python3)"
  if "$PY" "$SRC_DIR/scripts/db_tools.py" "$DB_PATH" checkpoint; then
    ok "Checkpoint WAL de SQLite completado"
  else
    echo "AVISO: el checkpoint no devolvio WAL vacio; intentamos igualmente."
  fi
  if "$PY" "$SRC_DIR/scripts/db_tools.py" "$DB_PATH" integrity | grep -q '^ok$'; then
    ok "Integridad SQLite verificada antes de copiar"
  else
    rollback "la base de datos no pasa integrity_check; NO se toca nada"
  fi
fi

tar -czf "$BACKUP_DIR/data.tar.gz" -C "$BASE_DIR" data || die "Fallo el backup de data/"
[ -d "$BASE_DIR/workspaces" ] && tar -czf "$BACKUP_DIR/workspaces.tar.gz" -C "$BASE_DIR" workspaces
tar -czf "$BACKUP_DIR/app-anterior.tar.gz" -C "$BASE_DIR" app
ls -la "$BACKUP_DIR" | head -8
ok "Backup en $BACKUP_DIR (restaurable tal cual)"

# ----------------------------------------------------------------------------
step "4/8 Copiando software nuevo"
# ----------------------------------------------------------------------------
# --delete elimina archivos obsoletos de la version anterior; los excludes
# protegen .env, data/, workspaces/ y backups/ de cualquier borrado.
rsync -a --delete --exclude '.git' --exclude '__pycache__' --exclude '.venv' \
      --exclude 'data' --exclude 'workspaces' --exclude 'backups' --exclude '.env' \
      "$SRC_DIR"/ "$APP_DIR"/ || rollback "rsync del codigo nuevo"
[ -f "$APP_DIR/.env" ] || cp -a "$BACKUP_DIR/.env" "$APP_DIR/.env" 2>/dev/null || true
ok "Codigo actualizado (.env, data/, workspaces/ y backups/ NO se tocan)"

# ----------------------------------------------------------------------------
step "5/8 Dependencias + migraciones"
# ----------------------------------------------------------------------------
"$PY" -m pip install -e "$APP_DIR" --quiet || rollback "pip install"
MIGRATED=0
if [ -f "$DB_PATH" ]; then
  HJ_APP_DIR="$APP_DIR" HJ_DATA_DB="$DB_PATH" \
  "$PY" - <<'PYEOF' || rollback "migraciones"
import asyncio, os, sys
sys.path.insert(0, os.environ["HJ_APP_DIR"])
from core.storage.database import Database
async def main():
    db = Database(os.environ["HJ_DATA_DB"])
    await db.connect()
    applied = await db.migrate()
    print(f"Migraciones aplicadas: {applied}")
    await db.recover()
    await db.close()
asyncio.run(main())
PYEOF
  MIGRATED=1
fi
ok "Dependencias y migraciones compatibles aplicadas"

# ----------------------------------------------------------------------------
step "6/8 Permisos: SOLO si divergen del usuario real del servicio"
# ----------------------------------------------------------------------------
# Bug corregido: antes se ejecutaba un chown -R a un usuario hardcodeado sin
# comprobar nada, rompiendo el acceso del usuario real (p. ej. hjcode) a
# SQLite, la boveda y los proyectos. Ahora: sin usuario detectado -> no se
# toca nada; con usuario -> chown unicamente donde el propietario difiera.
if [ -n "$SERVICE_USER" ] && id "$SERVICE_USER" >/dev/null 2>&1; then
  WANT="$(id -u "$SERVICE_USER"):$(id -g "$SERVICE_USER")"
  CHOWNED=0
  for pair in "data:$OWNER_DATA" "workspaces:$OWNER_WS" "backups:$OWNER_BK"; do
    d="${pair%%:*}"; prev="${pair##*:}"
    if [ -n "$prev" ] && [ "$prev" != "$WANT" ]; then
      chown -R "$WANT" "$BASE_DIR/$d"
      echo "  $d: $prev -> $WANT (antes del update era distinto al usuario del servicio)"
      CHOWNED=1
    fi
  done
  [ "$CHOWNED" = "0" ] && echo "  Propietarios correctos: nada que cambiar."
else
  echo "  Sin usuario de servicio detectado: permisos intactos."
fi
ok "Permisos verificados (sin cambios innecesarios)"

# ----------------------------------------------------------------------------
step "7/8 Arranque y comprobacion de salud"
# ----------------------------------------------------------------------------
systemctl start "$SERVICE" || rollback "systemctl start"
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

# ----------------------------------------------------------------------------
step "8/8 Resultado"
# ----------------------------------------------------------------------------
echo "Actualizacion completada desde $PREV_VERSION."
echo "Servicio: $SERVICE como usuario '${SERVICE_USER:-sin cambios}'"
echo "Backup y rollback listos en: $BACKUP_DIR"
echo "Modificaciones locales previas guardadas en: $LOCALMODS (revisalas si existian)."
echo "Comandos utiles: journalctl -u $SERVICE -f · /health y /testapi en Telegram"
