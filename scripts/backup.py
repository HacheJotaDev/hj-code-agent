"""Backups desde Python (alternativa multiplataforma a backup.sh)."""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main() -> None:
    ap = argparse.ArgumentParser(description="Backup consistente de HJ Code Agent")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    from core.config import load_settings
    from core.storage.database import Database

    s = load_settings()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) if args.out else Path(s.backups_dir) / f"py-backup-{stamp}.tar.gz"
    out.parent.mkdir(parents=True, exist_ok=True)

    db_path = Path(s.db_file)
    if db_path.exists():
        tmp_db = Path(s.backups_dir) / f"db-{stamp}.sqlite"
        db = Database(db_path)
        await db.connect()
        await db.one("PRAGMA wal_checkpoint(TRUNCATE)")
        await db.close()
        import sqlite3
        with sqlite3.connect(db_path) as a, sqlite3.connect(tmp_db) as b:
            a.backup(b)
    import tarfile
    with tarfile.open(out, "w:gz") as t:
        if db_path.exists():
            t.add(tmp_db, arcname="data/hj.db")
            tmp_db.unlink(missing_ok=True)
        t.add(s.workspaces_dir, arcname="workspaces")
    print(f"Backup creado: {out}")


if __name__ == "__main__":
    asyncio.run(main())
