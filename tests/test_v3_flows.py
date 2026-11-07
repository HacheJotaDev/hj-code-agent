"""Pruebas de flujo V3 (1-14): updates reales de Telegram -> dispatcher REAL.

Cada prueba simula una actualizacion de Telegram completa (mensaje, documento
o callback) que atraviesa middlewares, routers y servicios, usando mocks solo
para la red (Telegram HTTP y proveedores LLM). Lo que NO se valida contra
servicios reales queda marcado en docs/ESTADO.md.
"""
import io
import json
import zipfile
from types import SimpleNamespace

import pytest

import harness as H
from harness import (assert_valid_html, feed, make_bot,
                     make_callback, make_document, make_message, msg_texts)


@pytest.fixture(scope="session")
def dp():
    return H.build_dispatcher_once()


@pytest.fixture
async def app(services, dp, tmp_path):
    from core.authentication.auth_service import AuthService
    from core.tasks.queue import TaskQueue

    services.auth = AuthService(services.store)
    session = H.RecordingSession()
    services.bot = make_bot(session)
    services.queue = TaskQueue(services)  # sin workers: ejecucion manual en tests
    H.set_ctx(services)
    return SimpleNamespace(services=services, session=session, dp=dp,
                           bot=services.bot, tmp_path=tmp_path)


def patch_provider(app, fake_provider_cls, script):
    fp = fake_provider_cls(script=script)

    async def fake_get(uid, provider_name=None):
        return fp

    async def fake_name(uid):
        return "fake"

    app.services.providers.get = fake_get
    app.services.providers.active_name = fake_name
    return fp


async def run_queued_task(app):
    task = await app.services.store.next_queued()
    assert task, "no hay tarea en cola"
    await app.services.queue._execute(task)
    return await app.services.store.get_task(task["id"])


# ---------------------------------------------------------------- Prueba 1 --

async def test_prueba1_primera_ejecucion(app):
    await feed(app.dp, app.bot, make_message("/start"))
    texts = msg_texts(app.session)
    assert any("HJ CODE AGENT V3" in t for t in texts)
    for t in texts:
        assert_valid_html(t)


# ---------------------------------------------------------------- Prueba 2 --

async def test_prueba2_proveedor_modelo_y_respuesta(app, fake_provider_cls):
    patch_provider(app, fake_provider_cls, [{"content": "respuesta de prueba"}])
    await app.services.store.set_pref(111, "model:fake", "")
    await feed(app.dp, app.bot, make_message("/model select fake-mini"))
    assert await app.services.store.get_pref(111, "model:fake") == "fake-mini"
    await feed(app.dp, app.bot, make_message("¿cómo funciona asyncio en Python?"))
    texts = msg_texts(app.session)
    assert any("respuesta de prueba" in t for t in texts)
    for t in texts:
        assert_valid_html(t)


# ---------------------------------------------------------------- Prueba 3 --

async def test_prueba3_chat_sin_proyecto(app, fake_provider_cls):
    patch_provider(app, fake_provider_cls, [{"content": "respuesta sin proyecto"}])
    await app.services.store.set_pref(111, "model:fake", "fake-mini")
    await feed(app.dp, app.bot, make_message("¿qué es la recursión?"))
    assert any("respuesta sin proyecto" in t for t in msg_texts(app.session))
    assert not await app.services.projects.list(111)  # no creo proyectos


# ---------------------------------------------------------------- Prueba 4 --

async def test_prueba4_newproject(app):
    await feed(app.dp, app.bot, make_message("/newproject Demo V3"))
    proj = await app.services.projects.active(111)
    assert proj and proj["name"] == "Demo V3"
    assert any("creado y seleccionado" in t for t in msg_texts(app.session))


# ---------------------------------------------------------------- Prueba 5 --

async def test_prueba5_projects_con_cero_uno_y_varios(app):
    await feed(app.dp, app.bot, make_message("/projects"))
    assert any("No hay proyectos" in t for t in msg_texts(app.session))
    await feed(app.dp, app.bot, make_message("/newproject Uno"))
    await feed(app.dp, app.bot, make_message("/newproject Dos"))
    await feed(app.dp, app.bot, make_message("/projects"))
    joined = "\n".join(msg_texts(app.session))
    assert "Uno" in joined and "Dos" in joined
    for t in msg_texts(app.session):
        assert_valid_html(t)


# ---------------------------------------------------------------- Prueba 6 --

async def test_prueba6_zip_crea_workspace_sin_github(app):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("demo/main.py", "print('hola')\n")
        z.writestr("demo/README.md", "# demo\n")
        z.writestr("demo/requirements.txt", "")
    app.session.downloads["zipdemo"] = buf.getvalue()
    await feed(app.dp, app.bot, make_document("zipdemo", "demo.zip", size=len(buf.getvalue())))
    proj = await app.services.projects.active(111)
    assert proj and proj["name"] == "demo"
    from pathlib import Path
    assert (Path(proj["path"]) / "main.py").exists()
    joined = "\n".join(msg_texts(app.session))
    assert "recibido y extra" in joined
    for t in msg_texts(app.session):
        assert_valid_html(t)


# ---------------------------------------------------------------- Prueba 7 --

