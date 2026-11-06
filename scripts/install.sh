#!/usr/bin/env bash
# ============================================================================
# HJ CODE AGENT V2 - Instalacion por etapas verificables en el VPS
# NO detiene ni reinicia otros servicios de Docker. Solo gestiona su unidad.
# ============================================================================
set -euo pipefail

BASE_DIR="/opt/hj-code-agent"
SERVICE="hj-code-agent"
REPO_SRC="$(cd "$(dirname "$0")/.." && pwd)"

step() { echo -e "\n\033[1;36m== $1 ==\033[0m"; }
ok()   { echo -e "\033[1;32m✔ $1\033[0m"; }
die()  { echo -e "\033[1;31m✘ $1\033[0m"; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Ejecuta como root (sudo)."
step "1/7 Comprobando dependencias"
command -v python3 >/dev/null || die "python3 no encontrado"
PYV=$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || die "Se necesita Python >= 3.11 (encontrado $PYV)"
command -v git >/dev/null || die "git no encontrado"
if command -v docker >/dev/null; then docker info >/dev/null 2>&1 && DOCKER_OK=1 || DOCKER_OK=0; else DOCKER_OK=0; fi
echo "Python $PYV · Docker: $([ "$DOCKER_OK" = 1 ] && echo disponible || echo NO (sandbox local, menor aislamiento))"
ok "Dependencias base"

step "2/7 Creando directorios"
mkdir -p "$BASE_DIR/app" "$BASE_DIR/data" "$BASE_DIR/workspaces" "$BASE_DIR/backups"
ok "Directorios creados (sin tocar nada existente)"

step "3/7 Copiando aplicacion"
rsync -a --delete --exclude '.git' --exclude '__pycache__' --exclude '.venv' \
      --exclude 'data' --exclude 'workspaces' --exclude 'backups' \
      "$REPO_SRC"/ "$BASE_DIR/app"/
ok "Codigo en $BASE_DIR/app"

step "4/7 Entorno virtual Python"
python3 -m venv "$BASE_DIR/venv"
"$BASE_DIR/venv/bin/pip" install --upgrade pip --quiet
"$BASE_DIR/venv/bin/pip" install -e "$BASE_DIR/app" --quiet
ok "Dependencias instaladas"

step "5/7 Configuracion (.env)"
if [ ! -f "$BASE_DIR/app/.env" ]; then
  cp "$BASE_DIR/app/.env.example" "$BASE_DIR/app/.env"
  KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
  sed -i "s|^HJ_MASTER_KEY=.*|HJ_MASTER_KEY=$KEY|" "$BASE_DIR/app/.env"
  sed -i "s|^HJ_MASTER_KEY_FILE=.*|HJ_MASTER_KEY_FILE=|" "$BASE_DIR/app/.env"
  cat <<EOF

  ACCION REQUERIDA: edita $BASE_DIR/app/.env y rellena:
    HJ_TELEGRAM_BOT_TOKEN=  (token de @BotFather)
    HJ_ADMIN_USER_IDS=      (tu user_id de Telegram, de @userinfobot)

  La HJ_MASTER_KEY ya se genero aleatoriamente. GUARDA UNA COPIA FUERA DEL VPS:
  si la pierdes, no podras leer las credenciales cifradas.
EOF
else
  ok ".env ya existia: no se modifica"
fi

step "6/7 Unidad systemd"
cat > "/etc/systemd/system/${SERVICE}.service" <<EOF
[Unit]
Description=HJ Code Agent V2 (bot Telegram)
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$BASE_DIR/app
ExecStart=$BASE_DIR/venv/bin/python -m bot.main
Restart=always
RestartSec=5
User=root
# Reinicio automatico tras reinicio del VPS: Restart=always hace el trabajo
Environment=PYTHONUNBUFFERED=1
LimitNOFILE=8192

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null 2>&1
ok "Unidad $SERVICE creada y habilitada (solo esta unidad; otros servicios intactos)"

step "7/7 Estado"
echo "Para arrancar:   systemctl start $SERVICE"
echo "Logs:            journalctl -u $SERVICE -f"
echo "Actualizar:      sudo $BASE_DIR/app/scripts/update.sh"
echo "Desinstalar:     sudo $BASE_DIR/app/scripts/uninstall.sh"
echo "Despues de editar .env: systemctl restart $SERVICE"
ok "Instalacion completada por etapas"
