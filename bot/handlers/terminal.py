"""Terminal del proyecto dentro del sandbox + instalacion/tests/build."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from security.command_guard import CommandDenied
from ..utils import esc, send_long
from .helpers import get_project

router = Router(name="terminal")


async def _sandbox_for(message: Message, ctx, proj: dict):
    from pathlib import Path
    return await ctx.make_sandbox(Path(proj["path"]), proj)


@router.message(Command("terminal"))
async def cmd_terminal(message: Message, ctx, command: CommandObject = None):
    proj = await get_project(ctx, message)
    if not proj:
        return
    cmd = (command.args or "").strip() if command else ""
    if not cmd:
        await message.answer("Uso: /terminal <comando>\nEj: /terminal python --version")
        return
    sbx = await _sandbox_for(message, ctx, proj)
    try:
        await sbx.setup()
        res = await sbx.exec(cmd, timeout=ctx.settings.sandbox_timeout_s)
        await ctx.store.audit(message.from_user.id, "terminal", f"{proj['name']}: {cmd[:120]}")
        await send_long(message, f"<b>$ {esc(cmd)}</b>\n<pre>{esc(res.truncated(3500))}</pre>")
    except CommandDenied as e:
        await message.answer(f"⛔ Política de seguridad: {esc(e)}")
    except Exception as e:
        await message.answer(f"❌ {esc(e)}")


@router.message(Command("install"))
async def cmd_install(message: Message, ctx, command: CommandObject = None):
    proj = await get_project(ctx, message)
    if not proj:
        return
    cmd = (command.args or "").strip() if command else ""
    sbx = await _sandbox_for(message, ctx, proj)
    try:
        await sbx.setup()
        if not cmd:
            import asyncio as _a
            from pathlib import Path
            from security.path_guard import PathGuard
            from core.tools.context import AgentContext
            from core.tools.registry import detect_manager
            workspace = Path(proj["path"])
            ctx_tool = AgentContext(user_id=message.from_user.id,
                                    chat_id=message.chat.id, project=proj,
                                    workspace=workspace, guard=PathGuard(workspace),
                                    sandbox=sbx, services=ctx, cancel_event=_a.Event())
            detected = detect_manager(ctx_tool)
            if not detected:
                await message.answer("No detecto gestor de dependencias "
                                     "(requirements.txt, package.json, go.mod, pom.xml...). "
                                     "Usa: /install <comando>")
                return
            cmd = " ".join(detected)
        await message.answer(f"📦 Instalando: <code>{esc(cmd)}</code> ...")
        res = await sbx.exec(cmd, timeout=600)
        await send_long(message, f"<b>$ {esc(cmd)}</b>\n<pre>{esc(res.truncated(3000))}</pre>")
    except CommandDenied as e:
        await message.answer(f"⛔ {esc(e)}")
    except Exception as e:
        await message.answer(f"❌ {esc(e)}")


@router.message(Command("test"))
async def cmd_test(message: Message, ctx, command: CommandObject = None):
    proj = await get_project(ctx, message)
    if not proj:
        return
    cmd = (command.args or "").strip() or "python -m pytest -q"
    sbx = await _sandbox_for(message, ctx, proj)
    try:
        await sbx.setup()
        res = await sbx.exec(cmd, timeout=600)
        icon = "✅" if res.ok else "❌"
        await send_long(message, f"{icon} <b>$ {esc(cmd)}</b>\n<pre>{esc(res.truncated(3000))}</pre>")
    except CommandDenied as e:
        await message.answer(f"⛔ {esc(e)}")
    except Exception as e:
        await message.answer(f"❌ {esc(e)}")


@router.message(Command("build"))
async def cmd_build(message: Message, ctx, command: CommandObject = None):
    proj = await get_project(ctx, message)
    if not proj:
        return
    cmd = (command.args or "").strip() or "make"
    sbx = await _sandbox_for(message, ctx, proj)
    try:
        await sbx.setup()
        res = await sbx.exec(cmd, timeout=600)
        icon = "✅" if res.ok else "❌"
        await send_long(message, f"{icon} <b>$ {esc(cmd)}</b>\n<pre>{esc(res.truncated(3000))}</pre>")
    except CommandDenied as e:
        await message.answer(f"⛔ {esc(e)}")
    except Exception as e:
        await message.answer(f"❌ {esc(e)}")


@router.message(Command("processes"))
async def cmd_processes(message: Message, ctx):
    proj = await get_project(ctx, message)
    if not proj:
        return
    await message.answer("ℹ️ Los procesos corren dentro del sandbox del proyecto. "
                         "Usa /logs <id> para ver la actividad de tareas y "
                         "/sandbox status para el estado del contenedor.")


def proj_path(proj: dict):
    from pathlib import Path
    return Path(proj["path"])


@router.message(Command("sandbox"))
async def cmd_sandbox(message: Message, ctx, command: CommandObject = None):
    proj = await get_project(ctx, message)
    if not proj:
        return
    arg = (command.args or "").strip().lower() if command else ""
    from pathlib import Path
    sbx = await ctx.make_sandbox(Path(proj["path"]), proj)
    if arg == "reset":
        from ..keyboards import confirm_kb
        await message.answer("⚠️ ¿Reiniciar el sandbox del proyecto (se pierden procesos y "
                             "paquetes instalados, los archivos NO)?",
                             reply_markup=confirm_kb("sbxreset", str(proj["id"])))
        return
    if arg == "resources":
        await message.answer(
            f"⚙️ Límites del sandbox:\n"
            f"RAM: {ctx.settings.sandbox_memory_mb} MB\nCPU: {ctx.settings.sandbox_cpus}\n"
            f"Procesos: {ctx.settings.sandbox_pids}\nTimeout: {ctx.settings.sandbox_timeout_s}s\n"
            f"Red: {'sí' if proj.get('network_enabled', 1) else 'no'}")
        return
    info = sbx.info()
    lines = [f"<b>📦 Sandbox ({esc(info['kind'])})</b>"]
    for k, v in info.items():
        if k not in ("running", "workspace"):
            lines.append(f"• {k}: {esc(v)}")
    if info["kind"] == "local":
        lines.append("\n⚠️ Sandbox LOCAL (menor aislamiento). En producción usa Docker.")
    await message.answer("\n".join(lines))


@router.callback_query(F.data.startswith("sbxreset:"))
async def cb_sbx_reset(cb, ctx):
    _, yes_no, pid = cb.data.split(":")
    if yes_no != "yes":
        await cb.answer("Cancelado")
        return
    await cb.answer()
    proj = await ctx.store.get_project(int(pid))
    if not proj:
        return
    from pathlib import Path
    sbx = await ctx.make_sandbox(Path(proj["path"]), proj)
    try:
        await sbx.reset()
        await cb.message.edit_text("♻️ Sandbox reiniciado.")
    except Exception as e:
        await cb.message.edit_text(f"❌ {esc(e)}")
