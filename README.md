# HJ CODE AGENT V2

Agente **autónomo de programación controlado por Telegram**: chat real con
modelos de IA (DeepSeek por defecto), ejecución de código en sandbox aislado,
gestión de proyectos y archivos, GitHub con autorización humana, saldo/tokens
reales y **modo nativo sin system prompt oculto**.

> Regla fundamental del producto: **por defecto no se envía ningún system
> prompt** (ni rol `system`, ni `developer`, ni instrucciones ocultas). Solo se
> envía lo que el usuario configura explícitamente con `/system` o el prompt de
> proyecto. Verificado por pruebas automatizadas.

## Capacidades

| Área | Qué hace |
|---|---|
| Chat IA | Conversación real vía API (DeepSeek/OpenAI-compat/Anthropic), streaming opcional, historial persistente |
| System prompts | Modos nativo / personalizado / por proyecto; `/system set·edit·show·off·clear·reset·export·import·project` |
| Proveedores | Adaptadores intercambiables, `/models` con catálogo real de la API, parámetros por modelo |
| Saldo y consumo | `/balance` (endpoint oficial `/user/balance`), tokens y costes por llamada, presupuestos y alertas |
| Agente | Bucle de herramientas reales: leer/escribir/editar/patch, buscar, comandos, instalar, tests, build, git |
| Sandbox | Docker no privilegiado (cap-drop ALL, no-new-privileges, límites RAM/CPU/pids/timeout) o local con rlimits para desarrollo |
| GitHub | Clonar, ramas, commits, **push solo con autorización por botones**, PRs, autopush OFF por defecto |
| Archivos | Subida de archivos y ZIP con validación estricta (traversal, symlinks, bombas), export, backups |
| Tareas | Cola durable en SQLite, cancelación, reintentos, recuperación tras reinicio |
| Seguridad | Solo user_id autorizados, bóveda cifrada (Fernet + clave maestra externa), auditoría, formulario seguro `/setapi` |
| Multiagente | OPCIONAL y desactivado por defecto: pipeline de perfiles (programador/revisor/tester) configurables |

## Instalación rápida (VPS Ubuntu 24.04, Contabo 8 GB)

```bash
sudo apt-get update && sudo apt-get install -y python3-venv git rsync
# Docker recomendado para el sandbox aislado (opcional pero recomendado):
# curl -fsSL https://get.docker.com | sh

# copia o clona este repositorio en /opt/hj-code-agent
sudo mkdir -p /opt/hj-code-agent && sudo chown "$USER" /opt/hj-code-agent
cp -r hj-code-agent /opt/hj-code-agent/app  # o git clone ...

cd /opt/hj-code-agent/app
sudo bash scripts/install.sh     # etapas verificables; genera clave maestra
# (el instalador lanza el ASISTENTE POR CONSOLA si no hay .env:
#  te pide el TOKEN DEL BOT -oculto- y tu ADMIN USER_ID de Telegram;
#  SOLO ese user_id obtendra respuestas del bot)
sudo systemctl start hj-code-agent
journalctl -u hj-code-agent -f
```

Reconfigurar mas tarde (cambia token/admin por consola, sin editar archivos):

```bash
sudo /opt/hj-code-agent/venv/bin/python /opt/hj-code-agent/app/scripts/setup.py \
     --env /opt/hj-code-agent/app/.env --base-dir /opt/hj-code-agent
sudo systemctl restart hj-code-agent
```

Primeros pasos en Telegram:

1. `/start` → menú principal.
2. `/setapi` → pega tu API key de DeepSeek en el **formulario local** (nunca en el chat).
3. `/models` → lista real de la API; `/model select deepseek-chat` (o el que prefieras).
4. `/newproject MiProyecto` → proyecto con git local.
5. `/run crea un servidor FastAPI con tests` → el agente trabaja en el sandbox.
6. `/balance`, `/tokens`, `/cost` → consumo **real**.

Alternativa con Docker Compose: `docker compose up -d --build` (ver
`docker-compose.yml`; usa el socket de Docker solo para crear sandboxes hermanos).

## Estructura

```
hj-code-agent/
├── bot/            # aiogram 3: handlers, keyboards, middlewares, formulario /setapi
├── core/
│   ├── config/     # settings por variables de entorno
│   ├── authentication/ permissions/   # quién puede usar el bot y qué
│   ├── providers/  # adaptadores: deepseek, openai-compat, anthropic
│   ├── models/     # catálogo con cache TTL y ventanas de contexto
│   ├── prompts/    # ÚNICA fuente de system prompts (nativo por defecto)
│   ├── agent/      # motor de herramientas, aprobaciones, multiagente
│   ├── tools/      # 21 herramientas con validación estricta
│   ├── tasks/      # cola durable + workers + cancelación
│   ├── sandbox/    # docker endurecido / local con rlimits
│   ├── github/     # cliente REST + broker de credenciales (push autorizado)
│   ├── projects/   # proyectos, ZIP seguro, export/archivo
│   ├── billing/    # saldo real, tokens, tarifas, costes
│   └── storage/    # SQLite WAL + bóveda Fernet
├── database/       # migraciones SQL versionadas
├── security/       # path guard, command guard (capa independiente del modelo)
├── scripts/        # install / update / uninstall / backup / restore
├── tests/          # suite pytest (18 áreas del encargo)
└── docs/           # SECURITY, INSTALL, COMMANDS, BACKUPS, ARCHITECTURE, ESTADO
```

## Documentación

- `docs/INSTALL.md` — Telegram, DeepSeek, GitHub, etapas de instalación.
- `docs/SECURITY.md` — modelo de amenazas, sandbox, secretos, limitaciones honestas.
- `docs/COMMANDS.md` — todos los comandos con ejemplos.
- `docs/BACKUPS.md` — procedimiento de copias y recuperación.
- `docs/ARCHITECTURE.md` — cómo encaja todo.
- `docs/ESTADO.md` — funciones implementadas / verificadas / pendientes.

## Notas honestas

- Los modelos iniciales del encargo (`deepseek-flash`, `deepseek-v4-pro`) son
  nombres provisionales: el catálogo real se consulta SIEMPRE vía
  `GET /models`; si un nombre no existe, el bot lo indica en vez de asumirlo.
- El sandbox `local` es para desarrollo/pruebas; en producción usa Docker.
  Ver limitaciones en `docs/SECURITY.md`.
- Los costes se estiman con tarifas configurables (`/price set`); si un
  proveedor no expone saldo, se declara "no disponible" y no se inventa.
