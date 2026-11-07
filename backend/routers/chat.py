"""API de conversaciones y tareas: chat, plan, actividad en vivo (SSE),
cancelacion, reintento/continuacion e historial.

El flujo real: POST /conversations/{id}/messages -> TaskQueue.submit() ->
workers de WebTaskQueue ejecutan el motor V3 -> eventos en task_events ->
el navegador los consume por SSE (con reconexion via Last-Event-ID).
"""
from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.providers.errors import ProviderError

from ..deps import require_auth

router = APIRouter(prefix="/api", tags=["chat"])

TERMINAL_STATUS = {"done", "failed", "cancelled", "interrupted"}
MAX_MESSAGE_CHARS = 16000


async def _own_conversation(auth, cid: int) -> dict:
    conv = await auth.ctx.store.get_conversation(int(cid))
    if not conv or int(conv["user_id"]) != auth.agent_uid:
        raise HTTPException(status_code=404, detail="Conversacion no encontrada")
    return conv


async def _own_task(auth, tid: int) -> dict:
    task = await auth.ctx.store.get_task(int(tid))
    if not task or int(task["user_id"]) != auth.agent_uid:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return task


def _serialize_task(t: dict) -> dict:
    return {"id": t["id"], "status": t["status"], "title": t["title"],
            "kind": t["kind"], "project_id": t["project_id"],
            "conversation_id": t["conversation_id"], "steps": t["steps"],
            "max_steps": t["max_steps"], "error": t["error"], "result": t["result"],
            "created_at": t.get("created_at"), "finished_at": t.get("finished_at")}


# --------------------------- conversaciones -------------------------------


class ConversationIn(BaseModel):
    project_id: int | None = None
    title: str = Field(default="", max_length=120)


@router.get("/conversations")
async def list_conversations(limit: int = 50, auth=Depends(require_auth)):
    rows = await auth.ctx.store.list_conversations(auth.agent_uid, limit=max(1, min(limit, 100)))
    return {"conversations": rows}


@router.post("/conversations")
async def create_conversation(body: ConversationIn, auth=Depends(require_auth)):
    if body.project_id is not None:
        proj = await auth.ctx.store.get_project(int(body.project_id))
        if not proj or int(proj["user_id"]) != auth.agent_uid:
            raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    provider = await auth.ctx.providers.active_name(auth.agent_uid)
    model = await auth.ctx.store.get_pref(auth.agent_uid, f"model:{provider}") or ""
    cid = await auth.ctx.store.create_conversation(
        auth.agent_uid, body.project_id, provider, model, body.title)
    conv = await auth.ctx.store.get_conversation(cid)
    return {"ok": True, "conversation": conv}


@router.delete("/conversations/{cid}")
async def delete_conversation(cid: int, auth=Depends(require_auth)):
    await _own_conversation(auth, cid)
    await auth.ctx.store.delete_conversation(int(cid))
    return {"ok": True}


@router.get("/conversations/{cid}/messages")
async def get_messages(cid: int, limit: int = 300, auth=Depends(require_auth)):
    await _own_conversation(auth, cid)
    rows = await auth.ctx.store.get_messages(int(cid), limit=max(1, min(limit, 500)))
    out = []
    for r in rows:
        out.append({"id": r["id"], "role": r["role"], "content": r["content"],
                    "tool_calls": r.get("tool_calls"), "tool_call_id": r.get("tool_call_id"),
                    "name": r.get("name"), "tokens_in": r.get("tokens_in") or 0,
                    "tokens_out": r.get("tokens_out") or 0, "cost": r.get("cost") or 0.0})
    return {"messages": out}


# --------------------------- enviar mensaje -> tarea ----------------------


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    model: str | None = Field(default=None, max_length=120)
    provider: str | None = Field(default=None, max_length=60)
    project_id: int | None = None
    max_steps: int | None = Field(default=None, ge=1, le=300)
    kind: str = Field(default="agent", pattern="^(agent|multiagent)$")


