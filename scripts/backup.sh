#!/usr/bin/env bash
# Backup completo: BD (sqlite .backup consistente) + workspaces + .env
set -euo pipefail
BASE_DIR="/opt/hj-code-agent"
STAMP=$(date +%Y%m%d-%H%M%S)
OUT="${1:-$BASE_DIR/backups/full-$STAMP.tar.gz}"
mkdir -p "$(dirname "$OUT")"

# copia consistente de la BD con WAL
if [ -f "$BASE_DIR/data/hj.db" ]; then
  "$BASE_DIR/venv/bin/python" - "$BASE_DIR/data/hj.db" "$BASE_DIR/data/hj-backup-$STAMP.db" <<'EOF'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
with sqlite3.connect(src) as a, sqlite3.connect(dst) as b:
    a.backup(b)
EOF
fi
tar -czf "$OUT" -C "$BASE_DIR" data .env 2>/dev/null || tar -czf "$OUT" -C "$BASE_DIR" data
rm -f "$BASE_DIR/data/hj-backup-$STAMP.db"
echo "Backup creado: $OUT"
echo "Restaurar: sudo $BASE_DIR/app/scripts/restore.sh $OUT"
