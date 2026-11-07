"""Proveedores, API keys seguras, modelos y parametros de generacion."""
from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..keyboards import models_kb, providers_kb
from ..states import ProviderStates
from ..utils import esc, send_long, trunc
from .helpers import provider_error_message

router = Router(name="providers")


async def show_providers(message: Message, ctx, uid: int | None = None):
    uid = uid or message.from_user.id
    active = await ctx.providers.active_name(uid)
    rows = await ctx.store.list_providers()
    creds = await ctx.store.list_credential_providers(uid)
    lines = ["<b>🧠 Proveedores</b>", f"Activo: <b>{esc(active)}</b>", ""]
    for p in rows:
        key = "🔑" if p["name"] in creds else "—"
        mark = "●" if p["name"] == active else "○"
        lines.append(f"{mark} <b>{esc(p['name'])}</b> ({esc(p['kind'])}) {key} {esc(p['base_url'])}")
    lines += ["", "Conectar API key: /setapi · Probar: /testapi · Modelos: /models"]
    await message.answer("\n".join(lines), reply_markup=providers_kb(rows, active, creds))


@router.message(Command("provider"))
async def cmd_provider(message: Message, ctx, command: CommandObject = None):
    arg = (command.args or "").strip() if command else ""
    if not arg:
        await show_providers(message, ctx)
        return
    parts = arg.split(None, 1)
    sub = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    if sub == "select":
        await _select(ctx, message.from_user.id, rest, message)
    elif sub == "remove":
        await _remove(message, ctx, rest)
    elif sub == "add":
        await message.answer("Flujo guiado: envía el nombre del nuevo proveedor "
                             "(ej: 'miollama'). /cancel para abortar.")
        return
    else:
        await message.answer("Uso: /provider · /provider select &lt;nombre&gt; · "
                             "/provider add · /provider remove &lt;nombre&gt;")


@router.message(Command("providers"))
async def cmd_providers(message: Message, ctx):
    await show_providers(message, ctx)


async def _select(ctx, uid: int, name: str, message: Message):
    if not name:
        await message.answer("Uso: /provider select &lt;nombre&gt;")
        return
    cfg = await ctx.store.get_provider(name)
    if not cfg:
        await message.answer(f"Proveedor '{esc(name)}' no existe. /providers")
        return
    await ctx.store.set_pref(uid, "active_provider", name)
    model = await ctx.store.get_pref(uid, f"model:{name}")
    extra = f" · modelo: {esc(model)}" if model else " · elige modelo con /models"
    await message.answer(f"✔️ Proveedor activo: <b>{esc(name)}</b>{extra}")


async def _remove(message: Message, ctx, name: str):
    cfg = await ctx.store.get_provider(name)
    if not cfg:
        await message.answer("No existe (los builtin no se pueden eliminar).")
        return
    if cfg["builtin"]:
        await message.answer("Los proveedores integrados no se eliminan; usa /provider select.")
        return
    await ctx.store.remove_provider(name)
    await ctx.store.audit(message.from_user.id, "provider.remove", name)
    await message.answer(f"🗑 Proveedor '{esc(name)}' eliminado.")


# -------------------------- alta guiada de proveedor ------------------------


@router.callback_query(F.data == "prov:add")
async def cb_add(cb: CallbackQuery, ctx, state: FSMContext):
    await cb.answer()
    await state.set_state(ProviderStates.waiting_name)
    await cb.message.answer("➕ Nombre del nuevo proveedor (una palabra, ej: 'openrouter2'):")


@router.message(ProviderStates.waiting_name, F.text & ~F.text.startswith("/"))
async def on_name(message: Message, ctx, state: FSMContext):
    name = message.text.strip().lower()
    if not re.fullmatch(r"[a-z0-9_-]{2,24}", name):
        await message.answer("Nombre inválido (2-24 caracteres: a-z, 0-9, -, _).")
        return
    await state.update_data(name=name)
    await state.set_state(ProviderStates.waiting_kind)
    await message.answer("Tipo de adaptador: openai_compat · deepseek · anthropic")


