"""Motor del agente: bucle real de llamadas al modelo con herramientas nativas.

- Sin system prompt por defecto: los mensajes se construyen con PromptService.
- Cada llamada registra tokens/coste reales (usage de la API).
- Herramientas con validacion estricta; git_push y PR exigen aprobacion humana.
- Limites: pasos, presupuesto por tarea, cancelacion inmediata.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field

from ..providers.base import ChatResult, LLMProvider
from ..providers.errors import NoApiKey, ProviderError
from ..tools.context import AgentContext
from ..tools.registry import TOOL_SCHEMAS, execute_tool
from .approvals import ApprovalDenied, ApprovalManager, ApprovalTimeout

log = logging.getLogger(__name__)

MAX_HISTORY_CHARS = 90_000


class TaskCancelled(Exception):
    pass


class BudgetExceeded(Exception):
    pass


@dataclass
class StepRecord:
    step: int
    action: str
    detail: str = ""
    ok: bool = True


@dataclass
class TaskOutcome:
    summary: str = ""
    steps: list = field(default_factory=list)
    cost: float = 0.0
    cost_known: bool = False
    files_touched: list = field(default_factory=list)
    commands: list = field(default_factory=list)
    cancelled: bool = False
    error: str | None = None


class AgentEngine:
    def __init__(self, services) -> None:
        self.s = services
        self.approvals: ApprovalManager = services.approvals

    # --------------------- historial --------------------------------------
    def _history_to_api(self, rows: list[dict]) -> list[dict]:
        msgs: list[dict] = []
        for r in rows:
            role = r["role"]
            if role == "tool":
                msgs.append({"role": "tool", "tool_call_id": r["tool_call_id"] or "",
                             "content": r["content"] or ""})
                continue
            m: dict = {"role": role, "content": r["content"]}
            if r.get("tool_calls"):
                m["tool_calls"] = [{
                    "id": tc["id"], "type": "function",
                    "function": {"name": tc["name"], "arguments": tc.get("arguments", "{}")},
                } for tc in r["tool_calls"]]
                if not m["content"]:
                    m["content"] = None
            msgs.append(m)
        total = sum(len(str(m.get("content") or "")) + len(str(m.get("tool_calls") or ""))
                    for m in msgs)
        while total > MAX_HISTORY_CHARS and len(msgs) > 4:
            dropped = msgs.pop(0)
            total -= len(str(dropped.get("content") or ""))
        return msgs

    async def _save_message(self, ctx: AgentContext, role: str, content, **kw) -> None:
        try:
            if ctx.conversation_id:
                await self.s.store.add_message(ctx.conversation_id, role, content, **kw)
        except Exception:
            log.exception("No se pudo guardar el mensaje en la BD")

    # --------------------- presupuesto ------------------------------------
    async def _check_budget(self, ctx: AgentContext) -> None:
        b = await self.s.store.get_budget(ctx.user_id)
        cur = b.get("currency") or "USD"
        if b.get("per_task") is not None and ctx.approvals.get("spent", 0.0) >= float(b["per_task"]):
            raise BudgetExceeded(f"Presupuesto por tarea alcanzado ({b['per_task']} {cur})")
        if b.get("per_day") is not None:
            day = await self.s.usage.day_cost(ctx.user_id)
            if day >= float(b["per_day"]):
                raise BudgetExceeded(f"Presupuesto diario alcanzado ({b['per_day']} {cur})")

    # --------------------- punto de entrada normal ------------------------
    async def run_task(self, ctx: AgentContext, task_text: str, notify=None) -> TaskOutcome:
        provider_name = await self.s.providers.active_name(ctx.user_id)
        provider = await self.s.providers.get(ctx.user_id)
        model = await self.s.store.get_pref(ctx.user_id, f"model:{provider_name}")
        if not model:
            raise ProviderError("No hay modelo seleccionado. Usa /models y luego /model select.",
                                kind="bad_request")
        history_rows = []
        if ctx.conversation_id:
            history_rows = await self.s.store.get_messages(ctx.conversation_id)
        messages = await self.s.prompts.build_messages(ctx.user_id,
                                                       self._history_to_api(history_rows),
                                                       ctx.project)
        return await self._run_loop(ctx, provider, provider_name, model,
                                    messages, task_text, notify)

    # --------------------- punto de entrada multiagente -------------------
    async def run_task_with(self, ctx: AgentContext, provider: LLMProvider,
                            model: str, task_text: str, notify=None) -> TaskOutcome:
        messages = await self.s.prompts.build_messages(ctx.user_id, [], ctx.project)
        return await self._run_loop(ctx, provider,
                                    getattr(provider, "name", "unknown"),
                                    model, messages, task_text, notify,
                                    save_history=False)

    # --------------------- bucle comun ------------------------------------
    async def _run_loop(self, ctx: AgentContext, provider: LLMProvider, provider_name: str,
                        model: str, messages: list[dict], task_text: str,
                        notify=None, save_history: bool = True) -> TaskOutcome:
        outcome = TaskOutcome()
        logs: list[str] = [f"[{time.strftime('%H:%M:%S')}] Tarea iniciada: {task_text[:160]}"]
        ctx.approvals.setdefault("started_at", time.time())
        start = time.monotonic()
        try:
            messages.append({"role": "user", "content": task_text})
            if save_history:
                await self._save_message(ctx, "user", task_text)

            while ctx.steps < ctx.max_steps:
                if ctx.cancel_event.is_set():
                    raise TaskCancelled()
                await self._check_budget(ctx)
                ctx.steps += 1
                res: ChatResult = await provider.chat(
                    messages, model=model, tools=TOOL_SCHEMAS,
                    temperature=_opt(await self.s.store.get_pref(ctx.user_id, "temperature")),
                    top_p=_opt(await self.s.store.get_pref(ctx.user_id, "top_p")),
                    max_tokens=_opt_i(await self.s.store.get_pref(ctx.user_id, "max_tokens")),
                )
                cost = await self.s.usage.record(
                    ctx.user_id, provider_name, model, res.usage,
                    conversation_id=ctx.conversation_id, project_id=ctx.project["id"])
                if cost is not None:
                    outcome.cost_known = True
                    ctx.approvals["spent"] = ctx.approvals.get("spent", 0.0) + cost
                    outcome.cost = ctx.approvals["spent"]
                if res.usage:
                    logs.append(f"[{time.strftime('%H:%M:%S')}] LLM in={res.usage.prompt_tokens} "
                                f"out={res.usage.completion_tokens}")

                if res.tool_calls:
                    messages.append({
                        "role": "assistant", "content": res.content,
                        "tool_calls": [{"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                                       for tc in res.tool_calls]})
                    if save_history:
                        await self._save_message(
                            ctx, "assistant", res.content,
                            tool_calls=[{"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                                        for tc in res.tool_calls])
                    for tc in res.tool_calls:
                        if ctx.cancel_event.is_set():
                            raise TaskCancelled()
                        if tc.name == "git_push":
                            result, meta = await self._handle_push(ctx, tc)
                        elif tc.name == "github_pull_request":
                            result, meta = await self._handle_pr(ctx, tc)
                        else:
                            result, meta = await execute_tool(ctx, tc.name, tc.arguments)
                        outcome.steps.append(StepRecord(ctx.steps, f"tool:{tc.name}",
                                                        result[:200], ok=json_ok(result)))
                        logs.append(f"[{time.strftime('%H:%M:%S')}] {tc.name} "
                                    f"-> {result[:160]}")
                        if ctx.emit:
                            # V4 Web: actividad en vivo (aditivo; Telegram no emite)
                            await ctx.emit({"type": "tool", "step": ctx.steps,
                                            "name": tc.name, "ok": json_ok(result),
                                            "summary": result[:2000]})
                        messages.append({"role": "tool", "tool_call_id": tc.id,
                                         "content": result})
                        if save_history:
                            await self._save_message(ctx, "tool", result,
                                                     tool_call_id=tc.id, name=tc.name)
                        if notify and meta.get("modified"):
                            await notify(f"🔧 Paso {ctx.steps}: {tc.name} aplicado")
                    continue

                messages.append({"role": "assistant", "content": res.content or ""})
                if save_history:
                    await self._save_message(
                        ctx, "assistant", res.content,
                        tokens_in=(res.usage.prompt_tokens if res.usage else 0),
                        tokens_out=(res.usage.completion_tokens if res.usage else 0),
                        cost=cost or 0.0)
                outcome.summary = res.content or "(sin contenido)"
                break
            else:
                outcome.summary = ("Se alcanzo el limite de pasos sin respuesta final. "
                                   "Puedes reintentar con /task retry o subir el limite.")
                if ctx.emit and any(p["status"] in ("pending", "in_progress") for p in ctx.plan):
                    await ctx.emit({"type": "plan_incomplete",
                                    "note": "L\u00edmite de pasos alcanzado con pasos pendientes: "
                                            "no se marcan como completados."})
        except TaskCancelled:
            outcome.cancelled = True
            outcome.summary = "Tarea cancelada por el usuario."
        except ApprovalTimeout as e:
            outcome.error = str(e)
            outcome.summary = f"Accion pendiente sin autorizar: {e}"
        except ApprovalDenied as e:
            outcome.error = str(e)
            outcome.summary = f"Accion rechazada por el usuario: {e}"
        except BudgetExceeded as e:
            outcome.error = str(e)
            outcome.summary = str(e)
        except NoApiKey as e:
            outcome.error = str(e)
            outcome.summary = e.user_message
        except ProviderError as e:
            outcome.error = str(e)
            outcome.summary = e.user_message
        finally:
            outcome.files_touched = list(ctx.files_touched)
            outcome.commands = list(ctx.commands_run)
            cost_str = f"{outcome.cost:.4f}" if outcome.cost_known else "n/d"
            logs.append(f"[{time.strftime('%H:%M:%S')}] Fin en {time.monotonic() - start:.1f}s, "
                        f"{ctx.steps} pasos, coste={cost_str}")
            if ctx.task_id:
                await self.s.store.kv_set(f"tasklog:{ctx.task_id}", logs, ttl_s=7 * 86400)
        return outcome

    # --------------------- push / PR con autorizacion ----------------------
    def _notify_approval(self, ctx: AgentContext):
        async def _n(info: dict):
            if ctx.notify:
                await ctx.notify(
                    f"🔐 AUTORIZACION REQUERIDA\nAccion: {info['action']}\n{info['detail']}\n\n"
                    "Aprueba o rechaza con los botones (expira en 10 min).")
        return _n

    async def _handle_push(self, ctx: AgentContext, tc):
        args = _args(tc.arguments)
        branch = args.get("branch") or await self.s.broker.current_branch(ctx.project)
        detail = f"Proyecto: {ctx.project['name']}\nRama: {branch}"
        try:
            verdict = await self.approvals.request("git_push", detail,
                                                   self._notify_approval(ctx), ctx.user_id)
        except ApprovalTimeout as e:
            return _j({"ok": False, "error": str(e)}), {}
        if not verdict.get("approved"):
            return _j({"ok": False, "error": "El usuario RECHAZO el push"}), {}
        try:
            msg = await self.s.broker.push(ctx.project, branch, authorized=True)
            return _j({"ok": True, "result": msg}), {}
        except Exception as e:
            return _j({"ok": False, "error": str(e)[:400]}), {}

    async def _handle_pr(self, ctx: AgentContext, tc):
        args = _args(tc.arguments)
        state = await self.s.store.get_git_state(ctx.project["id"])
        if not state.get("repo_url"):
            return _j({"ok": False, "error": "Sin repositorio conectado (/repo add)"}), {}
        full = state["repo_url"].replace("https://github.com/", "").removesuffix(".git")
        head = args.get("head") or state.get("current_branch") or "main"
        base = args.get("base") or state.get("default_branch") or "main"
        try:
            verdict = await self.approvals.request(
                "github_pull_request",
                f"Repo: {full}\nhead: {head} -> base: {base}\nTitulo: {args.get('title', '')}",
                self._notify_approval(ctx), ctx.user_id)
        except ApprovalTimeout as e:
            return _j({"ok": False, "error": str(e)}), {}
        if not verdict.get("approved"):
            return _j({"ok": False, "error": "El usuario RECHAZO crear el PR"}), {}
        try:
            pr = await self.s.github.create_pull_request(
                full, title=args.get("title", "PR desde HJ Code Agent"),
                head=head, base=base, body=args.get("body", ""))
            return _j({"ok": True, "result": pr.get("html_url", "")}), {}
        except Exception as e:
            return _j({"ok": False, "error": str(e)[:400]}), {}


def _args(raw: str | None) -> dict:
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}


def _j(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False)


def json_ok(result: str) -> bool:
    try:
        return bool(json.loads(result).get("ok"))
    except (json.JSONDecodeError, AttributeError):
        return False


def _opt(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def _opt_i(v):
    try:
        return None if v in (None, "") else int(v)
    except (TypeError, ValueError):
        return None
