#!/bin/bash
# Verificación visual completa en UNA invocación: backend + navegador.
set -e
cd /home/z/my-project/hj-code-agent

export HJ_DATA_DIR=/tmp/hj-smoke/data HJ_WORKSPACES_DIR=/tmp/hj-smoke/workspaces \
       HJ_BACKUPS_DIR=/tmp/hj-smoke/backups HJ_SANDBOX_BACKEND=local \
       HJ_ALLOW_LOCAL_SANDBOX=1 HJ_MASTER_KEY=clave-smoke \
       HJ_WEB_PASSWORD=clave-web-smoke-1 HJ_WEB_USERNAME=smoke \
       HJ_WEB_AGENT_UID=111 HJ_WEB_SECURE_COOKIES=0 \
       HJ_WEB_HOST=127.0.0.1 HJ_WEB_PORT=8900

pkill -f "python3 -m backend" 2>/dev/null || true
sleep 1
setsid nohup python3 -m backend > /tmp/hj-smoke/backend3.log 2>&1 < /dev/null &
sleep 4
echo "health: $(curl -s http://127.0.0.1:8900/api/health | head -c 80)"

agent-browser set viewport 1280 800
agent-browser open http://127.0.0.1:3000/login
agent-browser wait --load networkidle
agent-browser screenshot /home/z/my-project/hj-code-agent/docs/img/login.png

# login real
agent-browser find label "Usuario" fill "smoke"
agent-browser find label "Contraseña" fill "clave-web-smoke-1"
agent-browser find text "Entrar" click
agent-browser wait --url "http://127.0.0.1:3000/" --timeout 15000 || true
agent-browser wait --load networkidle
echo "url tras login: $(agent-browser get url)"
agent-browser screenshot /home/z/my-project/hj-code-agent/docs/img/chat-vacio.png
agent-browser snapshot -i | head -25
echo "VISUAL OK"
pkill -f "python3 -m backend" 2>/dev/null || true
