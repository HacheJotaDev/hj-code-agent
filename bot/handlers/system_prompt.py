"""Comandos /system: gestion explicita y transparente de system prompts.

Por defecto el modo es NATIVO: no se envia ningun system prompt. Todo lo que
el usuario configure aqui es visible para el y se envia tal cual.
"""
from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from ..states import SystemPromptStates
from ..utils import esc, trunc

router = Router(name="system_prompt")

MODE_LABEL = {"native": "🟢 NATIVO (sin system prompt)",
              "custom": "🔵 PERSONALIZADO (tu prompt)",
              "project": "🟣 POR PROYECTO"}


async def show_prompt_menu(message: Message, ctx):
    uid = message.from_user.id
    proj = await ctx.projects.active(uid)
    eff = await ctx.prompts.status(uid, proj)
    text = [
        "<b>🧩 System prompts</b>",
        f"Modo actual: <b>{MODE_LABEL.get(eff.mode, eff.mode)}</b>",
        f"Origen: {esc(eff.source) if eff.source else '—'}",
        "",
        "Regla del producto: el modo <b>nativo</b> no envía ningún rol system/developer "
        "ni instrucciones ocultas. Solo se envía lo que TÚ configures aquí.",
    ]
    from ..keyboards import system_prompt_kb
    await message.answer("\n".join(text), reply_markup=system_prompt_kb(eff.mode, bool(eff.content)))


@router.message(Command("system"))
async def cmd_system(message: Message, ctx, command: CommandObject = None, state: FSMContext = None):
    arg = (command.args or "").strip() if command and command.args else ""
    uid = message.from_user.id
    if not arg:
        await show_prompt_menu(message, ctx)
        return
    parts = arg.split(None, 1)
    sub = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""
    if sub in ("set", "edit"):
        if rest:
            await ctx.prompts.set_custom(uid, rest)
            await message.answer("🔵 System prompt guardado (modo PERSONALIZADO). /system show")
        else:
            if state:
                await state.set_state(SystemPromptStates.waiting_text)
            await message.answer("✍️ Envía ahora el texto del system prompt (o /cancel).")
    elif sub == "show":
        await _show(message, ctx)
    elif sub == "off":
        await ctx.prompts.set_mode(uid, "native")
        await message.answer("📴 Modo NATIVO: no se enviará ningún system prompt.")
    elif sub == "clear":
        await ctx.prompts.clear(uid)
        await message.answer("🗑 System prompt eliminado. Modo: NATIVO.")
    elif sub == "reset":
        await ctx.prompts.reset(uid)
        await message.answer("♻️ Restablecido al modo NATIVO.")
    elif sub == "export":
        await _export(message, ctx)
    elif sub == "import":
        if state:
            await state.set_state(SystemPromptStates.waiting_import)
        await message.answer("📥 Envía un archivo .json con {\"mode\": ..., \"content\": ...}")
    elif sub == "project":
        await _project(message, ctx, rest)
    else:
        await message.answer("Subcomandos: set · edit · show · off · clear · reset · "
                             "export · import · project")


async def _show(message: Message, ctx):
    uid = message.from_user.id
    eff = await ctx.prompts.status(uid, await ctx.projects.active(uid))
    lines = [f"Modo: <b>{MODE_LABEL.get(eff.mode, eff.mode)}</b>"]
    if eff.content:
        lines.append("\n<b>Contenido que se envía con rol 'system':</b>")
        lines.append(f"<pre>{esc(eff.content[:3000])}</pre>")
    else:
        lines.append("\nNo se envía NINGÚN system prompt (comportamiento nativo).")
    await message.answer("\n".join(lines))


async def _export(message: Message, ctx):
    data = await ctx.prompts.export(message.from_user.id)
    blob = json.dumps(data, ensure_ascii=False, indent=2).encode()
    await message.answer_document(BufferedInputFile(blob, "system_prompt.json"),
                                  caption="📤 System prompt exportado")


