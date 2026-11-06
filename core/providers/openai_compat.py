"""Adaptador generico OpenAI-compatible (/chat/completions, /models, streaming SSE).

Cubre DeepSeek, OpenAI, OpenRouter, GLM/Z.ai, Ollama local y cualquier endpoint
compatible con la API OpenAI.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from .base import BalanceInfo, ChatResult, DeltaCallback, LLMProvider, ModelInfo, ToolCall, Usage
from .errors import ProviderError

log = logging.getLogger(__name__)


class OpenAICompatProvider(LLMProvider):
    name = "openai-compat"
    kind = "openai_compat"

    def __init__(self, base_url: str, api_key_getter, timeout: float = 180.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        super().__init__(base_url, api_key_getter, timeout)
        self._transport = transport
        self.capabilities.balance = False

    def _headers(self, key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    async def _client(self) -> httpx.AsyncClient:
        if self._transport is not None:
            return httpx.AsyncClient(timeout=self.timeout, transport=self._transport)
        return httpx.AsyncClient(timeout=self.timeout)

    async def list_models(self) -> list[ModelInfo]:
        key = await self._require_key()
        try:
            async with await self._client() as c:
                r = await c.get(f"{self.base_url}/models", headers=self._headers(key))
        except httpx.HTTPError as e:
            raise ProviderError(f"Sin conexion: {e}", kind="network") from e
        if r.status_code >= 400:
            raise self.map_http_error(r.status_code, r.text)
        data = r.json().get("data", [])
        return [ModelInfo(id=m.get("id", ""), owned_by=m.get("owned_by", ""), meta=m)
                for m in data if m.get("id")]

    async def chat(self, messages: list[dict], *, model: str, tools: list[dict] | None = None,
                   temperature: float | None = None, top_p: float | None = None,
                   max_tokens: int | None = None, stream: bool = False,
                   on_delta: DeltaCallback | None = None,
                   reasoning_effort: str | None = None) -> ChatResult:
        key = await self._require_key()
        payload: dict[str, Any] = {"model": model, "messages": messages}
        if temperature is not None:
            payload["temperature"] = temperature
        if top_p is not None:
            payload["top_p"] = top_p
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        if stream:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
            return await self._chat_stream(payload, key, on_delta)
        try:
            async with await self._client() as c:
                r = await c.post(f"{self.base_url}/chat/completions",
                                 headers=self._headers(key), json=payload)
        except httpx.HTTPError as e:
            raise ProviderError(f"Sin conexion: {e}", kind="network") from e
        if r.status_code >= 400:
            raise self.map_http_error(r.status_code, r.text)
        return self._parse_completion(r.json())

    def _parse_completion(self, data: dict) -> ChatResult:
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {}) or {}
        tool_calls = [ToolCall(id=tc.get("id", ""), name=tc.get("function", {}).get("name", ""),
                               arguments=tc.get("function", {}).get("arguments", "{}"))
                      for tc in msg.get("tool_calls") or []]
        usage = None
        u = data.get("usage")
        if u:
            usage = Usage(
                prompt_tokens=int(u.get("prompt_tokens", 0) or 0),
                completion_tokens=int(u.get("completion_tokens", 0) or 0),
                total_tokens=int(u.get("total_tokens", 0) or 0),
                details={k: v for k, v in u.items()
                         if k not in ("prompt_tokens", "completion_tokens", "total_tokens")},
            )
        return ChatResult(content=msg.get("content"), tool_calls=tool_calls,
                          finish_reason=choice.get("finish_reason"), usage=usage,
                          model=data.get("model"), raw=data)

    async def _chat_stream(self, payload: dict, key: str, on_delta: DeltaCallback | None) -> ChatResult:
        content_parts: list[str] = []
        tool_calls: dict[int, dict] = {}
        usage: Usage | None = None
        finish = None
        model_name = None
        try:
            async with await self._client() as c:
                async with c.stream("POST", f"{self.base_url}/chat/completions",
                                    headers=self._headers(key), json=payload) as r:
                    if r.status_code >= 400:
                        body = (await r.aread()).decode("utf-8", "replace")
                        raise self.map_http_error(r.status_code, body)
                    async for line in r.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        chunk = line[5:].strip()
                        if chunk == "[DONE]":
                            break
                        try:
                            d = json.loads(chunk)
                        except json.JSONDecodeError:
                            continue
                        model_name = model_name or d.get("model")
                        if d.get("usage"):
                            u = d["usage"]
                            usage = Usage(int(u.get("prompt_tokens", 0) or 0),
                                          int(u.get("completion_tokens", 0) or 0),
                                          int(u.get("total_tokens", 0) or 0))
                        for ch in d.get("choices") or []:
                            finish = ch.get("finish_reason") or finish
                            delta = ch.get("delta") or {}
                            piece = delta.get("content")
                            if piece:
                                content_parts.append(piece)
                                if on_delta:
                                    await on_delta(piece)
                            for tc in delta.get("tool_calls") or []:
                                idx = tc.get("index", 0)
                                slot = tool_calls.setdefault(
                                    idx, {"id": "", "name": "", "arguments": ""})
                                slot["id"] = slot["id"] or tc.get("id", "")
                                fn = tc.get("function") or {}
                                slot["name"] = slot["name"] or fn.get("name", "")
                                slot["arguments"] += fn.get("arguments", "") or ""
        except httpx.HTTPError as e:
            raise ProviderError(f"Sin conexion durante streaming: {e}", kind="network") from e
        calls = [ToolCall(id=v["id"], name=v["name"], arguments=v["arguments"] or "{}")
                 for _, v in sorted(tool_calls.items())]
        return ChatResult(content="".join(content_parts) or None, tool_calls=calls,
                          finish_reason=finish, usage=usage, model=model_name)

    async def balance(self) -> BalanceInfo | None:
        return None
