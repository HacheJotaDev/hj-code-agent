"""Modelos de datos y contrato base para todos los proveedores."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .errors import NoApiKey, ProviderError


@dataclass
class ModelInfo:
    id: str
    owned_by: str = ""
    context_window: int | None = None
    max_output: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON en crudo, como llega de la API


@dataclass
class ChatResult:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    usage: Usage | None = None
    model: str | None = None
    raw: dict[str, Any] | None = None


@dataclass
class BalanceInfo:
    currency: str = ""
    total_balance: float = 0.0
    granted_balance: float | None = None
    topped_up_balance: float | None = None
    is_available: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Capabilities:
    chat: bool = True
    tools: bool = True
    stream: bool = True
    balance: bool = False
    reasoning: bool = False
    list_models: bool = True


DeltaCallback = Callable[[str], Awaitable[None]]


class LLMProvider(ABC):
    """Contrato comun. `api_key_getter` se resuelve en cada llamada (boveda cifrada)."""

    name: str = "abstract"
    kind: str = "abstract"

    def __init__(self, base_url: str, api_key_getter, timeout: float = 180.0):
        self.base_url = base_url.rstrip("/")
        self._get_key = api_key_getter
        self.timeout = timeout
        self.capabilities = Capabilities()

    async def _require_key(self) -> str:
        key = await self._get_key() if callable(self._get_key) else self._get_key
        if not key:
            raise NoApiKey(f"Sin API key para el proveedor '{self.name}'")
        return key

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]: ...

    @abstractmethod
    async def chat(self, messages: list[dict], *, model: str, tools: list[dict] | None = None,
                   temperature: float | None = None, top_p: float | None = None,
                   max_tokens: int | None = None, stream: bool = False,
                   on_delta: DeltaCallback | None = None,
                   reasoning_effort: str | None = None) -> ChatResult: ...

    async def balance(self) -> BalanceInfo | None:
        """None = el proveedor no expone consulta de saldo."""
        return None

    async def close(self) -> None: ...

    @staticmethod
    def map_http_error(status: int, body: str) -> ProviderError:
        text = (body or "")[:500]
        if status in (401, 403):
            return ProviderError(f"{status}: {text}", kind="auth", status=status)
        if status == 402:
            return ProviderError(f"{status}: {text}", kind="insufficient_balance", status=status)
        if status == 404:
            return ProviderError(f"{status}: {text}", kind="not_found", status=status)
        if status == 429:
            return ProviderError(f"{status}: {text}", kind="rate_limit", status=status)
        if status >= 500:
            return ProviderError(f"{status}: {text}", kind="overloaded", status=status)
        return ProviderError(f"{status}: {text}", kind="bad_request", status=status)
