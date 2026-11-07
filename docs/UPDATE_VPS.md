# Actualización del VPS a V3 — Ubuntu 24.04 (Contabo, sin perder datos)

Guía para la instalación existente en `/opt/hj-code-agent` con servicio
`hj-code-agent`. **No hay que editar nada a mano ni usar nano**: el script de
actualización conserva `.env`, base de datos, clave maestra, vault cifrado
(credenciales DeepSeek) y todos los proyectos/workspaces.

## Qué se conserva y qué se toca

| Elemento | ¿Se conserva? |
|---|---|
| `.env` (token del bot, admin ID, HJ_MASTER_KEY, flags) | ✅ intacto |
| `data/` (SQLite: proyectos, conversaciones, preferencias, vault cifrado con la API key de DeepSeek) | ✅ intacto + backup coherente |
| `workspaces/` (código de tus proyectos) | ✅ intacto + backup |
| `backups/` | ✅ intacto |
| **Usuario del servicio** (p. ej. `hjcode`) | ✅ detectado con `systemctl show -p User`; no se crea ningún usuario ni se cambian propietarios salvo divergencia real |
| Unidad systemd `hj-code-agent.service` | ✅ sin modificaciones automáticas |
| Otros servicios Docker/sistema del VPS | ✅ ni se miran |
| Código en `/opt/hj-code-agent/app` | 🔄 se reemplaza por V3 (copia previa en el backup) |
| Archivos modificados a mano (p. ej. `providers.py`, `sandbox/factory.py`) | 📋 se guardan en `backups/update-<fecha>/localmods/` para revisión |

## Coherencia del backup y del rollback (nuevo en esta revisión)

1. El servicio se **detiene ANTES** de copiar (antes: se copiaba con el bot
   escribiendo → riesgo de SQLite incoherente con WAL).
2. Se ejecuta **checkpoint WAL** (`scripts/db_tools.py`): todo lo comprometido
   pasa de `hj.db-wal` a `hj.db` y se verifica `PRAGMA integrity_check` antes
   de crear el tar. Si la base no está íntegra, el actualizador ABORTA sin
   tocar nada.
3. El rollback es **completo**: restaura código anterior, dependencias
   (`pip install -e`), `data/` (revertir migraciones), `.env` y los
   **propietarios originales** de `data/`, `workspaces/` y `backups/`, y
   rearranca el servicio. Cada paso destructivo (rsync, pip, migraciones,
   arranque) invoca rollback automáticamente.

## El bot nunca queda detenido por un fallo previo (nuevo en esta revisión)

Cualquier fallo **después de `systemctl stop`** reinicia automáticamente el
servicio con la versión anterior:

- `checkpoint WAL`, `integrity_check`, cualquiera de los tres `tar` del
  backup, o cualquier otro error no gestionado (red de seguridad con
  `trap ERR` + `set -E`) → **rollback y arranque del servicio anterior**.
- Antes: un `tar` fallido dejaba el bot PARADO (`die()` y `set -e` no
  reiniciaban nada). Los tests e2e (`tests/test_update_e2e.py`) reproducen
  estos fallos de verdad y verifican que el servicio vuelve a arrancar.

## Migraciones parciales: la BD se restaura (nuevo en esta revisión)

- `MIGRATED=1` se activa **ANTES** de ejecutar `db.migrate()` (antes se
  marcaba al final): si una migración aplica cambios y la siguiente explota,
  el rollback **restaura la base de datos previa** desde el backup tomado
  tras el checkpoint WAL (sin `-wal`/`-shm` residuales de la migración a
  medias).
- Además hay **verificación de integridad POST-migración**: si la BD queda
  mal, rollback completo.
- Corregido también un cuelgue real: si `db.migrate()` lanzaba una excepción,
  la conexión aiosqlite no se cerraba y el hilo no-daemon dejaba el proceso
  **colgado para siempre** (el rollback jamás llegaba a ejecutarse).

## HJ_DB_PATH se respeta (nuevo en esta revisión)

Si tu instalación usa una ruta de base de datos distinta de la predeterminada,
el actualizador la detecta con el MISMO orden que usa el bot
(`core/config/settings.py`):

1. `HJ_DB_PATH` en el entorno con el que ejecutas `update.sh`;
2. `Environment="HJ_DB_PATH=..."` de la unidad systemd y sus drop-ins;
3. `HJ_DB_PATH=...` en el `.env` de la instalación (escrito por `scripts/setup.py`);
4. por defecto: `$BASE_DIR/data/hj.db`.