async def _project(message: Message, ctx, rest: str):
    uid = message.from_user.id
    proj = await ctx.projects.active(uid)
    if not proj:
        await message.answer("📁 No hay proyecto activo: /projects")
        return
    if rest.lower().startswith("on"):
        await ctx.store.update_project(proj["id"], prompt_enabled=1)
        await message.answer(f"🟣 Prompt de proyecto ACTIVADO para '{esc(proj['name'])}'.")
    elif rest.lower().startswith("off"):
        await ctx.store.update_project(proj["id"], prompt_enabled=0)
        await message.answer("🟢 Prompt de proyecto desactivado (modo nativo).")
    else:
        if rest:
            await ctx.store.update_project(proj["id"], system_prompt=rest, prompt_enabled=1)
            await message.answer("🟣 Prompt de proyecto guardado y activado.")
            return
        eff = await ctx.prompts.status(uid, proj)
        content = proj.get("system_prompt") or "(vacío)"
        await message.answer(
            f"📁 <b>Prompt de proyecto '{esc(proj['name'])}'</b>\n"
            f"Modo efectivo: {MODE_LABEL.get(eff.mode, eff.mode)}\n"
            f"Contenido:\n<pre>{esc(trunc(content, 600))}</pre>\n"
            "Editar: /system project &lt;texto&gt;\n"
            "Activar: /system project on · Desactivar: /system project off")


# ------------------------------ FSM y callbacks ------------------------------


@router.callback_query(F.data == "sysp:set")
async def cb_set(cb: CallbackQuery, ctx, state: FSMContext):
    await cb.answer()
    await state.set_state(SystemPromptStates.waiting_text)
    await cb.message.answer("✍️ Envía el texto del system prompt. Puede ser largo. "
                            "/cancel para abortar.")


@router.message(SystemPromptStates.waiting_text, F.text)
async def on_prompt_text(message: Message, ctx, state: FSMContext):
    await ctx.prompts.set_custom(message.from_user.id, message.text)
    await state.clear()
    await message.answer("🔵 System prompt guardado en modo PERSONALIZADO. "
                         "Se enviará con rol 'system' tal cual. Verlo: /system show")


@router.message(SystemPromptStates.waiting_import, F.document)
async def on_import_doc(message: Message, ctx, state: FSMContext):
    try:
        file = await ctx.bot.get_file(message.document.file_id)
        raw = await ctx.bot.download_file(file.file_path)
        data = json.loads(raw.read().decode("utf-8"))
        await ctx.prompts.import_prompt(message.from_user.id, data)
        await state.clear()
        await message.answer("📥 System prompt importado. /system show para verificar.")
    except Exception as e:
        await state.clear()
        await message.answer(f"❌ Import inválido: {esc(e)}")


@router.callback_query(F.data == "sysp:show")
async def cb_show(cb: CallbackQuery, ctx):
    await cb.answer()
    eff = await ctx.prompts.status(cb.from_user.id, await ctx.projects.active(cb.from_user.id))
    text = f"Modo: {MODE_LABEL.get(eff.mode, eff.mode)}\n\n"
    text += (f"<pre>{esc(eff.content[:2500])}</pre>" if eff.content else
             "No se envía ningún system prompt (nativo).")
    await cb.message.answer(text)


@router.callback_query(F.data.in_({"sysp:off", "sysp:clear", "sysp:reset"}))
async def cb_off(cb: CallbackQuery, ctx):
    await cb.answer()
    uid = cb.from_user.id
    if cb.data == "sysp:off":
        await ctx.prompts.set_mode(uid, "native")
        await cb.message.answer("📴 Desactivado: modo NATIVO.")
    elif cb.data == "sysp:clear":
        await ctx.prompts.clear(uid)
        await cb.message.answer("🗑 Eliminado: modo NATIVO.")
    else:
        await ctx.prompts.reset(uid)
        await cb.message.answer("♻️ Modo NATIVO restaurado.")


@router.callback_query(F.data == "sysp:export")
async def cb_export(cb: CallbackQuery, ctx):
    await cb.answer()
    await _export(cb.message, ctx)


@router.callback_query(F.data == "sysp:import")
async def cb_import(cb: CallbackQuery, ctx, state: FSMContext):
    await cb.answer()
    await state.set_state(SystemPromptStates.waiting_import)
    await cb.message.answer("📥 Envía el archivo JSON del system prompt.")


@router.callback_query(F.data == "sysp:project")
async def cb_project(cb: CallbackQuery, ctx):
    await cb.answer()
    await _project(cb.message, ctx, "")
