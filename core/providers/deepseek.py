"""Adaptador DeepSeek: API OpenAI-compatible + endpoint oficial de saldo."""
from __future__ import annotations

import logging

import httpx

from .base import BalanceInfo, ModelInfo
from .errors import ProviderError
from .openai_compat import OpenAICompatProvider

log = logging.getLogger(__name__)


class DeepSeekProvider(OpenAICompatProvider):
    name = "deepseek"
    kind = "deepseek"

    def __init__(self, base_url: str, api_key_getter, timeout: float = 180.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        super().__init__(base_url, api_key_getter, timeout, transport=transport)
        self.capabilities.balance = True

    async def balance(self) -> BalanceInfo | None:
        """GET /user/balance -> is_available + balance_infos[] (campos oficiales)."""
        key = await self._require_key()
        try:
            async with await self._client() as c:
                r = await c.get(f"{self.base_url}/user/balance",
                                headers=self._headers(key))
        except httpx.HTTPError as e:
            raise ProviderError(f"Sin conexion: {e}", kind="network") from e
        if r.status_code >= 400:
            raise self.map_http_error(r.status_code, r.text)
        data = r.json()
        info = data.get("balance_infos") or [{}]
        first = info[0] if info else {}
        return BalanceInfo(
            currency=first.get("currency", ""),
            total_balance=float(first.get("total_balance", 0) or 0),
            granted_balance=float(first["granted_balance"]) if first.get("granted_balance") not in (None, "") else None,
            topped_up_balance=float(first["topped_up_balance"]) if first.get("topped_up_balance") not in (None, "") else None,
            is_available=bool(data.get("is_available", False)),
            raw=data,
        )
