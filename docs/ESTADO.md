# Estado del proyecto — implementado / verificado / pendiente

Leyenda: ✅ implementado · 🧪 implementado + prueba automatizada · ⏳ pendiente

## Núcleo (versión funcional prioritaria)
| Función | Estado | Dónde |
|---|---|---|
| Bot Telegram aiogram 3, long polling, menú inline con estado | ✅ | `bot/` |
| Acceso privado por user_id + admins | 🧪 | `core/authentication`, `tests/test_auth.py` |
| Sin system prompt por defecto (modo nativo) | 🧪 | `core/prompts`, `tests/test_no_default_system_prompt.py` |
| Modos custom/proyecto + /system set·edit·show·off·clear·reset·export·import·project | ✅ | `bot/handlers/system_prompt.py` |
| Adaptador DeepSeek real (/chat/completions, /models, /user/balance) | 🧪 | `core/providers/deepseek.py`, `tests/test_providers_models.py`, `tests/test_balance.py` |
| Adaptadores OpenAI-compat y Anthropic (GLM, OpenRouter, Ollama…) | 🧪 | `core/providers/*`, `tests/test_providers_models.py` |
| /provider·/providers·add·select·remove·/setapi·/testapi·/models·/model·parámetros | ✅ | `bot/handlers/providers.py` |
| Formulario seguro de un solo uso para API keys (loopback + túnel SSH) | ✅ | `bot/formserver.py` |
| Saldo real, tokens por llamada, costes estimados, presupuestos, alertas | 🧪 | `core/billing`, `tests/test_balance_usage_cost.py` |
| Agente: 21 herramientas reales con validación estricta | 🧪 | `core/tools`, `tests/test_tools_fs.py` |
| Bucle del agente con límites de pasos, cancelación y presupuesto | 🧪 | `core/agent/engine.py`, `tests/test_agent_loop.py` |
| Sandbox local con rlimits (dev) | 🧪 | `tests/test_sandbox_local.py` |
| Sandbox Docker endurecido (cap-drop ALL, no-new-privileges, límites, red) | 🧪 | `core/sandbox/docker_sandbox.py`, `tests/test_sandbox_docker.py` (flags; ejecución real requiere Docker) |
| ZIP seguro (traversal, symlinks, bombas, límites) | 🧪 | `core/projects/ziputils.py`, `tests/test_zip_safety.py` |
| Path guard anti-escape | 🧪 | `tests/test_path_guard.py` |
| Env del sandbox sin secretos | 🧪 | `security/command_guard.py`, `tests/test_isolation.py` |
| GitHub: clone/branch/commit/diff/status; push SOLO con botón; PR autorizado | 🧪 | `core/github`, `tests/test_github_flow.py` |
| Autopush OFF por defecto + ramas permitidas | 🧪 | `tests/test_github_flow.py` |
| Cola durable, /task stop·retry·status, recuperación tras reinicio | 🧪 | `core/tasks/queue.py`, `tests/test_tasks_queue.py` |
| Conversaciones persistentes + export/search | 🧪 | `tests/test_persistence.py` |
| Subida de archivos/ZIP desde Telegram con límites | ✅ | `bot/handlers/projects.py` |
| **Asistente por consola**: pide token del bot (oculto) y admin user_id; solo ese ID recibe respuestas; genera clave maestra y `.env` 0600 | 🧪 | `scripts/setup.py`, `scripts/install.sh` (paso 5), `tests/test_setup_console.py` |
| Silencio total ante IDs no autorizados (`HJ_SILENT_REJECT=1`) / aviso único (defecto) | 🧪 | `bot/middlewares/auth.py`, `tests/test_auth.py` |
| Instalación por etapas, update, uninstall, backup/restore, systemd | ✅ | `scripts/` |
| Dockerfile + compose (sin tocar otros servicios) | ✅ | raíz |
| **Publicado en GitHub**: https://github.com/HacheJotaDev/hj-code-agent (push real, rama `main`) | ✅ | remoto |

