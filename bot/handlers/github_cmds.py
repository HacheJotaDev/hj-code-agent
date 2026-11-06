"""GitHub: conexion segura, repos, ramas, commits, push autorizado y PRs."""
from __future__ import annotations

from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..keyboards import confirm_kb, github_kb
from ..states import RepoStates
from ..utils import esc, send_long, trunc
from .helpers import get_project

router = Router(name="github")


async def gh_token_getter(ctx, user_id: int):
    async def _get() -> str:
        if not ctx.vault:
            return ""
        blob = await ctx.store.get_credential(user_id, "github")
        return ctx.vault.decrypt(blob) if blob else ""
    return _get


async def show_github_menu(message: Message, ctx):
    uid = message.from_user.id
    blob = await ctx.store.get_credential(uid, "github")
    await message.answer("🐙 <b>GitHub</b>\nEl token nunca entra en el sandbox de código: "
                         "las operaciones remotas pasan por el broker.",
                         reply_markup=github_kb(bool(blob)))


@router.message(Command("github"))
async def cmd_github(message: Message, ctx, command: CommandObject = None):
    arg = (command.args or "").strip() if command else ""
    if arg == "connect":
        await _connect(message, ctx)
        return
    if arg == "status":
        await _status(message, ctx)
        return
    if arg == "disconnect":
        await ctx.store.delete_credential(message.from_user.id, "github")
        await ctx.store.audit(message.from_user.id, "github.disconnect", "")
        await message.answer("⛔ Token de GitHub eliminado de la bóveda.")
        return
    await show_github_menu(message, ctx)


async def _connect(message: Message, ctx):
    uid = message.from_user.id
    token = ctx.store.new_token()
    await ctx.store.kv_set(f"form:{token}", {"kind": "github_token", "user_id": uid}, ttl_s=600)
    base = ctx.settings.form_base_url.rstrip("/") or f"http://{ctx.settings.form_host}:{ctx.settings.form_port}"
    url = f"{base}/set/{token}"
    await message.answer(
        "🔐 <b>Conexión segura de GitHub</b>\n\n"
        "1) Crea un fine-grained PAT con permisos mínimos: Contents=RW en los repos concretos.\n"
        "2) Abre (UN SOLO USO, 10 min):\n"
        f"{esc(url)}\n\n"
        f"3) Si el formulario está en el VPS: <code>ssh -L {ctx.settings.form_port}:127.0.0.1:"
        f"{ctx.settings.form_port} tu-vps</code>\n\n"
        "El token se guarda CIFRADO y jamás se muestra de nuevo ni entra en los sandboxes.")


async def _status(message: Message, ctx):
    uid = message.from_user.id
    get = await gh_token_getter(ctx, uid)
    token = await get()
    if not token:
        await message.answer("⛔ Sin token. Conecta con /github connect")
        return
    from core.github.client import GitHubClient
    client = GitHubClient(get)
    try:
        me = await client.whoami()
        login = me.get("login", "?")
    except Exception as e:
        await message.answer(f"❌ Token inválido o sin red: {esc(e)[:200]}")
        return
    proj = await ctx.projects.active(uid)
    git = await ctx.store.get_git_state(proj["id"]) if proj else {}
    await message.answer(
        f"✅ GitHub conectado como <b>{esc(login)}</b>\n"
        + (f"Proyecto: {esc(proj['name'])}\nRepo: {esc(git.get('repo_url') or '(sin conectar)')}\n"
           f"Rama: {esc(git.get('current_branch') or '-')} · autopush: "
           f"{'ON' if git.get('autopush') else 'OFF'}" if proj else "Sin proyecto activo."))


# ------------------------------ repos ---------------------------------------


