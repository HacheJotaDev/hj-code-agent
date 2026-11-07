"""Bus de eventos de tareas para el panel web (SSE + historial durable).

Cada evento se PERSISTE en la tabla task_events (SQLite) y despierta a los
suscriptores SSE en memoria. Gracias a la persistencia:
- la reconexion del navegador recupera todo desde Last-Event-ID,
- el historial sobrevive reinicios del backend,
- varios procesos pueden leer el mismo hilo de eventos.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict

log = logging.getLogger(__name__)


class TaskEventHub:
    def __init__(self, store) -> None:
        self.store = store
        self._subs: dict[int, set[asyncio.Event]] = defaultdict(set)

    # --------------------------- publicar ---------------------------------
    async def publish(self, task_id: int, data: dict) -> int:
        """Persiste el evento y despierta a los streamers SSE.

        El tipo del evento va en la columna `type`; el resto del dict en `data`.
        Devuelve el id global (secuencia para SSE).
        """
        ev_type = str(data.get("type", "event"))
        payload = {k: v for k, v in data.items() if k != "type"}
        ev_id = await self.store.db.insert(
            "INSERT INTO task_events (task_id, type, data) VALUES (?,?,?)",
            (int(task_id), ev_type, json.dumps(payload, ensure_ascii=False, default=str)))
        for ev in list(self._subs.get(int(task_id), ())):
            ev.set()
        return ev_id

    # --------------------------- suscripcion ------------------------------
    def subscribe(self, task_id: int) -> asyncio.Event:
        ev = asyncio.Event()
        self._subs[int(task_id)].add(ev)
        return ev

    def unsubscribe(self, task_id: int, ev: asyncio.Event) -> None:
        self._subs[int(task_id)].discard(ev)
        if not self._subs[int(task_id)]:
            self._subs.pop(int(task_id), None)

    # --------------------------- consulta ---------------------------------
    async def events_after(self, task_id: int, after_id: int = 0,
                           limit: int = 500) -> list[dict]:
        rows = await self.store.db.all(
            "SELECT id, task_id, type, data, created_at FROM task_events "
            "WHERE task_id=? AND id>? ORDER BY id LIMIT ?",
            (int(task_id), int(after_id), int(limit)))
        out = []
        for r in rows:
            try:
                data = json.loads(r["data"] or "{}")
            except (json.JSONDecodeError, TypeError):
                data = {}
            out.append({"id": r["id"], "task_id": r["task_id"], "type": r["type"],
                        "data": data, "created_at": r["created_at"]})
        return out

    async def latest_plan(self, task_id: int) -> list[dict] | None:
        row = await self.store.db.one(
            "SELECT data FROM task_events WHERE task_id=? AND type='plan' "
            "ORDER BY id DESC LIMIT 1", (int(task_id),))
        if not row:
            return None
        try:
            data = json.loads(row["data"] or "{}")
            return data.get("plan")
        except (json.JSONDecodeError, TypeError):
            return None
