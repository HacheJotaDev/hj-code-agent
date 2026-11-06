"""Proyectos, archivos, subidas validadas y backups."""
from __future__ import annotations

import asyncio
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from ..keyboards import project_actions_kb, projects_kb
from ..states import ProjectStates
from ..utils import esc, fmt_bytes, send_long, trunc
from .helpers import get_project

router = Router(name="projects")


async def show_projects(message: Message, ctx):
    uid = message.from_user.id
    rows = await ctx.projects.list(uid)
    active = await ctx.projects.active(uid)
    if not rows:
        await message.answer("No hay proyectos. Crea uno: /newproject <nombre>")
        return
    lines = ["<b>🗂 Proyectos</b>"]
    for p in rows:
        mark = "●" if active and p["id"] == active["id"] else "○"
        lines.append(f"{mark} #{p['id']} <b>{esc(p['name'])}</b>")
    lines.append("\nSelecciona con botones o /project select <id|nombre>")
    await message.answer("\n".join(lines), reply_markup=projects_kb(rows, active["id"] if active else None))


@router.message(Command("projects"))
async def cmd_projects(message: Message, ctx):
    await show_projects(message, ctx)


@router.message(Command("newproject"))
async def cmd_newproject(message: Message, ctx, command: CommandObject = None, state: FSMContext = None):
    if not command or not command.args:
        if state:
            await state.set_state(ProjectStates.waiting_name)
        await message.answer("📁 Envía el nombre del proyecto (o /newproject Nombre).")
        return
    await _create(message, ctx, command.args.strip())


async def _create(message: Message, ctx, name: str):
    try:
        proj = await ctx.projects.create(message.from_user.id, name)
    except Exception as e:
        await message.answer(f"❌ {esc(e)}")
        return
    await ctx.store.set_pref(message.from_user.id, "active_project", proj["id"])
    await message.answer(f"✅ Proyecto <b>{esc(name)}</b> creado y seleccionado.\n"
                         f"Ruta: {esc(proj['path'])}\n\nSube archivos (documento) o usa el agente: "
                         f"/run <tarea>")


@router.message(ProjectStates.waiting_name, F.text)
async def on_project_name(message: Message, ctx, state: FSMContext):
    await state.clear()
    await _create(message, ctx, message.text.strip()[:48])


@router.message(Command("project"))
async def cmd_project(message: Message, ctx, command: CommandObject = None):
    uid = message.from_user.id
    arg = (command.args or "").strip() if command else ""
    if not arg:
        proj = await ctx.projects.active(uid)
        if proj:
            await _info(message, ctx, proj)
        else:
            await show_projects(message, ctx)
        return
    sub, _, rest = arg.partition(" ")
    if sub == "select":
        try:
            proj = await ctx.projects.select(uid, rest.strip())
        except Exception as e:
            await message.answer(f"❌ {esc(e)}")
            return
        await message.answer(f"✔️ Proyecto activo: <b>{esc(proj['name'])}</b>")
    elif sub == "info":
        proj = await get_project(ctx, message)
        if proj:
            await _info(message, ctx, proj)
    elif sub == "rename":
        proj = await get_project(ctx, message)
        if proj and rest:
            await ctx.projects.rename(uid, proj["id"], rest.strip()[:48])
            await message.answer(f"✔️ Renombrado a <b>{esc(rest.strip())}</b>")
    elif sub == "export":
        proj = await get_project(ctx, message)
        if proj:
            await _export(message, ctx, proj)
    elif sub == "archive":
        proj = await get_project(ctx, message)
        if proj:
            out = await ctx.projects.archive(uid, proj["id"])
            await message.answer(f"💾 Archivado en {esc(str(out))}")
    elif sub == "delete":
        proj = await get_project(ctx, message)
        if proj:
            from ..keyboards import confirm_kb
            await message.answer(
                f"⚠️ ¿Borrar DEFINITIVAMENTE el proyecto '{esc(proj['name'])}' y su carpeta?\n"
                "Exporta antes si lo necesitas: /project export",
                reply_markup=confirm_kb("projdel", str(proj["id"])))
    else:
        await message.answer("Subcomandos: select · info · rename · export · archive · delete")


async def _info(message: Message, ctx, proj):
    info = await ctx.projects.info(proj["id"])
    p, git = info["project"], info["git"]
    lines = [f"<b>📁 {esc(p['name'])}</b> (#{p['id']})",
             f"Ruta: {esc(p['path'])}",
             f"Archivos: {info['files']} · Tamaño: {fmt_bytes(info['size_bytes'])}",
             f"Red en sandbox: {'sí' if p['network_enabled'] else 'no'}",
             f"Prompt de proyecto: {'activado' if p['prompt_enabled'] else 'desactivado'}"]
    if git.get("repo_url"):
        lines.append(f"GitHub: {esc(git['repo_url'])} (rama {esc(git.get('current_branch') or '-')}, "
                     f"autopush {'ON' if git.get('autopush') else 'OFF'})")
    await message.answer("\n".join(lines), reply_markup=project_actions_kb(proj["id"]))


