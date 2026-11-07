"""11) 12) 13) Sandbox local: ejecucion, limites, timeout y cancelacion."""
import asyncio
import os

import pytest

from core.sandbox.local_sandbox import LocalSandbox
from security.command_guard import CommandDenied


async def test_exec_basica(tmp_path):
    sbx = LocalSandbox(tmp_path / "ws")
    await sbx.setup()
    res = await sbx.exec("echo hola-sandbox")
    assert res.ok and "hola-sandbox" in res.stdout


async def test_cwd_limitado_al_workspace(tmp_path):
    ws = tmp_path / "ws"
    sbx = LocalSandbox(ws)
    await sbx.setup()
    (ws / "datos.txt").write_text("contenido")
    res = await sbx.exec("cat datos.txt")
    assert res.ok and "contenido" in res.stdout
    with pytest.raises(Exception):
        await sbx.exec("pwd", cwd="../../etc")


async def test_entorno_sin_secretos(tmp_path):
    os.environ["TELEGRAM_BOT_TOKEN"] = "super-secreto"
    try:
        sbx = LocalSandbox(tmp_path / "ws")
        await sbx.setup()
        res = await sbx.exec("echo \"$TELEGRAM_BOT_TOKEN\"")
        assert res.stdout.strip() == ""
    finally:
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)


async def test_timeout_mata_el_proceso(tmp_path):
    sbx = LocalSandbox(tmp_path / "ws", timeout_s=2)
    await sbx.setup()
    res = await sbx.exec("sleep 30", timeout=1)
    assert res.timed_out and not res.ok


async def test_limite_memoria(tmp_path):
    sbx = LocalSandbox(tmp_path / "ws", memory_mb=64)
    await sbx.setup()
    res = await sbx.exec("python3 -c \"x = bytearray(200 * 1024 * 1024)\"", timeout=30)
    assert not res.ok  # MemoryError -> exit != 0


async def test_cancelacion(tmp_path):
    sbx = LocalSandbox(tmp_path / "ws")
    await sbx.setup()
    task = asyncio.create_task(sbx.exec("sleep 20", key="larga"))
    await asyncio.sleep(0.4)
    assert await sbx.kill("larga")
    res = await asyncio.wait_for(task, timeout=5)
    assert not res.ok  # el proceso fue muerto desde fuera


async def test_comando_prohibido(tmp_path):
    sbx = LocalSandbox(tmp_path / "ws")
    await sbx.setup()
    with pytest.raises(CommandDenied):
        await sbx.exec("sudo id")


async def test_info_y_reset(tmp_path):
    sbx = LocalSandbox(tmp_path / "ws")
    await sbx.setup()
    info = sbx.info()
    assert info["kind"] == "local" and "warning" in info
    await sbx.reset()
