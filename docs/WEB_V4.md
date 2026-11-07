# HacheCode Agent V4 — Panel Web (arquitectura)

V4 transforma la interfaz de Telegram en una plataforma web profesional,
**reutilizando íntegramente el motor V3**. No es un agente nuevo: es el mismo
motor (`core/`), la misma base de datos y el mismo sandbox Docker rootless,
con una interfaz nueva.

```
┌────────────────────────┐        ┌─────────────────────────────────────┐
│  VERCEL (solo UI)      │        │  VPS CONTABO (motor)                │
│                        │        │                                     │
│  frontend/ (Next.js)   │  /api/*│  hj-code-agent-web (systemd, :8900) │
│  - App Router + TS     │ ──────►│  backend/ (FastAPI)                 │
│  - Tailwind 4          │ rewrite│   ├─ auth: sesiones+CSRF+scrypt     │
│  - Monaco Editor       │        │   ├─ routers: proyectos, archivos,  │
│  - SSE con reconexión  │        │   │   chat, tareas, modelos, git,   │
│                        │        │   │   exec, uso/presupuestos        │
│  El navegador NUNCA    │        │   └─ WebTaskQueue (hereda TaskQueue)│
│  habla con Docker ni   │        │       └─ AgentEngine V3 (core/)     │
│  con la BD.            │        │  core/ (SIN CAMBIOS estructurales)  │
└────────────────────────┘        │  sandbox Docker rootless (hjcode)   │
                                  │  bot Telegram V3 sigue funcionando  │
                                  └─────────────────────────────────────┘
```

## Reutilización del motor (lo que NO se reescribió)

| Módulo V3 | Uso en V4 |
|---|---|
| `core/agent/engine.py` | Bucle de agente con herramientas nativas (añadido `emit` opcional para eventos web) |
| `core/tasks/queue.py` | Cola durable en SQLite; `backend/queue_web.WebTaskQueue` hereda y sustituye SOLO la notificación (Telegram → SSE) |
| `core/storage/*` | Misma BD, mismos repositorios; migración `0002_web.sql` (aditiva) |
| `core/projects/*` | Proyectos, ZIP seguro (zip-slip, bombas, symlinks) |
| `core/sandbox/*` | Política estricta de Docker rootless (`HJ_DOCKER_HOST`, jamás el daemon principal) |
| `core/providers/*` | DeepSeek y compatibles, bóveda cifrada, catálogo real de modelos |
| `core/github/*` | Broker con token efímero (nunca en el contenedor) |
| `security/*` | `command_guard` y `path_guard` en todo acceso |
| `bot/` | **Intacto.** El bot de Telegram sigue corriendo en paralelo |

## Cambios aditivos en core (compatibles con la V3)

1. `core/tools/context.py`: campos `emit` (eventos web) y `plan` — opcionales, Telegram no los usa.
2. `core/tools/registry.py`: herramienta `update_plan` — el MODELO declara su plan de trabajo; la UI jamás inventa estados.
3. `core/agent/engine.py`: emite eventos de herramienta si `ctx.emit` existe.
4. `core/config/settings.py`: settings `HJ_WEB_*`.
5. `core/projects/manager.py`: bug latente corregido — `_run_git` no esperaba el proceso (`returncode=None`), con lo que `git init`/config/git_state no se aplicaban al crear proyectos.
6. `database/migrations/0002_web.sql`: tablas `web_users`, `web_sessions`, `task_events`.

## Seguridad

- **Autenticación**: usuario web único (bootstrap con `HJ_WEB_USERNAME`/`HJ_WEB_PASSWORD`), scrypt+salt, sesiones server-side (solo SHA-256 del token en BD), cookie `HttpOnly` + `SameSite=Strict` + `Secure` fuera de localhost.
- **CSRF**: token por sesión, cabecera `X-CSRF-Token` obligatoria en POST/PUT/PATCH/DELETE.
- **Rate limiting**: 5 logins/min por IP y usuario; 240 peticiones/min por sesión.
- **Autorización por proyecto**: todo endpoint filtra por `agent_uid` (el UID de Telegram del propietario); proyectos ajenos → 404.
- **Sandbox**: el navegador solo envía un comando shell; `command_guard` lo filtra y la fábrica V3 elige el backend. Sin `HJ_DOCKER_HOST` rootless → no se ejecuta nada (fail-safe).
- **Push GitHub**: dos pasos (`push-request` muestra repo/rama/commits + token efímero 10 min de un solo uso → `push-confirm` → broker con token efímero, jamás en URLs/logs).
- **Archivos**: `PathGuard` contra path traversal; ZIP con límites anti-bomba; sin symlinks.
- **Cabeceras**: `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Cache-Control: no-store` en /api.

## Flujo de una tarea (tiempo real)

1. `POST /api/conversations/{id}/messages` → valida modelo contra el catálogo REAL del proveedor → encola en SQLite.
2. `WebTaskQueue` reclama atómicamente (1 tarea por usuario), crea sandbox y ejecuta `AgentEngine`.
3. Cada llamada a herramientas genera evento persistido en `task_events` (plan, tool, notify, status).
4. El navegador consume `GET /api/tasks/{id}/stream` (SSE). Reconexión con `Last-Event-ID` → replay desde la BD. Si cierras Chrome, la tarea sigue; al volver, el progreso se recupera.
5. Estados finales: `done | failed | cancelled | interrupted`. El límite de pasos NUNCA finge completitud: se emite `plan_incomplete` y los pasos quedan pendientes; `POST /tasks/{id}/retry` continúa desde el estado real.
