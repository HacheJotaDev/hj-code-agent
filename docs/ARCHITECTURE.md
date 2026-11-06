# Arquitectura — HJ CODE AGENT V2

```
        Telegram (long polling, sin puertos públicos)
                          │  aiogram 3 + middlewares (contexto → auth)
                          ▼
   ┌──────────────────────────────────────────────────┐
   │ bot/handlers  (13 routers: chat, system, provs,  │
   │ billing, projects, agent, terminal, github, ...) │
   └───────────────┬──────────────────────────────────┘
                   ▼
   ┌──────────────────────────────────────────────────┐
   │ core (AppContext comparte servicios)             │
   │  prompts ──► ÚNICA fuente de system prompts      │
   │  providers: DeepSeek │ OpenAI-compat │ Anthropic │──► API externa
   │  agent: bucle de herramientas + aprobaciones     │
   │  tasks: cola durable (workers, cancel, retry)    │
   │  sandbox: docker endurecido │ local rlimits      │
   │  github: REST + broker (token efímero en host)   │──► GitHub
   │  billing: usage/costes + balance real            │
   └───────┬───────────────────────┬──────────────────┘
           ▼                       ▼
   SQLite (WAL) + bóveda      workspaces/<user>/<proyecto>
   (Fernet, clave maestra     montados SOLO en el sandbox
    externa a la BD)          del proyecto (contenedor hermano)
```

## Flujo del agente (tarea real)

1. `/run tarea` → fila `tasks` (queued) → worker de la cola.
2. Se prepara sandbox (docker/local) para el proyecto activo.
3. Bucle: historial (sin system en modo nativo) + herramienta tools nativas →
   `POST /chat/completions` → si responde `tool_calls`, se validan argumentos y
   rutas, se ejecuta la herramienta REAL y el resultado vuelve como `role:tool`.
4. `git_push` / `github_pull_request` pausan la tarea y piden botones de
   autorización al humano (timeout 10 min).
5. Cada llamada registra `usage` (tokens) y coste según tarifas; presupuestos
   por tarea/día cortan la ejecución si se alcanzan.
6. Final: resumen con archivos tocados, comandos y logs en `tasklog:<id>`.

## Sin system prompt por defecto

`PromptService.build_messages()` es el único punto donde se construyen los
mensajes: en modo nativo devuelve el historial sin ningún `system`. Los tests
`test_no_default_system_prompt.py` interceptan las llamadas al proveedor y
verifican que no existe rol `system`/`developer`.

## Recuperación

- SQLite en WAL; `recover()` hace checkpoint e integridad al arrancar.
- Tareas `running` al morir el proceso → `interrupted` (relanzables).
- La cola es persistente: lo encolado sobrevive reinicios.

## Multiagente

Pipeline secuencial de perfiles (`agent_profiles`) — cada uno con proveedor/
modelo/prompt explícito configurado por el usuario. OFF por defecto para
evitar costes. Nunca se inyectan prompts de rol ocultos.
