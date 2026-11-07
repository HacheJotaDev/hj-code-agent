# Actualización del VPS a V3 — Ubuntu 24.04 (Contabo, sin perder datos)

Guía para la instalación existente en `/opt/hj-code-agent` con servicio
`hj-code-agent`. **No hay que editar nada a mano ni usar nano**: el script de
actualización conserva `.env`, base de datos, clave maestra, vault cifrado
(credenciales DeepSeek) y todos los proyectos/workspaces.

## Qué se conserva y qué se toca

| Elemento | ¿Se conserva? |
|---|---|
| `.env` (token del bot, admin ID, HJ_MASTER_KEY, flags) | ✅ intacto |
| `data/` (SQLite: proyectos, conversaciones, preferencias, vault cifrado con la API key de DeepSeek) | ✅ intacto + backup |
| `workspaces/` (código de tus proyectos) | ✅ intacto + backup |
| `backups/` | ✅ intacto |
| Unidad systemd `hj-code-agent.service` existente | ✅ respetada (solo se endurece si corría como root) |
| Otros servicios Docker/sistema del VPS | ✅ ni se miran |
| Código en `/opt/hj-code-agent/app` | 🔄 se reemplaza por V3 (copia previa en el backup) |
| Archivos modificados a mano (p. ej. `providers.py`, `sandbox/factory.py`) | 📋 se guardan en `backups/update-<fecha>/localmods/` para revisión |

## Pasos

```bash
# 1) Copia el código nuevo al VPS (elige una forma):
#    a) git clone en una carpeta aparte
git clone https://github.com/HacheJotaDev/hj-code-agent /tmp/hj-v3
#    b) o scp/rsync desde tu PC
#       rsync -av --exclude .git --exclude .venv hj-code-agent/ vps:/tmp/hj-v3/

# 2) Ejecuta el actualizador (requiere sudo; SOLO gestiona este servicio)
sudo bash /tmp/hj-v3/scripts/update.sh /tmp/hj-v3
```

El script hace, en orden: detecta versión y cambios locales → backup completo
(`.env` + `data/` + `workspaces/` + código anterior) → detiene únicamente
`hj-code-agent` → copia el código nuevo (sin tocar datos) → `pip install` +
migraciones idempotentes → crea usuario sin privilegios `hjagent` si falta →
arranca y comprueba salud → **rollback automático** si algo falla (restaura el
código anterior y rearranca; `.env` y datos nunca se tocan).

## Verificación post-actualización (en Telegram, con tu admin ID)

1. `/start` → debe aparecer **HJ CODE AGENT V3** con el menú.
2. `/health` → base de datos ok, bóveda cifrada ok, sandbox backend.
3. `/testapi` → valida la credencial DeepSeek guardada en el vault (sin
   reescribirla: se conserva cifrada).
4. `/projects` → tus proyectos siguen ahí; `/files` dentro de uno.
5. Envía un ZIP de prueba → crea/selecciona el proyecto y extrae.
6. Escribe "ejecuta las pruebas del proyecto" → si el sandbox Docker está
   activo verás la salida real de pytest; si NO hay sandbox disponible el bot
   **lo dirá explícitamente y no ejecutará código** (sin fallback silencioso).

## Sandbox Docker rootless (recomendado antes de dar código al agente)

En el VPS ya hay Docker de producción. **No lo uses para el sandbox del bot**
y no le des el socket del host. La vía segura es un daemon rootless propio:

```bash
# como el usuario del servicio (o el que ejecutes), NO con sudo del daemon principal:
curl -fsSL https://get.docker.com/rootless | sh        # instala dockerd rootless
systemctl --user enable --now docker
echo 'export DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock' >> ~/.bashrc
# añade HJ_DOCKER_HOST=unix:///run/user/<UID>/docker.sock al .env (o pídeselo a /settings)
```

Referencias: `docs/SECURITY.md` (modelo de amenazas) e
`docs/INSTALL.md#sandbox-rootless`. Mientras no haya sandbox aislado probado,
la política de fábrica bloquea la ejecución de código (`HJ_ALLOW_LOCAL_SANDBOX`
debe seguir en 0 en producción).

## Si algo va mal

```bash
journalctl -u hj-code-agent -n 50 --no-pager     # diagnóstico
sudo ls /opt/hj-code-agent/backups/              # backups update-<fecha>
# rollback manual completo:
sudo systemctl stop hj-code-agent
sudo tar -xzf /opt/hj-code-agent/backups/update-<fecha>/app-anterior.tar.gz -C /opt/hj-code-agent
sudo /opt/hj-code-agent/venv/bin/pip install -e /opt/hj-code-agent/app
sudo systemctl start hj-code-agent
```

`.env`, `data/` y `workspaces/` nunca los mueve el actualizador; si quieres
además una copia externa: `sudo bash /opt/hj-code-agent/app/scripts/backup.py`.
