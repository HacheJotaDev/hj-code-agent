"""Dependencias FastAPI compartidas por los routers web."""
from __future__ import annotations

import hmac

from fastapi import HTTPException, Request

from .auth import (AuthedRequest, SESSION_COOKIE, UNSAFE_METHODS, RateLimiter,
                   get_session)

# Limitadores globales del proceso (instalados por create_app en app.state)
login_limiter = RateLimiter()
api_limiter = RateLimiter()


def get_ctx(request: Request):
    ctx = getattr(request.app.state, "ctx", None)
    if ctx is None:
        raise HTTPException(status_code=503, detail="El motor aun esta arrancando")
    return ctx


async def require_auth(request: Request) -> AuthedRequest:
    """Sesion valida + CSRF en metodos no seguros + rate limit por sesion."""
    ctx = get_ctx(request)
    token = request.cookies.get(SESSION_COOKIE, "")
    sess = await get_session(ctx.store, token)
    if not sess:
        raise HTTPException(status_code=401, detail="Sesion no valida")
    if request.method in UNSAFE_METHODS:
        sent = request.headers.get("x-csrf-token", "")
        if not sent or not hmac.compare_digest(sent, sess["csrf_token"]):
            raise HTTPException(status_code=403, detail="Token CSRF invalido o ausente")
    lim = getattr(request.app.state, "api_limiter", None)
    if lim is not None:
        per_min = int(getattr(ctx.settings, "web_rate_limit_per_min", 240))
        if not lim.allow(f"sess:{sess['token_hash'][:16]}", per_min):
            raise HTTPException(status_code=429, detail="Demasiadas peticiones")
    urow = await ctx.store.db.one(
        "SELECT * FROM web_users WHERE id=?", (sess["web_user_id"],))
    if not urow:
        raise HTTPException(status_code=401, detail="Usuario web eliminado")
    web_user = dict(urow)
    return AuthedRequest(store=ctx.store, settings=ctx.settings, ctx=ctx,
                         web_user=web_user, session=sess,
                         agent_uid=int(web_user["agent_uid"] or 0))
