# Migración de datos V3 → V4 y plan de rollback

## Principio: migración SIN borrado

La V4 **comparte la base de datos y los workspaces de la V3**. No hay
conversión de datos: la migración `0002_web.sql` solo AÑADE tres tablas
(`web_users`, `web_sessions`, `task_events`) y no modifica ninguna existente.
Al arrancar el backend web por primera vez:

- Se aplican las migraciones pendientes (idempotentes; el bot V3 también las
  tolera: las tablas nuevas le son indiferentes).
- Se crea el usuario web de bootstrap (solo si `web_users` está vacía).
- Tus proyectos, workspaces, historial de tareas, proveedores, credenciales
  cifradas (bóveda `HJ_MASTER_KEY`) y copias de seguridad siguen donde estaban,
  ahora visibles desde el panel web mediante `HJ_WEB_AGENT_UID`.

## Reversibilidad de la migración

```sql
-- Rollback de la migración 0002 (opcional; las tablas pueden quedarse):
DROP TABLE IF EXISTS task_events;
DROP TABLE IF EXISTS web_sessions;
DROP TABLE IF EXISTS web_users;
DELETE FROM schema_version WHERE version=2;
```

## Copia de seguridad previa (obligatoria antes de tocar producción)

```bash
# 1) Parar SOLO si vas a hacer checkpoint manual (el bot puede seguir vivo:
#    SQLite en WAL admite lectores concurrentes, pero haz backup limpio)
sudo systemctl stop hj-code-agent
sudo bash scripts/backup.sh            # backup existente de la V3
sudo systemctl start hj-code-agent

# 2) Backup específico del stack web (tras instalar la V4)
sudo bash scripts/web_backup.sh
```

## Convivencia Telegram + Web durante la migración

Ambas interfaces pueden correr a la vez (es el modo recomendado mientras
validas la web):

- Mismo motor, misma cola: **1 tarea simultánea por usuario** (regla V3), así
  que si lanzas tarea por Telegram, la web verá la cola ocupada.
- Los eventos `task_events` se generan desde la web; las notificaciones del
  bot siguen siendo Telegram. No hay interferencia.
- Cuando valides la web y quieras desactivar Telegram (paso que TÚ autorizarás
  después): `sudo systemctl disable --now hj-code-agent` — sin borrar nada.

## Plan de rollback completo

1. **Solo panel web**: `sudo systemctl disable --now hj-code-agent-web`
   → todo vuelve exactamente a como estaba (el bot ni se enteró).
2. **Código**: `sudo -u hjcode git checkout main` (las tablas web pueden
   quedarse; si quieres limpiarlas, usa el SQL de arriba).
3. **Datos**: si algo fuera mal con la BD (no debería: migración aditiva),
   restaura con `sudo bash scripts/restore.sh <backup>` según docs/BACKUPS.md.

## Qué NO migra / límites conocidos

- Los mensajes de Telegram no se copian a conversaciones web (históricos
  independientes; el historial de la BD SÍ es común porque es el mismo store).
- Preferencias por usuario (`prefs`) son las mismas: si en Telegram elegiste
  modelo, la web lo hereda (mismo `agent_uid`).
- Las aprobaciones de push que lleguen MIENTRAS la tarea corre por web se
  muestran en la propia web (panel de la tarea). El flujo de botones de
  Telegram sigue disponible si la tarea la lanzó el bot.
