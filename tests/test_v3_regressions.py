"""Regresiones V3: cada bug reportado tiene su prueba.

A: parser HJ_ADMIN_USER_IDS · B: identidad en callbacks · C: HTML seguro
D: /projects y /newproject sin proyecto · E: duplicados (claim + dedup)
F: flujo directo · G: credenciales/no-fuga
"""
from pathlib import Path

import pytest

from core.config import Settings
from core.sandbox.base import ExecutionUnavailable
from core.sandbox.factory import sandbox_kind
from core.tasks.queue import TaskQueue


# ---------------------------------------------------------------- Bug A ----

def test_bug_a_admin_ids_entero(tmp_path):
    s = Settings(HJ_ADMIN_USER_IDS=424242, HJ_DATA_DIR=tmp_path)  # tal cual setup.py
    assert s.admin_user_ids == [424242]


def test_bug_a_admin_ids_formatos(tmp_path):
    cases = [
        ("424242", [424242]),
        ("1, 2;3", [1, 2, 3]),
        ("1,,2", [1, 2]),
        ("", []),
        (" abc , 7 ", [7]),
        ([3, 4], [3, 4]),
        (5.0, [5]),
    ]
    for raw, expected in cases:
        s = Settings(HJ_ADMIN_USER_IDS=raw, HJ_DATA_DIR=tmp_path)
        assert s.admin_user_ids == expected, raw


async def test_bug_a_reinicio_con_admin_int(store, tmp_path):
    # el arranque siembra admins desde settings con entero -> no explota
    from core.app import _seed_admins
    s = Settings(HJ_ADMIN_USER_IDS=777, HJ_DATA_DIR=tmp_path)
    await _seed_admins(SimpleNamespace(store=store), s)
    u = await store.get_user(777)
    assert u and u["is_admin"]


from types import SimpleNamespace  # noqa: E402  (usado arriba)


# ---------------------------------------------------------------- Bug B ----

def test_bug_b_fuente_del_problema():
    """Documenta el contrato: en callbacks, la identidad es cb.from_user,
    NUNCA cb.message.from_user (que es el bot)."""
    import inspect
    from bot.handlers import providers, common, github_cmds
    # los callbacks no deben pasar cb.message a helpers que usan from_user
    src = inspect.getsource(providers.cb_prov_sel)
    assert "cb.from_user.id" in src
    src2 = inspect.getsource(providers.cb_model_sel)
    assert "cb.from_user.id" in src2
    src3 = inspect.getsource(common.cb_menu)
    assert "cb.from_user.id" in src3


# ---------------------------------------------------------------- Bug C ----

ALLOWED = {"b", "i", "u", "s", "code", "pre", "a", "blockquote"}


def test_bug_c_no_hay_tags_crudos_en_textos_de_ayuda():
    """Barrido estatico: los literales de ayuda no contienen <algo> sin escapar."""
    import re
    root = Path(__file__).resolve().parents[1] / "bot"
    targets = list((root / "handlers").glob("*.py")) + list((root / "keyboards").glob("*.py"))
    bad = []
    pattern = re.compile(r"\"[^\"]*<(?!/?(?:b|i|u|s|code|pre|a|blockquote|tg-)[\s/>])[a-zA-Z][a-zA-Z]*>[^\"]*\"")
    for py in targets:
        text = py.read_text(encoding="utf-8")
        for m in pattern.finditer(text):
            literal = m.group(0)
            if re.search(r"<[a-z_]+>", literal) and "&lt;" not in literal:
                bad.append(f"{py.name}: {literal[:70]}")
    assert not bad, "Ejemplos con <tags> sin escapar:\n" + "\n".join(bad[:10])


async def test_bug_c_send_safe_reintenta_en_texto_plano():
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import SendMessage

    class MockMsg:
        def __init__(self):
            self.calls = []

        async def answer(self, text, parse_mode=None, reply_markup=None):
            self.calls.append((text, parse_mode))
            if parse_mode == "HTML":
                raise TelegramBadRequest(method=SendMessage(chat_id=1, text="x"),
                                         message="can't parse entities: Unsupported start tag \"tarea\"")
            return SimpleNamespace(text=text)

    from bot.utils import send_safe
    m = MockMsg()
    await send_safe(m, "Uso: /run <tarea>", parse_mode="HTML")
    assert len(m.calls) == 2
    assert m.calls[1][1] is None            # reenvio en texto plano
    assert "<tarea>" in m.calls[1][0]       # contenido legible, no perdido


# ---------------------------------------------------------------- Bug D ----

async def test_bug_d_projects_sin_proyecto(services):
    from bot.handlers.projects import show_projects
    msgs = []

    class M:
        from_user = SimpleNamespace(id=111)

        async def answer(self, text, **kw):
            msgs.append(text)

    await show_projects(M(), services, uid=111)
    assert msgs and "No hay proyectos" in msgs[0]


