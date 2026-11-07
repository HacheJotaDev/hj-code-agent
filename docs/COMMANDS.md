# Comandos — HJ CODE AGENT V2

## General
| Comando | Descripción |
|---|---|
| `/start`, `/menu` | Menú principal con estado (proveedor, modelo, proyecto, tarea, saldo) |
| `/help` | Ayuda completa |
| `/status` | Estado detallado + últimas tareas |
| `/health` | Salud: BD, bóveda, cola, sandbox, disco, uptime |
| `/version` | Versión |
| `/settings` | Menú de configuración |
| `/cancel` | Cancela la tarea en ejecución |

## Chat y conversaciones
`/newchat` · `/chats` · `/chat select <id>` · `/history` · `/clear` · `/reset`
`/exportchat` · `/searchchat <texto>` · `/session` · `/sessions`
Mensajes sin `/` = chat directo con el modelo (modo nativo). `/context` muestra
la ventana del modelo y la ocupación estimada.

## System prompts
`/system` estado · `/system set [texto]` · `/system edit` · `/system show`
`/system off` · `/system clear` · `/system reset` (nativo) · `/system export`
`/system import` (JSON) · `/system project [texto|on|off]`

## Proveedores y modelos
`/provider` · `/providers` · `/provider add` · `/provider select <n>` ·
`/provider remove <n>` · `/setapi` · `/testapi` · `/models [refresh]` ·
`/model [info|select <n>]` · `/temperature <0-2>` · `/top_p <0-1>` ·
`/max_tokens <n>` · `/stream on|off` · `/reasoning low|medium|high` ·
`/params` · `/params reset` · `/price set <modelo> <in> <out> [moneda] [cache]`

## Saldo, tokens y costes
`/balance` (real, endpoint oficial) · `/tokens` · `/usage` · `/cost
[today|month]` · `/stats` · `/limits` · `/budget task|day <monto>` ·
`/alerts balance|daily <monto>`

## Proyectos y archivos
`/newproject <nombre>` · `/projects` · `/project select|info|rename|export|
archive|delete` · `/files [ruta]` · `/file read|download <ruta>` ·
`/upload` (envía documento o ZIP al proyecto activo) · `/workspace` ·
`/backup` · `/restore`

## Agente y tareas
`/run <tarea>` (agente con herramientas) · `/task <tarea|status|stop|retry>` ·
`/tasks` · `/queue` · `/logs [id]` · `/cancel`

## Terminal y sandbox
`/terminal <cmd>` · `/install [cmd]` · `/test [cmd]` · `/build [cmd]` ·
`/processes` · `/sandbox status|reset|resources`

## GitHub
`/github [connect|status|disconnect]` · `/repo add|clone|info` · `/repos` ·
`/branch <n>` · `/branches` · `/checkout <rama>` · `/gitstatus` · `/diff` ·
`/commit <msg>` · `/push [rama]` (autorización) · `/pull` · `/pr <título>` ·
`/history` · `/rollback <archivo>` · `/autopush on|off`

## Multiagente (opcional, OFF por defecto)
`/agents` · `/agents on|off` · `/agents add` (nombre → rol → proveedor:modelo →
prompt opcional) · `/agents remove <n>` · `/agents config` · `/agents status` ·
`/agents models`

## Administración
`/admin` · `/users` · `/authorize <id> [admin]` · `/revoke <id>` · `/security`
`/audit [n]` · `/notifications on|off` · `/diagnostics` · `/config export|import`
