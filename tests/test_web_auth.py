"""Pruebas de autenticacion web: bootstrap, login, CSRF, sesiones, rate limit."""
from __future__ import annotations

import pytest

from backend import auth as web_auth
from tests.web_utils import FakeWebProvider, build_env, make_web_settings

pytestmark = pytest.mark.asyncio


async def test_bootstrap_crea_usuario_web(tmp_path):
    s = make_web_settings(tmp_path)
    from core.storage.database import Database
    from core.storage.repositories import Store
    db = Database(tmp_path / "data" / "hj.db")
    await db.connect()
    await db.migrate()
    store = Store(db)
    assert await web_auth.count_web_users(store) == 0
    await web_auth.bootstrap_web_user(s, store)
    assert await web_auth.count_web_users(store) == 1
    # idempotente: segunda llamada no crea otro
    await web_auth.bootstrap_web_user(s, store)
    assert await web_auth.count_web_users(store) == 1
    user = await web_auth.get_web_user_by_name(store, "tester")
    assert user["agent_uid"] == 111 and user["is_admin"] == 1
    await db.close()


async def test_password_hash_y_verificacion():
    h = web_auth.hash_password("mi-clave-segura")
    assert h.startswith("scrypt$")
    assert web_auth.verify_password("mi-clave-segura", h)
    assert not web_auth.verify_password("otra-clave", h)
    with pytest.raises(ValueError):
        web_auth.hash_password("corta")


async def test_login_ok_y_me(tmp_path):
    s = make_web_settings(tmp_path)
    async with build_env(s, FakeWebProvider()) as env:
        csrf = await env.login()
        assert csrf
        r = await env.get("/api/auth/me")
        assert r.status_code == 200
        me = r.json()
        assert me["username"] == "tester" and me["agent_uid"] == 111
        assert me["csrf_token"] == csrf


async def test_login_rechaza_mal_password(tmp_path):
    s = make_web_settings(tmp_path)
    async with build_env(s, FakeWebProvider()) as env:
        r = await env.client.post("/api/auth/login",
                                  json={"username": "tester", "password": "incorrecta"})
        assert r.status_code == 401
        # sin sesion, /me es 401
        r = await env.get("/api/auth/me")
        assert r.status_code == 401


async def test_sin_password_no_hay_usuario(tmp_path):
    """Sin HJ_WEB_PASSWORD y tabla vacia: no se crea usuario -> login 401."""
    s = make_web_settings(tmp_path, HJ_WEB_PASSWORD="")
    async with build_env(s, FakeWebProvider()) as env:
        r = await env.client.post("/api/auth/login",
                                  json={"username": "tester", "password": "secreto-web-123"})
        assert r.status_code == 401


async def test_csrf_obligatorio_en_mutaciones(tmp_path):
    s = make_web_settings(tmp_path)
    async with build_env(s, FakeWebProvider()) as env:
        await env.login()
        # POST sin cabecera CSRF -> 403
        r = await env.client.post("/api/conversations", json={"title": "x"})
        assert r.status_code == 403
        # con CSRF correcto -> 200
        r = await env.post("/api/conversations", {"title": "x"})
        assert r.status_code == 200


async def test_logout_destruye_sesion(tmp_path):
    s = make_web_settings(tmp_path)
    async with build_env(s, FakeWebProvider()) as env:
        await env.login()
        r = await env.post("/api/auth/logout")
        assert r.status_code == 200
        r = await env.get("/api/auth/me")
        assert r.status_code == 401


async def test_login_rate_limit(tmp_path):
    s = make_web_settings(tmp_path)
    async with build_env(s, FakeWebProvider()) as env:
        for i in range(5):
            r = await env.client.post("/api/auth/login",
                                      json={"username": "tester", "password": "mala"})
            assert r.status_code == 401
        r = await env.client.post("/api/auth/login",
                                  json={"username": "tester", "password": "secreto-web-123"})
        assert r.status_code == 429
