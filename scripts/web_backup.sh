#!/usr/bin/env bash
# Copia de seguridad del stack web V4: BD (con checkpoint WAL) + workspaces + .env.web.
# Uso: bash scripts/web_backup.sh [destino]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:-$ROOT/backups/web}"
TS=$(date +%Y%m%d-%H%M%S)
mkdir -p "$DEST"

# 1) Coherencia SQLite (WAL) antes de copiar
DB="${HJ_DB_PATH:-$ROOT/data/hj.db}"
if command -v sqlite3 >/dev/null 2>&1 && [[ -f "$DB" ]]; then
  sqlite3 "$DB" "PRAGMA wal_checkpoint(TRUNCATE);" >/dev/null || true
fi

# 2) BD + workspaces (sin .git de cada proyecto) + copia del entorno web
tar czf "$DEST/web-v4-$TS.tar.gz" \
  -C "$ROOT" \
  data \
  workspaces \
  --exclude='workspaces/*/*/.git' \
  --exclude='workspaces/*/.git' 2>/dev/null \
  || tar czf "$DEST/web-v4-$TS.tar.gz" -C "$ROOT" data workspaces

[[ -f "$ROOT/.env.web" ]] && cp -f "$ROOT/.env.web" "$DEST/env.web.$TS.bak"

echo "[backup] $DEST/web-v4-$TS.tar.gz"
echo "[backup] La boveda de credenciales viaja cifrada dentro de la BD (HJ_MASTER_KEY)."
echo "[backup] Guarda la clave maestra aparte: sin ella el backup es ilegible."
