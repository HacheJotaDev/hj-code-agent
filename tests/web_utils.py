"""Utilidades compartidas de las pruebas del backend web V4."""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from core.config import Settings
from core.providers.base import ChatResult, LLMProvider, ModelInfo, Usage

from backend.app import create_app


def make_web_settings(tmp_path: Path, **extra) -> Settings:
    base = dict(
        HJ_TELEGRAM_BOT_TOKEN="",
        HJ_ADMIN_USER_IDS="111",
        HJ_DATA_DIR=tmp_path / "data",
        HJ_WORKSPACES_DIR=tmp_path / "workspaces",
        HJ_BACKUPS_DIR=tmp_path / "backups",
        HJ_SANDBOX_BACKEND="local",
        HJ_ALLOW_LOCAL_SANDBOX=1,
        HJ_SANDBOX_TIMEOUT_S=15,
        HJ_MASTER_KEY="clave-de-prueba-web",
        HJ_WEB_PASSWORD="secreto-web-123",
        HJ_WEB_USERNAME="tester",
        HJ_WEB_AGENT_UID="111",
        HJ_WEB_SECURE_COOKIES="0",
    )
    base.update(extra)
    s = Settings(**base)
    s.ensure_dirs()
    return s


class FakeWebProvider(LLMProvider):
    """Proveedor falso con guion, para exercer el motor completo sin red."""
    name = "fake"
    kind = "fake"

    def __init__(self, script=None):
        super().__init__("http://fake", lambda: "key")
        self.script = list(script or [])
        self.calls = []

    async def list_models(self):
        return [ModelInfo(id="fake-mini", context_window=8000)]

    async def chat(self, messages, *, model, tools=None, temperature=None,
                   top_p=None, max_tokens=None, stream=False, on_delta=None,
                   reasoning_effort=None):
        self.calls.append({"n_tools": len(tools or [])})
        item = self.script.pop(0) if self.script else {"content": "fin"}
        if isinstance(item, Exception):
            raise item
        if item.get("tool_calls"):
            return ChatResult(content=item.get("content"),
                              tool_calls=[SimpleNamespace(**tc) for tc in item["tool_calls"]],
                              finish_reason="tool_calls",
                              usage=Usage(10, 5, 15), model=model)
        return ChatResult(content=item.get("content", "ok"), finish_reason="stop",
                          usage=Usage(10, 5, 15), model=model)


class WebTestEnv:
    """App + cliente HTTP + motor con proveedor falso inyectado."""

    def __init__(self, client: AsyncClient, app, settings):
        self.client = client
        self.app = app
        self.settings = settings
        self.csrf: str | None = None

    async def login(self) -> str:
        r = await self.client.post("/api/auth/login",
                                   json={"username": "tester", "password": "secreto-web-123"})
        assert r.status_code == 200, r.text
        self.csrf = r.json()["csrf_token"]
        return self.csrf

    def headers(self) -> dict:
        return {"x-csrf-token": self.csrf or ""}

    async def get(self, url: str, **kw):
        return await self.client.get(url, **kw)

    async def post(self, url: str, json_body=None, **kw):
        return await self.client.post(url, json=json_body, headers=self.headers(), **kw)

    async def put(self, url: str, json_body=None, **kw):
        return await self.client.put(url, json=json_body, headers=self.headers(), **kw)

    async def delete(self, url: str, **kw):
        return await self.client.delete(url, headers=self.headers(), **kw)


@asynccontextmanager
async def build_env(settings: Settings, provider: FakeWebProvider):
    """App FastAPI con motor real + proveedor falso; yield WebTestEnv.

    La limpieza se hace SIEMPRE en orden fijo (cliente -> lifespan), sin
    inyectar excepciones en el generador cuando el test falla.
    """
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async def fake_get(user_id, provider_name=None):
            return provider

        app.state.ctx.providers.get = fake_get
        transport = ASGITransport(app=app)
        client = AsyncClient(transport=transport, base_url="http://test")
        env = WebTestEnv(client, app, settings)
        try:
            yield env
        finally:
            try:
                await client.aclose()
            except Exception:
                pass


@pytest.fixture
def fake_web_provider_cls():
    return FakeWebProvider


def tool_call(cid: str, name: str, **args) -> dict:
    return {"id": cid, "name": name, "arguments": json.dumps(args, ensure_ascii=False)}


async def wait_task_status(env: WebTestEnv, tid: int, statuses: set[str],
                           timeout_s: float = 30.0) -> dict:
    """Espera real de polling hasta que la tarea alcanza uno de los estados."""
    deadline = time.monotonic() + timeout_s
    task = {}
    while time.monotonic() < deadline:
        r = await env.get(f"/api/tasks/{tid}")
        task = r.json()
        if task["status"] in statuses:
            return task
        await asyncio.sleep(0.1)
    raise TimeoutError(f"Tarea {tid} no alcanzo {statuses}: {task}")
