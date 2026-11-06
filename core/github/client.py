"""Cliente REST de GitHub (solo operaciones que el broker no hace con git local).

El token nunca se registra en logs; los errores lo enmascaran.
"""
from __future__ import annotations

import httpx

API = "https://api.github.com"


def mask_token(t: str | None) -> str:
    if not t:
        return "(sin token)"
    return f"{t[:4]}***{t[-4:]}" if len(t) > 10 else "***"


class GitHubError(Exception):
    pass


class GitHubClient:
    def __init__(self, token_getter, timeout: float = 30.0) -> None:
        self._get = token_getter
        self.timeout = timeout

    async def _headers(self) -> dict:
        token = await self._get()
        if not token:
            raise GitHubError("No hay token de GitHub configurado (usa /github connect)")
        return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28"}

    async def _req(self, method: str, path: str, json_body: dict | None = None) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.request(method, f"{API}{path}", headers=await self._headers(),
                                    json=json_body)
        except httpx.HTTPError as e:
            raise GitHubError(f"Sin conexion con GitHub: {e}") from e
        if r.status_code >= 400:
            detail = r.json().get("message", r.text[:200]) if r.headers.get("content-type", "").startswith("application/json") else r.text[:200]
            raise GitHubError(f"GitHub {r.status_code}: {detail}")
        if r.status_code == 204 or not r.content:
            return {}
        return r.json()

    async def whoami(self) -> dict:
        return await self._req("GET", "/user")

    async def repo(self, full_name: str) -> dict:
        return await self._req("GET", f"/repos/{full_name}")

    async def create_pull_request(self, full_name: str, *, title: str, head: str, base: str,
                                  body: str = "") -> dict:
        return await self._req("POST", f"/repos/{full_name}/pulls",
                               {"title": title, "head": head, "base": base, "body": body})

    async def list_pulls(self, full_name: str, state: str = "open") -> list:
        return await self._req("GET", f"/repos/{full_name}/pulls?state={state}&per_page=10")

    async def list_commits(self, full_name: str, sha: str | None = None, per_page: int = 10) -> list:
        q = f"?per_page={per_page}" + (f"&sha={sha}" if sha else "")
        return await self._req("GET", f"/repos/{full_name}/commits{q}")
