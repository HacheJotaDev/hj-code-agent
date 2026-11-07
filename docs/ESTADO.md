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

## Modelos iniciales
El encargo nombra `deepseek-flash` y `deepseek-v4-pro`. El producto NO asume
esa lista: `/models` consulta siempre `GET /models` del proveedor y rechaza
nombres inexistentes avisándolo. Si DeepSeek publica esos ids, aparecerán
automáticamente en el catálogo.
