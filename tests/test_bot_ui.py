"""Capa del bot: teclados y middleware de autorizacion (sin red)."""
import pytest
from aiogram.types import User as TgUser


def test_teclados_se_construyen():
    from bot.keyboards.menus import (approval_kb, agents_kb, github_kb, main_menu_kb,
                                     models_kb, providers_kb, settings_kb, system_prompt_kb)
    assert main_menu_kb().inline_keyboard
    assert providers_kb([{"name": "deepseek", "kind": "deepseek", "base_url": "x"}],
                        "deepseek", ["deepseek"]).inline_keyboard
    assert models_kb(["a", "b"], 0).inline_keyboard
    assert github_kb(False).inline_keyboard
    assert settings_kb().inline_keyboard
    assert system_prompt_kb("native", False).inline_keyboard
    assert agents_kb(False).inline_keyboard
    kb = approval_kb("req123")
    assert any("auth:yes:req123" in (btn.callback_data or "") for row in kb.inline_keyboard
               for btn in row)
    # callback_data <= 64 bytes
    for row in models_kb(["x" * 60], 0).inline_keyboard:
        for btn in row:
            if btn.callback_data:
                assert len(btn.callback_data.encode()) <= 64


class _Bot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))


class _Ctx:
    def __init__(self, store):
        from core.authentication.auth_service import AuthService
        self.store = store
        self.auth = AuthService(store)
        self.bot = _Bot()


class _Handler:
    def __init__(self):
        self.called = False

    async def __call__(self, event, data):
        self.called = True


def _user(uid=999):
    return TgUser(id=uid, is_bot=False, first_name="T", username="t")


async def test_middleware_bloquea_no_autorizados(store):
    from bot.middlewares.auth import AuthMiddleware
    ctx = _Ctx(store)
    mw = AuthMiddleware()
    handler = _Handler()
    data = {"ctx": ctx, "event_from_user": _user(424242)}
    result = await mw(handler, object(), data)
    assert result is None and not handler.called
    assert ctx.bot.sent and "Acceso restringido" in ctx.bot.sent[0][1]


async def test_middleware_permite_autorizados(store):
    from bot.middlewares.auth import AuthMiddleware
    ctx = _Ctx(store)
    await ctx.auth.authorize(555)
    mw = AuthMiddleware()
    handler = _Handler()
    data = {"ctx": ctx, "event_from_user": _user(555)}
    await mw(handler, object(), data)
    assert handler.called
    assert data["allowed"] is True and data["is_admin"] is False