@router.message(ProviderStates.waiting_kind, F.text & ~F.text.startswith("/"))
async def on_kind(message: Message, ctx, state: FSMContext):
    kind = message.text.strip().lower()
    if kind not in ("openai_compat", "deepseek", "anthropic"):
        await message.answer("Tipo inválido. Opciones: openai_compat · deepseek · anthropic")
        return
    await state.update_data(kind=kind)
    await state.set_state(ProviderStates.waiting_url)
    await message.answer("URL base del endpoint (ej: https://api.ejemplo.com/v1):")


@router.message(ProviderStates.waiting_url, F.text & ~F.text.startswith("/"))
async def on_url(message: Message, ctx, state: FSMContext):
    url = message.text.strip()
    if not url.startswith(("http://", "https://")):
        await message.answer("URL inválida.")
        return
    data = await state.get_data()
    await ctx.store.add_provider(data["name"], data["kind"], url)
    await state.clear()
    await ctx.store.audit(message.from_user.id, "provider.add", f"{data['name']} {url}")
    await message.answer(f"✔️ Proveedor <b>{esc(data['name'])}</b> añadido.\n"
                         "Ahora: /provider select " + esc(data["name"]) + " y /setapi")


@router.callback_query(F.data.startswith("prov:sel:"))
async def cb_prov_sel(cb: CallbackQuery, ctx):
    name = cb.data.split(":", 2)[2]
    await _select(ctx, cb.from_user.id, name, cb.message)  # identidad del que pulsa
    await cb.answer(f"Proveedor: {name}")


@router.callback_query(F.data == "prov:rm")
async def cb_prov_rm(cb: CallbackQuery, ctx):
    await cb.answer()
    rows = [p for p in await ctx.store.list_providers() if not p["builtin"]]
    if not rows:
        await cb.message.answer("No hay proveedores personalizados que eliminar.")
        return
    names = ", ".join(p["name"] for p in rows)
    await cb.message.answer(f"Para eliminar: /provider remove &lt;nombre&gt;\nPersonalizados: {names}")


# ------------------------------ API keys seguras ----------------------------


@router.message(Command("setapi"))
async def cmd_setapi(message: Message, ctx, command: CommandObject = None):
    """Clave via formulario temporal de un solo uso (NUNCA en mensajes normales)."""
    uid = message.from_user.id
    provider = (command.args or "").strip() if command and command.args else ""
    if provider:
        cfg = await ctx.store.get_provider(provider)
        if not cfg:
            await message.answer(f"Proveedor '{esc(provider)}' no existe. /providers")
            return
    else:
        provider = await ctx.providers.active_name(uid)
    token = ctx.store.new_token()
    await ctx.store.kv_set(f"form:{token}",
                           {"kind": "api_key", "user_id": uid, "provider": provider},
                           ttl_s=600)
    base = ctx.settings.form_base_url.rstrip("/") or f"http://{ctx.settings.form_host}:{ctx.settings.form_port}"
    url = f"{base}/set/{token}"
    await message.answer(
        "🔐 <b>Configuración segura de API key</b>\n\n"
        f"Proveedor: <b>{esc(provider)}</b>\n\n"
        "1) Abre este enlace de UN SOLO USO (expira en 10 min):\n"
        f"{esc(url)}\n\n"
        "2) El formulario solo escucha en 127.0.0.1 del VPS. Desde tu PC:\n"
        f"<code>ssh -L {ctx.settings.form_port}:127.0.0.1:{ctx.settings.form_port} tu-vps</code>\n\n"
        "La clave se guarda CIFRADA en la base de datos (bóveda) y nunca se muestra "
        "de nuevo en Telegram ni en logs. No la envíes por chat.")


