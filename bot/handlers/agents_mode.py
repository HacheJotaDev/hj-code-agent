"""Modo multiagente OPCIONAL: desactivado por defecto."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..keyboards import agents_kb
from ..states import AgentsStates
from ..utils import esc, trunc

router = Router(name="agents")

ROLE_HINTS = "Roles sugeridos: coordinador · programador · revisor · tester · analizador"


async def _status_text(ctx, uid: int) -> str:
    enabled = bool(await ctx.store.get_pref(uid, "agents_enabled"))
    profiles = await ctx.store.list_agents(uid)
    lines = [f"<b>🤖 Multiagente: {'ACTIVADO' if enabled else 'DESACTIVADO (por defecto)'}</b>",
             "Aviso: cada perfil puede gastar tokens del modelo. Actívalo solo cuando lo necesites.",
             ""]
    for p in profiles:
        on = "✅" if p["enabled"] else "⏸"
        model = p.get("model") or "(mismo del proveedor activo)"
        lines.append(f"{on} <b>{esc(p['name'])}</b> [{esc(p['role'])}] {esc(model)}")
        if p.get("prompt"):
            lines.append(f"   prompt: {esc(trunc(p['prompt'], 80))}")
    if not profiles:
        lines.append("Sin perfiles. Añade con /agents add")
    return "\n".join(lines)


@router.message(Command("agents"))
async def cmd_agents(message: Message, ctx, command: CommandObject = None):
    arg = (command.args or "").strip().lower() if command else ""
    uid = message.from_user.id
    if arg == "on":
        await ctx.store.set_pref(uid, "agents_enabled", "1")
        await message.answer("🤖 Multiagente ACTIVADO. /run ejecutará el pipeline configurado.")
        return
    if arg == "off":
        await ctx.store.set_pref(uid, "agents_enabled", "0")
        await message.answer("⏹ Multiagente DESACTIVADO.")
        return
    if arg == "add":
        if hasattr(message, "bot"):
            pass
        await message.answer("➕ Nombre del perfil (ej: revisor):")
        return
    if arg == "remove":
        profiles = await ctx.store.list_agents(uid)
        names = ", ".join(p["name"] for p in profiles) or "(ninguno)"
        await message.answer(f"Uso: /agents remove <nombre>\nPerfiles: {names}")
        return
    if arg == "status":
        await message.answer(await _status_text(ctx, uid))
        return
    if arg == "models":
        rows = await ctx.store.list_agents(uid)
        lines = ["<b>Modelos por perfil</b>"]
        for p in rows:
            lines.append(f"• {esc(p['name'])}: {esc(p.get('model') or '(proveedor activo)')} "
                         f"@ {esc(p.get('provider') or 'activo')}")
        lines.append("\nCambia con /agents config")
        await message.answer("\n".join(lines))
        return
    if arg == "config":
        await message.answer("Para reconfigurar un perfil: /agents remove <nombre> y /agents add. "
                             "Cada perfil pide nombre, rol, proveedor/modelo y prompt opcional.")
        return
    await message.answer(await _status_text(ctx, uid), reply_markup=agents_kb(
        bool(await ctx.store.get_pref(uid, "agents_enabled"))))


@router.callback_query(F.data == "agents:toggle")
async def cb_agents_toggle(cb: CallbackQuery, ctx):
    await cb.answer()
    uid = cb.from_user.id
    cur = bool(await ctx.store.get_pref(uid, "agents_enabled"))
    await ctx.store.set_pref(uid, "agents_enabled", "0" if cur else "1")
    await cb.message.answer("🤖 Multiagente " + ("DESACTIVADO." if cur else "ACTIVADO."))


@router.callback_query(F.data == "agents:add")
async def cb_agents_add(cb: CallbackQuery, ctx, state: FSMContext):
    await cb.answer()
    await state.set_state(AgentsStates.waiting_name)
    await cb.message.answer("➕ Nombre del perfil:")


@router.callback_query(F.data == "agents:status")
async def cb_agents_status(cb: CallbackQuery, ctx):
    await cb.answer()
    await cb.message.answer(await _status_text(ctx, cb.from_user.id))


@router.callback_query(F.data == "agents:config")
async def cb_agents_config(cb: CallbackQuery, ctx):
    await cb.answer()
    await cb.message.answer("Reconfigurar: /agents remove <nombre> + /agents add")


@router.callback_query(F.data == "agents:remove")
async def cb_agents_remove(cb: CallbackQuery, ctx):
    await cb.answer()
    profiles = await ctx.store.list_agents(cb.from_user.id)
    names = ", ".join(p["name"] for p in profiles) or "(ninguno)"
    await cb.message.answer(f"Uso: /agents remove <nombre>\nPerfiles: {names}")


@router.message(AgentsStates.waiting_name, F.text)
async def ag_name(message: Message, ctx, state: FSMContext):
    name = message.text.strip()[:24]
    await state.update_data(name=name)
    await state.set_state(AgentsStates.waiting_role)
    await message.answer(f"Rol de '{esc(name)}' ({ROLE_HINTS}):")


@router.message(AgentsStates.waiting_role, F.text)
async def ag_role(message: Message, ctx, state: FSMContext):
    await state.update_data(role=message.text.strip()[:24])
    await state.set_state(AgentsStates.waiting_model)
    await message.answer("Proveedor/modelo (formato proveedor:modelo, vacío = usar el activo):")


@router.message(AgentsStates.waiting_model, F.text)
async def ag_model(message: Message, ctx, state: FSMContext):
    txt = message.text.strip()
    provider = model = None
    if txt and ":" in txt:
        provider, model = txt.split(":", 1)
    await state.update_data(provider=provider, model=model)
    await state.set_state(AgentsStates.waiting_prompt)
    await message.answer("Prompt del rol (OPCIONAL, visible y editable por ti; "
                         "vacío = sin prompt, modo nativo):")


@router.message(AgentsStates.waiting_prompt, F.text)
async def ag_prompt(message: Message, ctx, state: FSMContext):
    data = await state.get_data()
    prompt = None if message.text.strip().lower() in ("-", "no", "") else message.text.strip()
    await ctx.store.upsert_agent(message.from_user.id, data["name"], data["role"],
                                 data.get("provider"), data.get("model"), prompt)
    await state.clear()
    await message.answer(f"✔️ Perfil <b>{esc(data['name'])}</b> guardado. /agents status")


@router.message(Command("agents"), F.text.regexp(r"^/agents\s+remove\s+\S+"))
async def ag_remove_inline(message: Message, ctx, command: CommandObject = None):
    import re
    m = re.match(r"^/agents\s+remove\s+(\S+)", message.text)
    if m:
        await ctx.store.delete_agent(message.from_user.id, m.group(1))
        await message.answer(f"🗑 Perfil '{esc(m.group(1))}' eliminado.")
