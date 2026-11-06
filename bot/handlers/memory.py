"""Memoria de usuario: notas explicitas (NUNCA se inyectan en el modelo ocultas)."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from ..utils import esc, send_long, trunc

router = Router(name="memory")


@router.message(Command("memory"))
async def cmd_memory(message: Message, ctx, command: CommandObject = None):
    uid = message.from_user.id
    arg = (command.args or "").strip() if command else ""
    if arg == "clear":
        n = await ctx.store.memory_clear(uid)
        await message.answer(f"🧽 {n} nota(s) eliminadas.")
        return
    if arg == "list" or not arg:
        rows = await ctx.store.memory_list(uid)
        if not rows:
            await message.answer("Memoria vacía. Añade: /memory <texto>")
            return
        lines = ["<b>🧠 Memoria</b>"]
        for r in rows:
            lines.append(f"• #{r['id']} {esc(trunc(r['content'], 140))}")
        lines.append("\nNota: la memoria NO se inyecta en el modelo (modo nativo). "
                     "Úsala como recordatorio para ti o cópiala en el chat.")
        await send_long(message, "\n".join(lines))
        return
    await ctx.store.memory_add(uid, arg)
    await message.answer("✔️ Nota guardada. /memory list")
