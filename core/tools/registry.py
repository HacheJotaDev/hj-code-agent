"""Herramientas del agente: esquemas OpenAI de function calling + ejecucion real.

Cada herramienta valida argumentos y rutas, ejecuta dentro del sandbox/workspace
y devuelve un resultado JSON real al modelo. Nada aqui confia en el contenido
de los archivos del proyecto para conceder permisos.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from security.command_guard import CommandDenied, screen_command
from security.path_guard import PathDenied
from .context import AgentContext

MAX_READ_BYTES = 256 * 1024
MAX_WRITE_BYTES = 1024 * 1024
IGNORED_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".tox", "dist", "build"}

TOOL_NAMES = [
    "list_files", "read_file", "write_file", "edit_file", "apply_patch", "search_files",
    "search_code", "create_directory", "move_file", "delete_file", "execute_command",
    "install_dependencies", "run_tests", "run_build", "git_status", "git_diff", "git_branch",
    "git_commit", "git_push", "github_pull_request", "get_task_logs", "export_zip",
]

_S = {"type": "object", "properties": {}, "required": []}


def _schema(name: str, description: str, props: dict, required: list[str] | None = None) -> dict:
    return {"type": "function",
            "function": {"name": name, "description": description,
                         "parameters": {"type": "object", "properties": props,
                                        "required": required or []}}}


P = "ruta relativa dentro del proyecto"

TOOL_SCHEMAS: list[dict] = [
    _schema("list_files", "Lista archivos y carpetas del proyecto.",
            {"path": {"type": "string", "description": P + " (vacío = raíz)"},
             "recursive": {"type": "boolean", "description": "recorrer subcarpetas (default true)"}}),
    _schema("read_file", "Lee un archivo de texto (limitado a 256 KB / 2000 líneas).",
            {"path": {"type": "string", "description": P},
             "offset": {"type": "integer", "description": "línea inicial (0-based)"},
             "limit": {"type": "integer", "description": "nº de líneas (máx 2000)"}},
            ["path"]),
    _schema("write_file", "Crea o sobrescribe un archivo con contenido completo (máx 1 MB).",
            {"path": {"type": "string", "description": P},
             "content": {"type": "string"}}, ["path", "content"]),
    _schema("edit_file", "Edita un archivo reemplazando texto exacto.",
            {"path": {"type": "string", "description": P},
             "old": {"type": "string", "description": "texto a buscar"},
             "new": {"type": "string", "description": "reemplazo"},
             "count": {"type": "integer", "description": "nº de reemplazos (default 1, 0=todos)"}},
            ["path", "old", "new"]),
    _schema("apply_patch", "Aplica un parche unificado (diff) a un archivo.",
            {"path": {"type": "string", "description": P}, "patch": {"type": "string"}},
            ["path", "patch"]),
    _schema("search_files", "Busca archivos por patrón glob (ej: **/*.py).",
            {"pattern": {"type": "string"}}, ["pattern"]),
    _schema("search_code", "Busca expresión regular dentro del código del proyecto.",
            {"regex": {"type": "string"}, "path": {"type": "string", "description": P},
             "max_results": {"type": "integer"}}, ["regex"]),
    _schema("create_directory", "Crea una carpeta (y padres si hace falta).",
            {"path": {"type": "string", "description": P}}, ["path"]),
    _schema("move_file", "Mueve o renombra un archivo o carpeta.",
            {"src": {"type": "string", "description": P}, "dst": {"type": "string", "description": P}},
            ["src", "dst"]),
    _schema("delete_file", "Borra un archivo o carpeta dentro del proyecto.",
            {"path": {"type": "string", "description": P}, "recursive": {"type": "boolean"}},
            ["path"]),
    _schema("execute_command", "Ejecuta un comando shell dentro del sandbox del proyecto.",
            {"command": {"type": "string"}, "timeout": {"type": "integer", "description": "segundos (máx 600)"}},
            ["command"]),
    _schema("install_dependencies", "Instala dependencias detectando el gestor (pip/npm/go/maven) o con comando custom.",
            {"command": {"type": "string", "description": "opcional: comando de instalación"}}),
    _schema("run_tests", "Ejecuta la batería de pruebas del proyecto (pytest/npm test/go test...).",
            {"command": {"type": "string", "description": "opcional: comando de tests"}}),
    _schema("run_build", "Compila o construye el proyecto (npm run build, make, cargo build...).",
            {"command": {"type": "string", "description": "opcional: comando de build"}}),
    _schema("git_status", "Estado git del proyecto (porcelain).", {}),
    _schema("git_diff", "Diff de cambios (working tree vs HEAD).",
            {"path": {"type": "string", "description": "opcional: limitar a una ruta"}}),
    _schema("git_branch", "Lista ramas o crea una nueva.",
            {"name": {"type": "string", "description": "si se indica, crea y cambia a esa rama"}}),
    _schema("git_commit", "Crea un commit con los cambios actuales.",
            {"message": {"type": "string"}}, ["message"]),
    _schema("git_push", "Pide push a GitHub. REQUIERE autorización explícita del usuario en Telegram; la ejecución queda en pausa hasta aprobarse.",
            {"branch": {"type": "string", "description": "rama a publicar (default: actual)"}}),
    _schema("github_pull_request", "Crea un Pull Request en GitHub (la rama debe estar publicada).",
            {"title": {"type": "string"}, "body": {"type": "string"},
             "head": {"type": "string"}, "base": {"type": "string"}},
            ["title"]),
    _schema("get_task_logs", "Devuelve el registro de pasos de la tarea actual.",
            {"task_id": {"type": "integer", "description": "opcional; por defecto la tarea en curso"}}),
    _schema("export_zip", "Empaqueta el proyecto completo (sin .git/node_modules) en un ZIP y se lo entrega al usuario al terminar la tarea. Úsalo cuando el usuario pida el proyecto final o devolver los cambios.", {}),
]

# --------------------------- utilidades --------------------------------


def _arg_str(args: dict, key: str, default: str = "") -> str:
    v = args.get(key, default)
    if v is None:
        return default
    if not isinstance(v, str):
        raise ValueError(f"'{key}' debe ser texto")
    return v


def _arg_int(args: dict, key: str, default: int, lo: int, hi: int) -> int:
    v = args.get(key, default)
    try:
        v = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _ok(data: dict | list | str) -> str:
    return json.dumps({"ok": True, **({"result": data} if not isinstance(data, str) else {"result": data})},
                      ensure_ascii=False)


def _err(msg: str) -> str:
    return json.dumps({"ok": False, "error": str(msg)[:800]}, ensure_ascii=False)


def _iter_files(root: Path, path: str = "."):
    base = root / path if path else root
    for p in sorted(base.rglob("*")):
        if any(part in IGNORED_DIRS for part in p.relative_to(root).parts):
            continue
        yield p


# --------------------------- implementacion ----------------------------


async def tool_list_files(ctx: AgentContext, args: dict) -> str:
    path = _arg_str(args, "path", ".")
    recursive = bool(args.get("recursive", True))
    try:
        base = ctx.guard.resolve(path or ".", must_exist=True)
    except PathDenied as e:
        return _err(e)
    if base.is_file():
        return _ok([path])
    out = []
    if recursive:
        for p in _iter_files(ctx.workspace, base.relative_to(ctx.workspace).as_posix() if base != ctx.workspace else "."):
            rel = p.relative_to(ctx.workspace).as_posix()
            try:
                st = p.stat()
            except OSError:
                continue
            kind = "d" if p.is_dir() else "f"
            out.append(f"{kind} {rel} ({st.st_size}B)")
            if len(out) >= 500:
                out.append("...[limite de 500 entradas]")
                break
    else:
        for p in sorted(base.iterdir()):
            rel = p.relative_to(ctx.workspace).as_posix()
            out.append(("d " if p.is_dir() else "f ") + rel)
    return _ok("\n".join(out) or "(carpeta vacía)")


async def tool_read_file(ctx: AgentContext, args: dict) -> str:
    path = _arg_str(args, "path")
    if not path:
        return _err("Falta 'path'")
    try:
        f = ctx.guard.resolve(path, must_exist=True)
        if not f.is_file():
            return _err(f"No es un archivo: {path}")
        data = f.read_bytes()
        if len(data) > MAX_READ_BYTES:
            data = data[:MAX_READ_BYTES]
            truncated = True
        else:
            truncated = False
        text = data.decode("utf-8", "replace")
        lines = text.splitlines()
        offset = _arg_int(args, "offset", 0, 0, 10_000_000)
        limit = _arg_int(args, "limit", 2000, 1, 2000)
        window = lines[offset:offset + limit]
        header = f"[{path}] {len(lines)} líneas"
        if truncated:
            header += " (TRUNCADO a 256 KB)"
        return _ok(header + "\n" + "\n".join(window))
    except PathDenied as e:
        return _err(e)
    except OSError as e:
        return _err(f"Error leyendo: {e}")


async def tool_write_file(ctx: AgentContext, args: dict) -> str:
    path = _arg_str(args, "path")
    content = args.get("content")
    if not path or content is None or not isinstance(content, str):
        return _err("Se requieren 'path' y 'content' (texto)")
    if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
        return _err("Contenido supera 1 MB; divide la escritura")
    try:
        f = ctx.guard.resolve(path)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content, encoding="utf-8")
        ctx.touch(f.relative_to(ctx.workspace).as_posix())
        return _ok(f"Escrito {path} ({len(content.encode('utf-8'))} bytes)")
    except PathDenied as e:
        return _err(e)


async def tool_edit_file(ctx: AgentContext, args: dict) -> str:
    path = _arg_str(args, "path")
    old, new = args.get("old"), args.get("new")
    if not path or old is None or new is None:
        return _err("Se requieren 'path', 'old' y 'new'")
    count = _arg_int(args, "count", 1, 0, 1000)
    try:
        f = ctx.guard.resolve(path, must_exist=True)
        text = f.read_text(encoding="utf-8")
        n = text.count(old)
        if n == 0:
            return _err("No se encontró el texto 'old' (búsqueda exacta)")
        if count == 0 or n < count:
            count = n
        f.write_text(text.replace(old, new, count), encoding="utf-8")
        ctx.touch(f.relative_to(ctx.workspace).as_posix())
        return _ok(f"Editado {path}: {count} reemplazo(s)")
    except PathDenied as e:
        return _err(e)


def apply_unified_diff(text: str, patch: str) -> str:
    """Aplica un diff unificado simple (por hunks, con contexto)."""
    lines = text.splitlines(keepends=True)
    hunks = []
    cur = None
    for line in patch.splitlines(keepends=True):
        if line.startswith("@@"):
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
            if m:
                cur = {"start": int(m.group(1)), "old": [], "new": []}
                hunks.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith("-"):
            cur["old"].append(line[1:])
        elif line.startswith("+"):
            cur["new"].append(line[1:])
        else:
            body = line[1:] if line[:1] in (" ", "") else line
            cur["old"].append(body)
            cur["new"].append(body)
    if not hunks:
        raise ValueError("El parche no contiene hunks @@ válidos")
    pos = 0
    out: list[str] = []
    for h in hunks:
        # localizar el bloque 'old' a partir de pos (tolerancia de contexto)
        old = [l.rstrip("\n") for l in h["old"]]
        start = max(pos - 5, 0)
        found = -1
        for i in range(start, len(lines) + 1):
            window = [l.rstrip("\n") for l in lines[i:i + len(old)]]
            if window == old:
                found = i
                break
        if found < 0:
            raise ValueError("El parche no aplica: contexto no encontrado (archivo cambiado?)")
        out.extend(lines[pos:found])
        out.extend(l if l.endswith("\n") else l + "\n" for l in h["new"])
        pos = found + len(old)
    out.extend(lines[pos:])
    return "".join(out)


async def tool_apply_patch(ctx: AgentContext, args: dict) -> str:
    path = _arg_str(args, "path")
    patch = _arg_str(args, "patch")
    if not path or not patch:
        return _err("Se requieren 'path' y 'patch'")
    try:
        f = ctx.guard.resolve(path, must_exist=True)
        original = f.read_text(encoding="utf-8")
        updated = apply_unified_diff(original, patch)
        f.write_text(updated, encoding="utf-8")
        ctx.touch(f.relative_to(ctx.workspace).as_posix())
        return _ok(f"Parche aplicado a {path}")
    except PathDenied as e:
        return _err(e)
    except ValueError as e:
        return _err(str(e))


async def tool_search_files(ctx: AgentContext, args: dict) -> str:
    pattern = _arg_str(args, "pattern")
    if not pattern:
        return _err("Falta 'pattern'")
    matches = sorted(ctx.workspace.glob(pattern))
    out = [p.relative_to(ctx.workspace).as_posix() for p in matches if p.is_file()][:200]
    return _ok("\n".join(out) or "(sin coincidencias)")


async def tool_search_code(ctx: AgentContext, args: dict) -> str:
    regex = _arg_str(args, "regex")
    if not regex:
        return _err("Falta 'regex'")
    max_results = _arg_int(args, "max_results", 50, 1, 200)
    try:
        rx = re.compile(regex)
    except re.error as e:
        return _err(f"Regex inválida: {e}")
    out: list[str] = []
    try:
        for p in _iter_files(ctx.workspace):
            if p.stat().st_size > 2 * 1024 * 1024:
                continue
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh, 1):
                        if rx.search(line):
                            rel = p.relative_to(ctx.workspace).as_posix()
                            out.append(f"{rel}:{i}: {line.strip()[:200]}")
                            if len(out) >= max_results:
                                return _ok("\n".join(out))
            except (OSError, UnicodeError):
                continue
    except PathDenied:
        return _err("Ruta inválida")
    return _ok("\n".join(out) or "(sin coincidencias)")


async def tool_create_directory(ctx: AgentContext, args: dict) -> str:
    path = _arg_str(args, "path")
    if not path:
        return _err("Falta 'path'")
    try:
        d = ctx.guard.resolve(path)
        d.mkdir(parents=True, exist_ok=True)
        return _ok(f"Carpeta creada: {path}")
    except PathDenied as e:
        return _err(e)


async def tool_move_file(ctx: AgentContext, args: dict) -> str:
    src, dst = _arg_str(args, "src"), _arg_str(args, "dst")
    if not src or not dst:
        return _err("Se requieren 'src' y 'dst'")
    try:
        s = ctx.guard.resolve(src, must_exist=True)
        d = ctx.guard.resolve(dst)
        d.parent.mkdir(parents=True, exist_ok=True)
        s.rename(d)
        ctx.touch(d.relative_to(ctx.workspace).as_posix())
        return _ok(f"Movido {src} -> {dst}")
    except PathDenied as e:
        return _err(e)


async def tool_delete_file(ctx: AgentContext, args: dict) -> str:
    import shutil
    path = _arg_str(args, "path")
    if not path or path in (".", "/"):
        return _err("Ruta inválida")
    try:
        f = ctx.guard.resolve(path, must_exist=True)
        if f == ctx.workspace:
            return _err("No se puede borrar la raíz del proyecto con esta herramienta")
        if f.is_dir():
            shutil.rmtree(f)
        else:
            f.unlink()
        await ctx.services.store.audit(ctx.user_id, "tool.delete_file",
                                       f"task={ctx.task_id} path={path}")
        return _ok(f"Borrado: {path}")
    except PathDenied as e:
        return _err(e)


async def tool_execute_command(ctx: AgentContext, args: dict) -> str:
    cmd = _arg_str(args, "command")
    if not cmd:
        return _err("Falta 'command'")
    timeout = _arg_int(args, "timeout", ctx.sandbox.timeout_s, 1, 600)
    if ctx.cancel_event.is_set():
        return _err("Tarea cancelada")
    ctx.commands_run.append(cmd[:200])
    try:
        res = await ctx.sandbox.exec(cmd, timeout=timeout, key=f"t{ctx.task_id}:{len(ctx.commands_run)}",
                                     task_id=ctx.task_id)
        # Evidencia real: la salida del sandbox viaja al resumen de la tarea
        # (nada de inventar resultados: lo que se muestra es lo que ejecutó).
        ctx.command_results.append((cmd[:200], res.truncated(1200)))
        return _ok(res.truncated(6000))
    except CommandDenied as e:
        ctx.command_results.append((cmd[:200], f"DENEGADO: {e}"))
        return _err(str(e))


def detect_manager(ctx: AgentContext) -> list[str] | None:
    ws = ctx.workspace
    if (ws / "package.json").exists():
        return ["npm", "install"]
    if (ws / "requirements.txt").exists():
        return ["pip", "install", "-r", "requirements.txt"]
    if (ws / "pyproject.toml").exists():
        return ["pip", "install", "-e", "."]
    if (ws / "go.mod").exists():
        return ["go", "mod", "download"]
    if (ws / "pom.xml").exists():
        return ["mvn", "-q", "-DskipTests", "package"]
    if (ws / "Cargo.toml").exists():
        return ["cargo", "fetch"]
    if (ws / "Makefile").exists():
        return ["make"]
    return None


async def tool_install_dependencies(ctx: AgentContext, args: dict) -> str:
    cmd = _arg_str(args, "command")
    if not cmd:
        detected = detect_manager(ctx)
        if not detected:
            return _err("No se detectó gestor de dependencias; usa 'command'")
        cmd = " ".join(detected)
    return await tool_execute_command(ctx, {"command": cmd, "timeout": 600})


async def tool_run_tests(ctx: AgentContext, args: dict) -> str:
    cmd = _arg_str(args, "command")
    if not cmd:
        ws = ctx.workspace
        if (ws / "package.json").exists():
            cmd = "npm test"
        elif any(ws.glob("test_*.py")) or (ws / "tests").exists():
            cmd = "python -m pytest -q"
        elif (ws / "go.mod").exists():
            cmd = "go test ./..."
        elif (ws / "pom.xml").exists():
            cmd = "mvn -q test"
        else:
            return _err("No se detectaron pruebas; usa 'command'")
    ctx.tests_run.append(cmd[:200])
    return await tool_execute_command(ctx, {"command": cmd, "timeout": 600})


async def tool_run_build(ctx: AgentContext, args: dict) -> str:
    cmd = _arg_str(args, "command")
    if not cmd:
        ws = ctx.workspace
        if (ws / "package.json").exists():
            cmd = "npm run build"
        elif (ws / "Cargo.toml").exists():
            cmd = "cargo build"
        elif (ws / "Makefile").exists():
            cmd = "make"
        elif (ws / "pyproject.toml").exists():
            cmd = "pip install -e ."
        else:
            return _err("No se detectó build; usa 'command'")
    return await tool_execute_command(ctx, {"command": cmd, "timeout": 600})


# ------------------------------- git -----------------------------------


async def _git(ctx: AgentContext, args: list[str], timeout: int = 60) -> str:
    res = await ctx.sandbox.exec("git " + " ".join(a if " " not in a else f'"{a}"' for a in args),
                                 timeout=timeout, key=f"git:{args[0]}", task_id=ctx.task_id)
    return res.truncated(6000)


async def tool_git_status(ctx: AgentContext, args: dict) -> str:
    res = await _git(ctx, ["status", "--porcelain", "-b"])
    return _ok(res or "(repositorio limpio)")


async def tool_git_diff(ctx: AgentContext, args: dict) -> str:
    path = _arg_str(args, "path")
    extra = ["--", path] if path else []
    res = await _git(ctx, ["diff", "HEAD"] + extra)
    staged = await _git(ctx, ["diff", "--cached"] + extra)
    return _ok((res + ("\n--- staged ---\n" + staged if staged.strip() else "")).strip() or "(sin cambios)")


async def tool_git_branch(ctx: AgentContext, args: dict) -> str:
    name = _arg_str(args, "name")
    if not name:
        return _ok(await _git(ctx, ["branch", "-a"]))
    if not re.fullmatch(r"[A-Za-z0-9._/-]{1,80}", name) or ".." in name or name.startswith("-"):
        return _err("Nombre de rama inválido")
    res = await _git(ctx, ["checkout", "-b", name])
    if "already exists" in res or "ya existe" in res:
        res = await _git(ctx, ["checkout", name])
    await ctx.services.store.set_git_state(ctx.project["id"], current_branch=name)
    return _ok(res)


async def tool_git_commit(ctx: AgentContext, args: dict) -> str:
    msg = _arg_str(args, "message")
    if not msg or len(msg) > 500:
        return _err("Se requiere 'message' (<=500 caracteres)")
    if ctx.project["id"]:
        state = await ctx.services.store.get_git_state(ctx.project["id"])
        if state.get("autopush"):
            pass  # el push, si procede, se gestiona aparte con su autorización
    add = await _git(ctx, ["add", "-A"])
    res = await _git(ctx, ["commit", "-m", msg])
    if not res.strip() or "nothing to commit" in res:
        return _ok(add + "\n(sin cambios para commitear)")
    await ctx.services.store.audit(ctx.user_id, "tool.git_commit", f"task={ctx.task_id}: {msg[:120]}")
    return _ok(add + res)


# git_push y github_pull_request se ejecutan via broker con autorizacion
# (ver engine.py: _execute_with_authorization)


async def tool_get_task_logs(ctx: AgentContext, args: dict) -> str:
    tid = args.get("task_id") or ctx.task_id
    logs = await ctx.services.store.kv_get(f"tasklog:{tid}") or []
    return _ok("\n".join(logs[-50:]) or "(sin registros)")


async def tool_export_zip(ctx: AgentContext, args: dict) -> str:
    """Empaqueta el proyecto y registra el ZIP para entrega automatica al final."""
    import time as _t
    from ..projects.ziputils import ZipUnsafe, create_zip
    name = "proyecto"
    try:
        name = ctx.project.get("name") or name
    except Exception:
        pass
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "proyecto"
    out_dir = Path(getattr(ctx.services.settings, "backups_dir", "/tmp"))
    out = out_dir / f"project-{ctx.project.get('id', 0)}-{slug}-{_t.strftime('%Y%m%d-%H%M%S')}.zip"
    try:
        create_zip(Path(ctx.project["path"]), out)
    except (ZipUnsafe, OSError) as e:
        return _err(f"No se pudo crear el ZIP: {e}")
    ctx.exported_zip = str(out)
    return _ok(f"ZIP creado: {out.name} ({out.stat().st_size} bytes). Se entregara al finalizar.")


# --------------------------- despachador -------------------------------

TOOL_FUNCS = {
    "list_files": tool_list_files,
    "read_file": tool_read_file,
    "write_file": tool_write_file,
    "edit_file": tool_edit_file,
    "apply_patch": tool_apply_patch,
    "search_files": tool_search_files,
    "search_code": tool_search_code,
    "create_directory": tool_create_directory,
    "move_file": tool_move_file,
    "delete_file": tool_delete_file,
    "execute_command": tool_execute_command,
    "install_dependencies": tool_install_dependencies,
    "run_tests": tool_run_tests,
    "run_build": tool_run_build,
    "git_status": tool_git_status,
    "git_diff": tool_git_diff,
    "git_branch": tool_git_branch,
    "git_commit": tool_git_commit,
    "get_task_logs": tool_get_task_logs,
    "export_zip": tool_export_zip,
}


async def execute_tool(ctx: AgentContext, name: str, arguments: str | dict) -> tuple[str, dict]:
    """Ejecuta una herramienta con validacion estricta de argumentos.
    Devuelve (resultado_json, meta) donde meta incluye datos para el resumen."""
    meta: dict = {}
    try:
        if isinstance(arguments, str):
            try:
                args = json.loads(arguments or "{}")
            except json.JSONDecodeError as e:
                return _err(f"Argumentos JSON inválidos: {e}"), meta
        else:
            args = arguments
        if not isinstance(args, dict):
            return _err("Los argumentos deben ser un objeto JSON"), meta
        if name in ("git_push", "github_pull_request"):
            # gestionados por el motor con autorizacion del usuario
            return _err("Esta herramienta se gestiona con autorización del usuario"), meta
        fn = TOOL_FUNCS.get(name)
        if not fn:
            return _err(f"Herramienta desconocida: {name}"), meta
        result = await fn(ctx, args)
        if name in ("write_file", "edit_file", "apply_patch", "delete_file", "move_file"):
            meta["modified"] = True
        return result, meta
    except CommandDenied as e:
        return _err(f"Politica de seguridad: {e}"), meta
    except Exception as e:  # nunca tumbar la tarea por una herramienta
        return _err(f"Excepción interna en '{name}': {e}"), meta
