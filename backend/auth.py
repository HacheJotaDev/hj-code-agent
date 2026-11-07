"""Autenticacion web: usuarios, sesiones en BD, CSRF y limites de peticiones.

- Contraseñas con scrypt (stdlib) + salt aleatorio por usuario.
- Sesiones server-side: solo el SHA-256 del token se persiste; el token viaja
  en cookie HttpOnly SameSite=Strict (Secure automatico fuera de localhost).
- CSRF: token por sesion que el frontend envia en la cabecera X-CSRF-Token en
  toda peticion no segura.
- Rate limit en memoria (por IP en login, por sesion en la API).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

SESSION_COOKIE = "hj_web_session"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_LOGIN_WINDOW_S = 60


# --------------------------- contraseñas --------------------------------


def hash_password(password: str) -> str:
    if not password or len(password) < 8:
        raise ValueError("La contraseña debe tener al menos 8 caracteres")
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${h.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, hash_hex = (stored or "").split("$")
        if scheme != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
                              n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calc.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


# --------------------------- usuarios web --------------------------------


async def create_web_user(store, username: str, password: str, agent_uid: int,
                          is_admin: bool = True) -> int:
    username = (username or "").strip().lower()
    if not username or not all(c.isalnum() or c in "._-@" for c in username):
        raise ValueError("Nombre de usuario invalido")
    web_uid = await store.db.insert(
        "INSERT INTO web_users (username, password_hash, agent_uid, is_admin) VALUES (?,?,?,?)",
        (username, hash_password(password), int(agent_uid), int(is_admin)))
    return web_uid


async def count_web_users(store) -> int:
    row = await store.db.one("SELECT COUNT(*) AS n FROM web_users")
    return int(row["n"]) if row else 0


async def bootstrap_web_user(settings, store) -> None:
    """Crea el primer usuario web SOLO si la tabla esta vacia y hay contraseña."""
    if await count_web_users(store):
        return
    if not settings.web_password:
        log.warning("V4 web: no hay usuarios web y HJ_WEB_PASSWORD no esta definida; "
                    "el panel web quedara sin login hasta configurarla")
        return
    uid = int(settings.web_agent_uid or 0)
    if not uid and settings.admin_user_ids:
        uid = int(settings.admin_user_ids[0])
    await create_web_user(store, settings.web_username, settings.web_password, uid, True)
    await store.audit(uid or 0, "web.bootstrap_user", settings.web_username)
    log.info("V4 web: usuario '%s' creado (agente uid=%s)", settings.web_username, uid)


async def get_web_user_by_name(store, username: str) -> dict | None:
    row = await store.db.one("SELECT * FROM web_users WHERE username=?", (username.lower(),))
    return dict(row) if row else None


# --------------------------- sesiones ------------------------------------


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


async def create_session(store, web_user_id: int, ip: str = "", ua: str = "",
                         ttl_h: int = 72) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() + ttl_h * 3600))
    await store.db.execute(
        "INSERT INTO web_sessions (token_hash, web_user_id, csrf_token, expires_at, ip, user_agent) "
        "VALUES (?,?,?,?,?,?)", (token_hash, web_user_id, csrf, expires, ip[:64], ua[:200]))
    return token, csrf


async def get_session(store, token: str) -> dict | None:
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    row = await store.db.one("SELECT * FROM web_sessions WHERE token_hash=?", (token_hash,))
    if not row:
        return None
    sess = dict(row)
    if sess["expires_at"] <= _now():
        await store.db.execute("DELETE FROM web_sessions WHERE token_hash=?", (token_hash,))
        return None
    return sess


async def delete_session(store, token: str) -> None:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    await store.db.execute("DELETE FROM web_sessions WHERE token_hash=?", (token_hash,))


async def purge_sessions(store) -> None:
    await store.db.execute("DELETE FROM web_sessions WHERE expires_at <= ?", (_now(),))


def cookie_secure(settings) -> bool:
    if settings.web_secure_cookies is not None:
        return bool(settings.web_secure_cookies)
    return settings.web_host not in ("127.0.0.1", "localhost", "::1")


def set_session_cookie(response, token: str, settings) -> None:
    response.set_cookie(
        SESSION_COOKIE, token,
        max_age=int(settings.web_session_ttl_h) * 3600,
        httponly=True, secure=cookie_secure(settings),
        samesite="strict", path="/")


def clear_session_cookie(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


# --------------------------- rate limiting -------------------------------


class RateLimiter:
    """Ventana deslizante en memoria (suficiente para un VPS de un solo nodo)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_s: float = 60.0) -> bool:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > window_s:
            q.popleft()
        if len(q) >= max(limit, 1):
            return False
        q.append(now)
        return True

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)


@dataclass
class AuthedRequest:
    """Todo lo que un endpoint necesita del usuario autenticado."""
    store: Any
    settings: Any
    ctx: Any                    # AppContext (motor V3)
    web_user: dict
    session: dict
    agent_uid: int              # UID de HJ con el que trabaja el motor

    @property
    def username(self) -> str:
        return self.web_user["username"]
