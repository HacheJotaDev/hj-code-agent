"""Registro durable de consumo: tokens y costes por peticion."""
from __future__ import annotations

from ..providers.base import Usage
from ..storage.repositories import Store
from .pricing import Pricing


class UsageStore:
    def __init__(self, store: Store, pricing: Pricing) -> None:
        self.store = store
        self.pricing = pricing

    async def record(self, user_id: int, provider: str, model: str, usage: Usage | None,
                     conversation_id: int | None = None, project_id: int | None = None) -> float | None:
        """Guarda el consumo real devuelto por la API. Devuelve el coste (o None)."""
        if usage is None:
            return None
        cost, currency = await self.pricing.estimate(provider, model, usage)
        await self.store.record_usage(
            user_id, conversation_id, project_id, provider, model,
            usage.prompt_tokens, usage.completion_tokens, usage.total_tokens,
            cost, currency)
        return cost

    async def totals(self, user_id: int, since: str | None = None,
                     conversation_id: int | None = None, project_id: int | None = None) -> dict:
        return await self.store.usage_totals(user_id, since, conversation_id, project_id)

    async def by_model(self, user_id: int, since: str | None = None) -> list[dict]:
        return await self.store.usage_by_model(user_id, since)

    async def by_day(self, user_id: int, days: int = 14) -> list[dict]:
        return await self.store.usage_by_day(user_id, days)

    async def day_cost(self, user_id: int) -> float:
        from .period import today_start
        t = await self.totals(user_id, since=today_start())
        return t["cost"] or 0.0
