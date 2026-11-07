"""Fixtures comunes de la suite."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.config import Settings
from core.storage.crypto import Vault
from core.storage.database import Database
from core.storage.repositories import Store


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def settings(tmp_path) -> Settings:
    s = Settings(
        HJ_TELEGRAM_BOT_TOKEN="test-token",
        HJ_ADMIN_USER_IDS="111",
        HJ_DATA_DIR=tmp_path / "data",
        HJ_WORKSPACES_DIR=tmp_path / "workspaces",
        HJ_BACKUPS_DIR=tmp_path / "backups",
        HJ_SANDBOX_BACKEND="local",
        HJ_ALLOW_LOCAL_SANDBOX=1,   # los tests ejecutan con sandbox local explicito
        HJ_SANDBOX_MEMORY_MB=256,
        HJ_SANDBOX_TIMEOUT_S=10,
    )
    s.ensure_dirs()
    return s


@pytest.fixture
async def store(tmp_path) -> Store:
    db = Database(tmp_path / "test.db")
    await db.connect()
    await db.migrate()
    yield Store(db)
    await db.close()


@pytest.fixture
def vault() -> Vault:
    return Vault.from_passphrase("clave-de-prueba")


@pytest.fixture
async def services(store, vault, tmp_path, settings) -> SimpleNamespace:
    """Contexto minimo de servicios con adaptadores falsos."""
    from core.agent.approvals import ApprovalManager
    from core.agent.engine import AgentEngine
    from core.billing.pricing import Pricing
    from core.billing.usage_store import UsageStore
    from core.models.catalog import ModelCatalog
    from core.projects.manager import ProjectManager
    from core.prompts.service import PromptService
    from core.providers.registry import ProviderRegistry
    from core.tasks.queue import TaskQueue

    svc = SimpleNamespace()
    svc.settings = settings
    svc.store = store
    await store.upsert_user(111, is_admin=True, allowed=True)  # admin sembrado
    svc.vault = vault
    svc.pricing = Pricing(store)
    svc.usage = UsageStore(store, svc.pricing)
    svc.prompts = PromptService(store)
    svc.providers = ProviderRegistry(store)
    svc.providers.set_vault(vault)
    await svc.providers.seed("https://api.deepseek.com")
    svc.catalog = ModelCatalog(store)
    svc.projects = ProjectManager(store, tmp_path / "workspaces", tmp_path / "backups")
    svc.approvals = ApprovalManager(store)
    svc.engine = AgentEngine(svc)
    svc.github = SimpleNamespace(create_pull_request=lambda *a, **k: _async({"html_url": "ok"}))
    svc.broker = FakeBroker(store)

    from core.sandbox.factory import create_sandbox_backend

    async def make_sandbox(workspace, project=None):
        return await create_sandbox_backend(
            workspace, settings,
            project_id=project["id"] if project else None,
            project_network=(project.get("network_enabled") if project else None))

    svc.make_sandbox = make_sandbox
    svc.bot = FakeBot()
    svc.queue = None
    return svc


class FakeBroker:
    def __init__(self, store):
        self.store = store
        self.pushes = []

    async def current_branch(self, project) -> str:
        return "main"

    async def push(self, project, branch=None, *, authorized=False):
        if not authorized:
            from core.github.broker import PushNotAuthorized
            raise PushNotAuthorized("Push no autorizado")
        self.pushes.append((project["id"], branch))
        return "push ok"


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))


async def _async(v):
    return v


@pytest.fixture
def fake_provider_cls():
    """Fabrica de proveedores falsos con guion de respuestas."""
    from core.providers.base import ChatResult, LLMProvider, ModelInfo, Usage

    class FakeProvider(LLMProvider):
        name = "fake"
        kind = "fake"

        def __init__(self, script=None, **kw):
            super().__init__("http://fake", lambda: "key")
            self.script = list(script or [])
            self.calls = []

        async def list_models(self):
            return [ModelInfo(id="fake-mini", context_window=8000)]

        async def chat(self, messages, *, model, tools=None, temperature=None,
                       top_p=None, max_tokens=None, stream=False, on_delta=None,
                       reasoning_effort=None):
            self.calls.append({"messages": json.loads(json.dumps(messages, default=str)),
                               "model": model, "tools": tools})
            item = self.script.pop(0) if self.script else {"content": "fin"}
            if isinstance(item, Exception):
                raise item
            if item.get("tool_calls"):
                return ChatResult(content=item.get("content"),
                                  tool_calls=[SimpleNamespace(**tc) for tc in item["tool_calls"]],
                                  finish_reason="tool_calls",
                                  usage=Usage(item.get("pt", 10), item.get("ct", 5),
                                              item.get("pt", 10) + item.get("ct", 5)),
                                  model=model)
            return ChatResult(content=item.get("content", "ok"),
                              finish_reason="stop",
                              usage=Usage(item.get("pt", 10), item.get("ct", 5),
                                          item.get("pt", 10) + item.get("ct", 5)),
                              model=model)

        async def balance(self):
            return None

    return FakeProvider


@pytest.fixture
def project(store, tmp_path) -> dict:
    async def _make(user_id=111, name="demo"):
        ws = tmp_path / "workspaces" / str(user_id) / name
        ws.mkdir(parents=True, exist_ok=True)
        pid = await store.create_project(user_id, name, str(ws))
        return await store.get_project(pid)
    return _make
