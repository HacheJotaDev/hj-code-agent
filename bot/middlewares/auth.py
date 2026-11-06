"""Middleware de acceso: solo user_id autorizados. Acceso privado por defecto."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

log = logging.getLogger(__name__)


class AuthMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable, event: TelegramObject,
                       data: dict[str, Any]) -> Any:
        user: User | None = data.get("event_from_user")
        ctx = data.get("ctx")
        if ctx is None or user is None:
            return await handler(event, data)
        auth = ctx.auth
        await auth.register(user.id, user.username or "", user.first_name or "")
        if not await auth.is_allowed(user.id):
            # Comportamiento configurable:
            #   silent_reject=0 (defecto): UN solo aviso con su user_id; luego silencio.
            #   silent_reject=1: ni un aviso - el bot no responde a nadie no autorizado.
            log.info("Acceso denegado a user_id=%s", user.id)
            data["allowed"] = False
            settings = getattr(ctx, "settings", None)
            silent = bool(getattr(settings, "silent_reject", False))
            if not silent:
                try:
                    await ctx.bot.send_message(
                        user.id, "⛔ Acceso restringido.\nSolicita autorizacion al administrador "
                                 f"con tu user_id: <code>{user.id}</code>", parse_mode="HTML")
                except Exception:
                    pass
            return  # no llama al handler
        data["allowed"] = True
        data["is_admin"] = await auth.is_admin(user.id)
        return await handler(event, data)
