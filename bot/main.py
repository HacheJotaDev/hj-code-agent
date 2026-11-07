"""Punto de entrada del bot: aiogram 3 + long polling + servicios + formularios."""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from core.config import load_settings
from core.app import build_context

log = logging.getLogger("hj")


def setup_logging(settings) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if settings.log_file:
        from logging.handlers import RotatingFileHandler
        handlers.append(RotatingFileHandler(settings.log_file, maxBytes=5_000_000,
                                            backupCount=3, encoding="utf-8"))
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=handlers)


async def run() -> None:
    settings = load_settings()
    setup_logging(settings)
    log.info("=== HJ CODE AGENT V3 arrancando ===")
    if not settings.telegram_bot_token:
        log.critical("Falta HJ_TELEGRAM_BOT_TOKEN en el .env — el bot no puede arrancar")
        sys.exit(2)

    ctx = await build_context(settings)

    from bot.middlewares import AuthMiddleware, ContextMiddleware, UpdateDedupMiddleware
    from bot.handlers import ALL_ROUTERS
    from core.authentication.auth_service import AuthService

    ctx.auth = AuthService(ctx.store)

    bot = Bot(settings.telegram_bot_token,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    ctx.bot = bot
    dp = Dispatcher(storage=MemoryStorage())
    # orden: contexto -> dedup -> auth
    dp.update.middleware(ContextMiddleware(ctx))
    dp.update.middleware(UpdateDedupMiddleware())
    dp.update.middleware(AuthMiddleware())
    for r in ALL_ROUTERS:
        dp.include_router(r)

    from aiogram.types import BotCommand
    await bot.set_my_commands([
        BotCommand(command="start", description="Inicio y menú"),
        BotCommand(command="menu", description="Menú principal"),
        BotCommand(command="help", description="Ayuda con todos los comandos"),
        BotCommand(command="status", description="Estado actual"),
        BotCommand(command="newchat", description="Nueva conversación"),
        BotCommand(command="newproject", description="Nuevo proyecto"),
        BotCommand(command="projects", description="Mis proyectos"),
        BotCommand(command="run", description="Ejecutar tarea de código"),
        BotCommand(command="tasks", description="Tareas"),
        BotCommand(command="models", description="Modelos disponibles"),
        BotCommand(command="system", description="System prompt"),
        BotCommand(command="balance", description="Saldo real de la API"),
        BotCommand(command="tokens", description="Tokens consumidos"),
        BotCommand(command="cost", description="Costes"),
        BotCommand(command="github", description="GitHub"),
        BotCommand(command="terminal", description="Terminal del sandbox"),
        BotCommand(command="cancel", description="Cancelar tarea"),
    ])

    # formulario seguro para /setapi y /github connect
    from bot.formserver import start_form_server
    form_runner = await start_form_server(ctx)

    # cola de tareas + recuperacion tras reinicio
    await ctx.queue.start()

    try:
        log.info("Bot en marcha (long polling). Ctrl+C para detener.")
        # drop_pending_updates: tras una caida NO reprocesamos mensajes viejos
        # (evita respuestas duplicadas y comandos desactualizados)
        await dp.start_polling(bot, drop_pending_updates=True,
                               allowed_updates=dp.resolve_used_update_types())
    finally:
        log.info("Deteniendo servicios...")
        await ctx.queue.stop()
        if form_runner:
            await form_runner.cleanup()
        await ctx.db.close()
        await bot.session.close()


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        log.info("HJ Code Agent detenido")


if __name__ == "__main__":
    main()