## Administración y extras
| Función | Estado |
|---|---|
| /admin·/users·/authorize·/revoke·/security·/audit·/diagnostics·/notifications | ✅ |
| /config export/import (sin secretos) | ✅ |
| Menú principal con paginación/edición de mensajes | ✅ |
| Streaming de chat | ✅ (cliente SSE implementado; Telegram muestra el resultado final) |
| Multiagente (coordinador/programador/revisor/tester) opcional | ✅ (pipeline secuencial; desactivado por defecto) |
| /memory (notas de usuario, NO inyectadas al modelo) | ✅ |
| /agents models·status·config | ✅ |

## Pendiente / mejoras futuras (declaradas expresamente)
- ⏳ Streaming token-a-token editando el mensaje de Telegram (hoy: resultado
  final; el cliente SSE existe y `on_delta` está listo para paginar ediciones).
- ⏳ Ejecución de pruebas del catálogo de modelos contra APIs reales con
  credenciales del usuario (la suite usa mocks HTTP por diseño; la integración
  real se valida con /testapi desde Telegram).
- ⏳ Token counting preciso por proveedor (estimación chars/4 en /context).
- ⏳ Sandboxes en máquina separada (documentado en docs/SECURITY.md).
- ⏳ Webhooks de GitHub (hoy: pull manual y /history).
- ⏳ /system project con múltiples prompts por proyecto guardados (hoy: 1).

## Resultados de la suite V3 (noviembre 2026)

**169 pruebas automatizadas: 168 pasan, 0 fallan, 1 omitida.**
La omitida es `tests/test_sandbox_docker.py` (requiere un daemon Docker real;
este entorno de CI no lo tiene — se valida en el VPS).

### Revisión del VPS (bugs 1-4 de la segunda auditoría) — `tests/test_update_safety.py`

14 pruebas nuevas. **Verificación doble: con el código antiguo fallan 10/14
(los bugs reales); con el actual pasan 14/14.**

| Bug | Corrección | Prueba |
|---|---|---|
| 1. update.sh forzaba usuario `hjagent` (el servicio real corre como `hjcode`) → riesgo de perder acceso a SQLite/boveda/proyectos | Detecta el usuario EFECTIVO con `systemctl show -p User`; sin usuario no-root no toca permisos; chown solo si el propietario difiere; no crea usuarios; rollback restaura propietarios originales | 🧪 4 tests |
| 2. Sin `HJ_DOCKER_HOST` la CLI docker caía en el daemon PRINCIPAL del host | La fábrica no invoca docker sin host rootless autorizado; sockets `/var/run/docker.sock` y `/run/docker.sock` rechazados; defensa en profundidad en `sandbox_kind` | 🧪 4 tests |
| 3. El sandbox montaba la raíz GENERAL de workspaces (todos los proyectos) | `resolve_host_workspace()` devuelve el workspace EXACTO del proyecto (con traducción de ruta opcional conservando la subruta); `chown` interno solo si 1000:1000 no puede escribir | 🧪 4 tests |
| 4. Backup de SQLite con el bot escribiendo + rollback sin restaurar datos/permisos | Stop ANTES del backup → checkpoint WAL (`scripts/db_tools.py`) → integrity_check → tar; rollback completo (código, deps, datos, .env, propietarios, servicio) con rollback en cada paso destructivo | 🧪 2 tests + 4 de script |

### Revisión final del actualizador (fallo tras stop, migración parcial, HJ_DB_PATH)

Nueve pruebas nuevas (6 e2e + 3 estáticas). **Verificación doble: con el
script antiguo fallan 5/5 rápidas y la sexta SE CUELGA (bug real de
producción); con el actual pasan 9/9.**

| Fallo | Corrección | Prueba |
|---|---|---|
| Un `tar`/`checkpoint` fallido tras `systemctl stop` dejaba el bot PARADO (`die()` y `set -e` sin reiniciar) | `trap ERR` + `set -E` como red de seguridad y `\|\| rollback` en checkpoint, integridad y los tres tars del backup: el servicio anterior SIEMPRE rearraanca | 🧪 2 e2e + 1 estática |
| `MIGRATED=1` se marcaba AL FINAL: una migración parcial dejaba datos modificados sin restaurar | `MIGRATED=1` ANTES de `db.migrate()`; copia fiel de la BD (sin `-wal`/`-shm`) en el backup; restauración exacta por swap con conservación de la data descartada; integridad POST-migración | 🧪 2 e2e + 1 estática |
| Cuelgue real: si `db.migrate()` explotaba, la conexión aiosqlite sin cerrar dejaba el proceso COLGADO (hilo no-daemon) y el rollback jamás corría | El heredoc cierra la BD en `finally` y sale 1 ante cualquier error | 🧪 1 e2e (el antiguo no salta en 40 s) |
| `HJ_DB_PATH` del `.env`/entorno se ignoraba: se migraba `data/hj.db` aunque el bot usara otra base | Resolución en el MISMO orden que el bot (entorno > unidad systemd > .env > default); checkpoint/backup/migración/restauración sobre ESA ruta aunque sea externa a `data/` | 🧪 2 e2e + 1 estática |