@router.post("/conversations/{cid}/messages")
async def send_message(cid: int, body: MessageIn, auth=Depends(require_auth)):
    conv = await _own_conversation(auth, cid)
    queue = auth.ctx.queue
    if queue is None:
        raise HTTPException(status_code=503, detail="La cola de tareas no esta activa")
    # Modelo seleccionado en el picker (se persiste como preferencia del usuario,
    # exactamente como hace el motor V3)
    provider = body.provider or conv["provider"] or await auth.ctx.providers.active_name(auth.agent_uid)
    if body.model:
        try:
            prov = await auth.ctx.providers.get(auth.agent_uid, provider)
            m = await auth.ctx.catalog.ensure_model(prov, body.model)
        except ProviderError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if m is None:
            raise HTTPException(status_code=400,
                                detail=f"El proveedor '{provider}' no lista el modelo "
                                       f"'{body.model}'; no se aceptan modelos inventados")
        await auth.ctx.store.set_pref(auth.agent_uid, f"model:{provider}", body.model)
        await auth.ctx.store.touch_conversation(cid, provider=provider, model=body.model)
    # Proyecto: explicito -> conversacion -> activo; sin proyecto no hay tarea
    proj = None
    pid = body.project_id or conv["project_id"]
    if pid:
        proj = await auth.ctx.store.get_project(int(pid))
    if not proj:
        proj = await auth.ctx.projects.active(auth.agent_uid)
    if not proj or int(proj["user_id"]) != auth.agent_uid:
        raise HTTPException(status_code=400,
                            detail="Selecciona un proyecto antes de enviar la tarea")
    # Continua el historial existente: la conversacion ya contiene los mensajes
    if not conv["title"]:
        await auth.ctx.store.touch_conversation(cid, title=body.text.strip()[:60])
    tid = await queue.submit(auth.agent_uid, auth.agent_uid, proj, cid,
                             body.text.strip(), kind=body.kind,
                             max_steps=body.max_steps)
    await auth.store.audit(auth.agent_uid, "web.task_submit",
                           f"#{tid} conv={cid} project={proj['name']}")
    return {"ok": True, "task_id": tid, "conversation_id": cid,
            "project_id": proj["id"], "model": body.model or conv["model"] or "",
            "provider": provider}


# --------------------------- tareas ---------------------------------------


@router.get("/tasks")
async def list_tasks(conversation_id: int | None = None, limit: int = 30,
                     auth=Depends(require_auth)):
    rows = await auth.ctx.store.list_tasks(auth.agent_uid, limit=max(1, min(limit, 100)))
    if conversation_id is not None:
        rows = [r for r in rows if r["conversation_id"] == int(conversation_id)]
    return {"tasks": [_serialize_task(r) for r in rows]}


@router.get("/tasks/{tid}")
async def get_task(tid: int, auth=Depends(require_auth)):
    task = await _own_task(auth, tid)
    out = _serialize_task(task)
    plan = await auth.ctx.hub.latest_plan(tid) if hasattr(auth.ctx, "hub") else None
    if plan is not None:
        out["plan"] = plan
    zip_path = await auth.ctx.store.kv_get(f"taskzip:{tid}")
    out["zip_available"] = bool(zip_path)
    return out


@router.get("/tasks/{tid}/events")
async def task_events(tid: int, after: int = 0, auth=Depends(require_auth)):
    """Polling de respaldo (la via primaria es SSE)."""
    await _own_task(auth, tid)
    events = await auth.ctx.hub.events_after(int(tid), int(after))
    task = await auth.ctx.store.get_task(int(tid))
    return {"events": events, "status": task["status"] if task else "unknown"}


