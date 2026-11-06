"""Chat directo con la IA + gestion de conversaciones y memoria.

REGLA FUNDAMENTAL: aqui no se inyecta ningun system prompt oculto. Si el modo
es nativo, los mensajes enviados son EXACTAMENTE el historial + el mensaje del
usuario. Ver core/prompts/service.py y tests/test_no_default_system_prompt.py.
"""
from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, Message

from ..utils import esc, send_long, trunc
from .helpers import provider_model, provider_error_message

commands_router = Router(name="chat_cmds")
free_text_router = Router(name="chat_free")


# --------------------------- helpers de conversacion ------------------------


async def ensure_conversation(ctx, user_id: int) -> dict:
    cid = await ctx.store.get_pref(user_id, "active_conversation")
    conv = await ctx.store.get_conversation(int(cid)) if cid else None
    if not conv or conv["user_id"] != user_id:
        pname = await ctx.providers.active_name(user_id)
        model = await ctx.store.get_pref(user_id, f"model:{pname}") or ""
        cid = await ctx.store.create_conversation(user_id, None, pname, model, "Chat")
        await ctx.store.set_pref(user_id, "active_conversation", cid)
        conv = await ctx.store.get_conversation(cid)
    return conv


def rows_to_api(rows: list[dict]) -> list[dict]:
    """Filas de BD -> formato API (incluye pares tool_call/tool reales)."""
    out = []
    for r in rows:
        role = r["role"]
        if role == "tool":
            out.append({"role": "tool", "tool_call_id": r["tool_call_id"] or "",
                        "content": r["content"] or ""})
            continue
        m = {"role": role, "content": r["content"]}
        if r.get("tool_calls"):
            m["tool_calls"] = [{"id": tc["id"], "type": "function",
                                "function": {"name": tc["name"],
                                             "arguments": tc.get("arguments", "{}")}}
                               for tc in r["tool_calls"]]
            if not m["content"]:
                m["content"] = None
        out.append(m)
    return out


@free_text_router.message(F.text & ~F.text.startswith("/"))
async def free_chat(message: Message, ctx):
    uid = message.from_user.id
    conv = await ensure_conversation(ctx, uid)
    pname = await ctx.providers.active_name(uid)
    model = await ctx.store.get_pref(uid, f"model:{pname}")
    if not model:
        await message.answer("🧠 Primero elige un modelo: /models y /model select <nombre>")
        return
    try:
        provider = await ctx.providers.get(uid)
    except Exception as e:
        await message.answer(provider_error_message(e))
        return
    history = await ctx.store.get_messages(conv["id"], limit=30)
    # En modo nativo NO se anade system: build_messages devuelve el historial tal cual
    proj = await ctx.projects.active(uid)
    messages = await ctx.prompts.build_messages(uid, rows_to_api(history), proj)
    messages.append({"role": "user", "content": message.text})
    await ctx.store.add_message(conv["id"], "user", message.text)
    await ctx.store.touch_conversation(conv["id"], provider=pname, model=model)
    typing_msg = await message.answer("✍️")
    use_stream = (await ctx.store.get_pref(uid, "stream")) == "1"
    try:
        if use_stream and provider.capabilities.stream:
            async def on_delta(piece: str):
                pass  # el texto final se envia al terminar (evita ediciones masivas)

            result = await provider.chat(messages, model=model, stream=True, on_delta=on_delta)
        else:
            result = await provider.chat(messages, model=model)
        cost = await ctx.usage.record(uid, pname, model, result.usage,
                                      conversation_id=conv["id"],
                                      project_id=proj["id"] if proj else None)
        text = result.content or "(respuesta vacía)"
        await ctx.store.add_message(conv["id"], "assistant", text,
                                    tokens_in=result.usage.prompt_tokens if result.usage else 0,
                                    tokens_out=result.usage.completion_tokens if result.usage else 0,
                                    cost=cost or 0.0)
        footer = f"\n\n<i>{esc(model)} · {result.usage.total_tokens if result.usage else '?'} tokens"
        footer += f" · {cost:.4f} USD</i>" if cost is not None else "</i>"
        await send_long(message, esc(text) + footer)
    except Exception as e:
        await message.answer(provider_error_message(e))
    finally:
        try:
            await typing_msg.delete()
        except Exception:
            pass


# --------------------------- comandos de conversacion -----------------------


@commands_router.message(Command("newchat"))
async def cmd_newchat(message: Message, ctx):
    uid = message.from_user.id
    conv = await ensure_conversation(ctx, uid)
    title = f"Chat #{conv['id'] + 1}"
    pname, model = await provider_model(ctx, uid)
    cid = await ctx.store.create_conversation(uid, None, pname, model, title)
    await ctx.store.set_pref(uid, "active_conversation", cid)
    await message.answer(f"🆕 Nueva conversación #{cid}. El historial anterior se conserva "
                         f"en /chats.")


@commands_router.message(Command("chats"))
async def cmd_chats(message: Message, ctx):
    uid = message.from_user.id
    active = await ctx.store.get_pref(uid, "active_conversation")
    convs = await ctx.store.list_conversations(uid, limit=15)
    if not convs:
        await message.answer("No hay conversaciones todavía.")
        return
    lines = ["<b>💬 Conversaciones</b>"]
    for c in convs:
        mark = "●" if str(c["id"]) == str(active) else "○"
        lines.append(f"{mark} <b>#{c['id']}</b> {esc(trunc(c['title'] or '(sin título)', 30))} "
                     f"· {c['n_msgs']} msj · {esc(c['model'] or '-')}")
    lines.append("\nCambiar: /chat select <id>")


