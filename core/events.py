"""Bus de eventos interno minimo (publicar/suscribir) para notificaciones."""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event: str, handler: Handler) -> None:
        self._subs[event].append(handler)

    async def publish(self, event: str, payload: dict[str, Any]) -> None:
        for h in list(self._subs.get(event, [])):
            try:
                asyncio.create_task(h(payload))
            except Exception:  # pragma: no cover
                log.exception("Error publicando evento %s", event)
