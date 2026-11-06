"""6) Consulta de saldo real (endpoint oficial DeepSeek /user/balance)."""
import httpx
import pytest

from core.billing.balance import fetch_balance_summary
from core.providers.deepseek import DeepSeekProvider
from core.providers.openai_compat import OpenAICompatProvider


async def _key():
    return "sk-real"


def _deepseek(payload, status=200):
    return DeepSeekProvider("https://api.deepseek.com", _key, transport=httpx.MockTransport(
        lambda r: httpx.Response(status, json=payload)))


async def test_balance_campos_oficiales():
    p = _deepseek({
        "is_available": True,
        "balance_infos": [{"currency": "CNY", "total_balance": "110.27",
                           "granted_balance": "10.27", "topped_up_balance": "100.00"}]})
    info = await fetch_balance_summary(p)
    assert info["available"] and info["is_available"]
    assert info["currency"] == "CNY"
    assert info["total"] == 110.27
    assert info["granted"] == 10.27 and info["topped_up"] == 100.0


async def test_balance_no_disponible_cuenta():
    p = _deepseek({"is_available": False, "balance_infos": []})
    info = await fetch_balance_summary(p)
    assert info["available"] and not info["is_available"]


async def test_proveedor_sin_endpoint_declara_no_disponible():
    p = OpenAICompatProvider("https://api.openai.com/v1", _key)
    info = await fetch_balance_summary(p)
    assert not info["available"]
    assert "no expone" in info["reason"]


async def test_error_auth_en_balance():
    p = _deepseek({"error": "x"}, status=401)
    info = await fetch_balance_summary(p)
    assert not info["available"]