@router.message(Command("testapi"))
async def cmd_testapi(message: Message, ctx):
    uid = message.from_user.id
    pname = await ctx.providers.active_name(uid)
    try:
        provider = await ctx.providers.get(uid)
        models = await provider.list_models()
        await message.answer(f"✅ <b>{esc(pname)}</b>: conexión y autenticación correctas. "
                             f"{len(models)} modelos disponibles (/models).")
    except Exception as e:
        await message.answer(f"❌ <b>{esc(pname)}</b>: {esc(e)[:300]}\n\n"
                             "Si es autenticación: /setapi")


# --------------------------------- modelos ----------------------------------


async def send_models(message: Message, ctx, page: int = 0, force: bool = False,
                      uid: int | None = None):
    uid = uid or message.from_user.id
    try:
        provider = await ctx.providers.get(uid)
        models = await ctx.catalog.list(provider, force=force)
    except Exception as e:
        await message.answer(provider_error_message(e))
        return
    if not models:
        await message.answer("El proveedor no devolvió modelos. /models refresh o /testapi")
        return
    ids = [m.id for m in models]
    active = await ctx.store.get_pref(uid, f"model:{provider.name}")
    text = [f"<b>📦 Modelos de {esc(provider.name)}</b> ({len(ids)})",
            f"Activo: <b>{esc(active or '(ninguno)')}</b>", ""]
    for i, m in enumerate(models[page * 8:(page + 1) * 8], start=page * 8):
        cw = f" · ctx {m.context_window // 1000}k" if m.context_window else ""
        text.append(f"• {esc(m.id)}{cw}")
    text.append("\nSelecciona con los botones o /model select &lt;nombre&gt;")
    await message.answer("\n".join(text), reply_markup=models_kb(ids, page))


@router.message(Command("models"))
async def cmd_models(message: Message, ctx, command: CommandObject = None):
    force = bool(command and command.args and "refresh" in command.args.lower())
    await send_models(message, ctx, force=force)


@router.message(Command("model"))
async def cmd_model(message: Message, ctx, command: CommandObject = None):
    uid = message.from_user.id
    arg = (command.args or "").strip() if command else ""
    pname = await ctx.providers.active_name(uid)
    if not arg:
        model = await ctx.store.get_pref(uid, f"model:{pname}") or "(ninguno)"
        await message.answer(f"🧠 Proveedor: <b>{esc(pname)}</b>\n📦 Modelo activo: "
                             f"<b>{esc(model)}</b>\n\n/model select &lt;nombre&gt; · /model info")
        return
    sub, _, rest = arg.partition(" ")
    if sub == "select":
        await _model_select(ctx, uid, rest.strip(), message)
    elif sub == "info":
        await _model_info(message, ctx)
    else:
        await _model_select(ctx, uid, arg, message)


async def _model_select(ctx, uid: int, model: str, message: Message):
    if not model:
        await message.answer("Uso: /model select &lt;nombre exacto&gt;")
        return
    try:
        provider = await ctx.providers.get(uid)
    except Exception as e:
        await message.answer(provider_error_message(e))
        return
    info = await ctx.catalog.ensure_model(provider, model, allow_configured=True)
    if info is None:
        try:
            models = await ctx.catalog.list(provider)
        except Exception:
            models = []
        names = ", ".join(m.id for m in models[:12])
        await message.answer("⚠️ Ese modelo no aparece en el catálogo actual del proveedor.\n"
                             f"Disponibles: {esc(names)}\n"
                             "No asumimos que exista: consulta /models refresh.")
        return
    await ctx.store.set_pref(uid, f"model:{provider.name}", model)
    await ctx.store.set_model_meta(provider.name, model, info.context_window, info.max_output)
    await message.answer(f"✔️ Modelo activo: <b>{esc(model)}</b>\n"
                         + (f"Contexto: {info.context_window:,}" if info.context_window else ""))


