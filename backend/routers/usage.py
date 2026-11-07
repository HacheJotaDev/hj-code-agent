"""API de consumo y presupuestos: datos REALES del usage_log de la V3."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..deps import require_auth

router = APIRouter(prefix="/api", tags=["usage"])


@router.get("/usage/summary")
async def usage_summary(auth=Depends(require_auth)):
    uid = auth.agent_uid
    today = await auth.ctx.usage.day_cost(uid)
    totals = await auth.ctx.usage.totals(uid)
    by_model = await auth.ctx.usage.by_model(uid)
    return {"today_cost": today or 0.0,
            "totals": totals,
            "by_model": by_model[:20]}


@router.get("/budget")
async def get_budget(auth=Depends(require_auth)):
    return await auth.ctx.store.get_budget(auth.agent_uid)


class BudgetIn(BaseModel):
    per_task: float | None = Field(default=None, ge=0)
    per_day: float | None = Field(default=None, ge=0)
    notifications: int | None = Field(default=None, ge=0, le=1)


@router.put("/budget")
async def set_budget(body: BudgetIn, auth=Depends(require_auth)):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if fields:
        await auth.ctx.store.set_budget(auth.agent_uid, **fields)
    return {"ok": True, "budget": await auth.ctx.store.get_budget(auth.agent_uid)}
