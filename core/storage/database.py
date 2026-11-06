"""Acceso asincrono a SQLite con migraciones versionadas."""
from __future__ import annotations

import asyncio
import importlib.resources
import logging
from pathlib import Path

import aiosqlite

log = logging.getLogger(__name__)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("La base de datos no esta conectada")
        return self._conn

    async def execute(self, sql: str, params: tuple = ()) -> None:
        async with self._lock:
            await self.conn.execute(sql, params)
            await self.conn.commit()

    async def one(self, sql: str, params: tuple = ()):
        async with self._lock:
            cur = await self.conn.execute(sql, params)
            row = await cur.fetchone()
            await cur.close()
            return row

    async def all(self, sql: str, params: tuple = ()) -> list:
        async with self._lock:
            cur = await self.conn.execute(sql, params)
            rows = await cur.fetchall()
            await cur.close()
            return rows

    async def insert(self, sql: str, params: tuple = ()) -> int:
        async with self._lock:
            cur = await self.conn.execute(sql, params)
            await self.conn.commit()
            return cur.lastrowid

    # --- migraciones -------------------------------------------------------
    async def migrate(self) -> int:
        applied = 0
        await self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
        )
        row = await self.one("SELECT MAX(version) AS v FROM schema_version")
        current = (row["v"] if row and row["v"] is not None else 0) if row else 0
        for sql in _migration_files():
            version = int(sql.stem.split("_", 1)[0])
            if version <= current:
                continue
            log.info("Aplicando migracion %s", sql.name)
            await self.conn.executescript(sql.read_text(encoding="utf-8"))
            await self.conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
            await self.conn.commit()
            applied += 1
        return applied

    async def recover(self) -> None:
        """Integridad tras reinicio: checkpoint WAL y verificacion rapida."""
        await self.one("PRAGMA wal_checkpoint(TRUNCATE)")
        row = await self.one("PRAGMA quick_check")
        if row and str(row[0]).lower() != "ok":
            raise RuntimeError(f"La base de datos parece corrupta: {row[0]}")


def _migration_files() -> list[Path]:
    files: list[Path] = []
    try:
        root = importlib.resources.files("database") / "migrations"
        with importlib.resources.as_file(root) as d:
            files = sorted(d.glob("*.sql"), key=lambda p: int(p.stem.split("_", 1)[0]))
    except (ModuleNotFoundError, FileNotFoundError):
        fallback = Path(__file__).resolve().parents[3] / "database" / "migrations"
        if fallback.exists():
            files = sorted(fallback.glob("*.sql"), key=lambda p: int(p.stem.split("_", 1)[0]))
    if not files:
        raise RuntimeError("No se encontraron migraciones SQL")
    return files
