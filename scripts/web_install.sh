#!/usr/bin/env bash
# =============================================================
# HacheCode Agent V4 - instalacion/actualizacion del PANEL WEB
# en el VPS Contabo, SIN tocar el bot de Telegram ni el Docker
# principal.
#
#   sudo bash scripts/web_install.sh
#
# Que hace:
#   1. venv propio en .venv-web (no toca el del bot)
#   2. pip install -e ".[web]" (FastAPI, uvicorn, multipart, sse)
#   3. compila el frontend Next.js (frontend/.next)
#   4. genera .env.web si no existe (NUNCA sobreescribe)
#   5. instala systemd hj-code-agent-web.service (puerto 8900)
#
# Reversibles: desinstalar = systemctl disable --now hj-code-agent-web
#              + rm -rf .venv-web ; el bot no se toca.
# =============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ $EUID -ne 0 ]]; then
  echo "[web] Este script requiere root (systemd). Usa: sudo bash $0" >&2
  exit 1
fi

SERVICE=hj-code-agent-web
PY=python3

echo "[web] 1/5 venv dedicado (.venv-web)"
if [[ ! -d .venv-web ]]; then
  "$PY" -m venv .venv-web
fi
.venv-web/bin/pip -q install --upgrade pip

echo "[web] 2/5 dependencias del backend web"
.venv-web/bin/pip -q install -e ".[web]"

echo "[web] 3/5 compilando frontend Next.js"
if command -v node >/dev/null 2>&1; then
  (cd frontend && npm ci --no-audit --no-fund && npm run build)
else
  echo "[web] AVISO: node no disponible; compila el frontend aparte (Vercel lo hace)"
fi

echo "[web] 4/5 entorno .env.web"
if [[ ! -f .env.web ]]; then
  cat > .env.web <<'ENV'
# ================= HacheCode Agent V4 - PANEL WEB =================
# Comparte la BD/boveda con la V3 (migracion automatica, nada se borra)

# --- Motor (identicos a .env del bot) ---
HJ_DATA_DIR=/opt/hj-code-agent/data
HJ_WORKSPACES_DIR=/opt/hj-code-agent/workspaces
HJ_BACKUPS_DIR=/opt/hj-code-agent/backups
HJ_MASTER_KEY=                # la MISMA clave maestra del bot (boveda)
HJ_DB_PATH=                   # vacio = data/hj.db (igual que la V3)

# --- Docker rootless del usuario hjcode (NUNCA el daemon principal) ---
HJ_DOCKER_HOST=unix:///run/user/997/docker.sock
HJ_SANDBOX_BACKEND=docker
HJ_WORKSPACES_HOST_DIR=/opt/hj-code-agent/workspaces

# --- Panel web ---
HJ_WEB_HOST=127.0.0.1
HJ_WEB_PORT=8900
HJ_WEB_USERNAME=admin
HJ_WEB_PASSWORD=CAMBIA-ESTA-CONTRASENA-8CARACT-MIN
HJ_WEB_AGENT_UID=             # tu UID de Telegram (los proyectos de la V3)
HJ_WEB_SESSION_TTL_H=72
HJ_WEB_SECURE_COOKIES=1       # detras de proxy HTTPS

# --- Origen del frontend (CORS directo; con proxy /api no es necesario) ---
# FRONTEND_ORIGIN=https://tu-web.vercel.app
ENV
  chmod 600 .env.web
  echo "[web] CREADO .env.web (600) - EDITALO con tus valores antes de arrancar"
else
  echo "[web] .env.web ya existe: no se toca"
fi

echo "[web] 5/5 servicio systemd $SERVICE (independiente del bot)"
cat > /etc/systemd/system/$SERVICE.service <<UNIT
[Unit]
Description=HacheCode Agent V4 - Panel Web (FastAPI)
After=network.target

[Service]
Type=simple
User=hjcode
Group=hjcode
WorkingDirectory=$ROOT
EnvironmentFile=$ROOT/.env.web
ExecStart=$ROOT/.venv-web/bin/python -m backend
Restart=on-failure
RestartSec=3
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ReadWritePaths=$ROOT/data $ROOT/workspaces $ROOT/backups $ROOT

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable $SERVICE >/dev/null
echo "[web] Listo. Para arrancar:  systemctl start $SERVICE"
echo "[web] Verificar:             systemctl status $SERVICE"
echo "[web] Logs:                  journalctl -u $SERVICE -f"
echo "[web] NO se ha tocado el servicio del bot de Telegram."
