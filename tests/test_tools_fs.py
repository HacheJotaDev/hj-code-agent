"""Herramientas del sistema de archivos del agente (validacion estricta)."""
import json

import pytest

from core.tools.context import AgentContext
from core.tools.registry import (apply_unified_diff, execute_tool, tool_edit_file,
                                 tool_read_file, tool_write_file)


@pytest.fixture
def ctx(services, store, tmp_path):
    import asyncio as _a
    from security.path_guard import PathGuard
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    pid = store.db.path  # placeholder para tipar
    project = {"id": 1, "name": "t", "path": str(ws), "user_id": 111}
    return AgentContext(user_id=111, chat_id=1, project=project, workspace=ws,
                        guard=PathGuard(ws), sandbox=None, services=services,
                        cancel_event=_a.Event())


def _r(s: str) -> dict:
    return json.loads(s)


async def test_write_y_read(ctx):
    r = _r(await tool_write_file(ctx, {"path": "src/app.py", "content": "x = 1\n"}))
    assert r["ok"]
    r = _r(await tool_read_file(ctx, {"path": "src/app.py"}))
    assert "x = 1" in r["result"] and ctx.files_touched == ["src/app.py"]


async def test_read_limites(ctx):
    await tool_write_file(ctx, {"path": "big.txt", "content": "\n".join(map(str, range(500)))})
    r = _r(await tool_read_file(ctx, {"path": "big.txt", "offset": 10, "limit": 5}))
    assert r["result"].splitlines()[1] == "10"


async def test_edit_exacto(ctx):
    await tool_write_file(ctx, {"path": "a.py", "content": "def hola():\n    pass\n"})
    r = _r(await tool_edit_file(ctx, {"path": "a.py", "old": "pass", "new": "return 1"}))
    assert r["ok"]
    assert "return 1" in (ctx.workspace / "a.py").read_text()
    r = _r(await tool_edit_file(ctx, {"path": "a.py", "old": "no-existe", "new": "x"}))
    assert not r["ok"]


def test_apply_unified_diff_ok():
    original = "linea1\nlinea2\nlinea3\n"
    patch = ("--- a/f.txt\n+++ b/f.txt\n"
             "@@ -1,3 +1,3 @@\n linea1\n-linea2\n+LINEA2\n linea3\n")
    assert apply_unified_diff(original, patch) == "linea1\nLINEA2\nlinea3\n"


def test_apply_unified_diff_contexto_invalido():
    with pytest.raises(ValueError):
        apply_unified_diff("otro\n", "--- a/f\n+++ b/f\n@@ -1,1 +1,1 @@\n-x\n+y\n")


async def test_ruta_fuera_bloqueada(ctx):
    r = _r(await tool_write_file(ctx, {"path": "../escape.txt", "content": "x"}))
    assert not r["ok"]
    r = _r(await tool_read_file(ctx, {"path": "/etc/passwd"}))
    assert not r["ok"]


async def test_delete_auditado(ctx):
    await tool_write_file(ctx, {"path": "tmp.txt", "content": "x"})
    result, _meta = await execute_tool(ctx, "delete_file", {"path": "tmp.txt"})
    r = _r(result)
    assert r["ok"] and not (ctx.workspace / "tmp.txt").exists()


async def test_move_y_create_dir(ctx):
    _r(await tool_write_file(ctx, {"path": "d/old.txt", "content": "x"}))
    result, _m = await execute_tool(ctx, "create_directory", {"path": "nueva"})
    assert _r(result)["ok"]
    result, _m = await execute_tool(ctx, "move_file", {"src": "d/old.txt", "dst": "nueva/new.txt"})
    r = _r(result)
    assert r["ok"] and (ctx.workspace / "nueva" / "new.txt").exists()


async def test_search_code_y_files(ctx):
    await tool_write_file(ctx, {"path": "m.py", "content": "def secreto(): pass\n"})
    result, _m = await execute_tool(ctx, "search_code", {"regex": "def secreto"})
    r = _r(result)
    assert "m.py" in r["result"]
    result, _m = await execute_tool(ctx, "search_files", {"pattern": "**/*.py"})
    r = _r(result)
    assert "m.py" in r["result"]


async def test_herramienta_desconocida(ctx):
    result, _m = await execute_tool(ctx, "rm_rf_root", {})
    r = _r(result)
    assert not r["ok"]


async def test_args_json_invalidos(ctx):
    result, _m = await execute_tool(ctx, "read_file", "{mal json")
    r = _r(result)
    assert not r["ok"]
