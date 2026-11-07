"""Consulta de saldo REAL del proveedor (endpoint oficial /user/balance de DeepSeek).

Nunca se inventa un saldo: si el proveedor no expone consulta, se devuelve
None y la interfaz lo declara como no disponible.
"""
from __future__ import annotations

from ..providers.errors import ProviderError


async def fetch_balance_summary(provider) -> dict:
    """Devuelve un resumen listo para mostrar, o {'available': False, 'reason': ...}."""
    if not provider.capabilities.balance:
        return {"available": False,
                "reason": f"El proveedor '{provider.name}' no expone consulta de saldo por API"}
    try:
        info = await provider.balance()
    except ProviderError as e:
        return {"available": False, "reason": e.user_message}
    if info is None:
        return {"available": False,
                "reason": f"El proveedor '{provider.name}' no expone consulta de saldo por API"}
    return {
        "available": True,
        "is_available": info.is_available,
        "currency": info.currency,
        "total": info.total_balance,
        "granted": info.granted_balance,
        "topped_up": info.topped_up_balance,
        "raw": info.raw,
    }
