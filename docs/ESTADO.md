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

**146 pruebas automatizadas: 145 pasan, 0 fallan, 1 omitida.**
La omitida es `tests/test_sandbox_docker.py` (requiere un daemon Docker real;
este entorno de CI no lo tiene — se valida en el VPS).

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
