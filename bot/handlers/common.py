"""Comandos basicos: start, help, menu, status, health, version, settings, cancel."""
from __future__ import annotations

import asyncio
import shutil
import time

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from ..keyboards import main_menu_kb
from ..utils import esc, fmt_bytes, send_long
from .helpers import balance_line, provider_model

router = Router(name="common")

VERSION = "2.0.0"


def _menu_text(pname: str, model: str, proj_name: str | None, running: list, saldo: str) -> str:
    lines = [
        "<b>HJ CODE AGENT V2</b>",
        "🤖 Agente de programación",
        "",
        f"🧠 Proveedor: <b>{esc(pname)}</b> · Modelo: <b>{esc(model)}</b>",
        f"📁 Proyecto: <b>{esc(proj_name or '(ninguno)')}</b>",
        f"⚙️ Tarea en ejecución: <b>{', '.join(f'#{t}' for t in running) or 'ninguna'}</b>",
        f"💳 {saldo}",
        "",
        "Elige una opción:",
    ]
    return "\n".join(lines)


@router.message(CommandStart())
async def cmd_start(message: Message, ctx):
    await message.answer(
        "👋 <b>HJ CODE AGENT V2</b>\n\n"
        "Agente de programación real: chat con IA, proyectos, sandbox aislado, "
        "GitHub, saldo y consumo reales.\n\n"
        "📌 Recuerda: <b>modo nativo</b> por defecto — sin system prompt oculto.\n"
        "Escribe /help para ver todos los comandos.",
        reply_markup=main_menu_kb())


@router.message(Command("menu"))
async def cmd_menu(message: Message, ctx):
    await _show_menu(message)


async def _show_menu(message: Message):
    user_id = message.from_user.id
    pname, model = await provider_model(ctx, user_id)
    proj = await ctx.projects.active(user_id)
    running = ctx.queue.running_for_user(user_id) if ctx.queue else []
    saldo = await balance_line(ctx, user_id)
    await message.answer(_menu_text(pname, model, proj["name"] if proj else None, running, saldo),
                         reply_markup=main_menu_kb())


@router.message(Command("help"))
async def cmd_help(message: Message, ctx):
    await send_long(message, HELP_TEXT)


@router.message(Command("version"))
async def cmd_version(message: Message, ctx):
    import core
    await message.answer(f"HJ Code Agent <b>v{core.__version__}</b>\nPython runtime OK")


@router.message(Command("status"))
async def cmd_status(message: Message, ctx):
    uid = message.from_user.id
    pname, model = await provider_model(ctx, uid)
    proj = await ctx.projects.active(uid)
    running = ctx.queue.running_for_user(uid) if ctx.queue else []
    tasks = await ctx.store.list_tasks(uid, limit=5)
    saldo = await balance_line(ctx, uid)
    lines = [
        "<b>📊 Estado</b>",
        f"🧠 {esc(pname)} / {esc(model)}",
        f"📁 Proyecto: {esc(proj['name']) if proj else 'ninguno'}",
        f"💬 Conversación activa: #{await ctx.store.get_pref(uid, 'active_conversation') or '-'}",
        f"⚙️ En ejecución: {running or 'nada'}",
        f"💳 {saldo}",
    ]
    if tasks:
        lines.append("\nÚltimas tareas:")
        for t in tasks:
            icon = {"done": "✅", "failed": "❌", "running": "🏃", "queued": "⏳",
                    "cancelled": "🛑", "interrupted": "⚡"}.get(t["status"], "•")
            lines.append(f"  {icon} #{t['id']} {esc(t['title'][:40])} [{t['status']}]")
    await send_long(message, "\n".join(lines))


@router.message(Command("health"))
async def cmd_health(message: Message, ctx):
    checks = {"database": "ok", "boveda": "ok" if ctx.vault else "SIN CLAVE MAESTRA",
              "cola": "ok" if ctx.queue else "parada"}
    disk = shutil.disk_usage(ctx.settings.workspaces_dir)
    from core.sandbox.factory import docker_available
    docker_ok = await docker_available()
    kind = ctx.settings.sandbox_backend
    up = ctx.uptime_s()
    await message.answer(
        "<b>🩺 Salud del sistema</b>\n"
        f"• Base de datos: {checks['database']} (WAL activo)\n"
        f"• Bóveda cifrada: {checks['boveda']}\n"
        f"• Cola de tareas: {checks['cola']}\n"
        f"• Sandbox backend: <b>{esc(kind)}</b> (Docker disponible: {'sí' if docker_ok else 'no'})\n"
        f"• Disco workspaces: libre {fmt_bytes(disk.free)} de {fmt_bytes(disk.total)}\n"
        f"• Uptime: {up // 60} min {up % 60} s")


@router.message(Command("settings"))
async def cmd_settings(message: Message, ctx):
    from ..keyboards import settings_kb
    await message.answer("🔧 <b>Configuración</b>\nElige qué ajustar:", reply_markup=settings_kb())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, ctx):
    uid = message.from_user.id
    running = ctx.queue.running_for_user(uid)
    if not running:
        await message.answer("No hay tareas en ejecución.")
        return
    for tid in running:
        ctx.queue.cancel(tid)
    await message.answer(f"🛑 Cancelación solicitada para: {', '.join(map(str, running))}")


# ---------------------------- callbacks de menú ----------------------------


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery):
    await cb.answer()