@router.get("/tasks/{tid}/stream")
async def task_stream(request: Request, tid: int, after: int = 0,
                      auth=Depends(require_auth)):
    """SSE de la tarea: replay desde `after`/Last-Event-ID + vivo + heartbeat.

    Termina cuando la tarea alcanza estado final y todos los eventos se han
    enviado (evento `end`). El navegador puede reconectar con Last-Event-ID.
    """
    task = await _own_task(auth, tid)
    hub = auth.ctx.hub
    last = int(request.headers.get("last-event-id") or after or 0)

    async def gen():
        ev = hub.subscribe(int(tid))
        last_seq = last
        try:
            yield ": conectado\n\n"
            while True:
                rows = await hub.events_after(int(tid), last_seq)
                for r in rows:
                    last_seq = r["id"]
                    data = json.dumps(r["data"], ensure_ascii=False, default=str)
                    yield f"id: {r['id']}\nevent: {r['type']}\ndata: {data}\n\n"
                row = await auth.ctx.store.get_task(int(tid))
                finished = bool(row) and row["status"] in TERMINAL_STATUS
                if finished and not rows:
                    yield "event: end\ndata: {}\n\n"
                    return
                try:
                    await asyncio.wait_for(ev.wait(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                ev.clear()
                if await request.is_disconnected():
                    return
        finally:
            hub.unsubscribe(int(tid), ev)

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
               "Connection": "keep-alive"}
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)


@router.get("/tasks/{tid}/zip")
async def download_task_zip(tid: int, auth=Depends(require_auth)):
    """Descarga el ZIP que el agente genero (export_zip) para esta tarea."""
    from fastapi.responses import FileResponse
    from pathlib import Path as _P

    task = await _own_task(auth, tid)
    zip_path = await auth.ctx.store.kv_get(f"taskzip:{tid}")
    if not zip_path or not _P(str(zip_path)).exists():
        raise HTTPException(status_code=404, detail="Esta tarea no tiene ZIP disponible")
    p = _P(str(zip_path))
    await auth.store.audit(auth.agent_uid, "web.task_zip_download", f"#{tid} {p.name}")
    return FileResponse(p, media_type="application/zip", filename=p.name)


@router.post("/tasks/{tid}/cancel")
async def cancel_task(tid: int, auth=Depends(require_auth)):
    task = await _own_task(auth, tid)
    if task["status"] in TERMINAL_STATUS:
        raise HTTPException(status_code=400, detail="La tarea ya termino")
    queue = auth.ctx.queue
    cancelled_live = bool(queue and queue.cancel(int(tid)))
    if not cancelled_live and task["status"] == "queued":
        await auth.ctx.store.update_task(
            int(tid), status="cancelled", error="Cancelada mientras estaba en cola",
            finished_at=time.strftime("%Y-%m-%d %H:%M:%S"))
        await auth.ctx.hub.publish(int(tid), {"type": "status", "status": "cancelled"})
        cancelled_live = True
    if not cancelled_live:
        raise HTTPException(status_code=409, detail="La tarea no se esta ejecutando ahora")
    await auth.store.audit(auth.agent_uid, "web.task_cancel", f"#{tid}")
    return {"ok": True}


@router.post("/tasks/{tid}/retry")
async def retry_task(tid: int, auth=Depends(require_auth)):
    """Continuacion: relanza la instruccion ORIGINAL como tarea nueva.

    El contexto ya persiste en la conversacion (mensajes, archivos modificados),
    asi que el motor parte del estado existente. No se falsifica 'done'.
    """
    task = await _own_task(auth, tid)
    if task["status"] not in {"failed", "interrupted", "cancelled"}:
        raise HTTPException(status_code=400,
                            detail="Solo se pueden reintentar tareas fallidas, interrumpidas o canceladas")
    queue = auth.ctx.queue
    if queue is None:
        raise HTTPException(status_code=503, detail="La cola de tareas no esta activa")
    proj = None
    if task["project_id"]:
        proj = await auth.ctx.store.get_project(task["project_id"])
    if not proj:
        raise HTTPException(status_code=400, detail="El proyecto de la tarea ya no existe")
    params = dict(task.get("params") or {})
    params["retry_of"] = int(tid)
    new_tid = await queue.submit(auth.agent_uid, auth.agent_uid, proj,
                                 task["conversation_id"], task["title"],
                                 kind=task["kind"], max_steps=task["max_steps"])
    await auth.ctx.store.update_task(int(new_tid),
                                     params=json.dumps(params, ensure_ascii=False))
    await auth.store.audit(auth.agent_uid, "web.task_retry", f"#{tid} -> #{new_tid}")
    return {"ok": True, "task_id": new_tid}
