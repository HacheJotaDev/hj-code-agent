"""4) y 5) Adaptadores de proveedores y modelos con API mockeada (sin red real)."""
import json

import httpx
import pytest

from core.providers.base import ChatResult
from core.providers.deepseek import DeepSeekProvider
from core.providers.errors import NoApiKey, ProviderError
from core.providers.anthropic_compat import AnthropicProvider


def _mock(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


async def _key():
    return "sk-test"


async def test_deepseek_chat_parse_completo():
    body = {
        "model": "deepseek-chat",
        "choices": [{"finish_reason": "stop",
                     "message": {"role": "assistant", "content": "Hola!",
                                 "tool_calls": None}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19,
                  "prompt_cache_hit_tokens": 4, "prompt_cache_miss_tokens": 8},
    }
    def handler(request):
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["authorization"] == "Bearer sk-test"
        return httpx.Response(200, json=body)
    p = DeepSeekProvider("https://api.deepseek.com", _key, transport=_mock(handler))
    res = await p.chat([{"role": "user", "content": "hi"}], model="deepseek-chat")
    assert isinstance(res, ChatResult)
    assert res.content == "Hola!"
    assert res.usage.prompt_tokens == 12 and res.usage.total_tokens == 19
    assert res.usage.details["prompt_cache_hit_tokens"] == 4


async def test_deepseek_tool_calls_parse():
    body = {"choices": [{"finish_reason": "tool_calls", "message": {
        "role": "assistant", "content": None,
        "tool_calls": [{"id": "call1", "type": "function",
                        "function": {"name": "read_file", "arguments": "{\"path\":\"a.py\"}"}}]}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}}
    p = DeepSeekProvider("https://api.deepseek.com", _key, transport=_mock(
        lambda r: httpx.Response(200, json=body)))
    res = await p.chat([], model="deepseek-chat")
    assert res.tool_calls[0].name == "read_file"
    assert json.loads(res.tool_calls[0].arguments)["path"] == "a.py"


async def test_errores_mapeados():
    def make(status):
        return DeepSeekProvider("https://x", _key, transport=_mock(
            lambda r: httpx.Response(status, text='{"error":{"message":"boom"}}')))
    with pytest.raises(ProviderError) as e:
        await make(401).chat([], model="m")
    assert e.value.kind == "auth"
    with pytest.raises(ProviderError) as e:
        await make(402).chat([], model="m")
    assert e.value.kind == "insufficient_balance"
    with pytest.raises(ProviderError) as e:
        await make(429).chat([], model="m")
    assert e.value.kind == "rate_limit"
    with pytest.raises(ProviderError) as e:
        await make(503).chat([], model="m")
    assert e.value.kind == "overloaded"


async def test_sin_api_key_lanza_noapikey():
    p = DeepSeekProvider("https://x", lambda: _empty())
    with pytest.raises(NoApiKey):
        await p.chat([], model="m")


async def _empty():
    return ""


async def test_models_lista_real():
    def handler(request):
        assert request.url.path.endswith("/models")
        return httpx.Response(200, json={"data": [
            {"id": "deepseek-chat", "owned_by": "deepseek"},
            {"id": "deepseek-reasoner", "owned_by": "deepseek"}]})
    p = DeepSeekProvider("https://api.deepseek.com", _key, transport=_mock(handler))
    models = await p.list_models()
    assert {m.id for m in models} == {"deepseek-chat", "deepseek-reasoner"}


async def test_catalogo_no_inventa_modelos(services, store):
    from core.models.catalog import ModelCatalog
    cat = ModelCatalog(store)

    class P:
        name = "deepseek"
        async def list_models(self):
            return []
    assert await cat.ensure_model(P(), "deepseek-flash", allow_configured=True) is None


async def test_anthropic_mapeo_de_mensajes():
    def handler(request):
        payload = json.loads(request.content)
        # el system SOLO aparece si el usuario configuro uno
        assert "system" not in payload
        assert payload["messages"][0]["role"] == "user"
        return httpx.Response(200, json={"content": [{"type": "text", "text": "hey"}],
                                         "usage": {"input_tokens": 3, "output_tokens": 2},
                                         "model": "claude-x", "stop_reason": "end_turn"})
    p = AnthropicProvider("https://api.anthropic.com", _key, transport=_mock(handler))
    res = await p.chat([{"role": "user", "content": "hola"}], model="claude-x")
    assert res.content == "hey"
    assert res.usage.total_tokens == 5


async def test_anthropic_envia_system_solo_si_existe():
    seen = {}

    def handler(request):
        seen["sys"] = json.loads(request.content).get("system")
        return httpx.Response(200, json={"content": [], "usage": {}})

    p = AnthropicProvider("https://api.anthropic.com", _key, transport=_mock(handler))
    await p.chat([{"role": "system", "content": "prompt del usuario"},
                  {"role": "user", "content": "hi"}], model="m")
    assert seen["sys"] == "prompt del usuario"


async def test_registry_seed_y_select(services, store):
    names = {p["name"] for p in await store.list_providers()}
    assert {"deepseek", "openai", "anthropic", "glm", "openrouter", "ollama"} <= names
    await store.set_pref(111, "active_provider", "deepseek")
    assert await services.providers.active_name(111) == "deepseek"
    await store.add_provider("miproveedor", "openai_compat", "https://api.example.com/v1")
    assert await store.get_provider("miproveedor")
    await store.remove_provider("miproveedor")
    assert await store.get_provider("miproveedor") is None
