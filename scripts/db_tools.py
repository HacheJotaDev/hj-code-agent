#!/usr/bin/env python3
"""Utilidades SQLite para backups coherentes (update.sh, backup.py).

Con journal_mode=WAL, copiar hj.db sin mas puede capturar una base con las
transacciones aun en hj.db-wal. `wal_checkpoint(TRUNCATE)` fuerza a que toda
transaccion comprometida quede en el fichero principal y deja el -wal a 0
bytes; hecho con el servicio PARADO, garantiza un backup tar coherente.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def wal_checkpoint(db_path: str | Path, timeout: float = 30.0) -> dict:
    """Checkpoint TRUNCATE de una base SQLite.

    Devuelve {"mode": modo de journal, "checkpointed": paginas movidas,
    "wal_remaining": paginas que quedaron en el WAL (0 = limpio)}.
    """
    p = Path(db_path)
    if not p.exists():
        raise FileNotFoundError(f"No existe la base de datos: {p}")
    con = sqlite3.connect(str(p), timeout=timeout)
    try:
        mode = con.execute("PRAGMA journal_mode").fetchone()[0]
        if (mode or "").lower() != "wal":
            # No hay WAL: el fichero principal ya es autoconsistente.
            return {"mode": mode, "checkpointed": 0, "wal_remaining": 0}
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        remaining = con.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()[2] or 0
        return {"mode": mode, "checkpointed": 0, "wal_remaining": remaining}
    finally:
        con.close()


def check_integrity(db_path: str | Path, timeout: float = 30.0) -> str:
    """`PRAGMA integrity_check`: 'ok' = base restaurable/coherente."""
    con = sqlite3.connect(str(Path(db_path)), timeout=timeout)
    try:
        return con.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        con.close()


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("uso: db_tools.py <ruta-hj.db> [checkpoint|integrity]")
        sys.exit(2)
    action = sys.argv[2] if len(sys.argv) > 2 else "checkpoint"
    try:
        if action == "integrity":
            result = check_integrity(sys.argv[1])
            print(result)
            sys.exit(0 if result == "ok" else 1)
        info = wal_checkpoint(sys.argv[1])
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(info))
    sys.exit(0 if info["wal_remaining"] == 0 else 1)
