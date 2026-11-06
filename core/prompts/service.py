"""REGLA FUNDAMENTAL: sin system prompt por defecto.

- Modo NATIVO (predeterminado): no se envia ningun rol "system"/"developer".
  Las herramientas se declaran por el mecanismo nativo de function calling.
- Modo PERSONALIZADO: el usuario define su propio system prompt.
- Modo POR PROYECTO: cada proyecto puede tener su prompt, activable al entrar.

Este servicio es la UNICA fuente de system prompts de la aplicacion. El motor
de agente y el chat llaman a build_messages(); ningun otro modulo inyecta
instrucciones ocultas.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..storage.repositories import Store


@dataclass
class EffectivePrompt:
    mode: str                  # native | custom | project
    content: str | None        # None => no enviar system
    source: str = ""           # de donde viene (usuario / proyecto)


class PromptMode:
    NATIVE = "native"
    CUSTOM = "custom"
    PROJECT = "project"


class PromptService:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def status(self, user_id: int, project: dict | None = None) -> EffectivePrompt:
        """Estado actual: el modo nativo no genera contenido.

        Precedencia: si el proyecto activo tiene su prompt habilitado
        (/system project on), se usa el del proyecto; si no, el modo del
        usuario (custom) o nativo. Nunca hay contenido si no lo configuro el
        usuario explicitamente.
        """
        if project and project.get("prompt_enabled") and project.get("system_prompt"):
            return EffectivePrompt(PromptMode.PROJECT, project["system_prompt"],
                                   f"proyecto:{project['name']}")
        row = await self.store.get_system_prompt(user_id)
        mode = row["mode"] if row else PromptMode.NATIVE
        content = row["content"] if row else None
        if mode == PromptMode.CUSTOM and content:
            return EffectivePrompt(PromptMode.CUSTOM, content, "usuario")
        if mode == PromptMode.PROJECT:
            # el modo project sin proyecto valido cae a nativo (nada oculto)
            return EffectivePrompt(PromptMode.NATIVE, None, "")
        return EffectivePrompt(PromptMode.NATIVE, None, "")

    async def build_messages(self, user_id: int, history: list[dict],
                             project: dict | None = None,
                             extra_user: str | None = None) -> list[dict]:
        """Construye la lista de mensajes para la API.

        En modo nativo devuelve EXACTAMENTE el historial (+ mensaje extra),
        sin ningun rol system. Nunca se anade nada oculto.
        """
        eff = await self.status(user_id, project)
        messages: list[dict] = []
        if eff.content:
            # Solo el prompt explicitamente configurado por el usuario
            messages.append({"role": "system", "content": eff.content})
        messages.extend(history)
        if extra_user is not None:
            messages.append({"role": "user", "content": extra_user})
        return messages

    # ---------------- operaciones /system ---------------------------------
    async def set_custom(self, user_id: int, content: str) -> None:
        await self.store.set_system_prompt(user_id, content, PromptMode.CUSTOM)

    async def set_mode(self, user_id: int, mode: str) -> None:
        await self.store.set_prompt_mode(user_id, mode)

    async def show(self, user_id: int) -> tuple[str, str | None]:
        row = await self.store.get_system_prompt(user_id)
        if not row:
            return PromptMode.NATIVE, None
        return row["mode"], row["content"]

    async def clear(self, user_id: int) -> None:
        await self.store.clear_system_prompt(user_id)

    async def reset(self, user_id: int) -> None:
        """Volver al modo nativo: borra prompt y modo."""
        await self.store.clear_system_prompt(user_id)

    async def export(self, user_id: int) -> dict:
        row = await self.store.get_system_prompt(user_id)
        if not row:
            return {"mode": PromptMode.NATIVE, "content": None}
        return {"mode": row["mode"], "content": row["content"]}

    async def import_prompt(self, user_id: int, data: dict) -> None:
        mode = data.get("mode", PromptMode.CUSTOM)
        content = data.get("content")
        if mode == PromptMode.NATIVE or not content:
            await self.store.clear_system_prompt(user_id)
            return
        await self.store.set_system_prompt(user_id, str(content),
                                           PromptMode.CUSTOM if mode != PromptMode.PROJECT else mode)
