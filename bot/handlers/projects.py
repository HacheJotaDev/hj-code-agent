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


async def show_projects(message: Message, ctx, uid: int | None = None):
    uid = uid or message.from_user.id
    rows = await ctx.projects.list(uid)
    active = await ctx.projects.active(uid)
    if not rows:
        await message.answer("No hay proyectos. Envía un ZIP y creo uno, o usa "
                             "/newproject &lt;nombre&gt;.")
        return
    lines = ["<b>🗂 Proyectos</b>"]
    for p in rows:
        mark = "●" if active and p["id"] == active["id"] else "○"
        lines.append(f"{mark} #{p['id']} <b>{esc(p['name'])}</b>")
    lines.append("\nSelecciona con botones o /project select &lt;id|nombre&gt;")
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
                         f"Ruta: {esc(proj['path'])}\n\nEnvía archivos o escribe qué quieres "
                         f"que construya (también /run &lt;tarea&gt;).")


@router.message(ProjectStates.waiting_name, F.text & ~F.text.startswith("/"))
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


@router.message(Command("export"))
async def cmd_export(message: Message, ctx):
    """Entrega el ZIP del proyecto activo (flujo V3: sin GitHub)."""
    proj = await get_project(ctx, message)
    if not proj:
        return
    await _export(message, ctx, proj)


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
        await message.answer("Para editar: pídeselo al agente en lenguaje natural "
                             "(o /run edita X...).")
    else:
        await message.answer("Uso: /file read &lt;ruta&gt; · /file download &lt;ruta&gt;")


@router.message(Command("workspace"))
async def cmd_workspace(message: Message, ctx):
    proj = await get_project(ctx, message)
    if not proj:
        return
    await message.answer(f"🖥 Workspace del proyecto activo:\n<code>{esc(proj['path'])}</code>\n"
                         "Los sandboxes solo montan esta carpeta.")


# ------------------------------- subidas ------------------------------------


async def ensure_project(ctx, uid: int, prefer_name: str | None = None) -> dict:
    """Flujo V3: devuelve el proyecto activo; si no hay, usa el mas reciente;
    si no hay ninguno, crea uno automaticamente. Elimina los pasos manuales."""
    proj = await ctx.projects.active(uid)
    if proj:
        return proj
    rows = await ctx.projects.list(uid)
    if rows:
        await ctx.store.set_pref(uid, "active_project", rows[0]["id"])
        return rows[0]
    name = (prefer_name or "mi-proyecto").strip()[:48] or "mi-proyecto"
    proj = await ctx.projects.create(uid, name)
    await ctx.store.set_pref(uid, "active_project", proj["id"])
    return proj


@router.message(F.document)
async def on_document(message: Message, ctx, state: FSMContext):
    """Flujo V3: recibe archivos SIN pasos previos.

    - ZIP/TAR: crea (o reutiliza) un proyecto con el nombre del archivo, extrae
      con validaciones y resume que contiene.
    - Archivo suelto: lo guarda en el proyecto (activo, reciente o nuevo).
    Si hay un estado FSM capturando documentos (import system prompt / config),
    cede el paso (SkipHandler) al handler correspondiente.
    """
    if await state.get_state():
        from aiogram.dispatcher.event.bases import SkipHandler
        raise SkipHandler  # otro flujo (import json, config...) procesa el documento
    uid = message.from_user.id
    if await ctx.store.kv_get(f"cfgimport:{uid}"):
        from aiogram.dispatcher.event.bases import SkipHandler
        raise SkipHandler  # el usuario está importando configuración (admin.py)
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
    is_archive = name.lower().endswith((".zip", ".tar.gz", ".tgz", ".tar"))
    if is_archive:
        base_name = name.rsplit(".", 1)[0].replace(".tar", "") or "proyecto"
        # reutiliza el proyecto con el mismo nombre si existe; si no, crea uno
        proj = await ctx.store.get_project_by_name(uid, base_name)
        if not proj:
            try:
                proj = await ctx.projects.create(uid, base_name)
            except Exception as e:
                await message.answer(f"❌ No pude crear el proyecto: {esc(e)}")
                return
        await ctx.store.set_pref(uid, "active_project", proj["id"])
        conv_id = await ctx.store.get_pref(uid, "active_conversation")
        if conv_id:
            await ctx.store.touch_conversation(int(conv_id), title=f"{base_name}")
        dest = Path(proj["path"])
        import tempfile
        with tempfile.NamedTemporaryFile(suffix="-" + name, delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        try:
            stats = extract_archive(tmp_path, dest, max_files=ctx.settings.max_zip_files,
                                    max_unpacked_mb=ctx.settings.max_zip_unpacked_mb)
        except ZipUnsafe as e:
            await message.answer(f"⛔ ZIP RECHAZADO por seguridad: {esc(e)}")
            return
        finally:
            tmp_path.unlink(missing_ok=True)
        await ctx.store.audit(uid, "upload", f"{name} -> proyecto {proj['name']}")
        # Resumen del contenido
        exts: dict[str, int] = {}
        entry_points = []
        for p in dest.rglob("*"):
            if p.is_file() and ".git" not in p.parts:
                e = p.suffix.lower().lstrip(".") or "(sin ext)"
                exts[e] = exts.get(e, 0) + 1
                if p.name in ("main.py", "app.py", "manage.py", "bot.py", "run.py",
                              "package.json", "pyproject.toml", "requirements.txt",
                              "Makefile", "README.md"):
                    entry_points.append(p.relative_to(dest).as_posix())
        top = ", ".join(f".{k} ×{v}" for k, v in sorted(exts.items(), key=lambda x: -x[1])[:6])
        await message.answer(
            f"📦 <b>{esc(name)}</b> recibido y extraído en el proyecto "
            f"<b>{esc(proj['name'])}</b> (#{proj['id']}, seleccionado).\n"
            f"{stats['files']} archivos · {fmt_bytes(stats['unpacked_bytes'])}\n"
            + (f"Tipos: {esc(top)}\n" if top else "")
            + ("Puntos de entrada: " + esc(", ".join(entry_points[:6])) if entry_points else "")
            + "\n\nEscribe qué quieres que haga con él (p. ej. “revísalo, corrige los "
              "errores y pasa los tests”) y lo hago. /export te devuelve el ZIP.")
        return
    # archivo suelto -> proyecto activo, reciente o nuevo
    proj = await ensure_project(ctx, uid)
    from security.path_guard import PathGuard, PathDenied
    try:
        target = PathGuard(Path(proj["path"])).resolve(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        await message.answer(f"📄 Guardado como <b>{esc(name)}</b> "
                             f"({fmt_bytes(len(data))}) en el proyecto "
                             f"<b>{esc(proj['name'])}</b>.")
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