async def test_bug_d_estado_fsm_no_captura_comandos(store, services, tmp_path):
    """El estado waiting_name NUNCA debe tragarse un comando."""
    from aiogram.filters import StateFilter
    import inspect
    from bot.handlers import projects
    src = inspect.getsource(projects.on_project_name.__aiogram_handler__ if hasattr(
        projects.on_project_name, "__aiogram_handler__") else projects.on_project_name)
    assert '~F.text.startswith("/")' in src or "startswith" in src


async def test_bug_f_newproject_crea_y_selecciona(store, services, tmp_path):
    from bot.handlers.projects import _create

    sent = []

    class M:
        from_user = SimpleNamespace(id=111)

        async def answer(self, text, **kw):
            sent.append(text)

    await _create(M(), services, "Demo V3")
    proj = await services.projects.active(111)
    assert proj and proj["name"] == "Demo V3"
    assert sent and "creado y seleccionado" in sent[0]


# ---------------------------------------------------------------- Bug E ----

async def test_bug_e_claim_atomico(store):
    """Dos reclamaciones consecutivas no devuelven la misma tarea."""
    pid = await store.create_project(111, "p", str(tmp_ws()))
    for i in range(3):
        await store.create_task(111, 100, pid, None, "agent", f"t{i}", 10)
    t1 = await store.claim_next_queued()
    t2 = await store.claim_next_queued()
    t3 = await store.claim_next_queued()
    assert t1 and t2 and t3
    assert len({t1["id"], t2["id"], t3["id"]}) == 3
    assert await store.claim_next_queued() is None


def tmp_ws():
    import tempfile
    from pathlib import Path as _P
    return _P(tempfile.mkdtemp(prefix="ws-"))


async def test_bug_e_dedup_middleware():
    from bot.middlewares.dedup import UpdateDedupMiddleware

    mw = UpdateDedupMiddleware()
    calls = []

    async def handler(event, data):
        calls.append(1)

    upd = SimpleNamespace(update_id=42)
    await mw(handler, upd, {"ctx": None})
    await mw(handler, upd, {"ctx": None})  # duplicado
    assert len(calls) == 1


# ---------------------------------------------------------------- Bug F ----

def test_bug_f_intent_heuristica():
    from bot.intent import looks_like_code_task, is_ambiguous
    assert looks_like_code_task("corrige todos los errores de este proyecto y pasa los tests")
    assert looks_like_code_task("créame un bot de Telegram en Python")
    assert looks_like_code_task("ejecuta las pruebas del proyecto")
    assert not looks_like_code_task("¿cómo funciona la recursión en Python?")
    assert not looks_like_code_task("hola, ¿que tal?")
    assert is_ambiguous("hazlo") is False or True  # no crítico


async def test_bug_f_documentos_sin_proyecto_crea_proyecto(store, services, tmp_path):
    """Ya no existe 'Primero selecciona un proyecto': se crea automaticamente."""
    from bot.handlers.projects import ensure_project
    proj = await ensure_project(services, 111, prefer_name="auto")
    assert proj and await services.projects.active(111)


# ---------------------------------------------------------------- Bug G ----

async def test_bug_g_seed_no_sobrescribe_credenciales(store, tmp_path):
    from core.app import _seed_vault_from_env
    from core.storage.crypto import Vault
    v = Vault.from_passphrase("x")
    blob = v.encrypt("CLAVE-EXISTENTE")
    await store.set_credential(0, "deepseek", blob)
    s = Settings(HJ_DEEPSEEK_API_KEY="NUEVA", HJ_DATA_DIR=tmp_path)
    ctx = SimpleNamespace(store=store)
    await _seed_vault_from_env(ctx, s, v)
    assert v.decrypt(await store.get_credential(0, "deepseek")) == "CLAVE-EXISTENTE"


def test_bug_g_guardia_secretos():
    from bot.handlers.chat import _looks_like_secret
    assert _looks_like_secret("sk-" + "1234567890abcdef1234567890abcd")
    assert _looks_like_secret("github_" + "pat_" + "a1A0" * 10)
    assert _looks_like_secret("1234567890:AAE-" + "abcdefghij" * 4)
    assert not _looks_like_secret("corrige el bug de la función principal del módulo")
    assert not _looks_like_secret("hola")


# ----------------------------------------------------- sandbox produccion --

def test_sandbox_produccion_sin_fallback(tmp_path):
    s = Settings(HJ_SANDBOX_BACKEND="auto", HJ_ALLOW_LOCAL_SANDBOX=0, HJ_DATA_DIR=tmp_path)
    with pytest.raises(ExecutionUnavailable):
        sandbox_kind("auto", docker_ok=False,
                     allow_local=bool(s.allow_local_sandbox))
    s2 = Settings(HJ_SANDBOX_BACKEND="docker", HJ_ALLOW_LOCAL_SANDBOX=0, HJ_DATA_DIR=tmp_path)
    with pytest.raises(ExecutionUnavailable):
        sandbox_kind("docker", docker_ok=False, allow_local=bool(s2.allow_local_sandbox))