async def _model_info(message: Message, ctx):
    uid = message.from_user.id
    pname = await ctx.providers.active_name(uid)
    model = await ctx.store.get_pref(uid, f"model:{pname}") or "(ninguno)"
    provider = await ctx.providers.get(uid)
    info = None
    try:
        info = await ctx.catalog.ensure_model(provider, model)
    except Exception:
        pass
    rate = await ctx.store.get_rate(pname, model)
    meta = await ctx.store.get_model_meta(pname, model)
    lines = [f"<b>📦 {esc(model)}</b> @ {esc(pname)}"]
    if info and info.context_window:
        lines.append(f"Ventana de contexto: {info.context_window:,} tokens")
    if info and info.max_output:
        lines.append(f"Salida máxima: {info.max_output:,} tokens")
    if meta:
        lines.append(f"Meta local: ctx={meta['context_window']} out={meta['max_output']}")
    if rate:
        lines.append(f"Tarifa: in {rate['input_per_mtok']} / out {rate['output_per_mtok']} "
                     f"{rate['currency']} por 1M tokens")
    else:
        lines.append("Tarifa: sin configurar (/price set &lt;in&gt; &lt;out&gt; [moneda])")
    await message.answer("\n".join(lines))


@router.callback_query(F.data.startswith("mdl:sel:"))
async def cb_model_sel(cb: CallbackQuery, ctx):
    _, _, page, ref = cb.data.split(":", 3)
    if ref.isdigit():
        # seleccion por indice (nombres largos de modelo caben en el callback)
        provider = await ctx.providers.get(cb.from_user.id)
        models = await ctx.catalog.list(provider)
        idx = int(page) * 8 + int(ref)
        if 0 <= idx < len(models):
            await _model_select(ctx, cb.from_user.id, models[idx].id, cb.message)
    else:
        await _model_select(ctx, cb.from_user.id, ref, cb.message)
    await cb.answer("Modelo actualizado")


@router.callback_query(F.data.startswith("mdl:page:"))
async def cb_model_page(cb: CallbackQuery, ctx):
    page = int(cb.data.split(":")[2])
    await cb.answer()
    await send_models(cb.message, ctx, page=page, uid=cb.from_user.id)


@router.callback_query(F.data == "mdl:refresh")
async def cb_model_refresh(cb: CallbackQuery, ctx):
    await cb.answer("Actualizando catálogo...")
    await send_models(cb.message, ctx, force=True, uid=cb.from_user.id)


# ------------------------------ parametros ----------------------------------


def _num(text: str, lo: float, hi: float) -> float | None:
    try:
        v = float(text.replace(",", "."))
        return v if lo <= v <= hi else None
    except (TypeError, ValueError):
        return None


@router.message(Command("temperature"))
async def cmd_temperature(message: Message, ctx, command: CommandObject = None):
    uid = message.from_user.id
    if not command or not command.args:
        v = await ctx.store.get_pref(uid, "temperature")
        await message.answer(f"🌡 Temperature: {v if v is not None else '(por defecto del modelo)'}\n"
                             "Uso: /temperature &lt;0.0-2.0&gt; · /temperature off")
        return
    if command.args.strip().lower() in ("off", "none", "reset"):
        await ctx.store.set_pref(uid, "temperature", None)
        await message.answer("Temperature: por defecto del modelo.")
        return
    v = _num(command.args, 0, 2)
    if v is None:
        await message.answer("Valor inválido (0.0-2.0).")
        return
    await ctx.store.set_pref(uid, "temperature", str(v))
    await message.answer(f"✔️ Temperature = {v}")


@router.message(Command("top_p"))
async def cmd_top_p(message: Message, ctx, command: CommandObject = None):
    uid = message.from_user.id
    if not command or not command.args:
        v = await ctx.store.get_pref(uid, "top_p")
        await message.answer(f"🎯 Top P: {v if v is not None else '(por defecto del modelo)'}\n"
                             "Uso: /top_p &lt;0.0-1.0&gt; · /top_p off")
        return
    if command.args.strip().lower() in ("off", "none", "reset"):
        await ctx.store.set_pref(uid, "top_p", None)
        await message.answer("Top P: por defecto del modelo.")
        return
    v = _num(command.args, 0, 1)
    if v is None:
        await message.answer("Valor inválido (0.0-1.0).")
        return
    await ctx.store.set_pref(uid, "top_p", str(v))
    await message.answer(f"✔️ Top P = {v}")


