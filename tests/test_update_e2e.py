"""Tests e2e de scripts/update.sh: simulan los fallos reales del actualizador.

A diferencia de test_update_safety.py (analisis estatico del texto), estos
tests EJECUTAN el update.sh real contra una instalacion falsa pero fiel:

- systemctl / journalctl / id / tar son shims controlados (el resto son los
  binarios reales); el log de systemctl permite afirmar si el servicio quedo
  arrancado o parado tras un fallo.
- El python del venv es un shim: ejecuta el python REAL para db_tools.py y
  para las migraciones (SQLite de verdad), simula "pip install" y puede
  simular el fallo del checkpoint (HJ_FAIL_CHECKPOINT=1).
- La BD previa es SQLite de verdad con el esquema 0001 del repo.
- En la copia del codigo nuevo se INYECTAN migraciones: 99998 (valida, escribe
  y compromete) + 99999 (SQL invalido, explota) -> reproduce exactamente el
  escenario "db.migrate() aplica parcialmente cambios y luego falla".

Bugs que estos tests reproducen del script anterior:
  A. tar / checkpoint fallando despues de "systemctl stop" dejaban el bot
     PARADO (die() y set -e no reiniciaban nada).
  B. MIGRATED=1 se marcaba AL FINAL: un fallo parcial de migracion no
     restauraba la BD previa.
  C. HJ_DB_PATH del .env / entorno se ignoraba: se migraba data/hj.db aunque
     la instalacion usara otra ruta.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PYEXE = sys.executable

OLD_VERSION = '__version__ = "2.9.9"\n'
NEW_VERSION = '__version__ = "3.0.0"\n'
MIG_OK = "99998_hj_test_partial.sql"    # valida: crea tabla y compromete
MIG_FAIL = "99999_hj_test_fail.sql"     # invalida: revienta tras la parcial

ORIGINALES = ["dato-que-debe-perdurar", "en-el-wal"]


# ----------------------------------------------------------------- entorno ---

def _make_db(path: Path) -> None:
    """BD real con el esquema 0001 del repo + datos propios del harness."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.executescript((REPO / "database" / "migrations" / "0001_init.sql").read_text())
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("INSERT INTO schema_version (version) VALUES (1)")
    con.execute("CREATE TABLE harness_original (nota TEXT)")
    con.execute("INSERT INTO harness_original VALUES ('dato-que-debe-perdurar')")
    con.execute("INSERT INTO harness_original VALUES ('en-el-wal')")
    con.commit()
    con.close()


