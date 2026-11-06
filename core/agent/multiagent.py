"""Modo multiagente OPCIONAL (desactivado por defecto).

Pipeline secuencial de perfiles configurados por el usuario (programador,
revisor, tester...). Cada perfil puede tener su propio proveedor/modelo y su
propio prompt EXPLICITO configurado por el usuario. Si un perfil no tiene
prompt, corre en modo nativo: nunca se inyectan roles ocultos.
"""
from __future__ import annotations

import asyncio
import json
import time

from .engine import TaskCancelled, BudgetExceeded


class MultiAgentRunner:
    def __init__(self, services) -> None:
        self.s = services

    async def enabled(self, user_id: int) -> bool:
        return bool(await self.s.store.get_pref(user_id, "agents_enabled"))

    async def run_pipeline(self, ctx, task_text: str, notify=None) -> dict:
        profiles = [p for p in await self.s.store.list_agents(ctx.user_id) if p["enabled"]]
        if not profiles:
            return {"summary": "No hay perfiles de agentes configurados (/agents add).",
                    "phases": []}
        phases: list[dict] = []
        context_text = task_text
        for prof in profiles:
            if ctx.cancel_event.is_set():
                break
            if notify:
                await notify(f"🤖 Fase '{prof['name']}' ({prof['role']}) iniciada")
            # Cada fase es una ejecucion del motor con su modelo/prompt de perfil
            provider_name = prof.get("provider") or await self.s.providers.active_name(ctx.user_id)
            provider = await self.s.providers.get(ctx.user_id, provider_name)
            model = prof.get("model") or await self.s.store.get_pref(ctx.user_id, f"model:{provider_name}")
            task_for_phase = context_text
            if prof.get("prompt"):
                # prompt EXPLICITO del perfil (configurado por el usuario, visible)
                task_for_phase = f"[Instrucciones del rol '{prof['name']}' ({prof['role']})]\n{prof['prompt']}\n\n[Tarea]\n{context_text}"
            outcome = await self.s.engine.run_task_with(ctx, provider, model, task_for_phase,
                                                        notify=notify)
            phases.append({"phase": prof["name"], "role": prof["role"], "model": model,
                           "summary": outcome.summary[:1500],
                           "files": outcome.files_touched, "cost": outcome.cost,
                           "cost_known": outcome.cost_known,
                           "cancelled": outcome.cancelled, "error": outcome.error})
            context_text = (f"Tarea original:\n{task_text}\n\n"
                            f"Resultado de la fase anterior ({prof['role']}):\n{outcome.summary[:4000]}")
        final = phases[-1]["summary"] if phases else ""
        return {"summary": final, "phases": phases}