El checkpoint, `integrity_check`, backup, migraciones y restauración se
aplican a ESA ruta, aunque sea externa a `data/` (se copia además el fichero
de BD a `backups/update-<fecha>/db/` para poder restaurarlo por separado).
Antes: el actualizador ignoraba `HJ_DB_PATH` y migraba/comprobaba
`data/hj.db` aunque el bot usara otra base.

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

El script hace, en orden: detecta versión, usuario efectivo del servicio y
cambios locales → **detiene únicamente `hj-code-agent`** → checkpoint WAL +
integridad + backup completo (`.env` + fichero de BD + `data/` +
`workspaces/` + código anterior) → copia el código nuevo (sin tocar datos) →
`pip install` + migraciones idempotentes con verificación posterior →
permisos solo si divergen del usuario real del servicio (jamás crea
usuarios) → arranca y comprueba salud → **rollback automático con el
servicio en marcha** si algo falla (código, dependencias, datos, `.env` y
propietarios).

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

## Sandbox Docker rootless (obligatorio antes de dar código al agente)

En el VPS ya hay Docker de producción. **El sandbox jamás lo usa**: sin
`HJ_DOCKER_HOST` la fábrica ni siquiera invoca la CLI de docker, y si
`HJ_DOCKER_HOST` apunta a `/var/run/docker.sock` o `/run/docker.sock` se
rechaza (tests lo verifican). La vía segura es un daemon rootless propio:

```bash
# como el usuario del servicio (o el que ejecutes), NO con sudo del daemon principal:
curl -fsSL https://get.docker.com/rootless | sh        # instala dockerd rootless
systemctl --user enable --now docker
echo 'export DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock' >> ~/.bashrc
# añade HJ_DOCKER_HOST=unix:///run/user/<UID>/docker.sock al .env (o pídeselo a /settings)
```

Con el host rootless configurado, cada sandbox monta **únicamente el workspace
del proyecto** (`/opt/hj-code-agent/workspaces/<usuario>/<proyecto>` →
`/workspace`): nunca la raíz general ni proyectos ajenos.

Nota honesta: los mapeos de UID de Docker rootless (quién es propietario de
los archivos en el bind mount) dependen de la configuración de subuid del
daemon; el código minimiza los `chown` (solo si 1000:1000 no puede escribir),
pero **la verificación final de esa interacción requiere pruebas reales en tu
VPS** — no se ha podido ejecutar Docker en el entorno de build.

Referencias: `docs/SECURITY.md` (modelo de amenazas) e
`docs/INSTALL.md#sandbox-rootless`. Mientras no haya sandbox aislado probado,
la política de fábrica bloquea la ejecución de código (`HJ_ALLOW_LOCAL_SANDBOX`
debe seguir en 0 en producción).

## Si algo va mal

```bash
journalctl -u hj-code-agent -n 50 --no-pager     # diagnóstico
sudo ls /opt/hj-code-agent/backups/              # backups update-<fecha>
# rollback manual completo (el script ya lo hace automático):
sudo systemctl stop hj-code-agent
sudo rm -rf /opt/hj-code-agent/app
sudo tar -xzf /opt/hj-code-agent/backups/update-<fecha>/app-anterior.tar.gz -C /opt/hj-code-agent
sudo cp -a /opt/hj-code-agent/backups/update-<fecha>/.env /opt/hj-code-agent/app/.env
sudo /opt/hj-code-agent/venv/bin/pip install -e /opt/hj-code-agent/app
# si las migraciones escribieron en la BD, restaura también los datos:
sudo tar -xzf /opt/hj-code-agent/backups/update-<fecha>/data.tar.gz -C /opt/hj-code-agent
# si usas HJ_DB_PATH externa a data/, restaura además el fichero de BD:
sudo rm -f <tu-HJ_DB_PATH> <tu-HJ_DB_PATH>-wal <tu-HJ_DB_PATH>-shm
sudo cp -a /opt/hj-code-agent/backups/update-<fecha>/db/dbfile <tu-HJ_DB_PATH>
# y conserva el usuario de tu servicio (ejemplo hjcode):
sudo chown -R hjcode:hjcode /opt/hj-code-agent/data /opt/hj-code-agent/workspaces
sudo systemctl start hj-code-agent
```

`.env`, `data/` y `workspaces/` nunca los mueve el actualizador; si quieres
además una copia externa: `sudo bash /opt/hj-code-agent/app/scripts/backup.py`.
