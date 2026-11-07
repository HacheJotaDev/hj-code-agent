"""1) Autorizacion de Telegram: acceso privado por defecto."""
from types import SimpleNamespace

import pytest

from core.authentication.auth_service import AuthService
from core.permissions.authorizer import Authorizer, PermissionDenied


async def test_sin_registro_no_hay_acceso(store):
    auth = AuthService(store)
    assert not await auth.is_allowed(9999)


async def test_admin_sembrado_tiene_acceso(store, services):
    auth = AuthService(store)
    assert await auth.is_allowed(111)      # admin de settings
    assert await auth.is_admin(111)


async def test_register_y_authorize(store):
    auth = AuthService(store)
    u = await auth.register(222, "pepe", "Pepe")
    assert not await auth.is_allowed(222)
    await auth.authorize(222)
    assert await auth.is_allowed(222)
    assert not await auth.is_admin(222)
    await auth.authorize(333, admin=True)
    assert await auth.is_admin(333)


async def test_revoke_y_proteccion_admin(services, store):
    auth = AuthService(store)
    await store.upsert_user(111, is_admin=True, allowed=True)  # admin sembrado
    await auth.authorize(444)
    await auth.revoke(444)
    assert not await auth.is_allowed(444)
    with pytest.raises(PermissionError):
        await auth.revoke(111)  # admin no revocable por API


async def test_authorizer_acciones_admin(services, store):
    az = Authorizer(store)
    auth = AuthService(store)
    await az.check(111, "authorize")      # admin ok
    await auth.authorize(555)
    with pytest.raises(PermissionDenied):
        await az.check(555, "users")
    with pytest.raises(PermissionDenied):
        await az.require_confirmation(False, "project_delete")
    az.require_confirmation(True, "project_delete")  # no lanza


# ---------------------------------------------------------------------------
# Middleware de acceso: solo IDs autorizados obtienen respuestas del bot
# ---------------------------------------------------------------------------

async def _run_mw(services, user_id):
    from bot.middlewares.auth import AuthMiddleware

    services.auth = AuthService(services.store)  # como hace bot/main.py al arrancar
    mw = AuthMiddleware()
    called = []

    async def handler(event, data):
        called.append(True)
        return "ok"

    user = SimpleNamespace(id=user_id, username="u", first_name="U")
    data = {"event_from_user": user, "ctx": services}
    res = await mw(handler, SimpleNamespace(), data)
    return called, res, data


async def test_middleware_admin_pasa(services):
    called, res, data = await _run_mw(services, 111)
    assert called and res == "ok" and data["allowed"] is True


async def test_middleware_no_autorizado_no_responde(services):
    called, _, _ = await _run_mw(services, 424242)
    assert not called                      # el handler NUNCA se ejecuta
    assert len(services.bot.sent) == 1     # modo por defecto: un unico aviso


async def test_middleware_silencio_total(services):
    services.settings.silent_reject = True
    called, _, _ = await _run_mw(services, 424242)
    assert not called
    assert services.bot.sent == []         # ni un solo mensaje al intruso