Los e2e (`tests/test_update_e2e.py`) ejecutan el `update.sh` REAL contra una
instalación falsa pero fiel: `systemctl`/`journalctl`/`id`/`tar` simulados
con registro de acciones, SQLite real con el esquema `0001`, `pip`
simulado y migraciones inyectadas (99998 escribe y compromete + 99999 con
SQL inválido) para reproducir el fallo parcial de `db.migrate()`.

### Pruebas 1-14 del encargo (integración con dispatcher REAL de aiogram)
`tests/test_v3_flows.py`: **14/14 pasan**. Simulan updates de Telegram
completos (mensaje, documento, callback) que atraviesan middlewares,
routers y servicios reales; los mocks son solo de red (Telegram HTTP y LLM).

| # | Flujo | Estado |
|---|---|---|
| 1 | Primera ejecución: /start responde con menú V3, HTML válido | 🧪 |
| 2 | Proveedor/modelo seleccionables, respuesta real del LLM, preferencia persistida | 🧪 (LLM simulado) |
| 3 | Chat sin proyecto: responde y NO crea proyectos | 🧪 |
| 4 | /newproject crea y selecciona el proyecto | 🧪 |
| 5 | /projects con 0, 1 y varios proyectos | 🧪 |
| 6 | ZIP recibido SIN GitHub: workspace creado, raíz única aplanada, resumen con puntos de entrada | 🧪 |
| 7 | Petición en lenguaje natural → tarea con herramientas → archivo REAL creado | 🧪 |
| 8 | run_tests en sandbox: salida REAL de pytest incluida como evidencia en el resumen | 🧪 (sandbox local; Docker en VPS) |
| 9 | /export devuelve el ZIP del proyecto | 🧪 |
| 10 | GitHub opcional: todo funciona sin token; push exige autorización | 🧪 |
| 11 | HTML de Telegram siempre válido (`<tarea>`, código, rutas escapados) | 🧪 |
| 12 | ID no autorizado: sin acceso, aviso único, cero creación de datos | 🧪 |
| 13 | Persistencia tras reinicio: proyectos, conversaciones y mensajes en nueva conexión | 🧪 |
| 14 | Migraciones idempotentes + update.sh con backup/rollback | 🧪 (sintaxis y lógica; systemd real en VPS) |

### Verificado realmente (este entorno)
- Todo lo anterior, con el motor de intenciones, deduplicación de updates,
  cola, sandbox local (rlimits), vault, migraciones y GitHub broker reales.

### Requiere validación en el VPS (no ejecutable aquí)
- Docker rootless: flags del contenedor probados unitariamente, pero la
  creación real de contenedores necesita Docker (test omitido a propósito).
- DeepSeek en vivo: /testapi, /balance, listado real de modelos
  (`deepseek-flash`, `deepseek-v4-pro` si existen) — los tests usan mocks HTTP.
- systemd real: arranque, "Bot en marcha", rollback del update.sh.
- Renderizado real de mensajes >4096 caracteres y rate limits de Telegram.

## Modelos iniciales
El encargo nombra `deepseek-flash` y `deepseek-v4-pro`. El producto NO asume
esa lista: `/models` consulta siempre `GET /models` del proveedor y rechaza
nombres inexistentes avisándolo. Si DeepSeek publica esos ids, aparecerán
automáticamente en el catálogo.

---

# V4 — Panel Web (rama `feature/hachecode-web-v4`, noviembre 2026)

