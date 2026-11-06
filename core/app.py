"""Contenedor de servicios: construye e interconecta todos los modulos."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .agent.approvals import ApprovalManager
from .agent.engine import AgentEngine
from .billing.pricing import Pricing
from .billing.usage_store import UsageStore
from .github.broker import GitHubBroker
from .github.client import GitHubClient
from .models.catalog import ModelCatalog
from .prompts.service import PromptService
from .providers.registry import ProviderRegistry
from .sandbox.factory import create_sandbox_backend
from .storage.crypto import Vault
from .storage.database import Database
from .storage.repositories import Store
from .tasks.queue import TaskQueue

log = logging.getLogger(__name__)


@dataclass
class AppContext:
    settings: object
    db: Database
    store: Store
    vault: Vault | None
    providers: ProviderRegistry
    catalog: ModelCatalog
    prompts: PromptService
    pricing: Pricing
    usage: UsageStore
    projects: object
    github: GitHubClient
    broker: GitHubBroker
    approvals: ApprovalManager
    engine: AgentEngine
    queue: TaskQueue | None
    bot: object = None
    started_at: float = field(default_factory=time.time)
    make_sandbox: Callable = field(default=lambda *a, **k: None)

    def uptime_s(self) -> int:
        return int(time.time() - self.started_at)


async def build_context(settings) -> AppContext:
    db = Database(settings.db_file)
    await db.connect()
    await db.migrate()
    store = Store(db)

    vault = None
    try:
        vault = Vault.load(settings.master_key, settings.master_key_file or None)
    except Exception as e:
        log.error("Boveda no disponible: %s (las credenciales no podran leerse)", e)

    providers = ProviderRegistry(store)
    providers.set_vault(vault)
    await providers.seed(settings.deepseek_base_url)

    catalog = ModelCatalog(store)
    prompts = PromptService(store)
    pricing = Pricing(store)
    usage = UsageStore(store, pricing)

    from .projects.manager import ProjectManager
    projects = ProjectManager(store, settings.workspaces_dir, settings.backups_dir)

    async def gh_token() -> str:
        if vault is None:
            return ""
        blob = await store.get_credential(0, "github")
        return vault.decrypt(blob) if blob else ""

    github = GitHubClient(gh_token)
    broker = GitHubBroker(store, gh_token)
    approvals = ApprovalManager(store)
    ctx = AppContext(
        settings=settings, db=db, store=store, vault=vault, providers=providers,
        catalog=catalog, prompts=prompts, pricing=pricing, usage=usage,
        projects=projects, github=github, broker=broker, approvals=approvals,
        engine=None, queue=None,
    )
    ctx.engine = AgentEngine(ctx)
    ctx.queue = TaskQueue(ctx)

    async def make_sandbox(workspace: Path, project: dict | None = None):
        return await create_sandbox_backend(
            workspace, settings,
            project_id=project["id"] if project else None,
            project_network=(project.get("network_enabled") if project else None))
    ctx.make_sandbox = make_sandbox

    await _seed_admins(ctx, settings)
    await _seed_vault_from_env(ctx, settings, vault)
    return ctx


async def _seed_admins(ctx: AppContext, settings) -> None:
    for uid in settings.admin_user_ids:
        await ctx.store.upsert_user(uid, is_admin=True, allowed=True)
        log.info("Admin sembrado: %s", uid)


async def _seed_vault_from_env(ctx: AppContext, settings, vault) -> None:
    if vault is None:
        return
    if settings.deepseek_api_key:
        if not await ctx.store.get_credential(0, "deepseek"):
            await ctx.store.set_credential(0, "deepseek", vault.encrypt(settings.deepseek_api_key))
            log.info("API key de DeepSeek precargada desde entorno (scope sistema)")
    if settings.github_token:
        if not await ctx.store.get_credential(0, "github"):
            await ctx.store.set_credential(0, "github", vault.encrypt(settings.github_token))
            log.info("Token de GitHub precargado desde entorno (scope sistema)")
