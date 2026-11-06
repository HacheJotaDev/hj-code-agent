"""Adaptador Anthropic (Messages API): mapeo de mensajes y herramientas nativas.

Los mensajes internos usan formato OpenAI; este adaptador los convierte.
El system prompt solo se envia si el llamador lo incluyo explicitamente
(modo personalizado o de proyecto): aqui no se anade nada por defecto.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from .base import ChatResult, DeltaCallback, LLMProvider, ModelInfo, ToolCall, Usage
from .errors import ProviderError

log = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    kind = "anthropic"

    def __init__(self, base_url: str, api_key_getter, timeout: float = 180.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        super().__init__(base_url, api_key_getter, timeout)
        self._transport = transport
        self.capabilities.balance = False

    def _headers(self, key: str) -> dict[str, str]:
        return {"x-api-key": key, "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"}

    async def list_models(self) -> list[ModelInfo]:
        key = await self._require_key()
        try:
            client_kw = {'transport': self._transport} if self._transport else {}
            async with httpx.AsyncClient(timeout=self.timeout, **client_kw) as c:
                r = await c.get(f"{self.base_url}/v1/models", headers=self._headers(key))
        except httpx.HTTPError as e:
            raise ProviderError(f"Sin conexion: {e}", kind="network") from e
        if r.status_code >= 400:
            raise self.map_http_error(r.status_code, r.text)
        data = r.json().get("data", [])
        return [ModelInfo(id=m.get("id", ""), meta=m) for m in data if m.get("id")]

    @staticmethod
    def _convert(messages: list[dict]) -> tuple[str | None, list[dict]]:
        system_parts: list[str] = []
        out: list[dict] = []
        for m in messages:
            role, content = m.get("role"), m.get("content")
            if role == "system":
                if content:
                    system_parts.append(str(content))
                continue
            if role == "tool":
                out.append({"role": "user", "content": [{
                    "type": "tool_result", "tool_use_id": m.get("tool_call_id", ""),
                    "content": content or ""}]})
                continue
            if role == "assistant" and m.get("tool_calls"):
                blocks: list[dict] = []
                if content:
                    blocks.append({"type": "text", "text": content})
                for tc in m["tool_calls"]:
                    try:
                        args = json.loads(tc.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    blocks.append({"type": "tool_use", "id": tc.get("id", ""),
                                   "name": tc.get("name", ""), "input": args})
                out.append({"role": "assistant", "content": blocks})
                continue
            out.append({"role": "user" if role == "user" else "assistant",
                        "content": content if isinstance(content, str) else ""})
        return ("\n".join(system_parts) or None), out

    async def chat(self, messages: list[dict], *, model: str, tools: list[dict] | None = None,
                   temperature: float | None = None, top_p: float | None = None,
                   max_tokens: int | None = None, stream: bool = False,
                   on_delta: DeltaCallback | None = None,
                   reasoning_effort: str | None = None) -> ChatResult:
        key = await self._require_key()
        system, conv = self._convert(messages)
        payload: dict[str, Any] = {
            "model": model, "messages": conv,
            "max_tokens": max_tokens or 4096,
        }
        if system:
            payload["system"] = system  # solo si el usuario configuro un prompt
        if temperature is not None:
            payload["temperature"] = temperature
        if top_p is not None:
            payload["top_p"] = top_p
        if tools:
            payload["tools"] = [{
                "name": t["function"]["name"],
                "description": t["function"].get("description", ""),
                "input_schema": t["function"].get("parameters", {"type": "object"}),
            } for t in tools]
        try:
            client_kw = {'transport': self._transport} if self._transport else {}
            async with httpx.AsyncClient(timeout=self.timeout, **client_kw) as c:
                r = await c.post(f"{self.base_url}/v1/messages",
                                 headers=self._headers(key), json=payload)
        except httpx.HTTPError as e:
            raise ProviderError(f"Sin conexion: {e}", kind="network") from e
        if r.status_code >= 400:
            raise self.map_http_error(r.status_code, r.text)
        data = r.json()
        blocks = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        calls = [ToolCall(id=b.get("id", ""), name=b.get("name", ""),
                          arguments=json.dumps(b.get("input", {}), ensure_ascii=False))
                 for b in blocks if b.get("type") == "tool_use"]
        u = data.get("usage") or {}
        usage = Usage(prompt_tokens=int(u.get("input_tokens", 0) or 0),
                      completion_tokens=int(u.get("output_tokens", 0) or 0),
                      total_tokens=int(u.get("input_tokens", 0) or 0) + int(u.get("output_tokens", 0) or 0))
        return ChatResult(content=text or None, tool_calls=calls,
                          finish_reason=data.get("stop_reason"), usage=usage,
                          model=data.get("model"), raw=data)

    async def balance(self) -> None:
        return None