@router.message(Command("repo"))
async def cmd_repo(message: Message, ctx, command: CommandObject = None, state: FSMContext = None):
    proj = await get_project(ctx, message)
    if not proj:
        return
    arg = (command.args or "").strip() if command else ""
    sub, _, rest = arg.partition(" ")
    if sub == "add":
        if not rest.startswith("https://github.com/"):
            await message.answer("Uso: /repo add https://github.com/usuario/repo")
            return
        await ctx.store.set_git_state(proj["id"], repo_url=rest.strip())
        await message.answer(f"✔️ Repositorio registrado: {esc(rest.strip())}\n"
                             "Ahora clónalo: /repo clone")
    elif sub == "clone":
        url = rest.strip() or (await ctx.store.get_git_state(proj["id"])).get("repo_url")
        if not url:
            await state.set_state(RepoStates.waiting_url) if state else None
            await message.answer("Uso: /repo clone https://github.com/usuario/repo [rama]")
            return
        parts = url.split()
        try:
            msg = await ctx.broker.clone(proj, parts[0], parts[1] if len(parts) > 1 else None)
            await message.answer(f"⬇️ {esc(msg)}")
        except Exception as e:
            await message.answer(f"❌ {esc(e)[:400]}")
    elif sub == "info":
        git = await ctx.store.get_git_state(proj["id"])
        status = await ctx.broker.status(proj)
        await send_long(message,
                        f"<b>Repositorio</b>: {esc(git.get('repo_url') or '(sin conectar)')}\n"
                        f"<b>Rama</b>: {esc(git.get('current_branch') or '-')}\n"
                        f"<b>Remotos</b>:\n<pre>{esc(status.get('remotes') or '(ninguno)')}</pre>")
    elif sub == "select":
        await message.answer("Para cambiar de proyecto: /project select. "
                             "Un proyecto = un repositorio.")
    else:
        await message.answer("Uso: /repo add <url> · /repo clone [url|rama] · /repo info")


@router.message(RepoStates.waiting_url, F.text)
async def on_repo_url(message: Message, ctx, state: FSMContext):
    await state.clear()
    proj = await ctx.projects.active(message.from_user.id)
    if not proj:
        return
    await ctx.store.set_git_state(proj["id"], repo_url=message.text.strip())
    await message.answer("✔️ Repositorio registrado. /repo clone para clonarlo.")


@router.message(Command("repos"))
async def cmd_repos(message: Message, ctx):
    uid = message.from_user.id
    rows = await ctx.projects.list(uid)
    lines = ["<b>📂 Repos conectados</b>"]
    any_repo = False
    for p in rows:
        git = await ctx.store.get_git_state(p["id"])
        if git.get("repo_url"):
            any_repo = True
            lines.append(f"• {esc(p['name'])}: {esc(git['repo_url'])}")
    await message.answer("\n".join(lines) if any_repo else "Ningún proyecto tiene repositorio.")


# ------------------------------ git basico -----------------------------------


@router.message(Command("branch"))
async def cmd_branch(message: Message, ctx, command: CommandObject = None):
    proj = await get_project(ctx, message)
    if not proj:
        return
    name = (command.args or "").strip() if command else ""
    import re as _re
    if not name:
        await message.answer("Uso: /branch <nombre> para crear y cambiar; "
                             "/branches para listar")
        return
    if not _re.fullmatch(r"[A-Za-z0-9._/-]{1,80}", name) or ".." in name:
        await message.answer("Nombre de rama inválido.")
        return
    from core.tools.context import AgentContext
    import asyncio as _a
    from security.path_guard import PathGuard
    ws = Path(proj["path"])
    ctx_tool = AgentContext(user_id=message.from_user.id, chat_id=message.chat.id,
                            project=proj, workspace=ws, guard=PathGuard(ws),
                            sandbox=await ctx.make_sandbox(ws, proj),
                            services=ctx, cancel_event=_a.Event())
    from core.tools.registry import tool_git_branch
    result = await tool_git_branch(ctx_tool, {"name": name})
    await message.answer(f"<pre>{esc(result[:1500])}</pre>")


@router.message(Command("branches"))
async def cmd_branches(message: Message, ctx):
    proj = await get_project(ctx, message)
    if not proj:
        return
    code, out = await _git_host(proj["path"], "branch", "-a")
    await message.answer(f"🌿 <pre>{esc(out or '(sin ramas)')}</pre>")


@router.message(Command("checkout"))
async def cmd_checkout(message: Message, ctx, command: CommandObject = None):
    proj = await get_project(ctx, message)
    if not proj:
        return
    name = (command.args or "").strip() if command else ""
    if not name:
        await message.answer("Uso: /checkout <rama>")
        return
    code, out = await _git_host(proj["path"], "checkout", name)
    if code == 0:
        await ctx.store.set_git_state(proj["id"], current_branch=name)
    await message.answer(f"<pre>{esc(out[:800])}</pre>")


@router.message(Command("gitstatus"))
async def cmd_gitstatus(message: Message, ctx):
    proj = await get_project(ctx, message)
    if not proj:
        return
    code, out = await _git_host(proj["path"], "status", "--porcelain", "-b")
    await message.answer(f"📋 <pre>{esc(out or '(repositorio limpio)')}</pre>")


@router.message(Command("diff"))
async def cmd_diff(message: Message, ctx):
    proj = await get_project(ctx, message)
    if not proj:
        return
    code, out = await _git_host(proj["path"], "diff", "HEAD", "--stat")
    code2, out2 = await _git_host(proj["path"], "diff", "HEAD")
    text = out + ("\n\n" + out2 if len(out2) < 2500 else "\n(diff largo; usa /run para trabajar con él)")
    await send_long(message, f"📐 <pre>{esc(text or '(sin cambios)')}</pre>")