async def _export(message: Message, ctx, proj):
    out = await ctx.projects.export_zip(proj["id"])
    await message.answer_document(BufferedInputFile(out.read_bytes(), out.name),
                                  caption=f"📦 Proyecto {esc(proj['name'])}")


@router.callback_query(F.data.startswith("proj:sel:"))
async def cb_proj_sel(cb: CallbackQuery, ctx):
    pid = int(cb.data.split(":")[2])
    proj = await ctx.store.get_project(pid)
    if not proj or proj["user_id"] != cb.from_user.id:
        await cb.answer("No encontrado", show_alert=True)
        return
    await ctx.store.set_pref(cb.from_user.id, "active_project", pid)
    await cb.answer(f"Activo: {proj['name']}")
    await cb.message.answer(f"✔️ Proyecto activo: <b>{esc(proj['name'])}</b>")


@router.callback_query(F.data.startswith("proj:info:"))
async def cb_proj_info(cb: CallbackQuery, ctx):
    await cb.answer()
    proj = await ctx.store.get_project(int(cb.data.split(":")[2]))
    if proj and proj["user_id"] == cb.from_user.id:
        await _info(cb.message, ctx, proj)


@router.callback_query(F.data.startswith("proj:export:"))
async def cb_proj_export(cb: CallbackQuery, ctx):
    await cb.answer("Preparando ZIP...")
    proj = await ctx.store.get_project(int(cb.data.split(":")[2]))
    if proj and proj["user_id"] == cb.from_user.id:
        await _export(cb.message, ctx, proj)


@router.callback_query(F.data.startswith("proj:archive:"))
async def cb_proj_archive(cb: CallbackQuery, ctx):
    await cb.answer()
    proj = await ctx.store.get_project(int(cb.data.split(":")[2]))
    if proj and proj["user_id"] == cb.from_user.id:
        out = await ctx.projects.archive(cb.from_user.id, proj["id"])
        await cb.message.answer(f"💾 Archivado en {esc(str(out))}")


@router.callback_query(F.data.startswith("proj:del:"))
async def cb_proj_del(cb: CallbackQuery, ctx):
    await cb.answer()
    proj = await ctx.store.get_project(int(cb.data.split(":")[2]))
    if proj and proj["user_id"] == cb.from_user.id:
        from ..keyboards import confirm_kb
        await cb.message.answer(
            f"⚠️ ¿Confirmas el borrado DEFINITIVO de '{esc(proj['name'])}'?",
            reply_markup=confirm_kb("projdel", str(proj["id"])))


@router.callback_query(F.data.startswith("projdel:"))
async def cb_proj_del_confirm(cb: CallbackQuery, ctx):
    _, yes_no, pid = cb.data.split(":")
    if yes_no != "yes":
        await cb.answer("Cancelado")
        await cb.message.edit_text("Borrado cancelado.")
        return
    await cb.answer()
    try:
        await ctx.projects.delete(cb.from_user.id, int(pid), confirmed=True)
        await cb.message.edit_text("🗑 Proyecto eliminado definitivamente.")
    except Exception as e:
        await cb.message.edit_text(f"❌ {esc(e)}")


# ------------------------------- archivos -----------------------------------


@router.message(Command("files"))
async def cmd_files(message: Message, ctx, command: CommandObject = None):
    proj = await get_project(ctx, message)
    if not proj:
        return
    base = Path(proj["path"])
    sub = (command.args or "").strip() if command else ""
    from security.path_guard import PathGuard, PathDenied
    guard = PathGuard(base)
    try:
        target = guard.resolve(sub or ".", must_exist=True)
    except PathDenied as e:
        await message.answer(f"⛔ {esc(e)}")
        return
    if target.is_file():
        await message.answer(f"Es un archivo. /file read {esc(sub)}")
        return
    entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name))
    lines = [f"<b>📂 {esc(sub or '.')}</b>"]
    for p in entries[:100]:
        rel = p.relative_to(base).as_posix()
        size = p.stat().st_size if p.is_file() else 0
        icon = "📄" if p.is_file() else "📁"
        lines.append(f"{icon} {esc(rel)} {fmt_bytes(size) if size else ''}")
    if not entries:
        lines.append("(vacío)")
    await send_long(message, "\n".join(lines))


