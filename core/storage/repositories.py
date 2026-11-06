"""Repositorio unico de datos (SQLite). Todas las tablas se acceden desde aqui."""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .database import Database


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _rowdict(row) -> dict | None:
    return dict(row) if row is not None else None


class Store:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ============================ usuarios ================================
    async def upsert_user(self, tid: int, username: str = "", first_name: str = "",
                          is_admin: bool = False, allowed: bool = False) -> dict:
        await self.db.execute(
            """INSERT INTO users (telegram_id, username, first_name, is_admin, allowed)
               VALUES (?,?,?,?,?)
               ON CONFLICT(telegram_id) DO UPDATE SET username=excluded.username,
                 first_name=excluded.first_name, is_admin=excluded.is_admin,
                 allowed=excluded.allowed""",
            (tid, username or "", first_name or "", int(is_admin), int(allowed)),
        )
        return _rowdict(await self.db.one("SELECT * FROM users WHERE telegram_id=?", (tid,)))

    async def get_user(self, tid: int) -> dict | None:
        return _rowdict(await self.db.one("SELECT * FROM users WHERE telegram_id=?", (tid,)))

    async def list_users(self) -> list[dict]:
        return [dict(r) for r in await self.db.all("SELECT * FROM users ORDER BY telegram_id")]

    async def set_allowed(self, tid: int, allowed: bool) -> None:
        await self.db.execute("UPDATE users SET allowed=? WHERE telegram_id=?", (int(allowed), tid))

    async def set_admin(self, tid: int, is_admin: bool) -> None:
        await self.db.execute("UPDATE users SET is_admin=? WHERE telegram_id=?", (int(is_admin), tid))

    # ============================ preferencias ============================
    async def get_pref(self, tid: int, key: str, default=None):
        row = await self.db.one("SELECT value FROM prefs WHERE user_id=? AND key=?", (tid, key))
        return row["value"] if row else default

    async def set_pref(self, tid: int, key: str, value) -> None:
        await self.db.execute(
            """INSERT INTO prefs (user_id, key, value) VALUES (?,?,?)
               ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value""",
            (tid, key, None if value is None else str(value)),
        )
        if value is None:
            await self.db.execute("DELETE FROM prefs WHERE user_id=? AND key=?", (tid, key))

    async def all_prefs(self, tid: int) -> dict[str, str]:
        return {r["key"]: r["value"] for r in
                await self.db.all("SELECT key, value FROM prefs WHERE user_id=?", (tid,))}

    # ============================ proveedores =============================
    async def list_providers(self) -> list[dict]:
        return [dict(r) for r in await self.db.all("SELECT * FROM providers ORDER BY name")]

    async def get_provider(self, name: str) -> dict | None:
        return _rowdict(await self.db.one("SELECT * FROM providers WHERE name=?", (name,)))

    async def add_provider(self, name: str, kind: str, base_url: str, builtin: bool = False) -> None:
        await self.db.execute(
            """INSERT INTO providers (name, kind, base_url, builtin) VALUES (?,?,?,?)
               ON CONFLICT(name) DO NOTHING""",
            (name, kind, base_url, int(builtin)),
        )

    async def update_provider(self, name: str, *, base_url: str | None = None,
                              enabled: bool | None = None) -> None:
        if base_url is not None:
            await self.db.execute("UPDATE providers SET base_url=? WHERE name=?", (base_url, name))
        if enabled is not None:
            await self.db.execute("UPDATE providers SET enabled=? WHERE name=?",
                                  (int(enabled), name))

    async def remove_provider(self, name: str) -> None:
        await self.db.execute("DELETE FROM providers WHERE name=? AND builtin=0", (name,))

    # ============================ credenciales ============================
    async def set_credential(self, user_id: int, provider: str, encrypted: bytes) -> None:
        await self.db.execute(
            """INSERT INTO credentials (user_id, provider, secret) VALUES (?,?,?)
               ON CONFLICT(user_id, provider) DO UPDATE SET secret=excluded.secret,
                 updated_at=excluded.updated_at""",
            (user_id, provider, encrypted),
        )

    async def get_credential(self, user_id: int, provider: str) -> bytes | None:
        row = await self.db.one(
            "SELECT secret FROM credentials WHERE user_id=? AND provider=?", (user_id, provider))
        return row["secret"] if row else None

    async def list_credential_providers(self, user_id: int) -> list[str]:
        return [r["provider"] for r in await self.db.all(
            "SELECT provider FROM credentials WHERE user_id=? ORDER BY provider", (user_id,))]

    async def delete_credential(self, user_id: int, provider: str) -> None:
        await self.db.execute("DELETE FROM credentials WHERE user_id=? AND provider=?",
                              (user_id, provider))

    # ============================ system prompts ==========================
    async def get_system_prompt(self, tid: int) -> dict | None:
        return _rowdict(await self.db.one("SELECT * FROM system_prompts WHERE user_id=?", (tid,)))

    async def set_system_prompt(self, tid: int, content: str, mode: str = "custom") -> None:
        await self.db.execute(
            """INSERT INTO system_prompts (user_id, mode, content, updated_at) VALUES (?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET mode=excluded.mode, content=excluded.content,
                 updated_at=excluded.updated_at""",
            (tid, mode, content, now()),
        )

    async def set_prompt_mode(self, tid: int, mode: str) -> None:
        await self.db.execute(
            """INSERT INTO system_prompts (user_id, mode, updated_at) VALUES (?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET mode=excluded.mode, updated_at=excluded.updated_at""",
            (tid, mode, now()),
        )

    async def clear_system_prompt(self, tid: int) -> None:
        await self.db.execute("DELETE FROM system_prompts WHERE user_id=?", (tid,))

    # ============================ proyectos ===============================
    async def create_project(self, user_id: int, name: str, path: str) -> int:
        return await self.db.insert(
            "INSERT INTO projects (user_id, name, path) VALUES (?,?,?)", (user_id, name, path))

    async def list_projects(self, user_id: int) -> list[dict]:
        return [dict(r) for r in await self.db.all(
            "SELECT * FROM projects WHERE user_id=? AND archived=0 ORDER BY id DESC", (user_id,))]

    async def get_project(self, pid: int) -> dict | None:
        return _rowdict(await self.db.one("SELECT * FROM projects WHERE id=?", (pid,)))

    async def get_project_by_name(self, user_id: int, name: str) -> dict | None:
        return _rowdict(await self.db.one(
            "SELECT * FROM projects WHERE user_id=? AND name=? AND archived=0", (user_id, name)))

    async def update_project(self, pid: int, **fields) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        await self.db.execute(f"UPDATE projects SET {sets} WHERE id=?",
                              (*fields.values(), pid))

    async def delete_project(self, pid: int) -> None:
        await self.db.execute("DELETE FROM projects WHERE id=?", (pid,))
        await self.db.execute("DELETE FROM git_state WHERE project_id=?", (pid,))

    # ============================ conversaciones ==========================
    async def create_conversation(self, user_id: int, project_id: int | None,
                                  provider: str, model: str, title: str = "") -> int:
        return await self.db.insert(
            "INSERT INTO conversations (user_id, project_id, provider, model, title) VALUES (?,?,?,?,?)",
            (user_id, project_id, provider, model, title))

    async def get_conversation(self, cid: int) -> dict | None:
        return _rowdict(await self.db.one("SELECT * FROM conversations WHERE id=?", (cid,)))

    async def list_conversations(self, user_id: int, limit: int = 20) -> list[dict]:
        return [dict(r) for r in await self.db.all(
            """SELECT c.*, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) AS n_msgs
               FROM conversations c WHERE c.user_id=? ORDER BY c.id DESC LIMIT ?""",
            (user_id, limit))]

    async def touch_conversation(self, cid: int, provider: str | None = None,
                                 model: str | None = None, title: str | None = None) -> None:
        sets = ["updated_at=?"]
        vals: list = [now()]
        for col, v in (("provider", provider), ("model", model), ("title", title)):
            if v is not None:
                sets.append(f"{col}=?")
                vals.append(v)
        await self.db.execute(f"UPDATE conversations SET {', '.join(sets)} WHERE id=?",
                              (*vals, cid))

    async def delete_conversation(self, cid: int) -> None:
        await self.db.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
        await self.db.execute("DELETE FROM conversations WHERE id=?", (cid,))

    # ============================ mensajes ================================
    async def add_message(self, cid: int, role: str, content: str | None = None, *,
                          tool_calls: Any = None, tool_call_id: str | None = None,
                          name: str | None = None, tokens_in: int = 0,
                          tokens_out: int = 0, cost: float = 0.0) -> int:
        return await self.db.insert(
            """INSERT INTO messages (conversation_id, role, content, tool_calls, tool_call_id,
               name, tokens_in, tokens_out, cost) VALUES (?,?,?,?,?,?,?,?,?)""",
            (cid, role, content,
             json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
             tool_call_id, name, tokens_in, tokens_out, cost))

    async def get_messages(self, cid: int, limit: int | None = None,
                           offset_from_end: int = 0) -> list[dict]:
        rows = await self.db.all(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY id" + (
                f" LIMIT -1 OFFSET {int(offset_from_end)}" if offset_from_end else ""),
            (cid,))
        msgs = []
        for r in rows:
            d = dict(r)
            if d["tool_calls"]:
                try:
                    d["tool_calls"] = json.loads(d["tool_calls"])
                except (json.JSONDecodeError, TypeError):
                    d["tool_calls"] = None
            msgs.append(d)
        if limit:
            msgs = msgs[-limit:]
        return msgs

    async def count_messages(self, cid: int) -> int:
        row = await self.db.one("SELECT COUNT(*) AS n FROM messages WHERE conversation_id=?", (cid,))
        return row["n"] if row else 0

    async def clear_messages(self, cid: int) -> None:
        await self.db.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))

    async def search_messages(self, user_id: int, q: str, limit: int = 20) -> list[dict]:
        return [dict(r) for r in await self.db.all(
            """SELECT m.* FROM messages m JOIN conversations c ON c.id=m.conversation_id
               WHERE c.user_id=? AND m.content LIKE ? ORDER BY m.id DESC LIMIT ?""",
            (user_id, f"%{q}%", limit))]

    # ============================ uso y costes ============================
    async def record_usage(self, user_id: int, conversation_id: int | None, project_id: int | None,
                           provider: str, model: str, pt: int, ct: int, tt: int,
                           cost: float | None, currency: str = "USD") -> None:
        await self.db.execute(
            """INSERT INTO usage_log (user_id, conversation_id, project_id, provider, model,
               prompt_tokens, completion_tokens, total_tokens, cost, currency)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (user_id, conversation_id, project_id, provider, model, pt, ct, tt, cost, currency))

    async def usage_totals(self, user_id: int, since: str | None = None,
                           conversation_id: int | None = None,
                           project_id: int | None = None) -> dict:
        conds = ["user_id=?"]
        vals: list = [user_id]
        if since:
            conds.append("created_at>=?")
            vals.append(since)
        if conversation_id:
            conds.append("conversation_id=?")
            vals.append(conversation_id)
        if project_id:
            conds.append("project_id=?")
            vals.append(project_id)
        row = await self.db.one(
            f"""SELECT COALESCE(SUM(prompt_tokens),0) AS pt, COALESCE(SUM(completion_tokens),0) AS ct,
                COALESCE(SUM(total_tokens),0) AS tt, COALESCE(SUM(cost),0) AS cost,
                COUNT(*) AS calls FROM usage_log WHERE {' AND '.join(conds)}""", tuple(vals))
        return dict(row) if row else {"pt": 0, "ct": 0, "tt": 0, "cost": 0, "calls": 0}

    async def usage_by_model(self, user_id: int, since: str | None = None) -> list[dict]:
        conds, vals = ["user_id=?"], [user_id]
        if since:
            conds.append("created_at>=?")
            vals.append(since)
        return [dict(r) for r in await self.db.all(
            f"""SELECT provider, model, COUNT(*) AS calls, COALESCE(SUM(prompt_tokens),0) AS pt,
                COALESCE(SUM(completion_tokens),0) AS ct, COALESCE(SUM(total_tokens),0) AS tt,
                COALESCE(SUM(cost),0) AS cost
                FROM usage_log WHERE {' AND '.join(conds)} GROUP BY provider, model
                ORDER BY tt DESC""", tuple(vals))]

    async def usage_by_day(self, user_id: int, days: int = 30) -> list[dict]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        return [dict(r) for r in await self.db.all(
            """SELECT date(created_at) AS day, COALESCE(SUM(total_tokens),0) AS tt,
               COALESCE(SUM(cost),0) AS cost FROM usage_log
               WHERE user_id=? AND created_at>=? GROUP BY day ORDER BY day DESC LIMIT ?""",
            (user_id, since, days))]

    # ============================ presupuestos ============================
    async def get_budget(self, tid: int) -> dict:
        row = _rowdict(await self.db.one("SELECT * FROM budgets WHERE user_id=?", (tid,)))
        if not row:
            await self.db.execute("INSERT INTO budgets (user_id) VALUES (?)", (tid,))
            row = _rowdict(await self.db.one("SELECT * FROM budgets WHERE user_id=?", (tid,)))
        return row or {}

    async def set_budget(self, tid: int, **fields) -> None:
        await self.get_budget(tid)
        for k, v in fields.items():
            if v is not None:
                await self.db.execute(f"UPDATE budgets SET {k}=?, updated_at=? WHERE user_id=?",
                                      (v, now(), tid))

    # ============================ tareas ==================================
    async def create_task(self, user_id: int, chat_id: int, project_id: int | None,
                          conversation_id: int | None, kind: str, title: str,
                          max_steps: int, params: dict | None = None) -> int:
        return await self.db.insert(
            """INSERT INTO tasks (user_id, chat_id, project_id, conversation_id, kind, title,
               max_steps, params) VALUES (?,?,?,?,?,?,?,?)""",
            (user_id, chat_id, project_id, conversation_id, kind, title, max_steps,
             json.dumps(params, ensure_ascii=False) if params else None))

    async def update_task(self, tid: int, **fields) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        await self.db.execute(f"UPDATE tasks SET {sets} WHERE id=?", (*fields.values(), tid))

    async def get_task(self, tid: int) -> dict | None:
        row = _rowdict(await self.db.one("SELECT * FROM tasks WHERE id=?", (tid,)))
        if row and row.get("params"):
            try:
                row["params"] = json.loads(row["params"])
            except (json.JSONDecodeError, TypeError):
                row["params"] = None
        return row

    async def list_tasks(self, user_id: int | None = None, status: str | None = None,
                         limit: int = 20) -> list[dict]:
        conds, vals = [], []
        if user_id is not None:
            conds.append("user_id=?"); vals.append(user_id)
        if status:
            conds.append("status=?"); vals.append(status)
        where = f"WHERE {' AND '.join(conds)}" if conds else ""
        return [dict(r) for r in await self.db.all(
            f"SELECT * FROM tasks {where} ORDER BY id DESC LIMIT ?", (*vals, limit))]

    async def next_queued(self) -> dict | None:
        return _rowdict(await self.db.one(
            "SELECT * FROM tasks WHERE status='queued' ORDER BY id LIMIT 1"))

    async def recover_interrupted(self) -> int:
        cur = await self.db.one("SELECT COUNT(*) AS n FROM tasks WHERE status='running'")
        n = cur["n"] if cur else 0
        if n:
            await self.db.execute(
                """UPDATE tasks SET status='interrupted',
                   error='El bot se reinicio mientras la tarea se ejecutaba'
                   WHERE status='running'""")
        return n

    # ============================ git_state ===============================
    async def get_git_state(self, project_id: int) -> dict:
        row = _rowdict(await self.db.one("SELECT * FROM git_state WHERE project_id=?", (project_id,)))
        if not row:
            await self.db.execute(
                "INSERT INTO git_state (project_id) VALUES (?)", (project_id,))
            row = _rowdict(await self.db.one(
                "SELECT * FROM git_state WHERE project_id=?", (project_id,)))
        if row and row.get("allowed_branches"):
            try:
                row["allowed_branches"] = json.loads(row["allowed_branches"])
            except (json.JSONDecodeError, TypeError):
                row["allowed_branches"] = []
        else:
            if row:
                row["allowed_branches"] = []
        return row or {}

    async def set_git_state(self, project_id: int, **fields) -> None:
        await self.get_git_state(project_id)
        for k, v in fields.items():
            if v is None:
                continue
            if k == "allowed_branches":
                v = json.dumps(v)
            await self.db.execute(f"UPDATE git_state SET {k}=? WHERE project_id=?", (v, project_id))

    # ============================ tarifas =================================
    async def set_rate(self, provider: str, model: str, input_per_mtok: float,
                       output_per_mtok: float, currency: str = "USD",
                       cache_hit_per_mtok: float | None = None) -> None:
        await self.db.execute(
            """INSERT INTO pricing (provider, model, input_per_mtok, output_per_mtok,
               cache_hit_per_mtok, currency) VALUES (?,?,?,?,?,?)
               ON CONFLICT(provider, model) DO UPDATE SET input_per_mtok=excluded.input_per_mtok,
                 output_per_mtok=excluded.output_per_mtok,
                 cache_hit_per_mtok=excluded.cache_hit_per_mtok, currency=excluded.currency""",
            (provider, model, input_per_mtok, output_per_mtok, cache_hit_per_mtok, currency))

    async def get_rate(self, provider: str, model: str) -> dict | None:
        return _rowdict(await self.db.one(
            "SELECT * FROM pricing WHERE provider=? AND model=?", (provider, model)))

    async def list_rates(self) -> list[dict]:
        return [dict(r) for r in await self.db.all("SELECT * FROM pricing ORDER BY provider, model")]

    # ============================ memoria =================================
    async def memory_add(self, user_id: int, content: str) -> None:
        await self.db.execute("INSERT INTO memory_notes (user_id, content) VALUES (?,?)",
                              (user_id, content))

    async def memory_list(self, user_id: int, limit: int = 50) -> list[dict]:
        return [dict(r) for r in await self.db.all(
            "SELECT * FROM memory_notes WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))]

    async def memory_clear(self, user_id: int) -> int:
        row = await self.db.one("SELECT COUNT(*) AS n FROM memory_notes WHERE user_id=?", (user_id,))
        n = row["n"] if row else 0
        await self.db.execute("DELETE FROM memory_notes WHERE user_id=?", (user_id,))
        return n

    # ============================ auditoria ===============================
    async def audit(self, user_id: int | None, action: str, detail: str = "") -> None:
        await self.db.execute("INSERT INTO audit_log (user_id, action, detail) VALUES (?,?,?)",
                              (user_id, action, detail[:2000]))

    async def audit_list(self, limit: int = 30) -> list[dict]:
        return [dict(r) for r in await self.db.all(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))]

    # ============================ kv con TTL ==============================
    async def kv_set(self, key: str, value: Any, ttl_s: int | None = None) -> None:
        exp = None
        if ttl_s:
            exp = (datetime.now(timezone.utc) + timedelta(seconds=ttl_s)).strftime("%Y-%m-%d %H:%M:%S")
        await self.db.execute(
            """INSERT INTO kv (key, value, expires_at) VALUES (?,?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, expires_at=excluded.expires_at""",
            (key, json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value, exp))

    async def kv_get(self, key: str, default=None):
        row = await self.db.one("SELECT value, expires_at FROM kv WHERE key=?", (key,))
        if not row:
            return default
        if row["expires_at"] and row["expires_at"] < now():
            await self.db.execute("DELETE FROM kv WHERE key=?", (key,))
            return default
        raw = row["value"]
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    async def kv_del(self, key: str) -> None:
        await self.db.execute("DELETE FROM kv WHERE key=?", (key,))

    async def purge_expired_kv(self) -> None:
        await self.db.execute("DELETE FROM kv WHERE expires_at IS NOT NULL AND expires_at < ?",
                              (now(),))

    @staticmethod
    def new_token() -> str:
        return secrets.token_urlsafe(32)

    # ============================ perfiles multiagente ====================
    async def list_agents(self, user_id: int) -> list[dict]:
        return [dict(r) for r in await self.db.all(
            "SELECT * FROM agent_profiles WHERE user_id=? ORDER BY id", (user_id,))]

    async def upsert_agent(self, user_id: int, name: str, role: str, provider: str | None,
                           model: str | None, prompt: str | None, enabled: bool = True) -> None:
        await self.db.execute(
            """INSERT INTO agent_profiles (user_id, name, role, provider, model, prompt, enabled)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(user_id, name) DO UPDATE SET role=excluded.role,
                 provider=excluded.provider, model=excluded.model, prompt=excluded.prompt,
                 enabled=excluded.enabled""",
            (user_id, name, role, provider, model, prompt, int(enabled)))

    async def delete_agent(self, user_id: int, name: str) -> None:
        await self.db.execute("DELETE FROM agent_profiles WHERE user_id=? AND name=?",
                              (user_id, name))

    # ============================ meta de modelos =========================
    async def set_model_meta(self, provider: str, model: str, context_window: int | None,
                             max_output: int | None) -> None:
        await self.db.execute(
            """INSERT INTO model_meta (provider, model, context_window, max_output) VALUES (?,?,?,?)
               ON CONFLICT(provider, model) DO UPDATE SET context_window=excluded.context_window,
                 max_output=excluded.max_output""",
            (provider, model, context_window, max_output))

    async def get_model_meta(self, provider: str, model: str) -> dict | None:
        return _rowdict(await self.db.one(
            "SELECT * FROM model_meta WHERE provider=? AND model=?", (provider, model)))

    async def list_model_meta(self) -> list[dict]:
        return [dict(r) for r in await self.db.all("SELECT * FROM model_meta")]
