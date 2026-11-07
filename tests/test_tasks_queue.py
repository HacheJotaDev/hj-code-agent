"""12) 17) Cola de tareas, cancelacion y recuperacion tras reinicio."""
import asyncio

import pytest

from core.sandbox.local_sandbox import LocalSandbox
from core.tasks.queue import TaskQueue


class FakeEngine:
    def __init__(self, slow=0.0):
        self.calls = []
        self.slow = slow

    async def run_task(self, ctx, task_text, notify=None):
        self.calls.append(task_text)
        if self.slow:
            await asyncio.sleep(self.slow)
        from core.agent.engine import TaskOutcome
        return TaskOutcome(summary=f"hecho: {task_text}", files_touched=["a.py"],
                           cost=0.01, cost_known=True)


async def make_queue(services, store, engine=None, workers=1):
    services.engine = engine or FakeEngine()
    q = TaskQueue(services)
    services.settings.max_concurrent_tasks = workers
    async def make_sandbox(ws, proj):
        return LocalSandbox(ws)
    services.make_sandbox = make_sandbox
    await q.start()
    return q


async def test_tarea_ejecuta_y_finaliza(services, store, project):
    proj = await project()
    q = await make_queue(services, store)
    tid = await q.submit(111, 1, proj, None, "tarea simple")
    for _ in range(100):
        await asyncio.sleep(0.05)
        t = await store.get_task(tid)
        if t["status"] == "done":
            break
    assert t["status"] == "done"
    assert "hecho" in t["result"]
    assert t["steps"] >= 0
    # notificacion al chat
    assert services.bot.sent
    await q.stop()


async def test_recuperacion_tras_reinicio(services, store, project):
    proj = await project()
    tid = await store.create_task(111, 1, proj["id"], None, "agent", "volada", 5)
    await store.update_task(tid, status="running")  # simula muerte en ejecucion
    q = await make_queue(services, store)  # el arranque ejecuta recover
    t = await store.get_task(tid)
    assert t["status"] == "interrupted"
    await q.stop()


async def test_retry_tras_interrupcion(services, store, project):
    proj = await project()
    tid = await store.create_task(111, 1, proj["id"], None, "agent", "reintento", 5)
    await store.update_task(tid, status="interrupted", error="El bot se reinicio")
    q = await make_queue(services, store)
    await store.update_task(tid, status="queued")
    q.kick()
    for _ in range(100):
        await asyncio.sleep(0.05)
        t = await store.get_task(tid)
        if t["status"] == "done":
            break
    assert t["status"] == "done"
    await q.stop()


async def test_tarea_sobre_proyecto_inexistente_falla_limpio(services, store):
    tid = await store.create_task(111, 1, 99999, None, "agent", "fantasma", 5)
    q = await make_queue(services, store)
    q.kick()
    for _ in range(100):
        await asyncio.sleep(0.05)
        t = await store.get_task(tid)
        if t["status"] == "failed":
            break
    assert t["status"] == "failed"
    await q.stop()


async def test_1_tarea_por_usuario(services, store, project):
    proj = await project()
    q = await make_queue(services, store)
    engine = FakeEngine(slow=1.0)
    services.engine = engine
    t1 = await q.submit(111, 1, proj, None, "lenta")
    for _ in range(50):
        await asyncio.sleep(0.05)
        if (await store.get_task(t1))["status"] == "running":
            break
    # una segunda tarea del mismo usuario NO arranca hasta que acabe la primera
    t2 = await store.create_task(111, 1, proj["id"], None, "agent", "segunda", 5)
    await store.update_task(t2, status="queued")
    q.kick()
    await asyncio.sleep(0.3)
    assert (await store.get_task(t2))["status"] == "queued"
    assert q.running_for_user(111)
    # cancelar la primera desbloquea
    q.cancel(t1)
    for _ in range(200):
        await asyncio.sleep(0.05)
        if (await store.get_task(t1))["status"] in ("cancelled", "done"):
            break
    await q.stop()