@router.message(Command("max_tokens"))
async def cmd_max_tokens(message: Message, ctx, command: CommandObject = None):
    uid = message.from_user.id
    if not command or not command.args:
        v = await ctx.store.get_pref(uid, "max_tokens")
        await message.answer(f"📏 Max tokens: {v if v is not None else '(sin límite)'}\n"
                             "Uso: /max_tokens &lt;n&gt; · /max_tokens off")
        return
    if command.args.strip().lower() in ("off", "none", "reset"):
        await ctx.store.set_pref(uid, "max_tokens", None)
        await message.answer("Max tokens: sin límite.")
        return
    try:
        n = int(command.args)
        assert 1 <= n <= 200_000
    except (ValueError, AssertionError):
        await message.answer("Valor inválido (1-200000).")
        return
    await ctx.store.set_pref(uid, "max_tokens", str(n))
    await message.answer(f"✔️ Max tokens = {n}")


@router.message(Command("stream"))
async def cmd_stream(message: Message, ctx, command: CommandObject = None):
    uid = message.from_user.id
    arg = (command.args or "").strip().lower() if command else ""
    if arg not in ("on", "off"):
        cur = await ctx.store.get_pref(uid, "stream")
        await message.answer(f"📡 Streaming: {'ON' if cur == '1' else 'OFF'}\nUso: /stream on|off")
        return
    await ctx.store.set_pref(uid, "stream", "1" if arg == "on" else "0")
    await message.answer(f"📡 Streaming: {'ON' if arg == 'on' else 'OFF'}")


@router.message(Command("reasoning"))
async def cmd_reasoning(message: Message, ctx, command: CommandObject = None):
    uid = message.from_user.id
    arg = (command.args or "").strip().lower() if command else ""
    if not arg:
        cur = await ctx.store.get_pref(uid, "reasoning")
        await message.answer(f"🧮 Reasoning effort: {esc(cur or '(no configurado)')}\n"
                             "Uso: /reasoning low|medium|high · /reasoning off\n"
                             "(solo se envía si el modelo lo soporta)")
        return
    if arg == "off":
        await ctx.store.set_pref(uid, "reasoning", None)
        await message.answer("Reasoning: desactivado.")
        return
    if arg not in ("low", "medium", "high"):
        await message.answer("Nivel inválido: low · medium · high")
        return
    await ctx.store.set_pref(uid, "reasoning", arg)
    await message.answer(f"🧮 Reasoning effort = {arg} (solo proveedores que lo soporten)")


@router.message(Command("params"))
async def cmd_params(message: Message, ctx, command: CommandObject = None):
    uid = message.from_user.id
    arg = (command.args or "").strip().lower() if command else ""
    if arg == "reset":
        for key in ("temperature", "top_p", "max_tokens", "reasoning"):
            await ctx.store.set_pref(uid, key, None)
        await message.answer("♻️ Parámetros restablecidos a los valores por defecto del modelo.")
        return
    pname = await ctx.providers.active_name(uid)
    p = await ctx.store.all_prefs(uid)
    lines = [f"<b>🎚 Parámetros</b> (proveedor {esc(pname)})"]
    for key, label in (("temperature", "Temperature"), ("top_p", "Top P"),
                       ("max_tokens", "Max tokens"), ("stream", "Stream"),
                       ("reasoning", "Reasoning")):
        v = p.get(key)
        if key == "stream":
            v = "ON" if v == "1" else "OFF"
        lines.append(f"• {label}: {v if v not in (None, '') else '(por defecto)'}")
    lines.append("\n/params reset vuelve a los valores por defecto del modelo.")
    await message.answer("\n".join(lines))
