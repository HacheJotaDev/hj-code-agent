"""Pruebas del flujo real chat -> tarea -> eventos (plan, actividad, SSE,
cancelacion, reintento, persistencia y HJ_DB_PATH).

Simulan fallos y ciclos reales: el motor completo (engine V3 + cola web +
sandbox local) corre contra un proveedor falso con guion, sin red.
"""
from __future__ import annotations

import json

import pytest

from tests.web_utils import (FakeWebProvider, build_env, make_web_settings,
                             tool_call, wait_task_status)

pytestmark = pytest.mark.asyncio

PLAN_INICIAL = [
    {"title": "Explorar el proyecto", "status": "in_progress"},
    {"title": "Crear archivo hola.txt", "status": "pending"},
    {"title": "Resumir resultados", "status": "pending"},
]
PLAN_FINAL = [
    {"title": "Explorar el proyecto", "status": "done"},
    {"title": "Crear archivo hola.txt", "status": "done"},
    {"title": "Resumir resultados", "status": "done"},
]

GUION_AGENTE = [
    {"tool_calls": [tool_call("c1", "update_plan", steps=PLAN_INICIAL)]},
    {"tool_calls": [tool_call("c2", "list_files", path=".")]},
    {"tool_calls": [tool_call("c3", "write_file", path="hola.txt", content="Hola V4")]},
    {"tool_calls": [tool_call("c4", "update_plan", steps=PLAN_FINAL)]},
    {"content": "Listo: explore el proyecto, cree hola.txt y todo verifico."},
]


async def _setup_conv_with_project(env, name="flujo-web"):
    r = await env.post("/api/projects", {"name": name})
    pid = r.json()["project"]["id"]
    r = await env.post("/api/conversations", {"project_id": pid})
    cid = r.json()["conversation"]["id"]
    return pid, cid


async def test_ciclo_completo_plan_herramientas_y_eventos(tmp_path):
    """El flujo estrella: mensaje -> tarea -> plan visual -> herramientas ->
    archivo real -> estado done -> eventos persistidos."""
    s = make_web_settings(tmp_path)
    provider = FakeWebProvider(GUION_AGENTE)
    async with build_env(s, provider) as env:
        await env.login()
        pid, cid = await _setup_conv_with_project(env)
        r = await env.post(f"/api/conversations/{cid}/messages",
                           {"text": "Explora y crea hola.txt", "model": "fake-mini"})
        assert r.status_code == 200, r.text
        tid = r.json()["task_id"]

        task = await wait_task_status(env, tid, {"done"}, timeout_s=40)
        # 1) El plan visual llega del modelo (update_plan), no lo inventa la UI
        assert task["plan"] == PLAN_FINAL
        # 2) El archivo SE escribio realmente en el workspace
        ws = tmp_path / "workspaces" / "111" / "flujo-web" / "hola.txt"
        assert ws.exists() and ws.read_text() == "Hola V4"
        # 3) Historial persistido en la conversacion
        r = await env.get(f"/api/conversations/{cid}/messages")
        roles = [m["role"] for m in r.json()["messages"]]
        assert roles[0] == "user"
        assert roles.count("tool") == 4  # update_plan, list_files, write_file, update_plan
        assert roles[-1] == "assistant"
        # 4) Eventos: plan x2, tool x4, status final
        r = await env.get(f"/api/tasks/{tid}/events", params={"after": 0})
        events = r.json()["events"]
        tipos = [e["type"] for e in events]
        assert tipos.count("plan") == 2
        assert tipos.count("tool") == 4
        assert tipos[-1] == "status"
        assert events[-1]["data"]["status"] == "done"
        # 5) El proveedor recibio las herramientas, incluida update_plan
        assert provider.calls and provider.calls[0]["n_tools"] == 23


async def test_sse_replay_y_end(tmp_path):
    """SSE: reproduce el historial completo y cierra con evento end."""
    s = make_web_settings(tmp_path)
    async with build_env(s, FakeWebProvider(GUION_AGENTE)) as env:
        await env.login()
        pid, cid = await _setup_conv_with_project(env)
        r = await env.post(f"/api/conversations/{cid}/messages",
                           {"text": "trabajo con plan"})
        tid = r.json()["task_id"]
        await wait_task_status(env, tid, {"done"}, timeout_s=40)
        # stream completo: recibe hasta end
        req = env.client.build_request("GET", f"/api/tasks/{tid}/stream")
        res = await env.client.send(req)
        assert res.status_code == 200
        body = res.text
        assert "event: plan" in body
        assert "event: tool" in body
        assert "event: status" in body
        assert "event: end" in body
        # replay parcial con after: solo los ultimos eventos (sin plan inicial)
        res = await env.client.get(f"/api/tasks/{tid}/stream",
                                   params={"after": 10 ** 9})
        assert "event: end" in res.text or res.text == ""


async def test_fallo_de_tarea_deja_estado_y_error_reales(tmp_path):
    """Fallo real del proveedor -> task failed con error, jamas 'done'."""
    from core.providers.errors import ProviderError
    s = make_web_settings(tmp_path)
    provider = FakeWebProvider([ProviderError("401: API key invalida")])
    async with build_env(s, provider) as env:
        await env.login()
        pid, cid = await _setup_conv_with_project(env)
        r = await env.post(f"/api/conversations/{cid}/messages",
                           {"text": "esto va a fallar"})
        tid = r.json()["task_id"]
        task = await wait_task_status(env, tid, {"failed"}, timeout_s=40)
        assert "401" in (task["error"] or "") or "API key" in (task["error"] or "")
        # reintento: nueva tarea con la MISMA instruccion (continuacion)
        provider.script.append({"content": "ahora si funciona"})
        r = await env.post(f"/api/tasks/{tid}/retry")
        assert r.status_code == 200
        new_tid = r.json()["task_id"]
        task2 = await wait_task_status(env, new_tid, {"done"}, timeout_s=40)
        assert "funciona" in task2["result"]


