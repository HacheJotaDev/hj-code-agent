"""Verificacion central de permisos para acciones delicadas.

Las acciones administrativas nunca se ejecutan por instruccion del modelo:
siempre pasan por aqui y por el flujo humano correspondiente.
"""
from __future__ import annotations

from ..storage.repositories import Store


class PermissionDenied(Exception):
    pass


ADMIN_ACTIONS = {"admin", "authorize", "revoke", "config_import", "restore", "users",
                 "security", "audit", "diagnostics", "provider_remove", "provider_add"}

CONFIRM_ACTIONS = {"project_delete", "push", "pr", "restore", "sandbox_reset"}


class Authorizer:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def require_admin(self, user_id: int) -> None:
        user = await self.store.get_user(user_id)
        if not user or not user["is_admin"]:
            raise PermissionDenied("Accion reservada a administradores")

    async def require_allowed(self, user_id: int) -> None:
        user = await self.store.get_user(user_id)
        if not user or not (user["allowed"] or user["is_admin"]):
            raise PermissionDenied("Usuario no autorizado")

    async def check(self, user_id: int, action: str) -> None:
        await self.require_allowed(user_id)
        if action in ADMIN_ACTIONS:
            await self.require_admin(user_id)

    @staticmethod
    def require_confirmation(confirmed: bool, action: str) -> None:
        if action in CONFIRM_ACTIONS and not confirmed:
            raise PermissionDenied(f"Accion '{action}' requiere confirmacion explicita")
