"""Gestion de autorizaciones humanas (push, PR, acciones delicadas).

El modelo NO puede autoaprobarse: se crea una peticion con botones en Telegram
y el motor queda en pausa hasta que el usuario autorice, rechace o expire.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Awaitable, Callable


class ApprovalDenied(Exception):
    pass


class ApprovalTimeout(ApprovalDenied):
    pass


Notifier = Callable[[dict], Awaitable[None]]  # recibe dict(id, action, detail, ...)


class ApprovalManager:
    TTL_S = 600

    def __init__(self, store) -> None:
        self.store = store
        self._waiters: dict[str, asyncio.Future] = {}

    async def request(self, action: str, detail: str, notify: Notifier,
                      user_id: int) -> dict:
        req_id = uuid.uuid4().hex[:12]
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._waiters[req_id] = fut
        info = {"id": req_id, "action": action, "detail": detail, "user_id": user_id,
                "created_at": time.time()}
        try:
            await notify(info)
            return await asyncio.wait_for(fut, timeout=self.TTL_S)
        except asyncio.TimeoutError:
            raise ApprovalTimeout("La autorizacion expiro (10 min). Intentalo de nuevo.")
        finally:
            self._waiters.pop(req_id, None)

    def resolve(self, req_id: str, approved: bool) -> bool:
        fut = self._waiters.get(req_id)
        if not fut or fut.done():
            return False
        fut.set_result({"approved": approved})
        return True

    def pending(self, req_id: str) -> bool:
        fut = self._waiters.get(req_id)
        return bool(fut and not fut.done())
