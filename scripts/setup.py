#!/usr/bin/env python3
# ============================================================================
# HJ CODE AGENT V2 - Configuracion interactiva por consola
#
# Pide por consola (el token OCULTO, no se muestra al escribirlo):
#   1. Token del bot de Telegram (@BotFather)
#   2. Tu user_id de administrador (solo ese ID obtendra respuestas)
#   3. (Opcional) API key de DeepSeek
#   4. (Opcional) Silencio total para IDs no autorizados
#
# Genera la HJ_MASTER_KEY aleatoria y escribe el .env con permisos 0600.
# Solo usa la libreria estandar: se puede ejecutar antes de instalar nada.
#
# Uso:
#   python3 scripts/setup.py                          # ./.env, rutas por defecto
#   python3 scripts/setup.py --env /ruta/.env --base-dir /opt/hj-code-agent
#
# Automatizacion (sin TTY): orden de entrada por stdin -> token, admin_id,
# deepseek_key (vacío = omitir), silencio (s/N). También puede prefijarse con
# las variables HJ_SETUP_TOKEN y HJ_SETUP_ADMIN (se usan sin preguntar).
# ============================================================================
from __future__ import annotations

import argparse
import getpass
import os
import pathlib
import re
import secrets
import stat
import sys

TOKEN_RE = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{30,}$")

BANNER = r"""
============================================================
   HJ CODE AGENT V2 - Configuracion inicial (consola)
============================================================
Voy a preguntarte 4 cosas. El token se escribe OCULTO.
"""


def _hidden(prompt: str) -> str:
    """Lee un secreto por consola: oculto en TTY, normal si stdin es pipe."""
    if sys.stdin.isatty():
        try:
            return getpass.getpass(prompt).strip()
        except Exception:  # some terminals without termios
            return input(prompt).strip()
    line = sys.stdin.readline()
    if line == "":
        return ""
    return line.strip()


def _ask_hidden_secret(label: str) -> str:
    while True:
        v = _hidden(f"{label}: ")
        if v:
            return v
        print("  ✘ No puede estar vacío, inténtalo de nuevo.")


def _ask_int(label: str) -> int:
    while True:
        raw = _hidden(f"{label}: ").strip()
        try:
            v = int(raw)
            if v <= 0:
                raise ValueError
            return v
        except ValueError:
            print("  ✘ Debe ser un número entero positivo (ej. 123456789).")