@router.callback_query(F.data.startswith("menu:"))
async def cb_menu(cb: CallbackQuery, ctx):
    await cb.answer()
    section = cb.data.split(":", 1)[1]
    msg = cb.message
    if section == "chatinfo":
        uid = cb.from_user.id
        pname, model = await provider_model(ctx, uid)
        await msg.answer(
            f"💬 <b>Chat con IA</b>\n\nEscribe directamente cualquier mensaje (sin barra) y "
            f"te respondo con <b>{esc(model)}</b> vía <b>{esc(pname)}</b>.\n\n"
            "El modo es nativo: sin system prompt oculto.\n"
            "Para tareas de código con herramientas usa <code>/run &lt;tarea&gt;</code>.")
        return
    if section == "newproject":
        await msg.answer("📁 Nuevo proyecto: envía <code>/newproject Nombre</code>")
        return
    if section == "projects":
        from . import projects as pm
        await pm.show_projects(msg, ctx)
        return
    if section == "upload":
        await msg.answer("📤 Subida: envía un archivo (.py, .txt, .zip...) como documento "
                         "y quedará en el proyecto activo.")
        return
    if section == "github":
        from . import github_cmds as gh
        await gh.show_github_menu(msg, ctx)
        return
    if section == "providers":
        from . import providers as pv
        await pv.show_providers(msg, ctx)
        return
    if section == "sysprompt":
        from . import system_prompt as sp
        await sp.show_prompt_menu(msg, ctx)
        return
    if section == "billing":
        await msg.answer("💳 <b>Saldo y tokens</b>\n/balance · /tokens · /usage · /cost · "
                         "/stats · /budget · /alerts · /limits")
        return
    if section == "tasks":
        await msg.answer("⚙️ <b>Trabajos</b>\n/run · /tasks · /task status · /task stop · "
                         "/task retry · /queue · /logs · /cancel")
        return
    if section == "terminal":
        await msg.answer("🖥 <b>Terminal</b>\n/terminal &lt;cmd&gt; · /install · /test · /build · "
                         "/processes · /sandbox status")
        return
    if section == "stats":
        from . import billing as bl
        await bl.send_stats(msg, ctx)
        return
    if section == "settings":
        from .common import cmd_settings  # evita ciclo
        await cmd_settings(msg, ctx)
        return
    if section == "help":
        await cmd_help(msg, ctx)
        return


HELP_TEXT = """<b>📖 Comandos de HJ Code Agent V2</b>

<b>General</b>
/start · /menu · /help · /status · /health · /version · /settings · /cancel

<b>Chat y memoria</b>
/newchat · /chats · /chat select &lt;id&gt; · /history · /clear · /reset
/exportchat · /searchchat &lt;texto&gt; · /session · /sessions
/memory &lt;nota&gt; · /memory list · /memory clear

<b>System prompts</b>
/system · /system set · /system edit · /system show · /system off
/system clear · /system reset · /system export · /system import · /system project

<b>Proveedores y modelos</b>
/provider · /providers · /provider add · /provider select &lt;nombre&gt; · /provider remove &lt;nombre&gt;
/setapi · /testapi · /models [refresh] · /model · /model info · /model select &lt;nombre&gt;
/temperature &lt;0-2&gt; · /top_p &lt;0-1&gt; · /max_tokens &lt;n&gt; · /context
/stream on|off · /reasoning &lt;nivel&gt; · /params · /params reset · /price set &lt;modelo&gt; &lt;in&gt; &lt;out&gt; [moneda]

<b>Saldo, tokens y consumo</b>
/balance [refresh] · /tokens · /usage · /cost [today|month] · /limits · /budget
/stats · /alerts

<b>Proyectos y archivos</b>
/newproject &lt;nombre&gt; · /projects · /project select &lt;ref&gt; · /project info
/project rename &lt;nombre&gt; · /project export · /project archive · /project delete
/files [ruta] · /file read &lt;ruta&gt; · /file edit · /file download &lt;ruta&gt; · /upload
/workspace · /backup · /restore

<b>Agente y tareas</b>
/run &lt;tarea&gt; · /task &lt;tarea&gt; · /tasks · /task status &lt;id&gt; · /task stop &lt;id&gt;
/task retry &lt;id&gt; · /queue · /logs [id] · /cancel

<b>Terminal y sandbox</b>
/terminal &lt;cmd&gt; · /install · /test · /build · /processes
/sandbox status · /sandbox reset · /sandbox resources

<b>GitHub</b>
/github · /github connect · /github status · /github disconnect
/repo add &lt;url&gt; · /repo clone &lt;url&gt; [rama] · /repo info · /repos
/branch [nombre] · /branches · /checkout &lt;rama&gt; · /gitstatus · /diff
/commit &lt;mensaje&gt; · /push [rama] · /pull · /pr &lt;titulo&gt; · /history
/rollback &lt;archivo&gt; · /autopush on|off

<b>Multiagente (opcional)</b>
/agents · /agents on · /agents off · /agents add · /agents remove
/agents config · /agents status · /agents models

<b>Administración</b>
/admin · /users · /authorize &lt;id&gt; [admin] · /revoke &lt;id&gt; · /security
/audit · /alerts · /notifications · /diagnostics · /config export · /config import

<b>Notas</b>
• Mensajes sin barra = chat directo con el modelo (modo nativo, sin prompt oculto).
• /run ejecuta una tarea de código REAL con herramientas en el sandbox.
• El push a GitHub SIEMPRE pide tu autorización con botones."""
