#!/bin/bash
# Prueba de humo E2E real: backend FastAPI + frontend Next.js (proxy /api).
set -e
cd /home/z/my-project/hj-code-agent

export HJ_DATA_DIR=/tmp/hj-smoke/data
export HJ_WORKSPACES_DIR=/tmp/hj-smoke/workspaces
export HJ_BACKUPS_DIR=/tmp/hj-smoke/backups
export HJ_SANDBOX_BACKEND=local
export HJ_ALLOW_LOCAL_SANDBOX=1
export HJ_MASTER_KEY=clave-smoke
export HJ_WEB_PASSWORD=clave-web-smoke-1
export HJ_WEB_USERNAME=smoke
export HJ_WEB_AGENT_UID=111
export HJ_WEB_SECURE_COOKIES=0
export HJ_WEB_HOST=127.0.0.1
export HJ_WEB_PORT=8900
rm -rf /tmp/hj-smoke && mkdir -p /tmp/hj-smoke

echo "== 1) Arrancando backend FastAPI (uvicorn) =="
setsid nohup python3 -m backend > /tmp/hj-smoke/backend.log 2>&1 &
BACK_PID=$!
sleep 4

echo "== 2) Health (directo) =="
curl -s http://127.0.0.1:8900/api/health | head -c 300; echo

echo "== 3) Login web =="
curl -s -c /tmp/hj-smoke/cookies.txt -X POST http://127.0.0.1:8900/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"smoke","password":"clave-web-smoke-1"}' | head -c 200; echo
CSRF=$(curl -s -b /tmp/hj-smoke/cookies.txt http://127.0.0.1:8900/api/auth/me | python3 -c "import sys,json;print(json.load(sys.stdin)['csrf_token'])")
echo "CSRF=${CSRF:0:8}…"

echo "== 4) Crear proyecto + archivo (con CSRF) =="
curl -s -b /tmp/hj-smoke/cookies.txt -X POST http://127.0.0.1:8900/api/projects \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $CSRF" \
  -d '{"name":"proyecto-smoke"}' | head -c 200; echo
PID=$(curl -s -b /tmp/hj-smoke/cookies.txt http://127.0.0.1:8900/api/projects | python3 -c "import sys,json;print(json.load(sys.stdin)['projects'][0]['id'])")
curl -s -b /tmp/hj-smoke/cookies.txt -X PUT http://127.0.0.1:8900/api/projects/$PID/file \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $CSRF" \
  -d '{"path":"main.py","content":"print(40+2)\n"}'; echo
curl -s -b /tmp/hj-smoke/cookies.txt "http://127.0.0.1:8900/api/projects/$PID/file?path=main.py"; echo
echo "-- path traversal --"
curl -s -b /tmp/hj-smoke/cookies.txt -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8900/api/projects/$PID/file?path=../../etc/passwd"
echo "-- ejecucion sandbox real (echo + python) --"
curl -s -b /tmp/hj-smoke/cookies.txt -X POST http://127.0.0.1:8900/api/projects/$PID/exec \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $CSRF" \
  -d '{"command":"python3 main.py"}'; echo

echo "== 5) Arrancando frontend Next.js (next start, puerto 3000) =="
cd frontend
setsid nohup npx next start -p 3000 > /tmp/hj-smoke/frontend.log 2>&1 &
sleep 5
echo "== 6) Pagina de login a traves de Next =="
curl -s -o /dev/null -w "GET / -> %{http_code}\n" http://127.0.0.1:3000/login
echo "== 7) API proxied /api/health a traves de Next (rewrite) =="
curl -s http://127.0.0.1:3000/api/health; echo
echo "== 8) Login proxied (cookie + csrf via proxy) =="
curl -s -c /tmp/hj-smoke/cookies2.txt -X POST http://127.0.0.1:3000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"smoke","password":"clave-web-smoke-1"}' | head -c 160; echo

echo "== 9) Limpieza =="
kill -- -$BACK_PID 2>/dev/null || pkill -f "python3 -m backend" || true
pkill -f "next start" || true
echo "SMOKE OK"
