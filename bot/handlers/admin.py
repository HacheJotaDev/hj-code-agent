"""Administracion: usuarios, seguridad, auditoria, diagnostico, config."""
from __future__ import annotations

import json
import platform
import shutil

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, Message

from ..utils import esc, send_long
from .helpers import provider_error_message

router = Router(name="admin")


async def _is_admin(ctx, uid: int) -> bool:
    user = await ctx.store.get_user(uid)
    return bool(user and user["is_admin"])


@router.message(Command("admin"))
async def cmd_admin(message: Message, ctx):
    if not await _is_admin(ctx, message.from_user.id):
        await message.answer("⛔ Solo administradores.")
        return
    await message.answer(
        "🛡 <b>Administración</b>\n/users · /authorize <id> [admin] · /revoke <id>\n"
        "/security · /audit · /diagnostics · /config export|import · /notifications on|off")


@router.message(Command("users"))
async def cmd_users(message: Message, ctx):
    if not await _is_admin(ctx, message.from_user.id):
        await message.answer("⛔ Solo administradores.")
        return
    rows = await ctx.store.list_users()
    lines = ["<b>👥 Usuarios</b>"]
    for u in rows:
        marks = ("👑" if u["is_admin"] else "") + ("✅" if u["allowed"] else "⛔")
        lines.append(f"{marks} <code>{u['telegram_id']}</code> {esc(u['username'] or u['first_name'] or '')}")
    await send_long(message, "\n".join(lines))


@router.message(Command("authorize"))
async def cmd_authorize(message: Message, ctx, command: CommandObject = None):
    if not await _is_admin(ctx, message.from_user.id):
        await message.answer("⛔ Solo administradores.")
        return
    parts = ((command.args or "") if command else "").split()
    if not parts or not parts[0].isdigit():
        await message.answer("Uso: /authorize <user_id> [admin]")
        return
    uid = int(parts[0])
    admin = len(parts) > 1 and parts[1].lower() == "admin"
    await ctx.store.upsert_user(uid, is_admin=admin, allowed=True)
    await ctx.store.audit(message.from_user.id, "authorize", f"{uid} admin={admin}")
    await message.answer(f"✔️ Usuario <code>{uid}</code> autorizado"
                         + (" como administrador." if admin else "."))


@router.message(Command("revoke"))
async def cmd_revoke(message: Message, ctx, command: CommandObject = None):
    if not await _is_admin(ctx, message.from_user.id):
        await message.answer("⛔ Solo administradores.")
        return
    arg = (command.args or "").strip() if command else ""
    if not arg.isdigit():
        await message.answer("Uso: /revoke <user_id>")
        return
    uid = int(arg)
    try:
        user = await ctx.store.get_user(uid)
        if user and user["is_admin"]:
            await message.answer("⛔ No se puede revocar a un administrador (edita el .env).")
            return
        await ctx.store.set_allowed(uid, False)
        await ctx.store.audit(message.from_user.id, "revoke", str(uid))
        await message.answer(f"✔️ Usuario <code>{uid}</code> revocado.")
    except Exception as e:
        await message.answer(f"❌ {esc(e)}")


@router.message(Command("security"))
async def cmd_security(message: Message, ctx):
    if not await _is_admin(ctx, message.from_user.id):
        await message.answer("⛔ Solo administradores.")
        return
    s = ctx.settings
    from core.sandbox.factory import docker_available
    docker_ok = await docker_available()
    await message.answer(
        "🔐 <b>Postura de seguridad</b>\n"
        f"• Acceso: solo user_id autorizados ({len(await ctx.store.list_users())} registrados)\n"
        f"• Bóveda cifrada: {'sí' if ctx.vault else 'NO CONFIGURADA'}\n"
        f"• Sandbox: <b>{esc(s.sandbox_backend)}</b> (Docker disponible: {'sí' if docker_ok else 'no'})\n"
        f"• Secretos en sandbox: jamás (lista blanca de entorno)\n"
        f"• Push a GitHub: siempre con autorización; autopush OFF por defecto\n"
        f"• System prompt por defecto: NINGUNO (modo nativo)\n"
        "Recomendaciones en docs/SECURITY.md")


