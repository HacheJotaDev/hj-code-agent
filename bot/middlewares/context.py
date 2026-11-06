"""Inyeccion del contexto de servicios en cada handler."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject


class ContextMiddleware(BaseMiddleware):
    def __init__(self, ctx) -> None:
        self.ctx = ctx

    async def __call__(self, handler: Callable, event: TelegramObject,
                       data: dict[str, Any]) -> Any:
        data["ctx"] = self.ctx
        return await handler(event, data)
