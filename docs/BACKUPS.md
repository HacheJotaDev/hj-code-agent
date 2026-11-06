# Backups y recuperación

## Qué se guarda

- **Base de datos** (`data/hj.db`, WAL): usuarios, conversaciones, mensajes,
  consumo, tareas, configuración. Las credenciales están cifradas dentro.
- **Workspaces**: código de los proyectos (incluye `.git` local).
- **`.env`**: token del bot y clave maestra (si está en el archivo).

## Copia manual

```bash
sudo /opt/hj-code-agent/app/scripts/backup.sh              # full-<fecha>.tar.gz
sudo /opt/hj-code-agent/app/scripts/backup.sh /ruta/out.tar.gz
```

Usa `sqlite3 backup API` (copia consistente aunque haya escrituras).

## Copia programada

```
0 4 * * * /opt/hj-code-agent/app/scripts/backup.sh && \
  find /opt/hj-code-agent/backups -name 'full-*.tar.gz' -mtime +14 -delete
```

**Copia la clave maestra fuera del VPS.** Sin ella, las credenciales cifradas
de la BD no se pueden descifrar (irrecuperables por diseño).

## Recuperación

```bash
sudo /opt/hj-code-agent/app/scripts/restore.sh backups/full-YYYYMMDD-HHMM.tar.gz
journalctl -u hj-code-agent -f
```

Tras un reinicio del VPS el servicio vuelve solo (`Restart=always`); las tareas
que estaban corriendo quedan marcadas `interrupted` y puedes relanzarlas con
`/task retry <id>`.