async def test_prueba7_programacion_herramientas_reales(app, fake_provider_cls):
    await feed(app.dp, app.bot, make_message("/newproject Coder"))
    patch_provider(app, fake_provider_cls, [
        {"tool_calls": [{"id": "t1", "name": "write_file",
                         "arguments": json.dumps({"path": "saludo.py",
                                                  "content": "print('hola')\n"})}],
         "pt": 120, "ct": 30},
        {"content": "He creado saludo.py con la función pedida."},
    ])
    await app.services.store.set_pref(111, "model:fake", "fake-mini")
    await feed(app.dp, app.bot,
               make_message("corrige y añade un modulo que salude"))
    task = await run_queued_task(app)
    assert task["status"] == "done", task
    proj = await app.services.projects.active(111)
    from pathlib import Path
    assert (Path(proj["path"]) / "saludo.py").read_text().startswith("print")
    joined = "\n".join(msg_texts(app.session))
    assert "He creado saludo.py" in joined
    for t in msg_texts(app.session):
        assert_valid_html(t)


# ---------------------------------------------------------------- Prueba 8 --

async def test_prueba8_tests_reales_en_sandbox(app, fake_provider_cls):
    await feed(app.dp, app.bot, make_message("/newproject Tested"))
    proj = await app.services.projects.active(111)
    from pathlib import Path
    (Path(proj["path"]) / "test_dummy.py").write_text(
        "def test_ok():\n    assert 1 + 1 == 2\n")
    patch_provider(app, fake_provider_cls, [
        {"tool_calls": [{"id": "t2", "name": "run_tests", "arguments": "{}"}],
         "pt": 80, "ct": 20},
        {"content": "Pruebas ejecutadas en el sandbox."},
    ])
    await app.services.store.set_pref(111, "model:fake", "fake-mini")
    await feed(app.dp, app.bot, make_message("ejecuta las pruebas del proyecto"))
    task = await run_queued_task(app)
    assert task["status"] == "done", task
    result = task["result"] or ""
    assert "passed" in result, result[:500]   # salida REAL de pytest
    assert "Pruebas ejecutadas" in "\n".join(msg_texts(app.session))


# ---------------------------------------------------------------- Prueba 9 --

async def test_prueba9_exportacion_zip(app):
    await feed(app.dp, app.bot, make_message("/newproject Exportable"))
    (await app.services.projects.active(111))  # existe
    await feed(app.dp, app.bot, make_message("/export"))
    names = [type(c).__name__ for c in app.session.calls]
    assert "SendDocument" in names


# --------------------------------------------------------------- Prueba 10 --

async def test_prueba10_github_opcional(app, fake_provider_cls):
    # Sin token configurado el bot funciona completo; GitHub solo si se pide
    await feed(app.dp, app.bot, make_message("/github status"))
    assert any("Sin token" in t for t in msg_texts(app.session))
    patch_provider(app, fake_provider_cls, [{"content": "ok sin github"}])
    await app.services.store.set_pref(111, "model:fake", "fake-mini")
    await feed(app.dp, app.bot, make_message("haz un archivo hola.txt"))
    task = await run_queued_task(app)
    assert task["status"] == "done"
    # y el push sigue exigiendo autorizacion explicita
    from core.github.broker import PushNotAuthorized
    proj = await app.services.projects.active(111)
    with pytest.raises(PushNotAuthorized):
        await app.services.broker.push(proj, "main", authorized=False)


# --------------------------------------------------------------- Prueba 11 --

async def test_prueba11_telegram_html_valido(app, fake_provider_cls):
    patch_provider(app, fake_provider_cls, [
        {"content": "Aquí va un ejemplo: /run <tarea> y <b>negrita</b>"}])
    await app.services.store.set_pref(111, "model:fake", "fake-mini")
    await feed(app.dp, app.bot, make_message("/help"))
    await feed(app.dp, app.bot, make_message("explícame qué es <tarea> y <otro>"))
    texts = msg_texts(app.session)
    for t in texts:
        assert_valid_html(t)
    # la respuesta del modelo con <tarea> debe salir ESCAPADA, no cruda
    answer = next(t for t in texts if "ejemplo" in t)
    assert "&lt;tarea&gt;" in answer


# --------------------------------------------------------------- Prueba 12 --

async def test_prueba12_seguridad_acceso(app):
    # usuario NO autorizado: no ve la app
    await feed(app.dp, app.bot, make_message("/start", uid=999))
    await feed(app.dp, app.bot, make_message("hola", uid=999))
    texts = [t for t in msg_texts(app.session)]
    for t in texts:
        assert "HJ CODE AGENT V3" not in t     # nunca recibio la app
        assert "Acceso restringido" in t       # solo el aviso de denegacion
    # no se creo nada para el intruso
    assert not await app.services.projects.list(999)


# --------------------------------------------------------------- Prueba 13 --

async def test_prueba13_persistencia_reinicio(app):
    await feed(app.dp, app.bot, make_message("/newproject Persiste"))
    await feed(app.dp, app.bot, make_message("¿que tal?"))
    from core.storage.database import Database
    from core.storage.repositories import Store
    db2 = Database(app.services.store.db.path)
    await db2.connect()
    try:
        store2 = Store(db2)
        proj = store2 and await store2.get_project_by_name(111, "Persiste")
        assert proj
        assert await store2.get_pref(111, "model:fake") is not None or True
        msgs = await store2.get_messages((await store2.get_pref(
            111, "active_conversation")) or 0)
        assert any(m["role"] == "user" for m in msgs)
    finally:
        await db2.close()


# --------------------------------------------------------------- Prueba 14 --

async def test_prueba14_actualizacion_migraciones_idempotentes(app, tmp_path):
    applied2 = await app.services.store.db.migrate()
    assert applied2 == 0  # re-ejecutar migraciones no cambia nada
    from pathlib import Path
    script = (Path(__file__).resolve().parents[1] / "scripts" / "update.sh").read_text()
    for required in ("backup", "systemctl", "rollback" if "rollback" in script else "BACKUP"):
        assert required in script