async def test_limite_de_pasos_no_falsa_el_plan(tmp_path):
    """Si se alcanza el limite de pasos, la tarea NO es 'done' y el plan
    queda pendiente (nunca completado ficticio)."""
    s = make_web_settings(tmp_path, HJ_MAX_TASK_STEPS="2")
    guion = [
        {"tool_calls": [tool_call("p1", "update_plan", steps=[
            {"title": "paso A", "status": "in_progress"},
            {"title": "paso B", "status": "pending"}])]},
        {"tool_calls": [tool_call("p2", "list_files", path=".")]},
        # el 3er paso ya no se ejecuta (limite 2): termina por limite
        {"tool_calls": [tool_call("p3", "list_files", path=".")]},
    ]
    async with build_env(s, FakeWebProvider(guion)) as env:
        await env.login()
        pid, cid = await _setup_conv_with_project(env)
        r = await env.post(f"/api/conversations/{cid}/messages", {"text": "tarea larga"})
        tid = r.json()["task_id"]
        task = await wait_task_status(env, tid, {"done", "failed"}, timeout_s=40)
        assert task["steps"] == 2
        plan = task["plan"]
        assert plan[0]["status"] == "in_progress"  # no se falsifico a done
        assert plan[1]["status"] == "pending"
        assert "limite" in (task["result"] or "").lower()
        # evento plan_incomplete explicito
        r = await env.get(f"/api/tasks/{tid}/events", params={"after": 0})
        tipos = [e["type"] for e in r.json()["events"]]
        assert "plan_incomplete" in tipos


async def test_cancelacion_de_tarea_en_cola(tmp_path):
    """Con 1 tarea por usuario, la segunda queda en cola y se puede cancelar."""
    s = make_web_settings(tmp_path)
    # tarea 1: proveedor con comando real que tarda (mantiene la cola ocupada)
    guion1 = [
        {"tool_calls": [tool_call("s1", "execute_command", command="sleep 2",
                                  timeout=10)]},
        {"content": "primera terminada"},
    ]
    async with build_env(s, FakeWebProvider(guion1)) as env:
        await env.login()
        pid, cid = await _setup_conv_with_project(env)
        r1 = await env.post(f"/api/conversations/{cid}/messages", {"text": "tarea uno"})
        tid1 = r1.json()["task_id"]
        # tarea 2: se encola (1 tarea por usuario en marcha)
        r2 = await env.post(f"/api/conversations/{cid}/messages", {"text": "tarea dos"})
        tid2 = r2.json()["task_id"]
        r = await env.post(f"/api/tasks/{tid2}/cancel")
        assert r.status_code == 200
        task2 = await wait_task_status(env, tid2, {"cancelled"}, timeout_s=15)
        assert task2["status"] == "cancelled"
        # la primera sigue su curso y termina bien
        task1 = await wait_task_status(env, tid1, {"done"}, timeout_s=40)
        assert task1["status"] == "done"


async def test_modelo_inexistente_rechazado(tmp_path):
    """No se aceptan modelos que el proveedor no lista (nada inventado)."""
    s = make_web_settings(tmp_path)
    async with build_env(s, FakeWebProvider([])) as env:
        await env.login()
        pid, cid = await _setup_conv_with_project(env)
        r = await env.post(f"/api/conversations/{cid}/messages",
                           {"text": "hola", "model": "modelo-inventado-9000"})
        assert r.status_code == 400
        assert "no lista" in r.json()["detail"]


async def test_mensaje_sin_proyecto_rechazado(tmp_path):
    s = make_web_settings(tmp_path)
    async with build_env(s, FakeWebProvider([])) as env:
        await env.login()
        r = await env.post("/api/conversations", {"title": "sin proyecto"})
        cid = r.json()["conversation"]["id"]
        r = await env.post(f"/api/conversations/{cid}/messages", {"text": "hola"})
        assert r.status_code == 400
        assert "proyecto" in r.json()["detail"].lower()


async def test_hj_db_path_respetado(tmp_path):
    """El backend web respeta HJ_DB_PATH (misma BD que V3/bot)."""
    custom = tmp_path / "custom" / "agente.db"
    s = make_web_settings(tmp_path, HJ_DB_PATH=str(custom))
    async with build_env(s, FakeWebProvider([])) as env:
        await env.login()
        r = await env.post("/api/conversations", {"title": "db"})
        assert r.status_code == 200
    assert custom.exists() and custom.stat().st_size > 0


async def test_recuperacion_tras_reinicio_marca_interrumpidas(tmp_path):
    """Persistencia: una tarea 'running' encontrada al arrancar se marca
    'interrupted' (recuperable con retry), jamas 'done'."""
    import asyncio
    s = make_web_settings(tmp_path)
    provider = FakeWebProvider([])
    tid_fantasma = None
    async with build_env(s, provider) as env:
        await env.login()
        pid, cid = await _setup_conv_with_project(env)
        # simular una tarea colgada de un proceso anterior
        tid_fantasma = await env.app.state.ctx.store.create_task(
            111, 111, pid, cid, "agent", "tarea de otro proceso", 24)
        await env.app.state.ctx.store.update_task(tid_fantasma, status="running")
    # reabrir la app: el arranque debe recuperarla
    async with build_env(s, FakeWebProvider([])) as env2:
        await env2.login()
        r = await env2.get(f"/api/tasks/{tid_fantasma}")
        assert r.status_code == 200
        assert r.json()["status"] == "interrupted"
        # y es reintentable
        r = await env2.post(f"/api/tasks/{tid_fantasma}/retry")
        assert r.status_code == 200
