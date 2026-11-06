"""2) y 3) REGLA FUNDAMENTAL: sin system prompt por defecto; modo personalizado."""
import pytest

from core.prompts.service import PromptMode


async def test_nativo_no_envia_system(services, store, fake_provider_cls):
    """El mensaje recibido por la API NO contiene rol system en modo nativo."""
    prov = fake_provider_cls(script=[{"content": "hola"}])
    messages = await services.prompts.build_messages(111, [{"role": "user", "content": "hi"}])
    assert messages == [{"role": "user", "content": "hi"}]
    # a traves del motor del agente tambien
    services.providers.get = lambda *a, **k: _ret(prov)
    services.providers.active_name = lambda *a, **k: _ret("fake")
    await store.set_pref(111, "model:fake", "fake-mini")
    ws = store.db.path.parent / "ws-agente"
    ws.mkdir(parents=True, exist_ok=True)
    pid = await store.create_project(111, "demo", str(ws))
    proj = await store.get_project(pid)
    from core.tools.context import AgentContext
    import asyncio as _a
    from pathlib import Path
    from security.path_guard import PathGuard
    from core.sandbox.local_sandbox import LocalSandbox
    ctx = AgentContext(user_id=111, chat_id=1, project=proj, workspace=Path(ws),
                       guard=PathGuard(ws), sandbox=LocalSandbox(ws), services=services,
                       cancel_event=_a.Event())
    outcome = await services.engine.run_task(ctx, "saluda")
    first = prov.calls[0]["messages"][0]
    assert first["role"] != "system"
    assert outcome.summary == "hola"


async def _ret(v):
    return v


async def test_custom_envia_un_solo_system(services, store):
    await services.prompts.set_custom(111, "Eres un asistente de pruebas.")
    messages = await services.prompts.build_messages(111, [{"role": "user", "content": "hi"}])
    systems = [m for m in messages if m["role"] == "system"]
    assert len(systems) == 1
    assert systems[0]["content"] == "Eres un asistente de pruebas."


async def test_off_vuelve_a_nativo(services):
    await services.prompts.set_custom(111, "x")
    await services.prompts.set_mode(111, PromptMode.NATIVE)
    eff = await services.prompts.status(111)
    assert eff.mode == PromptMode.NATIVE and eff.content is None


async def test_clear_y_reset(services):
    await services.prompts.set_custom(111, "x")
    await services.prompts.clear(111)
    mode, content = await services.prompts.show(111)
    assert mode == PromptMode.NATIVE and content is None
    await services.prompts.set_custom(111, "y")
    await services.prompts.reset(111)
    eff = await services.prompts.status(111)
    assert eff.content is None


async def test_prompt_de_proyecto(services, store, project):
    proj = await project()
    # inactivo por defecto: nativo
    eff = await services.prompts.status(111, proj)
    assert eff.mode == PromptMode.NATIVE
    await store.update_project(proj["id"], system_prompt="Prompt del proyecto",
                               prompt_enabled=1)
    eff = await services.prompts.status(111, await store.get_project(proj["id"]))
    assert eff.mode == PromptMode.PROJECT
    assert eff.content == "Prompt del proyecto"


async def test_export_import(services):
    await services.prompts.set_custom(111, "mi prompt")
    data = await services.prompts.export(111)
    assert data["content"] == "mi prompt"
    await services.prompts.clear(111)
    await services.prompts.import_prompt(111, data)
    mode, content = await services.prompts.show(111)
    assert content == "mi prompt"
