"""API de autenticacion web: login, logout, sesion actual."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..auth import (SESSION_COOKIE, clear_session_cookie, create_session,
                    delete_session, get_session, get_web_user_by_name,
                    set_session_cookie, verify_password)
from ..deps import login_limiter, require_auth

router = APIRouter(prefix="/api/auth", tags=["auth"])

MAX_LOGIN_LEN = 200


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=MAX_LOGIN_LEN)
    password: str = Field(min_length=1, max_length=MAX_LOGIN_LEN)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response):
    ctx = request.app.state.ctx
    ip = _client_ip(request)
    limiter = request.app.state.login_limiter
    # 5 intentos por minuto por IP (y por usuario) contra fuerza bruta
    if not limiter.allow(f"ip:{ip}", 5) or not limiter.allow(f"u:{body.username.lower()}", 5):
        await asyncio.sleep(0.5)
        raise HTTPException(status_code=429, detail="Demasiados intentos; espera un minuto")
    user = await get_web_user_by_name(ctx.store, body.username)
    stored = user["password_hash"] if user else ""
    ok = verify_password(body.password, stored) if stored else False
    if not ok:
        # tiempo constante aproximado incluso sin usuario
        if not stored:
            verify_password(body.password, "scrypt$16384$8$1$00$00")
        await ctx.store.audit(0, "web.login_failed", f"{body.username[:60]} ip={ip}")
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    token, csrf = await create_session(
        ctx.store, user["id"], ip=ip,
        ua=request.headers.get("user-agent", "")[:200],
        ttl_h=int(ctx.settings.web_session_ttl_h))
    set_session_cookie(response, token, ctx.settings)
    await ctx.store.audit(user["agent_uid"] or 0, "web.login",
                          f"{user['username']} ip={ip}")
    return {"ok": True, "username": user["username"],
            "agent_uid": user["agent_uid"], "csrf_token": csrf}


@router.post("/logout")
async def logout(request: Request, response: Response, auth=Depends(require_auth)):
    token = request.cookies.get(SESSION_COOKIE, "")
    if token:
        await delete_session(auth.store, token)
    clear_session_cookie(response)
    await auth.store.audit(auth.agent_uid, "web.logout", auth.username)
    return {"ok": True}


@router.get("/me")
async def me(auth=Depends(require_auth)):
    return {"username": auth.username, "agent_uid": auth.agent_uid,
            "is_admin": bool(auth.web_user["is_admin"]),
            "csrf_token": auth.session["csrf_token"],
            "expires_at": auth.session["expires_at"]}
