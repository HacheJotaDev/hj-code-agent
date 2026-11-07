"""Catalogo de modelos con cache TTL y metadatos editables (ventana de contexto)."""
from __future__ import annotations

import time
from dataclasses import dataclass

from ..providers.base import ModelInfo
from ..providers.errors import ProviderError


@dataclass
class CatalogEntry:
    models: list[ModelInfo]
    fetched_at: float


class ModelCatalog:
    TTL_S = 300

    def __init__(self, store) -> None:
        self.store = store
        self._cache: dict[str, CatalogEntry] = {}

    async def refresh(self, provider: LLMProvider_like = None, user_id: int = 0) -> list[ModelInfo]:
        """Consulta GET /models real del proveedor y cachea el resultado."""
        if provider is None:
            raise ProviderError("Se necesita un proveedor", kind="bad_request")
        models = await provider.list_models()
        self._cache[provider.name] = CatalogEntry(models=models, fetched_at=time.time())
        return models

    async def list(self, provider, force: bool = False) -> list[ModelInfo]:
        entry = self._cache.get(provider.name)
        if force or not entry or time.time() - entry.fetched_at > self.TTL_S:
            return await self.refresh(provider)
        return entry.models

    async def ensure_model(self, provider, model: str, allow_configured: bool = True) -> ModelInfo | None:
        """Devuelve el modelo si existe en el catalogo vivo. No inventa modelos:
        si el proveedor no lo lista, se indica claramente."""
        models = await self.list(provider)
        for m in models:
            if m.id == model:
                return m
        if allow_configured:
            meta = await self.store.get_model_meta(provider.name, model)
            if meta:
                return ModelInfo(id=model, context_window=meta["context_window"],
                                 max_output=meta["max_output"], meta={"source": "config"})
        return None

    async def context_window(self, provider, model: str) -> int | None:
        m = await self.ensure_model(provider, model)
        if m and m.context_window:
            return m.context_window
        meta = await self.store.get_model_meta(provider.name, model)
        return meta["context_window"] if meta else None


LLMProvider_like = object
