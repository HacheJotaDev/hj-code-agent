-- V4 Web: usuarios/sesiones del panel web y eventos de tareas para SSE.
-- No altera ninguna tabla existente de la V3 (migracion aditiva y reversible:
-- el rollback solo requiere eliminar estas tablas; los datos de Telegram
-- quedan intactos).

CREATE TABLE IF NOT EXISTS web_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    agent_uid INTEGER NOT NULL DEFAULT 0,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS web_sessions (
    token_hash TEXT PRIMARY KEY,
    web_user_id INTEGER NOT NULL,
    csrf_token TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    ip TEXT DEFAULT '',
    user_agent TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_web_sessions_user ON web_sessions(web_user_id);

CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    data TEXT DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events(task_id, id);
