"""Asistente por consola: pide token del bot + admin ID y escribe .env 0600.

El token y el admin id NO van en archivos de ejemplo ni en el repo: los pide
scripts/setup.py por consola (token oculto en TTY).
"""
import os
import stat
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SETUP = REPO / "scripts" / "setup.py"

FAKE_TOKEN = "1234567890:AAE-fake-token-1234567890123456789AB"


def _run(tmp_path, stdin: str, extra_env: dict | None = None):
    env_out = tmp_path / ".env"
    env = os.environ.copy()
    for k in ("HJ_SETUP_TOKEN", "HJ_SETUP_ADMIN"):
        env.pop(k, None)
    env.update(extra_env or {})
    proc = subprocess.run(
        [sys.executable, str(SETUP), "--env", str(env_out), "--base-dir", str(tmp_path / "base")],
        input=stdin, capture_output=True, text=True, cwd=tmp_path, env=env, timeout=120,
    )
    return proc, env_out


def test_setup_consola_pide_token_y_admin(tmp_path):
    proc, env_out = _run(tmp_path, f"{FAKE_TOKEN}\n424242\n\nn\n")
    assert proc.returncode == 0, proc.stderr
    content = env_out.read_text(encoding="utf-8")
    assert f"HJ_TELEGRAM_BOT_TOKEN={FAKE_TOKEN}" in content
    assert "HJ_ADMIN_USER_IDS=424242" in content
    assert "HJ_MASTER_KEY=" in content and "HJ_MASTER_KEY= \n" not in content
    assert stat.S_IMODE(env_out.stat().st_mode) == 0o600   # permisos 0600
    assert "424242" in proc.stdout                          # confirma el admin


def test_setup_consola_token_invalido_reintenta(tmp_path):
    # token basura -> reintenta -> token valido -> admin
    proc, env_out = _run(tmp_path, f"no-es-un-token\n{FAKE_TOKEN}\n424242\nsk-xxx\ns\n")
    assert proc.returncode == 0, proc.stderr
    content = env_out.read_text(encoding="utf-8")
    assert f"HJ_TELEGRAM_BOT_TOKEN={FAKE_TOKEN}" in content
    assert "HJ_SILENT_REJECT=1" in content                  # respondió "s" al silencio
    assert "HJ_DEEPSEEK_API_KEY=sk-xxx" in content          # deepseek sembrada


def test_setup_consola_prefijos_de_entorno(tmp_path):
    proc, env_out = _run(tmp_path, "n\n", {"HJ_SETUP_TOKEN": FAKE_TOKEN, "HJ_SETUP_ADMIN": "777"})
    assert proc.returncode == 0, proc.stderr
    content = env_out.read_text(encoding="utf-8")
    assert f"HJ_TELEGRAM_BOT_TOKEN={FAKE_TOKEN}" in content
    assert "HJ_ADMIN_USER_IDS=777" in content


def test_setup_consola_admin_no_numerico_falla(tmp_path):
    proc, _ = _run(tmp_path, f"{FAKE_TOKEN}\n", {"HJ_SETUP_ADMIN": "abc"})
    assert proc.returncode == 2