@router.message(Command("commit"))
async def cmd_commit(message: Message, ctx, command: CommandObject = None):
    proj = await get_project(ctx, message)
    if not proj:
        return
    msg = (command.args or "").strip() if command else ""
    if not msg:
        await message.answer("Uso: /commit <mensaje>")
        return
    await _git_host(proj["path"], "add", "-A")
    code, out = await _git_host(proj["path"], "commit", "-m", msg)
    await ctx.store.audit(message.from_user.id, "git.commit", f"{proj['name']}: {msg[:100]}")
    await message.answer(f"✅ <pre>{esc(out[:800] or 'commit creado')}</pre>")


@router.message(Command("history"))
async def cmd_history_git(message: Message, ctx):
    proj = await get_project(ctx, message)
    if not proj:
        return
    code, out = await _git_host(proj["path"], "log", "--oneline", "-15")
    await message.answer(f"📜 <pre>{esc(out or '(sin commits)')}</pre>")


@router.message(Command("rollback"))
async def cmd_rollback(message: Message, ctx, command: CommandObject = None):
    proj = await get_project(ctx, message)
    if not proj:
        return
    path = (command.args or "").strip() if command else ""
    if not path:
        await message.answer("Uso: /rollback <archivo>  (restaura desde HEAD)")
        return
    code, out = await _git_host(proj["path"], "checkout", "--", path)
    await message.answer(f"↩️ <pre>{esc(out[:400] or f'{path} restaurado desde HEAD')}</pre>")


async def _git_host(path: str, *args: str) -> tuple[int, str]:
    import asyncio
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate()
    return proc.returncode or 0, (out.decode("utf-8", "replace") +
                                  err.decode("utf-8", "replace")).strip()


# ------------------------------ push / pull / PR -----------------------------


@router.message(Command("push"))
async def cmd_push(message: Message, ctx, command: CommandObject = None):
    """Push REAL: pide autorizacion explicita con botones."""
    proj = await get_project(ctx, message)
    if not proj:
        return
    branch = (command.args or "").strip() if command else None
    await _request_push(message, ctx, proj, branch)


async def _request_push(message: Message, ctx, proj: dict, branch: str | None):
    branch = branch or await ctx.broker.current_branch(proj) or "main"
    git = await ctx.store.get_git_state(proj["id"])
    if not git.get("repo_url"):
        await message.answer("❌ Sin repositorio conectado: /repo add + /repo clone")
        return
    token_req = ctx.store.new_token()
    req_id = f"push-{token_req[:10]}"
    await ctx.store.kv_set(f"pushreq:{req_id}",
                           {"project_id": proj["id"], "branch": branch,
                            "user_id": message.from_user.id}, ttl_s=600)
    from ..keyboards import approval_kb
    await message.answer(
        f"🔐 <b>Autorización de push</b>\nProyecto: {esc(proj['name'])}\n"
        f"Rama: <b>{esc(branch)}</b>\nDestino: {esc(git['repo_url'])}\n\n"
        "¿Autorizas el push?",
        reply_markup=approval_kb(req_id))


@router.callback_query(F.data.startswith("auth:"))
async def cb_approval(cb: CallbackQuery, ctx):
    _, yes_no, req_id = cb.data.split(":", 2)
    # Autorizaciones del motor (agente) resuelven su Future aqui
    resolved = ctx.approvals.resolve(req_id, approved=(yes_no == "yes"))
    if resolved:
        await cb.answer("Autorizado" if yes_no == "yes" else "Rechazado")
        await cb.message.edit_text(cb.message.html_text + "\n\n→ " +
                                   ("✅ Autorizado" if yes_no == "yes" else "❌ Rechazado"))
        return
    # Push iniciado por el usuario (/push)
    data = await ctx.store.kv_get(f"pushreq:{req_id}")
    if not data:
        await cb.answer("Solicitud expirada", show_alert=True)
        return
    await ctx.store.kv_del(f"pushreq:{req_id}")
    if yes_no != "yes":
        await cb.answer("Rechazado")
        await cb.message.edit_text(cb.message.html_text + "\n\n→ ❌ Rechazado")
        return
    await cb.answer("Publicando...")
    proj = await ctx.store.get_project(data["project_id"])
    try:
        msg = await ctx.broker.push(proj, data["branch"], authorized=True)
        await cb.message.edit_text(cb.message.html_text + f"\n\n→ ✅ {esc(msg)}")
    except Exception as e:
        await cb.message.edit_text(cb.message.html_text + f"\n\n→ ❌ {esc(e)[:300]}")


