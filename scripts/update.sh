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
#   9. NINGUN fallo posterior a "systemctl stop" deja el bot detenido: si
#      falla el checkpoint, integrity_check, cualquier tar del backup o
#      cualquier otro paso previo a la actualizacion, el servicio se
#      REINICIA automaticamente con la version anterior.
#  10. MIGRATED=1 se activa ANTES de ejecutar db.migrate(): si una migracion
#      aplica cambios parciales y luego falla, el rollback RESTAURA la base
#      de datos previa (copia tomada tras checkpoint WAL, sin -wal/-shm
#      residuales de la migracion a medias).
#  11. Respeta HJ_DB_PATH cuando esta configurado. Orden de resolucion (el
#      mismo que ve el bot): entorno de este script > Environment= de la
#      unidad systemd > HJ_DB_PATH= del .env de la instalacion >
#      $BASE_DIR/data/hj.db. El checkpoint, backup, migracion y restauracion
#      se aplican a ESA ruta aunque sea externa a data/.
#
# Uso:  sudo bash /opt/hj-code-agent/app/scripts/update.sh [ruta-del-codigo-nuevo]
# ============================================================================
set -Eeuo pipefail

BASE_DIR="${HJ_BASE_DIR:-/opt/hj-code-agent}"
APP_DIR="$BASE_DIR/app"
SERVICE="hj-code-agent"
SRC_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$BASE_DIR/backups/update-$TS"
PY="$BASE_DIR/venv/bin/python"
DB_PATH=""          # se resuelve al final del paso 1 (HJ_DB_PATH)
ROLLING=0           # 1 mientras rollback() se ejecuta (evita bucle del trap)

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
if grep -qs "__version__" "$APP_DIR/core/__init__.py"; then
  PREV_VERSION="$(grep -o '"[0-9.]*"' "$APP_DIR/core/__init__.py" 2>/dev/null | head -1 | tr -d '"' || true)"
fi
[ -n "$PREV_VERSION" ] || PREV_VERSION="desconocida"
echo "Version instalada: $PREV_VERSION"

# USUARIO EFECTIVO del servicio tal y como lo ve systemd (respeta User= de la
# unidad y sus drop-ins). Bug corregido: antes se forzaba "hjagent" y podia
# dejar a SQLite/boveda/proyectos sin duenio cuando el servicio corre como
# otro usuario (p. ej. "hjcode").
SERVICE_USER="$(systemctl show "$SERVICE" -p User --value 2>/dev/null | tr -d '[:space:]' || true)"
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
    if [ -f "$APP_DIR/$f" ]; then cp "$APP_DIR/$f" "$LOCALMODS/$f"; fi
  done <<< "$CHANGED"
fi

# Ruta REAL de la base de datos (requisito 11): el bot lee HJ_DB_PATH via
# core/config/settings.py; el update ANTES lo ignoraba y migraba/comprobaba
# $BASE_DIR/data/hj.db aunque la instalacion usara otra ruta.
if [ -z "$DB_PATH" ]; then
  DB_PATH="${HJ_DB_PATH:-}"
  if [ -n "$DB_PATH" ]; then echo "HJ_DB_PATH tomado del entorno de este script: $DB_PATH"; fi
