"""Registro de proveedores: seed inicial, creacion de adaptadores por usuario."""
from __future__ import annotations

from .anthropic_compat import AnthropicProvider
from .base import LLMProvider
from .deepseek import DeepSeekProvider
from .errors import ProviderError
from .openai_compat import OpenAICompatProvider

BUILTIN_PROVIDERS: list[tuple[str, str, str]] = [
    ("deepseek", "deepseek", "https://api.deepseek.com"),
    ("openai", "openai_compat", "https://api.openai.com/v1"),
    ("anthropic", "anthropic", "https://api.anthropic.com"),
    ("glm", "openai_compat", "https://open.bigmodel.cn/api/paas/v4"),
    ("openrouter", "openai_compat", "https://openrouter.ai/api/v1"),
    ("ollama", "openai_compat", "http://127.0.0.1:11434/v1"),
]

_KIND_CLASSES: dict[str, type[LLMProvider]] = {
    "deepseek": DeepSeekProvider,
    "openai_compat": OpenAICompatProvider,
    "anthropic": AnthropicProvider,
}


class ProviderRegistry:
    """Resuelve el adaptador activo por usuario.

    La API key se lee de la boveda cifrada EN CADA llamada (nunca se guarda en
    claro ni se cachea). `vault` se inyecta tras la construccion para evitar
    dependencias circulares.
    """

    def __init__(self, store) -> None:
        self.store = store
        self.vault = None

    async def seed(self, deepseek_base_url: str) -> None:
        for name, kind, url in BUILTIN_PROVIDERS:
            if name == "deepseek":
                url = deepseek_base_url
            await self.store.add_provider(name, kind, url, builtin=True)

    def set_vault(self, vault) -> None:
        self.vault = vault

    async def get(self, user_id: int, provider_name: str | None = None) -> LLMProvider:
        name = provider_name or await self.store.get_pref(user_id, "active_provider")
        if not name:
            rows = await self.store.list_providers()
            name = rows[0]["name"] if rows else "deepseek"
        cfg = await self.store.get_provider(name)
        if not cfg:
            raise ProviderError(f"Proveedor desconocido: {name}", kind="not_found")
        if not cfg["enabled"]:
            raise ProviderError(f"Proveedor desactivado: {name}", kind="bad_request")
        cls = _KIND_CLASSES.get(cfg["kind"])
        if not cls:
            raise ProviderError(f"Tipo de proveedor no soportado: {cfg['kind']}")

        store, vault = self.store, self.vault

        async def key_getter() -> str:
            blob = await store.get_credential(user_id, name)
            if not blob:
                return ""
            if vault is None:
                raise ProviderError("Boveda no configurada (falta la clave maestra)",
                                    kind="other")
            return vault.decrypt(blob)

        return cls(cfg["base_url"], key_getter)

    async def active_name(self, user_id: int) -> str:
        name = await self.store.get_pref(user_id, "active_provider")
        if not name:
            rows = await self.store.list_providers()
            name = rows[0]["name"] if rows else "deepseek"
        return name
