"""Comandos del agente V3: /run, /task, colas, cancelacion, logs y eleccion."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from ..utils import esc, send_long, trunc
from .helpers import get_project
from .projects import ensure_project

router = Router(name="agent_cmds")


@router.message(Command("run"))
async def cmd_run(message: Message, ctx, command: CommandObject = None):
    if not command or not command.args:
        await message.answer("Uso: /run &lt;tarea de código&gt;\nEj: /run crea un API REST con "
                             "FastAPI que sume dos números y añade tests con pytest")
        return
    await submit_task(message, ctx, command.args.strip(), kind="agent")


@router.message(Command("task"))
async def cmd_task(message: Message, ctx, command: CommandObject = None):
    uid = message.from_user.id  # Bug 4: antes no estaba definido (NameError)
    if not command or not command.args:
        await message.answer("Uso: /task &lt;tarea&gt; · /task status &lt;id&gt; · "
                             "/task stop &lt;id&gt; · /task retry &lt;id&gt;")
        return
    parts = command.args.strip().split(None, 1)
    if parts[0] in ("status", "stop", "retry") and len(parts) == 2 and parts[1].isdigit():
        sub, tid = parts[0], int(parts[1])
        task = await ctx.store.get_task(tid)
        if not task or task["user_id"] != uid:
            await message.answer("Tarea no encontrada.")
            return
        if sub == "status":
            await _task_info(message, ctx, task)
        elif sub == "stop":
            ok = ctx.queue.cancel(tid) if ctx.queue else False
            if ok:
                await message.answer(f"🛑 Cancelación solicitada para #{tid}.")
            else:
                await ctx.store.update_task(tid, cancel_requested=1, status="cancelled")
                await message.answer(f"🛑 Tarea #{tid} no estaba en ejecución; marcada cancelada.")
        else:  # retry
            if task["status"] in ("done", "running"):
                await message.answer("La tarea ya está hecha o en ejecución.")
                return
            await ctx.store.update_task(tid, status="queued", error=None, steps=0)
            ctx.queue.kick()
            await message.answer(f"🔁 Tarea #{tid} reencolada.")
        return
    await submit_task(message, ctx, command.args.strip(), kind="agent")


async def submit_task(message: Message, ctx, title: str, kind: str = "agent") -> None:
    """Encola una tarea del agente. V3: sin proyecto crea/selecciona uno solo."""
    uid = message.from_user.id
    proj = await ensure_project(ctx, uid)
    from .chat import ensure_conversation
    conv = await ensure_conversation(ctx, uid)
    running = ctx.queue.running_for_user(uid)
    if running:
        await message.answer(f"⚠️ Ya tienes una tarea en ejecución (#{running[0]}). "
                             "Espera, cancela con /cancel o usa /queue.")
        return
    tid = await ctx.queue.submit(uid, message.chat.id, proj, conv["id"], title, kind=kind)
    mode = "multiagente" if kind == "multiagent" else "agente con herramientas"
    await message.answer(
        f"🚀 Tarea <b>#{tid}</b> encolada ({mode}).\n"
        f"📁 {esc(proj['name'])} · 🧠 {esc(await ctx.providers.active_name(uid))}\n"
        f"📋 {esc(trunc(title, 120))}\n\n"
        "Te iré contando el progreso aquí. Ver detalles: /task status " + str(tid))


@router.message(Command("tasks"))
async def cmd_tasks(message: Message, ctx):
    uid = message.from_user.id
    tasks = await ctx.store.list_tasks(uid, limit=15)
    if not tasks:
        await message.answer("No hay tareas todavía. Pídeme algo de código o usa /run &lt;tarea&gt;.")
        return
    from ..keyboards import tasks_kb
    lines = ["<b>⚙️ Tareas</b>"]
    for t in tasks:
        icon = {"queued": "⏳", "running": "🏃", "done": "✅", "failed": "❌",
                "cancelled": "🛑", "interrupted": "⚡"}.get(t["status"], "•")
        lines.append(f"{icon} #{t['id']} [{t['status']}] {esc(trunc(t['title'], 44))}")
    await message.answer("\n".join(lines), reply_markup=tasks_kb(tasks))


@router.message(Command("queue"))
async def cmd_queue(message: Message, ctx):
    queued = await ctx.store.list_tasks(status="queued", limit=10)
    running = await ctx.store.list_tasks(status="running", limit=10)
    await message.answer(f"⏳ En cola: {len(queued)}\n🏃 En ejecución: {len(running)}\n"
                         "(máx 1 tarea simultánea por usuario)")


@router.message(Command("logs"))
async def cmd_logs(message: Message, ctx, command: CommandObject = None):
    uid = message.from_user.id
    tid = None
    if command and command.args and command.args.strip().isdigit():
        tid = int(command.args.strip())
    else:
        running = ctx.queue.running_for_user(uid)
        if running:
            tid = running[0]
    if not tid:
        await message.answer("Uso: /logs &lt;id de tarea&gt;")
        return
    task = await ctx.store.get_task(tid)
    if not task or task["user_id"] != uid:
        await message.answer("Tarea no encontrada.")
        return
    logs = await ctx.store.kv_get(f"tasklog:{tid}") or []
    text = "\n".join(logs[-40:]) if logs else "(sin registros aún)"
    await send_long(message, f"<b>📜 Logs tarea #{tid}</b>\n<pre>{esc(text)}</pre>")


async def _task_info(message: Message, ctx, task: dict):
    icon = {"queued": "⏳", "running": "🏃", "done": "✅", "failed": "❌",
            "cancelled": "🛑", "interrupted": "⚡"}.get(task["status"], "•")
    lines = [f"{icon} <b>Tarea #{task['id']}</b> [{task['status']}]",
             f"📋 {esc(task['title'][:200])}",
             f"Pasos: {task['steps']}/{task['max_steps']}"]
    if task.get("result"):
        lines.append("\n" + esc(trunc(task["result"], 2500)))
    if task.get("error"):
        lines.append(f"\n❌ {esc(task['error'])}")
    await send_long(message, "\n".join(lines))


@router.callback_query(F.data.startswith("task:info:"))
async def cb_task_info(cb: CallbackQuery, ctx):
    await cb.answer()
    task = await ctx.store.get_task(int(cb.data.split(":")[2]))
    if task and task["user_id"] == cb.from_user.id:
        await _task_info(cb.message, ctx, task)


# ------------------- elección ambigua: tarea vs chat ------------------------


@router.callback_query(F.data.startswith("choice:"))
async def cb_choice(cb: CallbackQuery, ctx):
    await cb.answer()
    _, what, token = cb.data.split(":", 2)
    text = await ctx.store.kv_get(f"choice:{token}")
    if text is None:
        await cb.message.answer("⌛ La solicitud expiró; reenvíame tu mensaje, por favor.")
        return
    await ctx.store.kv_del(f"choice:{token}")
    if what == "task":
        await submit_task(cb.message, ctx, str(text))
    else:
        from .chat import run_plain_chat
        await run_plain_chat(cb.message, ctx, cb.from_user.id, str(text))
