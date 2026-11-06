"""Helpers compartidos por los handlers."""
from __future__ import annotations

from aiogram.types import Message

from ..utils import esc, fmt_cost


def fmt_u(user) -> str:
    name = user.first_name or user.username or str(user.id)
    return f"{name} (<code>{user.id}</code>)"


async def get_project(ctx, message: Message, *, required: bool = True):
    proj = await ctx.projects.active(message.from_user.id)
    if not proj and required:
        await message.answer(
            "📁 No hay proyecto seleccionado.\n"
            "Crea uno con <code>/newproject</code> o elige con <code>/projects</code>.")
    return proj


async def provider_model(ctx, user_id: int) -> tuple[str, str]:
    pname = await ctx.providers.active_name(user_id)
    model = await ctx.store.get_pref(user_id, f"model:{pname}") or "(sin modelo)"
    return pname, model


async def balance_line(ctx, user_id: int) -> str:
    """Saldo real si el proveedor lo expone; nunca inventa cifras."""
    try:
        provider = await ctx.providers.get(user_id)
        from core.billing.balance import fetch_balance_summary
        info = await fetch_balance_summary(provider)
        if info.get("available"):
            if info.get("is_available"):
                return f"Saldo API: {info['total']:.2f} {info.get('currency', '')}"
            return "Saldo API: cuenta no disponible (is_available=false)"
        return f"Saldo API: no disponible ({info.get('reason', '')[:60]})"
    except Exception as e:
        return f"Saldo API: no disponible ({esc(e) if hasattr(e, '__str__') else e})"


def provider_error_message(e: Exception) -> str:
    kind = getattr(e, "kind", "other")
    if kind == "no_api_key":
        return "🔑 Este proveedor no tiene API key. Configúrala con /setapi"
    if kind == "auth":
        return "🔐 Error de autenticación con el proveedor. Revisa la clave con /setapi y /testapi"
    if kind == "insufficient_balance":
        return "💳 Saldo insuficiente en el proveedor. Recarga tu cuenta y usa /balance refresh"
    if kind == "rate_limit":
        return "⏳ Límite de peticiones alcanzado. Espera unos segundos e inténtalo de nuevo"
    if kind == "overloaded":
        return "🌩 El proveedor está sobrecargado. Inténtalo de nuevo en unos minutos"
    if kind == "bad_request":
        return "⚠️ Parámetros o modelo inválido para este proveedor. Revisa /params y /models"
    if kind == "not_found":
        return "🔎 Modelo o recurso no encontrado en el proveedor. Consulta /models"
    if kind == "network":
        return "📡 Sin conexión con el proveedor. Revisa la red del VPS"
    return f"❌ Error: {esc(e)}"


def user_error_message(e: Exception) -> str:
    return f"❌ Error: {esc(e)}"
