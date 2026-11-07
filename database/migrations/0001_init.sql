-- HJ CODE AGENT V2 - esquema inicial
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS users (
  telegram_id INTEGER PRIMARY KEY,
  username TEXT DEFAULT '',
  first_name TEXT DEFAULT '',
  is_admin INTEGER NOT NULL DEFAULT 0,
  allowed INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS prefs (
  user_id INTEGER NOT NULL,
  key TEXT NOT NULL,
  value TEXT,
  PRIMARY KEY (user_id, key)
);

CREATE TABLE IF NOT EXISTS providers (
  name TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  base_url TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  builtin INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS credentials (
  user_id INTEGER NOT NULL,
  provider TEXT NOT NULL,
  secret BLOB NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (user_id, provider)
);

CREATE TABLE IF NOT EXISTS system_prompts (
  user_id INTEGER PRIMARY KEY,
  mode TEXT NOT NULL DEFAULT 'native',
  content TEXT,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  path TEXT NOT NULL,
  system_prompt TEXT,
  prompt_enabled INTEGER NOT NULL DEFAULT 0,
  network_enabled INTEGER NOT NULL DEFAULT 1,
  archived INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (user_id, name)
);

CREATE TABLE IF NOT EXISTS conversations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  project_id INTEGER,
  provider TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id INTEGER NOT NULL,
  role TEXT NOT NULL,
  content TEXT,
  tool_calls TEXT,
  tool_call_id TEXT,
  name TEXT,
  tokens_in INTEGER NOT NULL DEFAULT 0,
  tokens_out INTEGER NOT NULL DEFAULT 0,
  cost REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id);

CREATE TABLE IF NOT EXISTS usage_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  conversation_id INTEGER,
  project_id INTEGER,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_tokens INTEGER NOT NULL DEFAULT 0,
  completion_tokens INTEGER NOT NULL DEFAULT 0,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  cost REAL,
  currency TEXT NOT NULL DEFAULT 'USD',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_usage_user_time ON usage_log(user_id, created_at);

CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  chat_id INTEGER NOT NULL,
  project_id INTEGER,
  conversation_id INTEGER,
  kind TEXT NOT NULL DEFAULT 'agent',
  title TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'queued',
  params TEXT,
  result TEXT,
  error TEXT,
  steps INTEGER NOT NULL DEFAULT 0,
  max_steps INTEGER NOT NULL DEFAULT 24,
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  started_at TEXT,
  finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

CREATE TABLE IF NOT EXISTS budgets (
  user_id INTEGER PRIMARY KEY,
  per_task REAL,
  per_day REAL,
  currency TEXT NOT NULL DEFAULT 'USD',
  alert_balance REAL,
  alert_daily REAL,
  notifications INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS git_state (
  project_id INTEGER PRIMARY KEY,
  repo_url TEXT,
  default_branch TEXT DEFAULT 'main',
  current_branch TEXT,
  autopush INTEGER NOT NULL DEFAULT 0,
  allowed_branches TEXT NOT NULL DEFAULT '[]',
  last_push_at TEXT
);

CREATE TABLE IF NOT EXISTS pricing (
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  input_per_mtok REAL,
  output_per_mtok REAL,
  cache_hit_per_mtok REAL,
  currency TEXT NOT NULL DEFAULT 'USD',
  PRIMARY KEY (provider, model)
);

CREATE TABLE IF NOT EXISTS memory_notes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  action TEXT NOT NULL,
  detail TEXT DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS kv (
  key TEXT PRIMARY KEY,
  value TEXT,
  expires_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_profiles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  role TEXT NOT NULL,
  provider TEXT,
  model TEXT,
  prompt TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  UNIQUE (user_id, name)
);

CREATE TABLE IF NOT EXISTS model_meta (
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  context_window INTEGER,
  max_output INTEGER,
  PRIMARY KEY (provider, model)
);