def _shim(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def build_env(tmp_path: Path, dotenv_db: Path | None = None,
              create_default_db: bool = True) -> dict:
    """Instalacion falsa de $BASE_DIR con app/, data/, venv y shims."""
    base = tmp_path / "base"
    app = base / "app"
    (app / "core").mkdir(parents=True)
    (app / "core" / "__init__.py").write_text(OLD_VERSION)
    shutil.copy(REPO / "pyproject.toml", app / "pyproject.toml")

    # python del venv: shim (pip simulado; python real para SQLite/migraciones)
    vbin = base / "venv" / "bin"
    vbin.mkdir(parents=True)
    _shim(vbin / "python", f"""#!/usr/bin/env bash
# shim de prueba del python del venv.
# Solo falla cuando el ULTIMO argumento es la accion "checkpoint" (el nombre
# del tmp de pytest puede contener "checkpoint" sin que sea la accion).
_last="${{*: -1}}"
if [ "${{HJ_FAIL_CHECKPOINT:-0}}" = "1" ] && [ "$_last" = "checkpoint" ] \\
   && [[ "$*" == *db_tools.py* ]]; then
  echo "shim: checkpoint simulado como FALLO" >&2
  exit 7
fi
if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then
  echo "(pip simulado ok)"
  exit 0
fi
exec "{PYEXE}" "$@"
""")

    data = base / "data"
    data.mkdir(parents=True)
    if create_default_db:
        _make_db(data / "hj.db")

    env_lines = ["HJ_TELEGRAM_BOT_TOKEN=token-de-prueba", "HJ_ADMIN_USER_IDS=111"]
    if dotenv_db is not None:
        env_lines.append(f"HJ_DB_PATH={dotenv_db}")
    (app / ".env").write_text("\n".join(env_lines) + "\n")

    shims = tmp_path / "shims"
    shims.mkdir()
    _shim(shims / "systemctl", """#!/usr/bin/env bash
echo "$*" >> "$HJ_SYSTEMCTL_LOG"
case "$1" in
  stop) rm -f "$HJ_SYSTEMCTL_STATE"; exit 0;;
  start) touch "$HJ_SYSTEMCTL_STATE"; exit 0;;
  is-active) if [ -f "$HJ_SYSTEMCTL_STATE" ]; then exit 0; else exit 3; fi;;
  show) exit 0;;   # sin User= no-root: el update usara el propietario de data/
  *) exit 0;;
esac
""")
    _shim(shims / "journalctl", '#!/usr/bin/env bash\necho "INFO: Bot en marcha. Polling activo."\n')
    real_id = shutil.which("id")
    _shim(shims / "id", f"""#!/usr/bin/env bash
# solo falsifica root en "id -u" SIN usuario; "id -u <usuario>" es real
if [ "$#" -eq 1 ] && [ "$1" = "-u" ]; then echo 0; else exec "{real_id}" "$@"; fi
""")
    real_tar = shutil.which("tar")
    _shim(shims / "tar", f"""#!/usr/bin/env bash
if [ -n "${{HJ_FAIL_TAR:-}}" ] && [[ "$*" == *"$HJ_FAIL_TAR"* ]]; then
  echo "tar: fallo simulado ($HJ_FAIL_TAR)" >&2
  exit 2
fi
exec "{real_tar}" "$@"
""")
    return {
        "base": base, "app": app, "data": data, "shims": shims,
        "log": tmp_path / "systemctl.log", "state": tmp_path / "state",
    }


def make_src(tmp_path: Path, migrations: str = "none") -> Path:
    """Copia del repositorio como 'codigo nuevo', con migraciones inyectadas."""
    src = tmp_path / "src"
    shutil.copytree(REPO, src, ignore=shutil.ignore_patterns(
        ".git", "__pycache__", ".venv", "*.pyc"))
    mdir = src / "database" / "migrations"
    if migrations in ("ok", "both"):
        (mdir / MIG_OK).write_text(
            "CREATE TABLE IF NOT EXISTS hj_test_partial (valor INTEGER);\n"
            "INSERT INTO hj_test_partial VALUES (42);\n")
    if migrations == "both":
        (mdir / MIG_FAIL).write_text(
            "INSERT INTO hj_test_tabla_que_no_existe VALUES (1);\n")
    override = os.environ.get("HJ_UPDATE_SH_OVERRIDE")
    if override:
        shutil.copy(override, src / "scripts" / "update.sh")
    return src


def run_update(env: dict, src: Path, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    environ = os.environ.copy()
    environ.pop("HJ_DB_PATH", None)  # el entorno del sandbox no debe filtrarse
    environ["PATH"] = f"{env['shims']}:{environ['PATH']}"
    environ["HJ_BASE_DIR"] = str(env["base"])
    environ["HJ_SYSTEMCTL_LOG"] = str(env["log"])
    environ["HJ_SYSTEMCTL_STATE"] = str(env["state"])
    environ.update({k: str(v) for k, v in (extra_env or {}).items()})
    return subprocess.run(
        ["bash", str(src / "scripts" / "update.sh"), str(src)],
        env=environ, capture_output=True, text=True, timeout=300,
    )


def svc_actions(env: dict) -> list[str]:
    """Acciones stop/start que vio el systemctl simulado, en orden."""
    out = []
    for line in env["log"].read_text().splitlines():
        parts = line.split()
        if parts and parts[0] in ("stop", "start"):
            out.append(parts[0])
    return out


def db_state(path: Path) -> dict:
    con = sqlite3.connect(str(path))
    try:
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        ver = con.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        originals = ([r[0] for r in con.execute("SELECT nota FROM harness_original")]
                     if "harness_original" in tables else None)
        partial = ([r[0] for r in con.execute("SELECT valor FROM hj_test_partial")]
                   if "hj_test_partial" in tables else None)
        integ = con.execute("PRAGMA integrity_check").fetchone()[0]
        return {"tables": tables, "version": ver, "originals": originals,
                "partial": partial, "integrity": integ}
    finally:
        con.close()


# ------------- Bug A: fallo del backup tras stop deja el bot PARADO ----------

def test_fallo_tar_tras_stop_reinicia_el_servicio(tmp_path):
    """tar de data/ falla despues de systemctl stop -> el script aborta y el
    servicio ANTERIOR vuelve a arrancar (antes: die() lo dejaba parado)."""
    env = build_env(tmp_path)
    src = make_src(tmp_path)
    proc = run_update(env, src, {"HJ_FAIL_TAR": "data.tar.gz"})

    assert proc.returncode != 0
    acts = svc_actions(env)
    assert "stop" in acts
    assert acts[-1] == "start", f"el bot quedo parado; acciones: {acts}"
    # el fallo fue ANTES de tocar nada: codigo y BD intactos
    assert (env["app"] / "core" / "__init__.py").read_text() == OLD_VERSION
    st = db_state(env["data"] / "hj.db")
    assert st["originals"] == ORIGINALES and st["version"] == 1
    assert st["integrity"] == "ok"


def test_fallo_checkpoint_aborta_reinicia_y_no_toca_nada(tmp_path):
    """checkpoint WAL falla -> rollback inmediato con servicio en marcha y sin
    ninguna modificacion (antes: solo un aviso y seguia actualizando igual)."""
    env = build_env(tmp_path)
    src = make_src(tmp_path)
    proc = run_update(env, src, {"HJ_FAIL_CHECKPOINT": "1"})

    assert proc.returncode != 0
    assert "FALLO" in proc.stdout
    assert svc_actions(env)[-1] == "start"
    # nada fue actualizado: la version del codigo sigue siendo la anterior
    assert (env["app"] / "core" / "__init__.py").read_text() == OLD_VERSION
    st = db_state(env["data"] / "hj.db")
    assert st["version"] == 1 and st["integrity"] == "ok"
    assert st["originals"] == ORIGINALES


# -------- Bug B: migracion parcial dejaba la BD modificada sin restaurar -----

def test_migracion_parcial_fallida_restaura_la_bd_y_reinicia(tmp_path):
    """99998 escribe y compromete; 99999 explota -> el rollback debe restaurar
    la BD previa (sin la tabla parcial) y reiniciar el servicio. Con el script
    antiguo (MIGRATED=1 al final) la tabla parcial quedaba escrita."""
    env = build_env(tmp_path)             # BD por defecto dentro de data/
    src = make_src(tmp_path, migrations="both")
    proc = run_update(env, src)

    assert proc.returncode != 0
    acts = svc_actions(env)
    assert "stop" in acts and acts[-1] == "start"
    # rollback completo: el codigo vuelve a la version anterior
    assert (env["app"] / "core" / "__init__.py").read_text() == OLD_VERSION
    # BD restaurada EXACTAMENTE al estado previo
    st = db_state(env["data"] / "hj.db")
    assert st["partial"] is None, "la escritura parcial de la migracion quedo en la BD"
    assert st["version"] == 1
    assert st["originals"] == ORIGINALES
    assert st["integrity"] == "ok"
    # sin -wal/-shm residuales de la migracion a medias
    wal = Path(str(env["data"] / "hj.db") + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0
    # la data descartada se conserva para analisis, no se borra
    assert list(env["base"].glob("data.pre-rollback-*")), \
        "la data parcialmente migrada deberia conservarse en data.pre-rollback-*"
    # .env intacto tras el rollback
    assert "HJ_TELEGRAM_BOT_TOKEN=token-de-prueba" in (env["app"] / ".env").read_text()


def test_migracion_parcial_con_hj_db_path_externo_restaura_esa_bd(tmp_path):
    """Igual que el anterior pero con HJ_DB_PATH del .env apuntando FUERA de
    data/: el backup/restore por fichero debe cubrir esa ruta tambien."""
    extdb = tmp_path / "extdb" / "agentes.db"
    env = build_env(tmp_path, dotenv_db=extdb, create_default_db=False)
    _make_db(extdb)
    src = make_src(tmp_path, migrations="both")
    proc = run_update(env, src)

    assert proc.returncode != 0
    assert svc_actions(env)[-1] == "start"
    st = db_state(extdb)
    assert st["partial"] is None
    assert st["version"] == 1
    assert st["originals"] == ORIGINALES
    assert st["integrity"] == "ok"
    wal = Path(str(extdb) + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0


# --------------- Bug C: HJ_DB_PATH ignorado por el actualizador --------------

def test_update_exitoso_aplica_migraciones_en_hj_db_path_del_env_file(tmp_path):
    """.env con HJ_DB_PATH externo: las migraciones se aplican a ESA base, la
    default data/hj.db no se crea ni se toca, y el update termina en verde."""
    custom = tmp_path / "extdb" / "agentes.db"
    env = build_env(tmp_path, dotenv_db=custom, create_default_db=False)
    _make_db(custom)
    src = make_src(tmp_path, migrations="ok")
    proc = run_update(env, src)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    st = db_state(custom)
    assert st["partial"] == [42]          # 99998 aplicada en la BD CORRECTA
    assert st["version"] == 99998
    assert st["originals"] == ORIGINALES
    assert st["integrity"] == "ok"
    assert not (env["data"] / "hj.db").exists()   # la default no se toco
    acts = svc_actions(env)
    assert "stop" in acts and acts[-1] == "start"
    assert '"3.0.0"' in (env["app"] / "core" / "__init__.py").read_text()
    assert "Actualizacion completada" in proc.stdout


def test_hj_db_path_del_entorno_tiene_prioridad_sobre_el_dotenv(tmp_path):
    """HJ_DB_PATH en el entorno de update.sh manda sobre el .env (igual que el
    orden de variables del bot)."""
    envdb = tmp_path / "extdb" / "primera.db"
    dotenvdb = tmp_path / "extdb" / "segunda.db"
    env = build_env(tmp_path, dotenv_db=dotenvdb, create_default_db=False)
    _make_db(envdb)
    _make_db(dotenvdb)
    src = make_src(tmp_path, migrations="ok")
    proc = run_update(env, src, {"HJ_DB_PATH": str(envdb)})

    assert proc.returncode == 0, proc.stdout + proc.stderr
    st1 = db_state(envdb)
    assert st1["partial"] == [42] and st1["version"] == 99998
    st2 = db_state(dotenvdb)
    assert st2["partial"] is None and st2["version"] == 1  # la del .env intacta