@router.message(Command("pull"))
async def cmd_pull(message: Message, ctx):
    proj = await get_project(ctx, message)
    if not proj:
        return
    try:
        msg = await ctx.broker.pull(proj)
        await message.answer(f"⬇️ {esc(msg)}")
    except Exception as e:
        await message.answer(f"❌ {esc(e)[:400]}")


@router.message(Command("pr"))
async def cmd_pr(message: Message, ctx, command: CommandObject = None):
    proj = await get_project(ctx, message)
    if not proj:
        return
    title = (command.args or "").strip() if command else ""
    if not title:
        await message.answer("Uso: /pr <titulo del PR> (la rama debe estar publicada)")
        return
    git = await ctx.store.get_git_state(proj["id"])
    if not git.get("repo_url"):
        await message.answer("❌ Sin repositorio conectado.")
        return
    req_id = ctx.store.new_token()[:12]
    await ctx.store.kv_set(f"pushreq:{req_id}",
                           {"project_id": proj["id"], "pr_title": title,
                            "user_id": message.from_user.id}, ttl_s=600)
    from ..keyboards import approval_kb
    await message.answer(
        f"🔐 <b>Crear Pull Request</b>\n{esc(git['repo_url'])}\nTítulo: {esc(title)}\n\n¿Autorizas?",
        reply_markup=approval_kb(req_id))


@router.message(Command("autopush"))
async def cmd_autopush(message: Message, ctx, command: CommandObject = None):
    proj = await get_project(ctx, message)
    if not proj:
        return
    arg = (command.args or "").strip().lower() if command else ""
    git = await ctx.store.get_git_state(proj["id"])
    if arg in ("on", "off"):
        if arg == "on":
            branches = [b for b in (git.get("allowed_branches") or []) if b]
            await ctx.store.set_git_state(proj["id"], autopush=1,
                                          allowed_branches=branches or ["main"])
            await message.answer(
                "⚠️ Auto-push ACTIVADO por defecto para: " +
                ", ".join(branches or ["main"]) +
                "\nDesactívalo con /autopush off. Recuerda: nunca en ramas protegidas sin lista.")
        else:
            await ctx.store.set_git_state(proj["id"], autopush=0)
            await message.answer("⏹ Auto-push DESACTIVADO (por defecto).")
        return
    await message.answer(f"🚀 Auto-push: {'ON' if git.get('autopush') else 'OFF (por defecto)'}\n"
                         "Uso: /autopush on|off (limitado a ramas autorizadas)")


@router.callback_query(F.data == "gh:connect")
async def cb_gh_connect(cb: CallbackQuery, ctx):
    await cb.answer()
    await _connect(cb.message, ctx)


@router.callback_query(F.data == "gh:status")
async def cb_gh_status(cb: CallbackQuery, ctx):
    await cb.answer()
    await _status(cb.message, ctx)


@router.callback_query(F.data == "gh:repoadd")
async def cb_gh_repoadd(cb: CallbackQuery, ctx):
    await cb.answer()
    await cb.message.answer("Uso: /repo add https://github.com/usuario/repo")


@router.callback_query(F.data == "gh:clone")
async def cb_gh_clone(cb: CallbackQuery, ctx):
    await cb.answer()
    await cb.message.answer("Uso: /repo clone https://github.com/usuario/repo [rama]")


@router.callback_query(F.data == "gh:branches")
async def cb_gh_branches(cb: CallbackQuery, ctx):
    await cb.answer()
    await cmd_branches(cb.message, ctx)


@router.callback_query(F.data == "gh:history")
async def cb_gh_history(cb: CallbackQuery, ctx):
    await cb.answer()
    await cmd_history_git(cb.message, ctx)


@router.callback_query(F.data == "gh:push")
async def cb_gh_push(cb: CallbackQuery, ctx):
    await cb.answer()
    await cmd_push(cb.message, ctx)


@router.callback_query(F.data == "gh:pull")
async def cb_gh_pull(cb: CallbackQuery, ctx):
    await cb.answer()
    await cmd_pull(cb.message, ctx)


@router.callback_query(F.data == "gh:autopush")
async def cb_gh_autopush(cb: CallbackQuery, ctx):
    await cb.answer()
    await cmd_autopush(cb.message, ctx)


@router.callback_query(F.data == "gh:disconnect")
async def cb_gh_disconnect(cb: CallbackQuery, ctx):
    await cb.answer()
    await ctx.store.delete_credential(cb.from_user.id, "github")
    await cb.message.answer("⛔ Token de GitHub eliminado.")
