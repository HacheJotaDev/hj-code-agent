"""Ejecucion aislada de comandos bajo demanda (boton 'Ejecutar' del IDE web).

- El navegador NUNCA envia instrucciones Docker: solo un comando shell como
  texto. El backend elige el backend de sandbox (fabrica V3 con politica
  estricta de HJ_DOCKER_HOST rootless) y valida el comando con command_guard.
- Sin sandbox aislado disponible -> NO se ejecuta nada (fail-safe de V3).
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.sandbox.base import ExecutionUnavailable
from core.sandbox.factory import sandbox_semaphore
from security.command_guard import CommandDenied, screen_command
from security.path_guard import PathGuard

from ..deps import require_auth

router = APIRouter(prefix="/api/projects/{pid}", tags=["exec"])

MAX_OUTPUT = 12000


class ExecIn(BaseModel):
    command: str = Field(min_length=1, max_length=2000)
    timeout: int = Field(default=60, ge=1, le=600)


@router.post("/exec")
async def exec_command(pid: int, body: ExecIn, auth=Depends(require_auth)):
    proj = await auth.ctx.store.get_project(int(pid))
    if not proj or int(proj["user_id"]) != auth.agent_uid or proj["archived"]:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    from pathlib import Path
    workspace = Path(proj["path"])
    if not workspace.exists():
        raise HTTPException(status_code=400, detail="El workspace no existe")
    try:
        screen_command(body.command)
    except CommandDenied as e:
        await auth.store.audit(auth.agent_uid, "web.exec_denied",
                               f"#{pid}: {body.command[:150]}")
        raise HTTPException(status_code=400, detail=str(e))
    sem = sandbox_semaphore(getattr(auth.settings, "max_concurrent_sandboxes", 1))
    started = time.monotonic()
    async with sem:
        try:
            sandbox = await auth.ctx.make_sandbox(workspace, proj)
        except ExecutionUnavailable as e:
            raise HTTPException(status_code=409, detail=str(e))
        try:
            await sandbox.setup()
            try:
                res = await sandbox.exec(body.command, timeout=int(body.timeout),
                                         key=f"web:{pid}:{int(time.time())}", task_id=None)
            except CommandDenied as e:
                raise HTTPException(status_code=400, detail=str(e))
        except ExecutionUnavailable as e:
            raise HTTPException(status_code=409, detail=str(e))
        finally:
            try:
                await sandbox.cleanup()
            except Exception:
                pass
    await auth.store.audit(auth.agent_uid, "web.exec", f"#{pid}: {body.command[:150]}")
    return {"ok": True, "output": res.truncated(MAX_OUTPUT),
            "duration_ms": int((time.monotonic() - started) * 1000)}
