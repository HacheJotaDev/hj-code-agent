"""Filtrado de comandos y entorno para ejecucion en sandbox.

Nota honesta: una lista de denegacion nunca es una garantia absoluta; el
aislamiento real lo dan los contenedores (docker sandbox). Esta capa bloquea
patrones claramente peligrosos y evita filtrar secretos por entorno.
"""
from __future__ import annotations

import os
import re


class CommandDenied(Exception):
    pass


# Patrones que el agente y el usuario no pueden ejecutar en el sandbox
_DANGER = [
    (r"\bsudo\b", "uso de sudo"),
    (r"\bsu\s+-?\w", "cambio de usuario"),
    (r"\bmkfs(\.\w+)?\b", "formateo de sistema de archivos"),
    (r"\bdd\s+[^|]*of=/dev/", "escritura directa en dispositivo"),
    (r"\b(shutdown|reboot|poweroff|halt|init)\b", "apagado del sistema"),
    (r"rm\s+-rf\s+/(?:\s|$)", "borrado del sistema de archivos raiz"),
    (r"\bchmod\s+777\s+/\s*$", "chmod masivo en raiz"),
    (r"\bchown\b\s+-R\s+\w+:\w+\s+/\s*$", "chown masivo en raiz"),
    (r"\b(docker|podman|ctr|crictl|nsenter|unshare)\b", "acceso a contenedores/namespaces del host"),
    (r"\bmount\b", "montaje de sistemas de archivos"),
    (r"\biptables\b|\bnft\b", "manipulacion del firewall"),
    (r"(curl|wget)\b[^|;]*\|\s*(sudo\s+)?(ba)?sh", "ejecucion de codigo descargado por pipe"),
    (r"/dev/(sd[a-z]|nvme|vd[a-z])", "acceso a discos del host"),
    (r"/proc/1/", "acceso al proceso 1 del host"),
    (r">\s*/dev/sd[a-z]", "escritura en disco del host"),
    (r"\bssh\b\s+.*(root|@localhost|@127\.0\.0\.1)", "ssh hacia el host"),
    (r"/var/run/docker\.sock", "acceso al socket de Docker"),
    (r"\bapt(-get)?\s+.*(-y|--yes)\s+install\s+.*(sudo|policykit)", "instalacion de escalada de privilegios"),
]

SECRET_ENV_KEYS = {
    "TELEGRAM_BOT_TOKEN", "HJ_TELEGRAM_BOT_TOKEN", "BOT_TOKEN",
    "DEEPSEEK_API_KEY", "HJ_DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
    "GITHUB_TOKEN", "HJ_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PAT",
    "HJ_MASTER_KEY", "MASTER_KEY", "HJ_FORM_PORT", "HJ_ADMIN_USER_IDS",
}

# Variables que se propagan al sandbox (lista blanca)
_ENV_WHITELIST = [
    "PATH", "LANG", "LC_ALL", "TERM", "TZ", "PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE",
    "npm_config_registry", "PIP_INDEX_URL", "PIP_DEFAULT_TIMEOUT", "HTTP_PROXY", "HTTPS_PROXY",
    "NO_PROXY", "CI",
]


def screen_command(cmd: str) -> None:
    """Lanza CommandDenied si el comando esta prohibido."""
    c = cmd or ""
    for pattern, reason in _DANGER:
        if re.search(pattern, c, flags=re.IGNORECASE):
            raise CommandDenied(f"Comando bloqueado por politica de seguridad ({reason})")


def clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Construye un entorno minimo SIN secretos del host."""
    env: dict[str, str] = {}
    for k in _ENV_WHITELIST:
        if k in os.environ and os.environ[k]:
            env[k] = os.environ[k]
    env.setdefault("HOME", "/tmp")
    env.setdefault("PYTHONUNBUFFERED", "1")
    if extra:
        for k, v in extra.items():
            k = str(k)
            if k in SECRET_ENV_KEYS or "TOKEN" in k.upper() or "SECRET" in k.upper() or "KEY" in k.upper():
                raise CommandDenied(f"Variable de entorno prohibida: {k}")
            env[k] = str(v)
    return env
