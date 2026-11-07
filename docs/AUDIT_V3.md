# AUDIT_V3 — Auditoría integral de HJ Code Agent (V2 → V3)

Fecha: auditoría completa del árbol `bot/`, `core/`, `security/`, `database/`,
`scripts/` (~9.800 líneas Python + SQL + scripts shell). Metodología: lectura
lineal de todos los módulos + análisis de los flujos reportados + trazado del
orden de routers de aiogram 3.

## 1. Resumen ejecutivo

La base V2 es sólida en seguridad (PathGuard, command_guard, bóveda cifrada,
sandbox Docker endurecido, push autorizado, sin system prompt por defecto),
pero contiene **7 bugs confirmados** reportados por el usuario y **11 defectos
adicionales** encontrados en la auditoría, 3 de ellos graves (ejecución
duplicada de tareas, handler muerto de importación de config, fuga potencial
de API keys al modelo).

## 2. Bugs confirmados (reportados) — causa raíz y corrección

### Bug A — `TypeError: 'int' object is not iterable` en admin ID
- **Causa raíz**: `core/config/settings.py::_parse_ids` hacía `return list(v)`
  para cualquier no-string; cuando `HJ_ADMIN_USER_IDS=424242` (entero, tal y
  como lo escribe `scripts/setup.py`) pydantic entrega un `int` y `list(int)`
  explota.
- **Corrección**: aceptar `int` → `[v]`, floats enteros, y descartar tokens no
  numéricos con log en vez de romper el arranque.

### Bug B — Los botones seleccionaban proveedor/modelo para el BOT
- **Causa raíz**: en aiogram 3, `callback.message.from_user` es **el bot**, no
  quien pulsó. Los handlers usaban `cb.message` y reutilizaban funciones de
  comandos que leen `message.from_user.id`.
  - `providers.py`: `cb_prov_sel → _select(cb.message)`,
    `cb_model_sel → _model_select(cb.message)`,
    `cb_model_page/refresh → send_models(cb.message)`.
  - `common.py`: `cb_menu` ("projects"/"providers"/"sysprompt"/"stats") pasaba
    `cb.message`.
  - `github_cmds.py`: `gh:branches|push|pull|autopush` → `cmd_*(cb.message)`
    → `get_project()` del BOT.
- **Corrección**: helpers con parámetro `uid` explícito; todos los callbacks
  pasan `cb.from_user.id`. Persistencia de proveedor/modelo era correcta
  (`prefs` por user_id); el problema era solo la identidad.

### Bug C — `TelegramBadRequest: Unsupported start tag "tarea"`
- **Causa raíz**: textos de ayuda con ejemplos `/<cmd> <tarea>` enviados con
  `parse_mode=HTML` heredado de `DefaultBotProperties`. Detectados en:
  `projects.py` (×3), `agent_cmds.py` (×4), `chat.py` (×3), `providers.py`
  (×4), `admin.py` (×3), `billing.py` (×4), `github_cmds.py` (×3),
  `terminal.py` (×2), `common.py`.
- **Corrección**: (1) todos los ejemplos escapados (`&lt;…&gt;`) o mensajes en
  texto plano; (2) red de seguridad `send_safe()`: si Telegram rechaza el HTML,
  reintenta en texto plano sin perder el contenido ni el estado.

### Bug D — `/projects` respondía "Primero selecciona un proyecto"
- **Causa raíz**: el mensaje provenía de `on_document` (envío de archivo sin
  proyecto activo), no de `/projects`. Además, el estado FSM
  `ProjectStates.waiting_name` con filtro `F.text` capturaba **comandos**
  (`/projects` se convertía en nombre de proyecto).
- **Corrección**: los documentos ahora **crean el proyecto automáticamente**
  (flujo V3); los handlers FSM excluyen textos que empiezan por `/`;
  `/projects` y `/newproject` verificados sin estado previo.

### Bug E — Respuestas duplicadas
Tres causas raíz independientes:
1. **Ejecución doble de tareas**: `Store.next_queued()` era un `SELECT` sin
   reclamación atómica → con 2 workers, ambos podían tomar la misma tarea y
   ejecutarla dos veces (mensajes y trabajo duplicados). → `claim_next_queued()`
   con `UPDATE … WHERE id=(SELECT …) RETURNING *`.
2. **Replay tras reinicio**: `start_polling` sin `drop_pending_updates=True`
   reprocesaba mensajes acumulados durante la caída. → corregido.
3. **Reenvío por segunda instancia**: sin deduplicación de `update_id`.
   → middleware `UpdateDedup` (protege también contra polling doble).

### Bug F — Demasiados pasos manuales
- **Corrección (V3)**: enviar un ZIP/archivo **crea el proyecto solo**, lo
  selecciona, lo asocia a la conversación y resume lo encontrado; el texto
  natural con intención de código sobre un proyecto activo **encola una tarea
  del agente** (equivalente a /run) sin comando; si no hay proyecto pero hay
  intención de código se ofrece botón "usar el último proyecto / solo chat";
  sin proyecto también se puede chatear. `/export` entrega el ZIP.

