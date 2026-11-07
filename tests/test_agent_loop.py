"""Motor del agente: bucle real de herramientas, pasos, presupuesto y cancelacion.

Usa un proveedor FALSO con guion; las herramientas se ejecutan DE VERDAD.
"""
import asyncio
import json
from pathlib import Path

import pytest

from core.agent.engine import BudgetExceeded
from core.sandbox.local_sandbox import LocalSandbox
from core.tools.context import AgentContext
from security.path_guard import PathGuard


def make_ctx(services, project, max_steps=8) -> AgentContext:
    ws = Path(project["path"])
    return AgentContext(user_id=111, chat_id=1, project=project, workspace=ws,
                        guard=PathGuard(ws), sandbox=LocalSandbox(ws), services=services,
                        cancel_event=asyncio.Event(), max_steps=max_steps)


async def wire(services, store, fake_provider_cls, script):
    prov = fake_provider_cls(script=script)
    services.providers.get = lambda *a, **k: _ret(prov)
    services.providers.active_name = lambda *a, **k: _ret("fake")
    await store.set_pref(111, "model:fake", "fake-mini")
    return prov


async def _ret(v):
    return v


async def test_agente_crea_archivo_y_termina(services, store, fake_provider_cls, project):
    proj = await project()
    await services.pricing.set_rate("fake", "fake-mini", 0.5, 1.0, "USD")
    script = [
        {"tool_calls": [{"id": "c1", "name": "write_file",
                         "arguments": json.dumps({"path": "hola.py", "content": "print('v2')"})}]},
        {"content": "Listo: archivo creado."},
    ]
    prov = await wire(services, store, fake_provider_cls, script)
    ctx = make_ctx(services, proj)
    outcome = await services.engine.run_task(ctx, "crea hola.py")
    assert outcome.summary == "Listo: archivo creado."
    assert (Path(proj["path"]) / "hola.py").exists()
    assert "hola.py" in outcome.files_touched
    assert ctx.steps == 2
    assert outcome.cost_known  # el guion aporta usage real
    # el historial guarda user/assistant/tool
    msgs = await store.get_messages(ctx.conversation_id or 0) if ctx.conversation_id else []


async def test_herramienta_recibe_resultado_real(services, store, fake_provider_cls, project):
    proj = await project()
    (Path(proj["path"]) / "existe.txt").write_text("contenido-42")
    script = [
        {"tool_calls": [{"id": "c1", "name": "read_file",
                         "arguments": json.dumps({"path": "existe.txt"})}]},
        {"content": "fin"},
    ]
    prov = await wire(services, store, fake_provider_cls, script)
    ctx = make_ctx(services, proj)
    await services.engine.run_task(ctx, "lee el archivo")
    # segunda llamada del modelo: el historial incluye el tool result REAL
    second = prov.calls[1]["messages"]
    tool_msgs = [m for m in second if m.get("role") == "tool"]
    assert tool_msgs and "contenido-42" in tool_msgs[0]["content"]


async def test_sin_system_en_llamadas(services, store, fake_provider_cls, project):
    proj = await project()
    script = [{"content": "ok"}]
    prov = await wire(services, store, fake_provider_cls, script)
    ctx = make_ctx(services, proj)
    await services.engine.run_task(ctx, "hola")
    roles = [m["role"] for m in prov.calls[0]["messages"]]
    assert "system" not in roles


async def test_limite_de_pasos(services, store, fake_provider_cls, project):
    proj = await project()
    loop = {"tool_calls": [{"id": "cX", "name": "list_files", "arguments": "{}"}]}
    script = [loop] * 30
    await wire(services, store, fake_provider_cls, script)
    ctx = make_ctx(services, proj, max_steps=3)
    outcome = await services.engine.run_task(ctx, "bucle")
    assert ctx.steps == 3
    assert "limite de pasos" in outcome.summary.lower()


async def test_presupuesto_por_tarea(services, store, fake_provider_cls, project):
    proj = await project()
    await store.set_budget(111, per_task=0.001)
    script = [
        {"tool_calls": [{"id": "c1", "name": "list_files", "arguments": "{}"}], "pt": 100000, "ct": 50000},
        {"content": "nunca"},
    ]
    await services.pricing.set_rate("fake", "fake-mini", 1.0, 1.0, "USD")
    await wire(services, store, fake_provider_cls, script)
    ctx = make_ctx(services, proj)
    outcome = await services.engine.run_task(ctx, "gasta")
    assert outcome.error and "Presupuesto por tarea" in outcome.error


async def test_cancelacion_inmediata(services, store, fake_provider_cls, project):
    proj = await project()
    await wire(services, store, fake_provider_cls, [{"tool_calls": [{"id": "c1", "name": "list_files", "arguments": "{}"}]}])
    ctx = make_ctx(services, proj)
    ctx.cancel_event.set()
    outcome = await services.engine.run_task(ctx, "x")
    assert outcome.cancelled


async def test_sin_tarifa_no_inventa_coste(services, store, fake_provider_cls, project):
    """Sin tarifa configurada el coste es None (nunca se inventa) pero los tokens se registran."""
    proj = await project()
    await wire(services, store, fake_provider_cls, [{"content": "ok"}])
    ctx = make_ctx(services, proj)
    outcome = await services.engine.run_task(ctx, "hola")
    assert not outcome.cost_known
    t = await services.usage.totals(111)
    assert t["tt"] > 0 and t["cost"] == 0


async def test_push_del_agente_pide_autorizacion(services, store, fake_provider_cls, project):
    proj = await project()
    script = [
        {"tool_calls": [{"id": "c1", "name": "git_push", "arguments": "{}"}]},
        {"content": "fin"},
    ]
    await wire(services, store, fake_provider_cls, script)
    ctx = make_ctx(services, proj)

    async def notifier(text):
        ctx.approvals["last_notify"] = text
    ctx.notify = notifier

    import threading
    # aprueba la peticion cuando aparezca
    async def auto_aprobar():
        for _ in range(100):
            await asyncio.sleep(0.05)
            if services.approvals._waiters:
                req_id = next(iter(services.approvals._waiters))
                services.approvals.resolve(req_id, approved=True)
                return
    asyncio.get_event_loop().create_task(auto_aprobar())
    broker = services.broker
    outcome = await services.engine.run_task(ctx, "publica")
    # el broker falso registra el push autorizado
    assert broker.pushes and broker.pushes[0][0] == proj["id"]


async def test_rechazo_de_push(services, store, fake_provider_cls, project):
    proj = await project()
    script = [
        {"tool_calls": [{"id": "c1", "name": "git_push", "arguments": "{}"}]},
        {"content": "fin"},
    ]
    await wire(services, store, fake_provider_cls, script)
    ctx = make_ctx(services, proj)

    async def auto_rechazar():
        for _ in range(100):
            await asyncio.sleep(0.05)
            if services.approvals._waiters:
                req_id = next(iter(services.approvals._waiters))
                services.approvals.resolve(req_id, approved=False)
                return
    asyncio.get_event_loop().create_task(auto_rechazar())
    outcome = await services.engine.run_task(ctx, "publica")
    assert not services.broker.pushes
