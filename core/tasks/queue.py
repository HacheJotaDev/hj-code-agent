"""Cola de trabajos durable: ejecucion cancelable, reintentos y recuperacion.

- Persistida en SQLite: sobrevive reinicios.
- Tras un reinicio, las tareas 'running' se marcan 'interrupted' y pueden
  relanzarse con /task retry.
- Concurrencia limitada globalmente (HJ_MAX_CONCURRENT_TASKS) y 1 tarea
  simultanea por usuario para no pisar workspaces.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from security.path_guard import PathGuard
from ..agent.engine import TaskOutcome
from ..tools.context import AgentContext

log = logging.getLogger(__name__)


@dataclass
class RunningTask:
    task_id: int
    cancel_event: asyncio.Event
    sandbox: object
    ctx: AgentContext | None = None


class TaskQueue:
    def __init__(self, services) -> None:
        self.s = services
        self._workers: list[asyncio.Task] = []
        self._running: dict[int, RunningTask] = {}  # task_id -> RunningTask
        self._user_busy: dict[int, int] = {}
        self._wake = asyncio.Event()
        self._stopping = False

    # ------------------------- ciclo de vida ------------------------------
    async def start(self) -> None:
        interrupted = await self.s.store.recover_interrupted()
        if interrupted:
            log.warning("Recuperacion: %d tareas marcadas como interrumpidas", interrupted)
        n = max(1, int(self.s.settings.max_concurrent_tasks))
        self._workers = [asyncio.create_task(self._worker(i)) for i in range(n)]
        log.info("Cola de tareas iniciada con %d workers", n)

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        for t in self._workers:
            t.cancel()
        for rt in list(self._running.values()):
            rt.cancel_event.set()
        await asyncio.gather(*self._workers, return_exceptions=True)

    def kick(self) -> None:
        self._wake.set()

    # ------------------------- API publica --------------------------------
    async def submit(self, user_id: int, chat_id: int, project: dict, conversation_id: int | None,
                     title: str, kind: str = "agent", max_steps: int | None = None) -> int:
        tid = await self.s.store.create_task(
            user_id, chat_id, project["id"] if project else None, conversation_id,
            kind, title, max_steps or self.s.settings.max_task_steps)
        self.kick()
        return tid

    def cancel(self, task_id: int) -> bool:
        rt = self._running.get(task_id)
        if rt:
            rt.cancel_event.set()
            return True
        return False

    def is_running(self, task_id: int) -> bool:
        return task_id in self._running

    def running_for_user(self, user_id: int) -> list[int]:
        return [tid for tid, rt in self._running.items()
                if rt.ctx and rt.ctx.user_id == user_id]

    # ------------------------- workers ------------------------------------
    async def _worker(self, idx: int) -> None:
        while not self._stopping:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=30)
            except asyncio.TimeoutError:
                continue
            self._wake.clear()
            while not self._stopping:
                # Vistazo para respetar 1 tarea por usuario sin reclamar:
                peek = await self.s.store.next_queued()
                if not peek:
                    break
                if self._user_busy.get(peek["user_id"]):
                    break
                # Reclamacion ATOMICA: solo uno de varios workers obtiene la fila.
                task = await self.s.store.claim_next_queued()
                if not task:
                    continue  # otro worker se la llevo; reintentar
                await self._execute(task)

    async def _execute(self, task: dict) -> None:
        tid = task["id"]
        uid, chat_id = task["user_id"], task["chat_id"]
        project = None
        if task["project_id"]:
            project = await self.s.store.get_project(task["project_id"])
        if not project:
            await self.s.store.update_task(tid, status="failed",
                                           error="El proyecto ya no existe",
                                           finished_at=time.strftime("%Y-%m-%d %H:%M:%S"))
            return
        # El claim ya la puso en 'running'; aqui solo registramos el estado vivo.
        self._user_busy[uid] = tid
        cancel_event = asyncio.Event()
        rt = RunningTask(task_id=tid, cancel_event=cancel_event, sandbox=None)
        self._running[tid] = rt

        async def notify(text: str) -> None:
            try:
                await self.s.bot.send_message(chat_id, text[:4000])
            except Exception:
                log.warning("No se pudo notificar al chat %s", chat_id)

        try:
            from pathlib import Path
            from ..sandbox.factory import sandbox_semaphore
            workspace = Path(project["path"])
            guard = PathGuard(workspace)
            # Limite global de sandboxes simultaneos (produccion: 1)
            sem = sandbox_semaphore(getattr(self.s.settings, "max_concurrent_sandboxes", 1))
            async with sem:
                sandbox = await self.s.make_sandbox(workspace, project)
                rt.sandbox = sandbox
                await sandbox.setup()
                ctx = AgentContext(
                    user_id=uid, chat_id=chat_id, project=project, workspace=workspace,
                    guard=guard, sandbox=sandbox, services=self.s, cancel_event=cancel_event,
                    task_id=tid, max_steps=task["max_steps"], notify=notify)
                rt.ctx = ctx
                if task["kind"] == "multiagent":
                    from ..agent.multiagent import MultiAgentRunner
                    result = await MultiAgentRunner(self.s).run_pipeline(ctx, task["title"], notify)
                    outcome = TaskOutcome(summary=result["summary"], files_touched=[
                        f for ph in result["phases"] for f in ph.get("files", [])])
                    outcome.cost = sum(p.get("cost") or 0 for p in result["phases"])
                    outcome.cost_known = any(p.get("cost_known") for p in result["phases"])
                    outcome.cancelled = any(p.get("cancelled") for p in result["phases"])
                else:
                    outcome = await self.s.engine.run_task(ctx, task["title"], notify=notify)
                await self._finalize(task, ctx, outcome)
        except Exception as e:
            log.exception("Error ejecutando tarea %s", tid)
            await self.s.store.update_task(
                tid, status="failed", error=str(e)[:900],
                finished_at=time.strftime("%Y-%m-%d %H:%M:%S"))
            await notify(f"❌ Tarea #{tid} fallo: {e}")
        finally:
            self._running.pop(tid, None)
            self._user_busy.pop(uid, None)
            if rt.sandbox:
                try:
                    await rt.sandbox.cleanup()
                except Exception:
                    pass
            self.kick()

    async def _finalize(self, task: dict, ctx: AgentContext, outcome: TaskOutcome) -> None:
        tid = task["id"]
        status = "cancelled" if outcome.cancelled else "done"
        if outcome.error and not outcome.cancelled:
            status = "failed"
        summary = self.format_summary(task, ctx, outcome)
        await self.s.store.update_task(
            tid, status=status, result=summary[:8000], error=outcome.error,
            steps=ctx.steps, finished_at=time.strftime("%Y-%m-%d %H:%M:%S"))
        b = await self.s.store.get_budget(task["user_id"])
        if b.get("notifications", 1):
            try:
                await self.s.bot.send_message(task["chat_id"], summary[:4000])
            except Exception:
                pass
        # Entrega del ZIP del proyecto si el agente lo genero (flujo V3)
        zip_path = getattr(ctx, "exported_zip", None)
        if zip_path:
            try:
                from pathlib import Path as _P
                from aiogram.types import BufferedInputFile
                p = _P(zip_path)
                if p.exists() and p.stat().st_size <= 49 * 1024 * 1024:
                    await self.s.bot.send_document(
                        task["chat_id"], BufferedInputFile(p.read_bytes(), p.name),
                        caption=f"📦 Proyecto {ctx.project['name']} exportado")
            except Exception:
                log.warning("No se pudo enviar el ZIP exportado de la tarea %s", tid)
        await self.s.store.audit(task["user_id"], "task.finish", f"#{tid} {status}")

    @staticmethod
    def format_summary(task: dict, ctx: AgentContext, outcome: TaskOutcome) -> str:
        icon = {"done": "✅", "cancelled": "🛑", "failed": "❌"}.get(
            "cancelled" if outcome.cancelled else ("failed" if outcome.error and not outcome.cancelled else "done"), "✅")
        lines = [f"{icon} Tarea #{task['id']} — {task['title'][:80]}",
                 f"Proyecto: {ctx.project['name']} | Pasos: {ctx.steps}"]
        cost = f"{outcome.cost:.4f}" if outcome.cost_known else "n/d"
        lines.append(f"Coste estimado: {cost}")
        if outcome.files_touched:
            lines.append("Archivos tocados: " + ", ".join(outcome.files_touched[:12]))
        if outcome.commands:
            lines.append(f"Comandos ejecutados: {len(outcome.commands)}")
        lines.append("")
        lines.append(outcome.summary or "(sin resumen)")
        return "\n".join(lines)
