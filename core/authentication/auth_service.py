"""Autorizacion de usuarios de Telegram.

- Solo user_id autorizados pueden usar el bot (acceso privado por defecto).
- Los admins vienen de HJ_ADMIN_USER_IDS y quedan sembrados al arrancar.
- La decision de autorizacion es una capa de software, nunca algo que el
  modelo pueda cambiar.
"""
from __future__ import annotations

from ..storage.repositories import Store


class AuthService:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def register(self, tid: int, username: str = "", first_name: str = "") -> dict:
        user = await self.store.get_user(tid)
        if user:
            if username or first_name:
                await self.store.upsert_user(tid, username, first_name,
                                             bool(user["is_admin"]), bool(user["allowed"]))
            return await self.store.get_user(tid)
        return await self.store.upsert_user(tid, username, first_name, False, False)

    async def is_allowed(self, tid: int) -> bool:
        user = await self.store.get_user(tid)
        return bool(user and (user["allowed"] or user["is_admin"]))

    async def is_admin(self, tid: int) -> bool:
        user = await self.store.get_user(tid)
        return bool(user and user["is_admin"])

    async def authorize(self, tid: int, *, admin: bool = False) -> None:
        await self.store.upsert_user(tid, is_admin=admin, allowed=True)

    async def revoke(self, tid: int) -> None:
        user = await self.store.get_user(tid)
        if user and user["is_admin"]:
            raise PermissionError("No se puede revocar a un administrador")
        await self.store.set_allowed(tid, False)
