# Despliegue del BACKEND web en el VPS Contabo (V4) — sin interferencias

Objetivo: añadir el panel web al VPS **sin tocar** el bot de Telegram, el
Docker principal ni ningún otro servicio. Todo lo que se crea es nuevo y
reversible.

## Qué NO se toca

| Recurso existente | V4 |
|---|---|
| Servicio systemd del bot (`hj-code-agent`) | Intacto; sigue corriendo |
| Docker principal del host (`/var/run/docker.sock`) | Jamás se usa; el sandbox solo ve `HJ_DOCKER_HOST` rootless |
| BD SQLite `data/hj.db` | Se comparte (migración aditiva 0002_web.sql; no borra ni altera tablas V3) |
| `.env` del bot | Intacto; el panel web usa `.env.web` separado |
| Caddy/nginx existente | Solo se añade un site/subdominio nuevo |

## Pasos

### 1. Traer el código

```bash
cd /opt/hj-code-agent
sudo -u hjcode git fetch origin
sudo -u hjcode git checkout feature/hachecode-web-v4
```

### 2. Instalar

```bash
sudo bash scripts/web_install.sh
```

Crea: `.venv-web/` (venv propio), compila `frontend/`, escribe `.env.web`
(0600, no sobreescribe) y registra `hj-code-agent-web.service`.

### 3. Configurar `.env.web`

```bash
sudo nano /opt/hj-code-agent/.env.web
```

Valores clave:

- `HJ_MASTER_KEY`: **la misma del bot** (sin ella la bóveda no descifra las API keys y no habrá modelos).
- `HJ_WEB_PASSWORD`: contraseña del panel (mín. 8 caracteres).
- `HJ_WEB_AGENT_UID`: tu UID de Telegram — es lo que vincula el panel con TUS proyectos/tareas/credenciales existentes de la V3.
- `HJ_DOCKER_HOST=unix:///run/user/997/docker.sock` y `HJ_SANDBOX_BACKEND=docker`: rootless de `hjcode`, igual que la V3.
- `HJ_WEB_SECURE_COOKIES=1` cuando haya HTTPS por delante.

### 4. Arrancar y verificar

```bash
sudo systemctl start hj-code-agent-web
journalctl -u hj-code-agent-web -n 30 --no-pager
curl -s http://127.0.0.1:8900/api/health
# {"ok":true,...,"docker_host_authorized":true,...}
```

`docker_host_authorized:true` confirma que el sandbox rootless está bien
configurado (false = revisa `HJ_DOCKER_HOST`).

### 5. HTTPS público (obligatorio para Vercel)

Con Caddy (si ya lo usas, añade el bloque; si no: `apt install caddy`):

```caddy
api.tudominio.com {
    reverse_proxy 127.0.0.1:8900
}
```

El backend escucha en `127.0.0.1` — no queda expuesto sin TLS.

### 6. Permisos de workspaces (Docker rootless)

El servicio corre como `hjcode` (el mismo usuario del rootless), por lo que
los montajes del sandbox funcionan igual que en la V3. No hay `chown -R`
masivos en ningún punto del código web.

## Verificación final (checklist)

- [ ] `systemctl status hj-code-agent` → el bot sigue **active** (intacto).
- [ ] `curl --unix-socket /run/user/997/docker.sock http://x/info` responde (rootless vivo).
- [ ] `/api/health` con `docker_host_authorized:true`.
- [ ] Login web OK; crear proyecto OK; ejecutar `python3 --version` desde Archivos → responde del sandbox.
- [ ] Enviar tarea simple → plan visible, eventos en vivo, ZIP exportable.
- [ ] Backup: `bash scripts/web_backup.sh` genera el tarball.

## Rollback (ver docs/MIGRACION_V4.md)

```bash
sudo systemctl disable --now hj-code-agent-web
sudo -u hjcode git checkout main
```

Las tablas web de la BD pueden quedarse (no molestan a la V3).
