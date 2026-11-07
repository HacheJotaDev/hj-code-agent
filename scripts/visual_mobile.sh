#!/bin/bash
# Capturas móviles (rápido): asume frontend :3000 vivo; levanta backend.
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
setsid nohup python3 -m backend > /tmp/hj-smoke/backend5.log 2>&1 < /dev/null &
sleep 3
IMG=/home/z/my-project/hj-code-agent/docs/img

agent-browser set viewport 375 812
agent-browser open http://127.0.0.1:3000/login
agent-browser wait --load networkidle
agent-browser screenshot $IMG/login-movil.png
agent-browser eval "(async()=>{document.querySelector('input[autocomplete=\"username\"]').value='';})()"
agent-browser find label "Usuario" fill "smoke"
agent-browser find label "Contraseña" fill "clave-web-smoke-1"
agent-browser find text "Entrar" click
sleep 2
agent-browser screenshot $IMG/chat-movil.png
agent-browser eval "document.querySelector('button[title=\"Panel de tareas, archivos y git\"]').click()"
sleep 1
agent-browser screenshot $IMG/panel-movil.png
agent-browser eval "[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='Archivos').click()"
sleep 1
agent-browser screenshot $IMG/archivos-movil.png
echo "MOBILE OK"
pkill -f "python3 -m backend" 2>/dev/null || true