Migración de interfaz Telegram → Web **reutilizando el motor V3**. Ver
`docs/WEB_V4.md`, `docs/DEPLOY_VERCEL.md`, `docs/DEPLOY_BACKEND_VPS.md`,
`docs/MIGRACION_V4.md`.

## Implementado y probado
| Función | Estado | Dónde |
|---|---|---|
| Backend FastAPI con auth (scrypt, sesiones server-side, CSRF, rate-limit) | 🧪 | `backend/`, `tests/test_web_auth.py` |
| Proyectos: CRUD, árbol, archivos (leer/escribir/borrar/descargar) con PathGuard | 🧪 | `backend/routers/projects.py`, `tests/test_web_projects.py` |
| Import/export ZIP seguros (flatten raíz, zip-slip rechazado, rollback de import fallido) | 🧪 | `tests/test_web_projects.py` |
| Chat: conversaciones, mensajes, historial persistido | 🧪 | `backend/routers/chat.py`, `tests/test_web_chat.py` |
| Tareas: envío → cola web → motor real → estado final | 🧪 | `backend/queue_web.py`, `tests/test_web_chat.py` |
| Plan de trabajo visual declarado por el MODELO (`update_plan`); límite de pasos NO finge completitud (`plan_incomplete`) | 🧪 | `core/tools/registry.py`, `tests/test_web_chat.py` |
| Actividad en vivo: eventos por herramienta persistidos + SSE con replay (`Last-Event-ID`) y heartbeat | 🧪 | `backend/events.py`, `backend/routers/chat.py`, `tests/test_web_chat.py` |
| Cancelación (en cola y en marcha) y reintento/continuación desde estado real | 🧪 | `tests/test_web_chat.py` |
| Recuperación tras reinicio: tareas `running` → `interrupted` (reintentables) | 🧪 | `tests/test_web_chat.py` |
| Selector de modelos con catálogo REAL del proveedor (nada inventado) | 🧪 | `backend/routers/models.py` |
| Git: status/log/diff/ramas/stage/commit; push en DOS pasos con token efímero de un solo uso | 🧪 | `backend/routers/gitops.py`, `tests/test_web_git_exec.py` |
| Ejecución sandbox a demanda: command_guard + fail-safe sin rootless | 🧪 | `backend/routers/execrun.py`, `tests/test_web_git_exec.py` |
| Consumo/costes reales y presupuestos | 🧪 | `backend/routers/usage.py` |
| Frontend Next.js 15 (App Router, TS, Tailwind 4, Monaco, tema claro/oscuro, móvil-first con drawer/overlay) — **`next build` compila** | 🧪 | `frontend/` |
| Proxy `/api/*` (rewrite) probado end-to-end con `next start` | ✅ | `scripts/smoke_web.sh` |
| Bug latente V3 corregido: `_run_git` no esperaba el proceso → proyectos sin git init/config | 🧪 | `core/projects/manager.py` |
| Bug real de defaults corregido: sin `active_provider` la web caía en `anthropic` (primer proveedor alfabético) | 🧪 | `backend/app.py` |

## Smoke E2E real (`scripts/smoke_web.sh`)
Backend uvicorn + `next start`: health OK, login con cookie+CSRF, proyecto y
archivos reales, path traversal → 400, `python3 main.py` ejecutado en sandbox
(`42`), login y API a través del proxy de Next.js → todo verificado.

## Requiere validación en el VPS (no ejecutable aquí)
- ⏳ Docker rootless real para sandboxes de la web (mismas garantías V3; flags probados unitariamente).
- ⏳ DeepSeek en vivo con la API key real (catálogo, chat, costes).
- ⏳ Despliegue Vercel + dominio/TLS (docs listas; no se despliega desde aquí).
- ⏳ Experiencia táctil real en Android (layout probado por CSS; sin dispositivo aquí).
- ⏳ Carga concurrente de varios navegadores (diseño mono-usuario).

## Resultados de la suite con V4 (noviembre 2026)
**199 pruebas automatizadas: 199 pasan, 0 fallan, 1 omitida** (Docker real,
se valida en el VPS). Incluye 53 pruebas web nuevas; la suite V3 completa
(14 flujos incluidos) sigue en verde: la interfaz Telegram no se tocó.

