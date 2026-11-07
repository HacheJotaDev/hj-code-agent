"""Cola de tareas para el panel web (subclase de la cola V3).

Hereda de core.tasks.queue.TaskQueue la reclama atomica de SQLite, la
concurrencia limitada, la recuperacion tras reinicio y el limite de 1 tarea
simultanea por usuario. Sustituye SOLO la capa de notificacion:

- notify()/emit() -> eventos persistidos en task_events (SSE), no Telegram.
- La entrega del ZIP exportado se registra en kv y la descarga el usuario
  desde la web (no hay envio por bot).
- El bot de Telegram NO recibe nada desde aqui (no existe self.s.bot).
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from core.tasks.queue import RunningTask, TaskQueue
from core.tools.context import AgentContext
from security.path_guard import PathGuard

log = logging.getLogger(__name__)


class WebTaskQueue(TaskQueue):
    def __init__(self, services, hub) -> None:
        super().__init__(services)
        self.hub = hub

    # ------------------------- ejecucion ----------------------------------
    async def _execute(self, task: dict) -> None:
        tid = task["id"]
        uid = task["user_id"]
        project = None
        if task["project_id"]:
            project = await self.s.store.get_project(task["project_id"])
        if not project:
            await self.s.store.update_task(
                tid, status="failed", error="El proyecto ya no existe",
                finished_at=time.strftime("%Y-%m-%d %H:%M:%S"))
            await self.hub.publish(tid, {"type": "status", "status": "failed",
                                         "error": "El proyecto ya no existe"})
            self.kick()
            return
        self._user_busy[uid] = tid
        cancel_event = asyncio.Event()
        rt = RunningTask(task_id=tid, cancel_event=cancel_event, sandbox=None)
        self._running[tid] = rt

        async def notify(text: str) -> None:
            await self.hub.publish(tid, {"type": "notify", "text": str(text)[:2000]})

        async def emit(ev: dict) -> None:
            await self.hub.publish(tid, ev)

        try:
            await self.hub.publish(tid, {"type": "status", "status": "running",
                                         "title": (task["title"] or "")[:200]})
            from core.sandbox.factory import sandbox_semaphore
            workspace = Path(project["path"])
            guard = PathGuard(workspace)
            sem = sandbox_semaphore(getattr(self.s.settings, "max_concurrent_sandboxes", 1))
            async with sem:
                sandbox = await self.s.make_sandbox(workspace, project)
                rt.sandbox = sandbox
                await sandbox.setup()
                ctx = AgentContext(
                    user_id=uid, chat_id=task["chat_id"], project=project,
                    workspace=workspace, guard=guard, sandbox=sandbox,
                    services=self.s, cancel_event=cancel_event, task_id=tid,
                    conversation_id=task["conversation_id"],
                    max_steps=task["max_steps"], notify=notify, emit=emit)
                rt.ctx = ctx
                if task["kind"] == "multiagent":
                    from core.agent.multiagent import MultiAgentRunner
                    result = await MultiAgentRunner(self.s).run_pipeline(ctx, task["title"], notify)
                    from core.agent.engine import TaskOutcome
                    outcome = TaskOutcome(summary=result["summary"], files_touched=[
                        f for ph in result["phases"] for f in ph.get("files", [])])
                    outcome.cost = sum(p.get("cost") or 0 for p in result["phases"])
                    outcome.cost_known = any(p.get("cost_known") for p in result["phases"])
                    outcome.cancelled = any(p.get("cancelled") for p in result["phases"])
                else:
                    outcome = await self.s.engine.run_task(ctx, task["title"], notify=notify)
                await self._finalize(task, ctx, outcome)
        except Exception as e:
            log.exception("Error ejecutando tarea web %s", tid)
            await self.s.store.update_task(
                tid, status="failed", error=str(e)[:900],
                finished_at=time.strftime("%Y-%m-%d %H:%M:%S"))
            await self.hub.publish(tid, {"type": "status", "status": "failed",
                                         "error": str(e)[:900]})
        finally:
            self._running.pop(tid, None)
            self._user_busy.pop(uid, None)
            if rt.sandbox:
                try:
                    await rt.sandbox.cleanup()
                except Exception:
                    pass
            self.kick()

    # ------------------------- finalizacion --------------------------------
    async def _finalize(self, task: dict, ctx: AgentContext, outcome) -> None:
        tid = task["id"]
        status = "cancelled" if outcome.cancelled else (
            "failed" if outcome.error and not outcome.cancelled else "done")
        summary = self.format_summary(task, ctx, outcome)
        await self.s.store.update_task(
            tid, status=status, result=summary[:8000], error=outcome.error,
            steps=ctx.steps, finished_at=time.strftime("%Y-%m-%d %H:%M:%S"))
        # Entrega del ZIP: la descarga el usuario desde la web (sin Telegram)
        zip_path = getattr(ctx, "exported_zip", None)
        if zip_path:
            try:
                await self.s.store.kv_set(f"taskzip:{tid}", zip_path, ttl_s=7 * 86400)
            except Exception:
                log.warning("No se pudo registrar el ZIP de la tarea %s", tid)
        await self.hub.publish(tid, {
            "type": "status", "status": status,
            "summary": (outcome.summary or "")[:4000],
            "steps": ctx.steps,
            "cost": outcome.cost if outcome.cost_known else None,
            "files_touched": ctx.files_touched[:60],
            "commands": len(ctx.commands_run),
            "tests": len(ctx.tests_run),
        })
        await self.s.store.audit(task["user_id"], "task.finish", f"#{tid} {status} (web)")
