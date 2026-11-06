# Instalación y configuración — HJ CODE AGENT V2

## 1. Requisitos

- Ubuntu 24.04 (o similar) con Python ≥ 3.11, git, rsync.
- Docker recomendado para el sandbox aislado (opcional).
- Un bot de Telegram y una cuenta de DeepSeek con saldo.

## 2. Crear el bot de Telegram

1. Habla con **@BotFather** → `/newbot` → guarda el **token**.
2. Obtén tu `user_id` con **@userinfobot**.
3. Ningún puerto público es necesario (long polling saliente).

## 3. Instalación por etapas

```bash
sudo bash scripts/install.sh
```

Etapas verificables: dependencias → directorios (`/opt/hj-code-agent/{data,
workspaces,backups}`) → código → venv + dependencias → **asistente por
consola** → unidad systemd (`Restart=always`: reinicia solo tras un
reinicio del VPS) → estado. **No detiene ni reinicia otros servicios.**

### Asistente por consola (paso 5 del instalador)

Si no existe `.env`, el instalador lanza `scripts/setup.py`, que pregunta por
consola:

1. **Token del bot** (entrada oculta; lo de @BotFather).
2. **Tu admin user_id** → solo ese ID recibirá respuestas; el resto de
   usuarios son ignorados (con `HJ_SILENT_REJECT=1`, ni un aviso).
3. (Opcional) API key de DeepSeek — se siembra cifrada.
4. (Opcional) Silencio total para IDs no autorizados.

Genera la `HJ_MASTER_KEY` aleatoria y escribe `.env` con permisos `0600`.
Puedes reejecutarlo cuando quieras (guarda un `.env.bak`):

```bash
sudo /opt/hj-code-agent/venv/bin/python /opt/hj-code-agent/app/scripts/setup.py \
     --env /opt/hj-code-agent/app/.env --base-dir /opt/hj-code-agent
sudo systemctl restart hj-code-agent
```

Edición manual alternativa:

```bash
sudo nano /opt/hj-code-agent/app/.env
# HJ_TELEGRAM_BOT_TOKEN=123456:ABC...
# HJ_ADMIN_USER_IDS=123456789
sudo systemctl restart hj-code-agent
```

## 4. DeepSeek

1. Regístrate en platform.deepseek.com y crea una **API key**.
2. En Telegram: `/setapi` → el bot devuelve un enlace de un solo uso.
3. Desde tu PC: `ssh -L 8977:127.0.0.1:8977 tu-vps` y abre
   `http://127.0.0.1:8977/set/<token>`.
4. Pega la clave → se guarda **cifrada** en la bóveda.
5. `/testapi` valida conexión; `/models` lista los modelos reales de la API;
   `/model select <id>` elige el activo.
6. `/balance` muestra el saldo real (endpoint oficial `/user/balance`).

Tarifas para costes: `/price set <modelo> <input$> <output$> [moneda] [cache_hit$]`
(precios por 1M de tokens, actualízalos con las tarifas vigentes del proveedor).

Otros proveedores: `/provider add` (openai_compat · deepseek · anthropic),
`/provider select`, `/setapi` con el proveedor activo. Incluidos por defecto:
deepseek, openai, anthropic, glm (Z.ai), openrouter, ollama local.

## 5. GitHub

1. Crea un **fine-grained PAT** con permisos mínimos: *Contents: Read/Write*
   solo en los repos concretos que vayas a editar.
2. `/github connect` → enlace de formulario de un solo uso → pega el token.
3. Por proyecto:
   - `/repo add https://github.com/tu/repo`
   - `/repo clone`
   - trabajo del agente → `/commit "mensaje"` → `/push` (botón de autorización)
   - PR: `/pr titulo` (también con autorización)
4. `/autopush on` SOLO si aceptas pushes automáticos; queda limitado a las
   ramas de la lista y nunca en ramas protegidas sin lista explícita.

El token **no entra** en los sandboxes: el push lo ejecuta el broker del host
con credencial efímera.

## 6. Actualización / desinstalación / backups

```bash
sudo bash scripts/update.sh      # solo toca este servicio
sudo bash scripts/uninstall.sh   # detiene/deshabilita su unidad systemd
sudo bash scripts/backup.sh      # BD consistente + workspaces + .env
sudo bash scripts/restore.sh backups/full-XXXX.tar.gz
```

Cron recomendado: `0 4 * * * /opt/hj-code-agent/app/scripts/backup.sh`