def _ask_yes_no(label: str, default: bool = False) -> bool:
    hint = "S/n" if default else "s/N"
    raw = input(f"{label} [{hint}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("s", "si", "sí", "y", "yes", "1", "true", "on")


def default_paths(base_dir: str | None) -> dict:
    root = os.geteuid() == 0
    base = base_dir or ("/opt/hj-code-agent" if root else str(pathlib.Path.home() / ".local/share/hj-code-agent"))
    data = f"{base}/data"
    return {
        "HJ_DATA_DIR": data,
        "HJ_WORKSPACES_DIR": f"{base}/workspaces",
        "HJ_BACKUPS_DIR": f"{base}/backups",
        "HJ_DB_PATH": f"{data}/hj.db",
        "HJ_LOG_FILE": f"{data}/agent.log",
        "HJ_WORKSPACES_HOST_DIR": f"{base}/workspaces",
        "HJ_MASTER_KEY_FILE": "",
    }


def build_env(token: str, admin: int, deepseek_key: str, silent: bool, base_dir: str | None) -> str:
    p = default_paths(base_dir)
    lines = [
        "# ============================================================",
        "# HJ CODE AGENT V2 - .env generado por scripts/setup.py",
        f"# Fecha: generada por consola. Permisos del archivo: 0600.",
        "# NUNCA subas este archivo a git ni lo compartas.",
        "# ============================================================",
        "",
        "# Telegram",
        f"HJ_TELEGRAM_BOT_TOKEN={token}",
        f"HJ_ADMIN_USER_IDS={admin}",
        "HJ_SILENT_REJECT=" + ("1" if silent else "0"),
        "",
        "# Cifrado (clave maestra aleatoria generada ahora - copia de seguridad fuera del VPS)",
        f"HJ_MASTER_KEY={secrets.token_urlsafe(32)}",
        f"HJ_MASTER_KEY_FILE={p['HJ_MASTER_KEY_FILE']}",
        "",
        "# Rutas",
        f"HJ_DATA_DIR={p['HJ_DATA_DIR']}",
        f"HJ_WORKSPACES_DIR={p['HJ_WORKSPACES_DIR']}",
        f"HJ_BACKUPS_DIR={p['HJ_BACKUPS_DIR']}",
        f"HJ_DB_PATH={p['HJ_DB_PATH']}",
        f"HJ_LOG_FILE={p['HJ_LOG_FILE']}",
        "",
        "# Proveedor inicial (DeepSeek). La key se guarda CIFRADA en la BBDD via /setapi;",
        "# aqui solo se siembra si la has introducido ahora.",
        "HJ_DEFAULT_PROVIDER=deepseek",
        "HJ_DEEPSEEK_BASE_URL=https://api.deepseek.com",
        f"HJ_DEEPSEEK_API_KEY={deepseek_key}",
        "HJ_GITHUB_TOKEN=",
        "",
        "# Sandbox",
        "HJ_SANDBOX_BACKEND=auto",
        "HJ_SANDBOX_IMAGE=python:3.12-slim",
        "HJ_SANDBOX_MEMORY_MB=512",
        "HJ_SANDBOX_CPUS=1.0",
        "HJ_SANDBOX_PIDS=128",
        "HJ_SANDBOX_TIMEOUT_S=120",
        "HJ_SANDBOX_NETWORK=1",
        f"HJ_WORKSPACES_HOST_DIR={p['HJ_WORKSPACES_HOST_DIR']}",
        "",
        "# Limites del agente",
        "HJ_MAX_TASK_STEPS=24",
        "HJ_MAX_CONCURRENT_TASKS=2",
        "",
        "# Limites de subidas",
        "HJ_MAX_FILE_MB=20",
        "HJ_MAX_ZIP_FILES=2000",
        "HJ_MAX_ZIP_UNPACKED_MB=200",
        "",
        "# Formulario seguro /setapi (solo loopback; usar tunel SSH)",
        "HJ_FORM_HOST=127.0.0.1",
        "HJ_FORM_PORT=8977",
        "HJ_FORM_BASE_URL=",
        "",
        "# Logs",
        "HJ_LOG_LEVEL=INFO",
    ]
    return "\n".join(lines) + "\n"


def write_env(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # por si venia permisivo
        backup = path.with_suffix(path.suffix + ".bak")
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        os.chmod(backup, stat.S_IRUSR | stat.S_IWUSR)
        print(f"  · .env existente copiado a {backup.name}")
    path.write_text(content, encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600


def ensure_data_dirs(env_path: pathlib.Path, base_dir: str | None) -> None:
    p = default_paths(base_dir)
    for key in ("HJ_DATA_DIR", "HJ_WORKSPACES_DIR", "HJ_BACKUPS_DIR"):
        d = pathlib.Path(p[key])
        try:
            d.mkdir(parents=True, exist_ok=True)
            if key == "HJ_DATA_DIR":
                os.chmod(d, stat.S_IRWXU)  # 0700
        except PermissionError:
            print(f"  ⚠ No pude crear {d} (permisos). Créalo a mano antes de arrancar.")


def mask(v: str) -> str:
    return (v[:4] + "…" + v[-4:]) if len(v) > 10 else "•••"


def main() -> int:
    ap = argparse.ArgumentParser(description="Configuración interactiva de HJ Code Agent V2")
    ap.add_argument("--env", default=".env", help="ruta del .env a generar")
    ap.add_argument("--base-dir", default=None, help="directorio base para rutas de datos")
    args = ap.parse_args()
    env_path = pathlib.Path(args.env).expanduser().resolve()

    print(BANNER)
    preset_token = os.environ.get("HJ_SETUP_TOKEN", "").strip()
    preset_admin = os.environ.get("HJ_SETUP_ADMIN", "").strip()

    # 1. Token del bot (oculto)
    if preset_token:
        token = preset_token
        print(f"Token del bot: (prefijado por entorno) {mask(token)}")
    else:
        print("1) Token del bot de Telegram. Créalo con @BotFather (/newbot).")
        token = _ask_hidden_secret("   Token del bot")
        while not TOKEN_RE.match(token):
            print("  ✘ Formato inválido. Debe ser algo como 1234567890:AAE..._xyz (35+ chars).")
            token = _ask_hidden_secret("   Token del bot")

    # 2. Admin ID
    if preset_admin:
        try:
            admin = int(preset_admin)
            print(f"Admin user_id: {admin} (prefijado por entorno)")
        except ValueError:
            print("  ✘ HJ_SETUP_ADMIN no es un número válido", file=sys.stderr)
            return 2
    else:
        print("\n2) Tu user_id de Telegram (envía cualquier mensaje a @userinfobot para verlo).")
        print("   SOLO ese ID recibirá respuestas del bot; el resto de usuarios son ignorados.")
        admin = _ask_int("   Admin user_id")

    # 3. DeepSeek (opcional)
    print("\n3) API key de DeepSeek (opcional; también puedes configurarla luego con /setapi).")
    deepseek = _hidden("   API key de DeepSeek [Enter para omitir]: ")

    # 4. Silencio total (opcional)
    silent = False
    if sys.stdin.isatty():
        print("\n4) ¿Silencio total para IDs no autorizados? (ni un aviso; por defecto se les")
        print("   envía UN solo aviso con su user_id y luego son ignorados)")
        silent = _ask_yes_no("   Silencio total")
    else:
        line = sys.stdin.readline()
        raw = line.strip().lower() if line else ""
        silent = raw in ("s", "si", "sí", "y", "yes", "1", "true", "on")

    content = build_env(token, admin, deepseek, silent, args.base_dir)
    write_env(env_path, content)
    ensure_data_dirs(env_path, args.base_dir)

    print("\n────────────────────────────────────────────")
    print(f"✔ .env escrito en {env_path} (permisos 0600)")
    print(f"  Token bot : {mask(token)}")
    print(f"  Admin     : {admin}  (solo este ID obtiene respuestas)")
    print(f"  DeepSeek  : {'sembrada ' + mask(deepseek) if deepseek else 'sin configurar → usa /setapi deepseek en Telegram'}")
    print("  Master key: generada aleatoriamente (guarda copia fuera del VPS)")
    print("────────────────────────────────────────────")
    print("Siguientes pasos:")
    print("  sudo systemctl start hj-code-agent   # o: python -m bot.main en desarrollo")
    print("  journalctl -u hj-code-agent -f       # ver logs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