@router.message(Command("audit"))
async def cmd_audit(message: Message, ctx, command: CommandObject = None):
    if not await _is_admin(ctx, message.from_user.id):
        await message.answer("⛔ Solo administradores.")
        return
    limit = 30
    if command and command.args and command.args.strip().isdigit():
        limit = min(int(command.args), 100)
    rows = await ctx.store.audit_list(limit)
    lines = [f"<b>🧾 Auditoría ({len(rows)})</b>"]
    for r in rows:
        lines.append(f"#{r['id']} [{r['created_at'][5:16]}] user={r['user_id']} "
                     f"{esc(r['action'])} {esc((r['detail'] or '')[:60])}")
    await send_long(message, "\n".join(lines))


@router.message(Command("notifications"))
async def cmd_notifications(message: Message, ctx, command: CommandObject = None):
    arg = ((command.args or "").strip().lower() if command else "")
    b = await ctx.store.get_budget(message.from_user.id)
    if arg in ("on", "off"):
        await ctx.store.set_budget(message.from_user.id, notifications=1 if arg == "on" else 0)
        await message.answer(f"🔔 Notificaciones de tareas: {arg.upper()}")
        return
    await message.answer(f"🔔 Notificaciones: {'ON' if b.get('notifications', 1) else 'OFF'}\n"
                         "Uso: /notifications on|off")


@router.message(Command("diagnostics"))
async def cmd_diagnostics(message: Message, ctx):
    if not await _is_admin(ctx, message.from_user.id):
        await message.answer("⛔ Solo administradores.")
        return
    checks = []
    checks.append(("Python", platform.python_version()))
    disk = shutil.disk_usage(ctx.settings.data_dir)
    checks.append(("Disco libre", f"{disk.free // (1024**3)} GB"))
    checks.append(("DB", f"{ctx.settings.db_file} (WAL)"))
    checks.append(("Bóveda", "ok" if ctx.vault else "FALTA CLAVE MAESTRA"))
    queued = await ctx.store.list_tasks(status="queued", limit=100)
    running = await ctx.store.list_tasks(status="running", limit=100)
    checks.append(("Cola", f"{len(queued)} en cola, {len(running)} en ejecución"))
    kv_expired = await ctx.store.purge_expired_kv()
    checks.append(("Tokens de formulario", "limpiados los expirados"))
    from core.sandbox.factory import docker_available
    checks.append(("Docker", "sí" if await docker_available() else "no"))
    lines = [f"🩺 <b>Diagnóstico</b>"] + [f"• {k}: {esc(v)}" for k, v in checks]
    await send_long(message, "\n".join(lines))


@router.message(Command("config"))
async def cmd_config(message: Message, ctx, command: CommandObject = None):
    uid = message.from_user.id
    arg = ((command.args or "").strip().lower() if command else "")
    if arg == "export":
        data = {"prefs": await ctx.store.all_prefs(uid),
                "budget": await ctx.store.get_budget(uid),
                "system_prompt": await ctx.prompts.export(uid),
                "pricing": await ctx.store.list_rates()}
        blob = json.dumps(data, ensure_ascii=False, indent=2).encode()
        await message.answer_document(BufferedInputFile(blob, "hj-config.json"),
                                      caption="📤 Config exportada (SIN secretos)")
        return
    if arg == "import":
        await message.answer("📥 Envía el archivo hj-config.json (sin secretos).")
        return
    await message.answer("Uso: /config export · /config import")


@router.message(F.document, F.document.file_name == "hj-config.json")
async def on_config_import(message: Message, ctx, state: FSMContext):
    if not await _is_admin(ctx, message.from_user.id):
        return
    try:
        file = await ctx.bot.get_file(message.document.file_id)
        raw = await ctx.bot.download_file(file.file_path)
        data = json.loads(raw.read().decode())
        for k, v in (data.get("prefs") or {}).items():
            if k.startswith("model:"):
                await ctx.store.set_pref(message.from_user.id, k, v)
        if data.get("budget"):
            for k in ("per_task", "per_day", "alert_balance", "alert_daily"):
                if data["budget"].get(k) is not None:
                    await ctx.store.set_budget(message.from_user.id, **{k: data["budget"][k]})
        if data.get("system_prompt"):
            await ctx.prompts.import_prompt(message.from_user.id, data["system_prompt"])
        for r in data.get("pricing") or []:
            await ctx.pricing.set_rate(r["provider"], r["model"], r["input_per_mtok"],
                                       r["output_per_mtok"], r.get("currency", "USD"),
                                       r.get("cache_hit_per_mtok"))
        await message.answer("📥 Config importada (preferencias, presupuesto, prompt y tarifas).")
    except Exception as e:
        await message.answer(f"❌ Import inválido: {esc(e)}")
