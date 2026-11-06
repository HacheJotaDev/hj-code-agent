"""Tarifas y estimacion de costes.

Los precios se configuran por proveedor/modelo (por 1M de tokens). Nunca se
inventa un coste: si no hay tarifa configurada el coste se guarda como None y
la interfaz lo indica. Para DeepSeek, los campos de cache del usage se usan
cuando hay tarifa de cache configurada.
"""
from __future__ import annotations

from ..providers.base import Usage
from ..storage.repositories import Store


class Pricing:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def set_rate(self, provider: str, model: str, input_per_mtok: float,
                       output_per_mtok: float, currency: str = "USD",
                       cache_hit_per_mtok: float | None = None) -> None:
        await self.store.set_rate(provider, model, input_per_mtok, output_per_mtok,
                                  currency, cache_hit_per_mtok)

    async def estimate(self, provider: str, model: str, usage: Usage) -> tuple[float | None, str]:
        """Devuelve (coste, moneda). (None, '') si no hay tarifa configurada."""
        rate = await self.store.get_rate(provider, model)
        if not rate or rate["input_per_mtok"] is None or rate["output_per_mtok"] is None:
            return None, ""
        in_price = float(rate["input_per_mtok"])
        out_price = float(rate["output_per_mtok"])
        cache_price = rate["cache_hit_per_mtok"]
        pt = usage.prompt_tokens
        if cache_price is not None:
            hit = usage.details.get("prompt_cache_hit_tokens") or 0
            miss = usage.details.get("prompt_cache_miss_tokens", pt - hit)
            try:
                miss = max(int(miss), 0)
            except (TypeError, ValueError):
                miss = pt
            cost = (miss * in_price + hit * float(cache_price) + usage.completion_tokens * out_price)
        else:
            cost = (pt * in_price + usage.completion_tokens * out_price)
        return cost / 1_000_000.0, rate["currency"] or "USD"