fi
if [ -z "$DB_PATH" ]; then
  UNIT_FILE="/etc/systemd/system/${SERVICE}.service"
  for uf in "$UNIT_FILE" "$UNIT_FILE.d"/*.conf; do
    [ -f "$uf" ] || continue
    v="$(grep -hoE 'Environment="?HJ_DB_PATH=[^"[:space:]]+' "$uf" 2>/dev/null | head -1 | cut -d= -f3- | tr -d '"' || true)"
    if [ -n "$v" ]; then DB_PATH="$v"; echo "HJ_DB_PATH tomado de la unidad systemd: $DB_PATH"; break; fi
  done
fi
if [ -z "$DB_PATH" ] && [ -f "$APP_DIR/.env" ]; then
  line="$(grep -E '^[[:space:]]*(export[[:space:]]+)?HJ_DB_PATH=' "$APP_DIR/.env" 2>/dev/null | tail -1 || true)"
  if [ -n "$line" ]; then
    v="${line#*HJ_DB_PATH=}"
    v="${v//\"/}"; v="${v//\'/}"
    v="$(echo "$v" | tr -d '[:space:]')"
    if [ -n "$v" ]; then DB_PATH="$v"; echo "HJ_DB_PATH tomado del .env de la instalacion: $DB_PATH"; fi
  fi
fi
[ -n "$DB_PATH" ] || DB_PATH="$BASE_DIR/data/hj.db"
case "$DB_PATH" in
  /*) ;;  # absoluta: ok
  *)  DB_PATH="$APP_DIR/$DB_PATH"; echo "HJ_DB_PATH relativa: se resuelve contra $APP_DIR";;
esac
echo "Base de datos en uso: $DB_PATH"

ok "Deteccion completada (usuario: ${SERVICE_USER:-sin usuario no-root})"

# ----------------------------------------------------------------------------
step "2/8 Deteniendo UNICAMENTE $SERVICE (antes del backup)"
# ----------------------------------------------------------------------------
# El backup de SQLite se hace con el servicio PARADO: sin escritores
# concurrentes + checkpoint WAL = copia coherente garantizada.
systemctl stop "$SERVICE" 2>/dev/null || true
ok "Servicio detenido (otros servicios intactos)"

# ============================================================================
# A PARTIR DE AQUI EL BOT ESTA PARADO: cualquier fallo debe devolverlo arriba.
# ============================================================================
# Red de seguridad (requisito 9): con set -E, el trap ERR captura CUALQUIER
# fallo no gestionado (tar, mkdir, chown, etc.) y reinicia el servicio con la
# version anterior. Nunca se deja el bot detenido por un fallo del updater.
emergencia() {
  local code="$1" line="${2:-?}"
  if [ "${ROLLING:-0}" != "1" ]; then
    echo -e "\n\033[1;31m✘ FALLO inesperado (linea $line, exit $code): nada fue actualizado\033[0m" >&2
  fi
  echo "Reiniciando $SERVICE con la version anterior (el bot nunca queda detenido)..." >&2
  systemctl start "$SERVICE" 2>/dev/null || true
  if [ "${ROLLING:-0}" != "1" ]; then
    echo "Servicio anterior en marcha. Revision del fallo: bash -x este script." >&2
  fi
  exit 1
}
trap 'emergencia $? $LINENO' ERR

# Rollback COMPLETO: codigo anterior, dependencias, DATOS, .env y permisos.
rollback() {
  ROLLING=1
  echo -e "\n\033[1;31m!! FALLO: $1 — iniciando ROLLBACK COMPLETO\033[0m"
  # 1) codigo anterior (rm + untar: deja la instalacion EXACTAMENTE como estaba;
  #    .env se restaura desde el backup porque vive dentro de app/)
  if [ -f "$BACKUP_DIR/app-anterior.tar.gz" ]; then
    rm -rf "$APP_DIR"
    if tar -xzf "$BACKUP_DIR/app-anterior.tar.gz" -C "$BASE_DIR"; then
      [ -f "$BACKUP_DIR/.env" ] && cp -a "$BACKUP_DIR/.env" "$APP_DIR/.env" || true
      "$PY" -m pip install -e "$BASE_DIR/app" --quiet || echo "  AVISO: pip del rollback fallo; revisa el venv"
    else
      echo "  AVISO: no se pudo restaurar el codigo anterior desde el backup"
    fi
  else
    echo "  (sin backup de codigo: no se habia modificado nada todavia)"
  fi
  # 2) datos anteriores si las migraciones pudieron escribir: MIGRATED=1 se
  #    activa ANTES de db.migrate() (requisito 10), no despues de terminar.
  if [ "${MIGRATED:-0}" = "1" ]; then
    if [ -f "$BACKUP_DIR/data.tar.gz" ]; then
      STAGE="$BACKUP_DIR/.stage-data"
      rm -rf "$STAGE"; mkdir -p "$STAGE"
      if tar -xzf "$BACKUP_DIR/data.tar.gz" -C "$STAGE"; then
        # swap: la data parcialmente migrada se conserva en data.pre-rollback-*
        mv "$BASE_DIR/data" "$BASE_DIR/data.pre-rollback-$TS" 2>/dev/null || true
        if mv "$STAGE/data" "$BASE_DIR/data"; then
          echo "  data/ restaurada EXACTAMENTE desde el backup (migraciones revertidas)"
          echo "  (la data descartada se conserva en: $BASE_DIR/data.pre-rollback-$TS)"
        else
          echo "  AVISO: no se pudo instalar data/ restaurada"
        fi
      else
        echo "  AVISO: data.tar.gz ilegible; data/ se deja como estaba"
      fi
    fi
    # 2b) copia fiel de la BD tomada tras el checkpoint: cubre HJ_DB_PATH
    #     externo a data/ y elimina cualquier -wal/-shm de la migracion parcial.
    if [ -f "$BACKUP_DIR/db/dbfile" ]; then
      rm -f "$DB_PATH" "$DB_PATH-wal" "$DB_PATH-shm"
      cp -a "$BACKUP_DIR/db/dbfile" "$DB_PATH"
      [ -f "$BACKUP_DIR/db/dbfile-wal" ] && cp -a "$BACKUP_DIR/db/dbfile-wal" "$DB_PATH-wal" || true
      [ -f "$BACKUP_DIR/db/dbfile-shm" ] && cp -a "$BACKUP_DIR/db/dbfile-shm" "$DB_PATH-shm" || true
      echo "  BD restaurada al estado previo (sin WAL parcial): $DB_PATH"
    fi
  fi
  # 3) propietarios originales de los directorios de datos
  [ -n "$OWNER_DATA" ] && chown -R "$OWNER_DATA" "$BASE_DIR/data" 2>/dev/null || true
  [ -n "$OWNER_WS" ]   && chown -R "$OWNER_WS" "$BASE_DIR/workspaces" 2>/dev/null || true
  [ -n "$OWNER_BK" ]   && chown -R "$OWNER_BK" "$BASE_DIR/backups" 2>/dev/null || true
  # 4) servicio en marcha SIEMPRE, incluso si algo de lo anterior fallo
  systemctl start "$SERVICE" 2>/dev/null || true
  echo "Rollback completado: version anterior en marcha. Backup: $BACKUP_DIR"
  exit 1
}

# ----------------------------------------------------------------------------
step "3/8 Backup coherente (env + SQLite con WAL + workspaces + codigo)"
# ----------------------------------------------------------------------------
mkdir -p "$BACKUP_DIR"
cp -a "$APP_DIR/.env" "$BACKUP_DIR/.env" 2>/dev/null || echo "(sin .env en app/)"

if [ -f "$DB_PATH" ]; then
  [ -x "$PY" ] || PY="$(command -v python3)"
  # Checkpoint WAL: todo lo comprometido pasa de hj.db-wal a hj.db y el -wal
  # queda a 0 bytes. Con el servicio parado, el tar posterior es coherente.
  # Si el checkpoint falla NO se continua: rollback + servicio en marcha.
  "$PY" "$SRC_DIR/scripts/db_tools.py" "$DB_PATH" checkpoint || \
    rollback "checkpoint WAL de SQLite fallo (se aborta antes de tocar nada)"
  ok "Checkpoint WAL de SQLite completado"
  "$PY" "$SRC_DIR/scripts/db_tools.py" "$DB_PATH" integrity | grep -q '^ok$' || \
    rollback "la base de datos no pasa integrity_check; NO se toca nada"
  ok "Integridad SQLite verificada antes de copiar"
  # Copia fiel del fichero de BD (ademas del tar de data/): cubre HJ_DB_PATH
  # externo a data/ y permite restaurar sin -wal/-shm residuales.
  mkdir -p "$BACKUP_DIR/db"
  cp -a "$DB_PATH" "$BACKUP_DIR/db/dbfile"
  [ -f "$DB_PATH-wal" ] && cp -a "$DB_PATH-wal" "$BACKUP_DIR/db/dbfile-wal" || true
  [ -f "$DB_PATH-shm" ] && cp -a "$DB_PATH-shm" "$BACKUP_DIR/db/dbfile-shm" || true
fi

# Cualquier fallo de tar ahora hace rollback (antes: die/set -e dejaban el
# bot PARADO). El rollback restaura lo restaurable y reinicia el servicio.
tar -czf "$BACKUP_DIR/data.tar.gz" -C "$BASE_DIR" data || rollback "backup tar de data/"
if [ -d "$BASE_DIR/workspaces" ]; then
  tar -czf "$BACKUP_DIR/workspaces.tar.gz" -C "$BASE_DIR" workspaces || rollback "backup tar de workspaces/"
fi
tar -czf "$BACKUP_DIR/app-anterior.tar.gz" -C "$BASE_DIR" app || rollback "backup tar del codigo anterior"
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
  # Requisito 10: se marca ANTES de migrar. Si db.migrate() aplica una
  # migracion y la siguiente explota, el rollback RESTAURA la BD previa.
  # (Antes se marcaba al final: un fallo parcial dejaba datos modificados.)
  MIGRATED=1
  HJ_APP_DIR="$APP_DIR" HJ_DATA_DB="$DB_PATH" \
  "$PY" - <<'PYEOF' || rollback "migraciones"
import asyncio, os, sys
sys.path.insert(0, os.environ["HJ_APP_DIR"])
from core.storage.database import Database

async def main():
    db = Database(os.environ["HJ_DATA_DB"])
    try:
        await db.connect()
        applied = await db.migrate()
        print(f"Migraciones aplicadas: {applied}")
        await db.recover()
    finally:
        # CRITICO: cerrar SIEMPRE la conexion. Si migrate() explota sin cerrar,
        # el hilo no-daemon de aiosqlite deja el proceso colgado y el rollback
        # jamas se ejecutaria (bug detectado por los tests e2e).
        try:
            await db.close()
        except Exception:
            pass

try:
    asyncio.run(main())
except Exception as e:
    print(f"ERROR en migraciones: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
  # Verificacion POST-migracion: si la BD quedo mal, rollback completo.
  "$PY" "$SRC_DIR/scripts/db_tools.py" "$DB_PATH" integrity | grep -q '^ok$' || \
    rollback "integridad perdida tras migrar"
  ok "Migraciones aplicadas e integridad verificada en: $DB_PATH"
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
  for d in data workspaces backups; do
    case "$d" in
      data)       prev="$OWNER_DATA";;
      workspaces) prev="$OWNER_WS";;
      backups)    prev="$OWNER_BK";;
    esac
    if [ -n "$prev" ] && [ "$prev" != "$WANT" ]; then
      chown -R "$WANT" "$BASE_DIR/$d" || rollback "chown de $BASE_DIR/$d"
      echo "  $d: $prev -> $WANT (antes del update era distinto al usuario del servicio)"
      CHOWNED=1
    fi
  done
  if [ "$CHOWNED" = "0" ]; then echo "  Propietarios correctos: nada que cambiar."; fi
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
LOG_OK="${LOG_OK:-0}"
if [ "$LOG_OK" -eq 0 ]; then
  sleep 6
  LOG_OK=$(journalctl -u "$SERVICE" --since "60 seconds ago" --no-pager 2>/dev/null | grep -c "Bot en marcha" || true)
  LOG_OK="${LOG_OK:-0}"
fi
[ "$LOG_OK" -ge 1 ] || rollback "no se vio 'Bot en marcha' en los logs"
ok "Servicio activo y polling en marcha"

# ----------------------------------------------------------------------------
step "8/8 Resultado"
# ----------------------------------------------------------------------------
echo "Actualizacion completada desde $PREV_VERSION."
echo "Servicio: $SERVICE como usuario '${SERVICE_USER:-sin cambios}'"
echo "Base de datos: $DB_PATH (respeta HJ_DB_PATH)"
echo "Backup y rollback listos en: $BACKUP_DIR"
echo "Modificaciones locales previas guardadas en: $LOCALMODS (revisalas si existian)."
echo "Comandos utiles: journalctl -u $SERVICE -f · /health y /testapi en Telegram"
exit 0
