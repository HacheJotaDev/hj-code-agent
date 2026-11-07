"""Fabrica de la app FastAPI del panel web V4.

- Construye el AppContext del motor V3 (BD, boveda, proveedores, proyectos,
  engine) y arranca la WebTaskQueue dentro del mismo proceso.
- El servicio web es INDEPENDIENTE del bot de Telegram: no importa aiogram ni
  toca el socket del bot; ambos pueden convivir en el mismo VPS y la misma BD.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.config import Settings, load_settings

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # ---- arranque: motor V3 + cola web ------------------------------
        from core.app import build_context
        from .auth import bootstrap_web_user, purge_sessions
        from .events import TaskEventHub
        from .queue_web import WebTaskQueue

        ctx = await build_context(s)
        await bootstrap_web_user(s, ctx.store)
        await purge_sessions(ctx.store)
        # Limpieza de eventos antiguos (historial de 7 dias)
        await ctx.store.db.execute(
            "DELETE FROM task_events WHERE created_at < datetime('now', '-7 days')")
        # Proveedor y modelo por defecto SOLO si el usuario no eligio uno
        # (active_name() sin preferencia devolveria el primer proveedor por
        # orden alfabetico, p.ej. 'anthropic', y no el principal del despliegue)
        uid = int(s.web_agent_uid or 0) or (s.admin_user_ids[0] if s.admin_user_ids else 0)
        if uid and not await ctx.store.get_pref(uid, "active_provider"):
            await ctx.store.set_pref(uid, "active_provider", "deepseek")
        if uid and not await ctx.store.get_pref(uid, "model:deepseek"):
            await ctx.store.set_pref(uid, "model:deepseek", s.web_default_model)
            log.info("V4 web: proveedor/modelo por defecto prefijados para uid %s", uid)

        hub = TaskEventHub(ctx.store)
        queue = WebTaskQueue(ctx, hub)
        ctx.queue = queue
        ctx.hub = hub
        await queue.start()
        app.state.ctx = ctx
        app.state.hub = hub
        log.info("V4 web: motor y cola listos (db=%s)", s.db_file)
        yield
        # ---- parada ordenada --------------------------------------------
        await queue.stop()
        await ctx.db.close()
        log.info("V4 web: backend detenido limpiamente")

    app = FastAPI(title="HacheCode Agent V4 (web)", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    # CORS solo si se configura FRONTEND_ORIGIN (sin proxy se necesita;
    # con proxy /api/* de Next.js las peticiones son same-origin)
    if s.frontend_origin:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[s.frontend_origin.rstrip("/")],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["*"],
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if request.url.path.startswith("/api"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        msg = f"Datos invalidos: {first.get('msg', 'error de validacion')}"
        return JSONResponse(status_code=422, content={"detail": msg})

    from .auth import RateLimiter
    app.state.login_limiter = RateLimiter()   # nueva instancia por app (aislada)
    app.state.api_limiter = RateLimiter()

    @app.get("/api/health")
    async def health():
        from core.sandbox.factory import docker_host_authorized
        ctx = app.state.ctx
        return {"ok": True, "service": "hj-code-agent-web", "uptime_s": ctx.uptime_s(),
                "docker_host_authorized": docker_host_authorized(ctx.settings),
                "sandbox_backend": ctx.settings.sandbox_backend}

    from .routers import auth as r_auth
    from .routers import chat as r_chat
    from .routers import execrun as r_exec
    from .routers import gitops as r_git
    from .routers import models as r_models
    from .routers import projects as r_projects
    from .routers import usage as r_usage

    app.include_router(r_auth.router)
    app.include_router(r_projects.router)
    app.include_router(r_chat.router)
    app.include_router(r_models.router)
    app.include_router(r_git.router)
    app.include_router(r_exec.router)
    app.include_router(r_usage.router)

    return app


def main() -> None:
    """Entrada del servicio: python -m backend (tras instalar dependencias)."""
    import uvicorn

    from core.config import load_settings

    s = load_settings()
    logging.basicConfig(
        level=getattr(logging, s.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        filename=str(s.log_file) if s.log_file else None)
    app = create_app(s)
    uvicorn.run(app, host=s.web_host, port=int(s.web_port), log_level="info")


if __name__ == "__main__":
    main()
