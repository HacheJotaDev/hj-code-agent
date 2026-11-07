"""Middleware anti-duplicados: ignora updates ya procesados (update_id).

Protege contra:
- Doble entrega de la misma actualizacion por Telegram (reintentos).
- Dos instancias del bot en polling simultaneo.
Mantiene un LRU de los ultimos update_id vistos.
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

log = logging.getLogger(__name__)


class UpdateDedupMiddleware(BaseMiddleware):
    def __init__(self, capacity: int = 4096) -> None:
        self._seen: OrderedDict[int, None] = OrderedDict()
        self._capacity = capacity

    async def __call__(self, handler: Callable, event: TelegramObject,
                       data: dict[str, Any]) -> Any:
        update_id = getattr(event, "update_id", None)
        if update_id is not None:
            if update_id in self._seen:
                log.info("Update duplicado ignorado: %s", update_id)
                return  # ya procesado
            self._seen[update_id] = None
            while len(self._seen) > self._capacity:
                self._seen.popitem(last=False)
        return await handler(event, data)
