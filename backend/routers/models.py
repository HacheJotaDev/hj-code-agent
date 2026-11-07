"""API de modelos y proveedores: catalogo REAL del proveedor activo.

No se inventa ningun modelo: si el proveedor no responde o no hay API key,
se devuelve el error real y una lista vacia. Las claves viven cifradas en la
boveda (core/storage/crypto.py) y jamás viajan al frontend.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.providers.base import LLMProvider
from core.providers.errors import ProviderError

from ..deps import require_auth

router = APIRouter(prefix="/api", tags=["models"])


@router.get("/providers")
async def list_providers(auth=Depends(require_auth)):
    rows = await auth.ctx.store.list_providers()
    creds = set(await auth.ctx.store.list_credential_providers(auth.agent_uid))
    active = await auth.ctx.providers.active_name(auth.agent_uid)
    return {"providers": [{"name": r["name"], "kind": r["kind"],
                           "base_url": r["base_url"], "enabled": bool(r["enabled"]),
                           "has_key": r["name"] in creds} for r in rows],
            "active": active}


class ProviderSelect(BaseModel):
    name: str = Field(min_length=1, max_length=60)


@router.post("/providers/select")
async def select_provider(body: ProviderSelect, auth=Depends(require_auth)):
    cfg = await auth.ctx.store.get_provider(body.name)
    if not cfg or not cfg["enabled"]:
        raise HTTPException(status_code=404, detail="Proveedor no disponible")
    await auth.ctx.store.set_pref(auth.agent_uid, "active_provider", body.name)
    await auth.store.audit(auth.agent_uid, "web.provider_select", body.name)
    return {"ok": True, "active": body.name}


@router.get("/models")
async def list_models(provider: str | None = None, auth=Depends(require_auth)):
    """Catalogo vivo del proveedor (GET /models real, cacheado 5 min)."""
    name = provider or await auth.ctx.providers.active_name(auth.agent_uid)
    selected = await auth.ctx.store.get_pref(auth.agent_uid, f"model:{name}") or ""
    try:
        prov: LLMProvider = await auth.ctx.providers.get(auth.agent_uid, name)
    except ProviderError as e:
        return {"provider": name, "selected": selected, "models": [], "error": str(e)}
    try:
        models = await auth.ctx.catalog.list(prov)
    except ProviderError as e:
        return {"provider": name, "selected": selected, "models": [], "error": str(e)}
    return {"provider": name, "selected": selected,
            "models": [{"id": m.id, "context_window": m.context_window,
                        "max_output": m.max_output} for m in models]}


class ModelSelect(BaseModel):
    model: str = Field(min_length=1, max_length=120)
    provider: str | None = Field(default=None, max_length=60)


@router.post("/models/select")
async def select_model(body: ModelSelect, auth=Depends(require_auth)):
    name = body.provider or await auth.ctx.providers.active_name(auth.agent_uid)
    try:
        prov = await auth.ctx.providers.get(auth.agent_uid, name)
        m = await auth.ctx.catalog.ensure_model(prov, body.model)
    except ProviderError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if m is None:
        raise HTTPException(status_code=400,
                            detail=f"El proveedor '{name}' no lista el modelo '{body.model}'")
    await auth.ctx.store.set_pref(auth.agent_uid, f"model:{name}", body.model)
    await auth.store.audit(auth.agent_uid, "web.model_select", f"{name}/{body.model}")
    return {"ok": True, "provider": name, "selected": body.model}