@router.message(Command("file"))
async def cmd_file(message: Message, ctx, command: CommandObject = None):
    proj = await get_project(ctx, message)
    if not proj:
        return
    arg = (command.args or "").strip() if command else ""
    sub, _, rest = arg.partition(" ")
    from security.path_guard import PathGuard, PathDenied
    guard = PathGuard(Path(proj["path"]))
    if sub == "read":
        try:
            f = guard.resolve(rest, must_exist=True)
            data = f.read_bytes()[:256 * 1024]
            await send_long(message, f"<pre>{esc(data.decode('utf-8', 'replace'))}</pre>")
        except (PathDenied, OSError) as e:
            await message.answer(f"❌ {esc(e)}")
    elif sub == "download":
        try:
            f = guard.resolve(rest, must_exist=True)
            await message.answer_document(BufferedInputFile(f.read_bytes(), f.name))
        except (PathDenied, OSError) as e:
            await message.answer(f"❌ {esc(e)}")
    elif sub == "edit":
        await message.answer("Para editar: usa el agente (/run edita X...) o /file edit <ruta> "
                             "<contenido> no es interactivo. El flujo recomendado es /run.")
    else:
        await message.answer("Uso: /file read <ruta> · /file download <ruta>")


@router.message(Command("workspace"))
async def cmd_workspace(message: Message, ctx):
    proj = await get_project(ctx, message)
    if not proj:
        return
    await message.answer(f"🖥 Workspace del proyecto activo:\n<code>{esc(proj['path'])}</code>\n"
                         "Los sandboxes solo montan esta carpeta.")


# ------------------------------- subidas ------------------------------------


@router.message(F.document)
async def on_document(message: Message, ctx):
    """Recibe archivos individuales o ZIP/TAR hacia el proyecto activo."""
    uid = message.from_user.id
    proj = await ctx.projects.active(uid)
    if not proj:
        await message.answer("📁 Primero selecciona un proyecto: /projects")
        return
    doc = message.document
    if doc.file_size and doc.file_size > ctx.settings.max_file_mb * 1024 * 1024:
        await message.answer(f"⛔ El archivo supera {ctx.settings.max_file_mb} MB (/limits)")
        return
    try:
        file = await ctx.bot.get_file(doc.file_id)
        raw = await ctx.bot.download_file(file.file_path)
        data = raw.read()
    except Exception as e:
        await message.answer(f"❌ Descarga fallida: {esc(e)}")
        return
    name = doc.file_name or "archivo.bin"
    from core.projects.ziputils import ZipUnsafe, extract_archive
    dest = Path(proj["path"])
    if name.lower().endswith((".zip", ".tar.gz", ".tgz", ".tar")):
        tmp = Path("/tmp") / f"upload-{uid}-{name}"
        tmp.write_bytes(data)
        try:
            stats = extract_archive(tmp, dest, max_files=ctx.settings.max_zip_files,
                                    max_unpacked_mb=ctx.settings.max_zip_unpacked_mb)
            await message.answer(
                f"📦 <b>{esc(name)}</b> descomprimido en el proyecto.\n"
                f"{stats['files']} archivos · {fmt_bytes(stats['unpacked_bytes'])}")
        except ZipUnsafe as e:
            await message.answer(f"⛔ ZIP RECHAZADO por seguridad: {esc(e)}")
        finally:
            tmp.unlink(missing_ok=True)
    else:
        from security.path_guard import PathGuard, PathDenied
        try:
            target = PathGuard(dest).resolve(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            await message.answer(f"📄 Guardado como <b>{esc(name)}</b> "
                                 f"({fmt_bytes(len(data))}) en el proyecto activo.")
        except PathDenied as e:
            await message.answer(f"⛔ {esc(e)}")
    await ctx.store.audit(uid, "upload", f"{name} -> {proj['name']}")


# ------------------------------- backups ------------------------------------


@router.message(Command("backup"))
async def cmd_backup(message: Message, ctx):
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(ctx.settings.backups_dir) / f"hj-backup-{ts}.tar.gz"
    data_name = Path(ctx.settings.data_dir).name
    ws_name = Path(ctx.settings.workspaces_dir).name
    parent = str(Path(ctx.settings.data_dir).parent)
    proc = await asyncio.create_subprocess_exec(
        "tar", "-czf", str(out), "-C", parent, data_name, ws_name,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    if proc.returncode != 0:
        await message.answer(f"❌ Backup falló: {esc(err.decode()[:200])}")
        return
    await message.answer_document(BufferedInputFile(out.read_bytes(), out.name),
                                  caption=f"💾 Backup completo ({fmt_bytes(out.stat().st_size)})")


@router.message(Command("restore"))
async def cmd_restore(message: Message, ctx):
    await message.answer(
        "♻️ Restauración: detén el bot, coloca el .tar.gz en data/ y ejecuta:\n"
        "<code>sudo /opt/hj-code-agent/scripts/restore.sh data/hj-backup-XXXX.tar.gz</code>\n"
        "Por seguridad, la restauración automática desde Telegram está desactivada.")