@commands_router.message(Command("chat"))
async def cmd_chat(message: Message, ctx, command: CommandObject):
    uid = message.from_user.id
    if not command.args or not command.args.replace("select", "").strip().isdigit():
        await message.answer("Uso: /chat select <id>")
        return
    cid = int(command.args.replace("select", "").strip())
    conv = await ctx.store.get_conversation(cid)
    if not conv or conv["user_id"] != uid:
        await message.answer("Conversación no encontrada.")
        return
    await ctx.store.set_pref(uid, "active_conversation", cid)
    await message.answer(f"✔️ Conversación activa: #{cid} ({conv['n_msgs'] if conv.get('n_msgs') else await ctx.store.count_messages(cid)} mensajes)")


@commands_router.message(Command("history"))
async def cmd_history(message: Message, ctx):
    uid = message.from_user.id
    conv = await ensure_conversation(ctx, uid)
    rows = await ctx.store.get_messages(conv["id"], limit=10)
    if not rows:
        await message.answer("(historial vacío)")
        return
    lines = [f"<b>Historial #{conv['id']} (últimos {len(rows)})</b>"]
    for r in rows:
        icon = {"user": "🧑", "assistant": "🤖", "tool": "🔧", "system": "⚙️"}.get(r["role"], "•")
        content = r["content"] or ("[tool_calls]" if r.get("tool_calls") else "")
        lines.append(f"{icon} <b>{r['role']}</b>: {esc(trunc(content, 220))}")
    await send_long(message, "\n\n".join(lines))


@commands_router.message(Command("clear"))
async def cmd_clear(message: Message, ctx):
    uid = message.from_user.id
    conv = await ensure_conversation(ctx, uid)
    await ctx.store.clear_messages(conv["id"])
    await message.answer(f"🧹 Historial de la conversación #{conv['id']} vaciado "
                         "(la conversación sigue activa).")


@commands_router.message(Command("reset"))
async def cmd_reset(message: Message, ctx):
    """Reinicio total de sesion de chat: conversacion nueva + sin prompt."""
    uid = message.from_user.id
    conv = await ensure_conversation(ctx, uid)
    await ctx.store.clear_messages(conv["id"])
    await ctx.store.set_pref(uid, "active_conversation", None)
    await message.answer("♻️ Sesión de chat reiniciada (historial vaciado). "
                         "El system prompt configurado no cambia: usa /system reset para el modo nativo.")


@commands_router.message(Command("exportchat"))
async def cmd_exportchat(message: Message, ctx):
    uid = message.from_user.id
    conv = await ensure_conversation(ctx, uid)
    rows = await ctx.store.get_messages(conv["id"])
    data = json.dumps({"conversation": conv, "messages": rows}, ensure_ascii=False, indent=2)
    await message.answer_document(
        BufferedInputFile(data.encode(), filename=f"chat-{conv['id']}.json"),
        caption=f"📤 Exportación de la conversación #{conv['id']} ({len(rows)} mensajes)")


@commands_router.message(Command("searchchat"))
async def cmd_searchchat(message: Message, ctx, command: CommandObject):
    uid = message.from_user.id
    if not command.args:
        await message.answer("Uso: /searchchat <texto>")
        return
    rows = await ctx.store.search_messages(uid, command.args, limit=10)
    if not rows:
        await message.answer("Sin resultados.")
        return
    lines = [f"🔎 <b>{len(rows)} resultado(s)</b>"]
    for r in rows:
        lines.append(f"#{r['conversation_id']} [{r['role']}] {esc(trunc(r['content'], 160))}")
    await send_long(message, "\n".join(lines))


@commands_router.message(Command("session"))
@commands_router.message(Command("sessions"))
async def cmd_sessions(message: Message, ctx):
    uid = message.from_user.id
    conv = await ensure_conversation(ctx, uid)
    total = await ctx.store.count_messages(conv["id"])
    await message.answer(
        f"<b>Sesión actual</b>\nConversación: #{conv['id']}\nMensajes: {total}\n"
        f"Proveedor: {esc(conv['provider'])} · Modelo: {esc(conv['model'] or '-')}\n"
        "Uso /chats para ver todas.")


@commands_router.message(Command("context"))
async def cmd_context(message: Message, ctx):
    uid = message.from_user.id
    pname, model = await provider_model(ctx, uid)
    provider = await ctx.providers.get(uid)
    window = await ctx.catalog.context_window(provider, model)
    conv = await ensure_conversation(ctx, uid)
    rows = await ctx.store.get_messages(conv["id"])
    chars = sum(len(r["content"] or "") for r in rows)
    est_tokens = chars // 4
    lines = [f"<b>📐 Contexto</b>\nModelo: {esc(model)}"]
    if window:
        pct = 100 * est_tokens / window
        lines.append(f"Ventana: {window:,} tokens · ocupación estimada: {est_tokens:,} ({pct:.1f}%)")
        lines.append("Barra: " + "▰" * int(min(pct, 100) // 5) + "▱" * max(0, 20 - int(min(pct, 100) // 5)))
    else:
        lines.append(f"Ventana: no publicada por el proveedor · estimación local: {est_tokens:,} tokens")
    await message.answer("\n".join(lines))