### Bug G — Configuración de API
- El seed de la bóveda desde entorno ya no sobrescribe credenciales
  (`_seed_vault_from_env` solo si no existe) — verificado, se conserva.
- **Riesgo corregido**: una API key pegada en el chat iba **directa al modelo**
  (fuga). Ahora se detecta (`sk-…`, `github_pat_…`, `ghp_…`, tokens largos),
  NO se envía al modelo, NO se guarda, se avisa que se revoque y se sugiere
  /setapi. `/setapi` mantiene el formulario de un solo uso en loopback.

## 3. Defectos adicionales encontrados (nuevos)

| # | Gravedad | Lugar | Defecto | Corrección |
|---|---|---|---|---|
| 1 | Grave | `tasks/queue.py` + `repositories.py` | Carrera de workers (ver Bug E.1) | claim atómico |
| 2 | Grave | `admin.py::on_config_import` | Handler muerto: `projects.on_document` (F.document, sin estado, router anterior) captura TODO documento → `hj-config.json` nunca se importaba | FSM `ConfigStates.waiting_import` + `SkipHandler` en `on_document` cuando hay estado activo |
| 3 | Grave | `chat.py::free_chat` | Fuga de claves al modelo (ver Bug G) | guardia anti-secretos |
| 4 | Alto | `agent_cmds.py::cmd_task` | `uid` sin definir → `NameError` en `/task status <id>` | definido |
| 5 | Alto | `chat.py::cmd_chats` | Construía la lista y **no la enviaba** (`/chats` sin respuesta) | envío añadido |
| 6 | Alto | `agents_mode.py` | `/agents remove <nombre>` muerto: el handler con regex estaba registrado DESPUÉS de `cmd_agents` y nunca disparaba | borrado implementado dentro de `cmd_agents` |
| 7 | Medio | `keyboards.menus` | Botones "⬅️ Volver" con `callback_data="menu"` (sin `:`) sin handler → spinner eterno | handler `F.data == "menu"` |
| 8 | Medio | `keyboards.menus::models_kb` | Nombre de modelo truncado a 48 chars en callback → selección corrupta para ids largos | selección por índice `mdl:i:…` |
| 9 | Medio | `sandbox/factory.py` | `backend=docker` sin Docker → caía a **local silenciosamente** (inseguro en producción) | `ExecutionUnavailable`; local solo con `HJ_ALLOW_LOCAL_SANDBOX=1` |
| 10 | Medio | `main.py` | FSM en `MemoryStorage` → estados FSM se pierden al reiniciar (aceptable; documentado) | documentado |
| 11 | Bajo | `bot/main.py`, textos | Banner "V2", `VERSION="2.0.0"` obsoletos | V3 en toda la UI |

## 4. Política de sandbox para producción (nueva)

- `sandbox_kind()` ya **nunca** hace fallback silencioso: si el backend
  configurado no está disponible lanza `ExecutionUnavailable` y el usuario
  recibe "ejecución no disponible", jamás ejecución local insegura.
- `HJ_ALLOW_LOCAL_SANDBOX=1` queda como interruptor explícito solo para
  desarrollo/tests (los tests lo activan en sus fixtures).
- Soporte de Docker **rootless** independiente vía `HJ_DOCKER_HOST`
  (p. ej. `unix:///run/user/1001/docker.sock`); el daemon del host nunca se
  usa por defecto y el socket no se monta jamás en sandboxes.
- Semáforo global `HJ_MAX_CONCURRENT_SANDBOXES` (por defecto 1) y RAM por
  defecto elevada a 1024 MB según requisitos.
- `scripts/install.sh`/`update.sh` crean usuario sin privilegios (`hjagent`),
  la unidad systemd corre con `User=hjagent`, `NoNewPrivileges=yes`,
  `ProtectSystem=full` y sin acceso a Docker.

## 5. Qué NO se ha cambiado (verificado correcto)

- `PathGuard`, `command_guard` (lista de denegación + entorno sin secretos),
  `ziputils` (traversal/symlinks/bombas), `broker` (token efímero GIT_ASKPASS,
  push solo autorizado, ramas protegidas), `approvals` (autorización humana
  con timeout), `prompts` (modo nativo sin inyección), `DeepSeekProvider`
  (saldo/modelos reales), migraciones SQLite versionadas, WAL.

## 6. Límites de la auditoría

- No se ejecutó contra la API real de Telegram/DeepSeek/GitHub desde este
  entorno (solo mocks); la validación real se hace con `/testapi` y `/balance`
  en el VPS.
- El sandbox Docker no puede arrancarse aquí: sus pruebas cubren banderas de
  seguridad y contrato, no la ejecución real de contenedores (marcado como
  tal en la suite).
