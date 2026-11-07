"""Tests de seguridad de actualizacion y aislamiento Docker (revision VPS).

Cada test corresponde a un bug real detectado antes de instalar en el VPS:
1. update.sh forzaba el usuario "hjagent" (el servicio real corre como otro,
   p. ej. "hjcode") -> riesgo de perder acceso a SQLite/boveda/proyectos.
2. Sin HJ_DOCKER_HOST, la CLI de docker usaba el daemon PRINCIPAL del host.
3. El sandbox montaba la raiz GENERAL de workspaces (todos los proyectos).
4. Backup de SQLite con el bot escribiendo (sin checkpoint WAL) y rollback
   que no restauraba datos ni permisos.

Las pruebas 2 y 3 se verifican con mocks del binario docker; la ejecucion
REAL de Docker rootless requiere el VPS (documentado en docs/ESTADO.md).
"""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from core.config import Settings
from core.sandbox import factory
from core.sandbox.base import ExecutionUnavailable
from core.sandbox.docker_sandbox import DockerSandbox

REPO = Path(__file__).resolve().parents[1]


def make_settings(tmp_path, **extra) -> Settings:
    s = Settings(
        HJ_TELEGRAM_BOT_TOKEN="t",
        HJ_ADMIN_USER_IDS="111",
        HJ_DATA_DIR=tmp_path / "data",
        HJ_WORKSPACES_DIR=tmp_path / "workspaces",
        HJ_BACKUPS_DIR=tmp_path / "backups",
        HJ_SANDBOX_MEMORY_MB=256,
        HJ_SANDBOX_TIMEOUT_S=10,
        **extra,
    )
    s.ensure_dirs()
    return s


# =========================== Bug 2: daemon principal ==========================


async def test_sin_hj_docker_host_no_se_invoca_docker(tmp_path, monkeypatch):
    """Sin HJ_DOCKER_HOST, docker_available NO ejecuta el binario (da igual que
    exista un daemon principal): nunca se toca el Docker del host."""
    calls = []

    async def _boom(*a, **k):
        calls.append(a)
        raise AssertionError("docker CLI invocado sin HJ_DOCKER_HOST")

    monkeypatch.setattr("asyncio.create_subprocess_exec", _boom)
    s = make_settings(tmp_path)  # docker_host = ""
    assert await factory.docker_available(s) is False
    assert calls == []
    assert factory.docker_env(s) == {}


async def test_socket_principal_del_host_rechazado(tmp_path):
    """HJ_DOCKER_HOST apuntando al socket del daemon principal -> NO autorizado."""
    for forbidden in ("unix:///var/run/docker.sock", "unix:///run/docker.sock"):
        s = make_settings(tmp_path, HJ_DOCKER_HOST=forbidden)
        assert factory.docker_host_authorized(s) is False, forbidden
        assert factory.docker_env(s) == {}
    # un socket rootless de usuario SI es valido
    s2 = make_settings(tmp_path, HJ_DOCKER_HOST="unix:///run/user/1001/docker.sock")
    assert factory.docker_host_authorized(s2) is True
    assert factory.docker_env(s2) == {"DOCKER_HOST": "unix:///run/user/1001/docker.sock"}


async def test_sandbox_kind_falla_si_docker_sin_host_autorizado():
    """Defensa en profundidad: docker_ok=True pero sin host autorizado -> fallo seguro."""
    with pytest.raises(ExecutionUnavailable) as e:
        factory.sandbox_kind("docker", True, docker_host_ok=False)
    assert "HJ_DOCKER_HOST" in str(e.value)


async def test_backend_auto_sin_docker_ni_permiso_local_falla_seguro(tmp_path, monkeypatch):
    """auto + sin Docker rootless autorizado + HJ_ALLOW_LOCAL_SANDBOX=0 -> ExecutionUnavailable."""
    s = make_settings(tmp_path, HJ_SANDBOX_BACKEND="auto")  # allow_local_sandbox=False
    async def fake_avail(_): return False
    monkeypatch.setattr(factory, "docker_available", fake_avail)
    with pytest.raises(ExecutionUnavailable):
        await factory.create_sandbox_backend(tmp_path / "ws", s, project_id=1)


async def test_fabrica_docker_usa_host_rootless_configurado(tmp_path, monkeypatch):
    """Con HJ_DOCKER_HOST valido, docker_env llega al DockerSandbox (y solo el)."""
    captured: dict = {}

    class FakeDockerSandbox:
        def __init__(self, workspace, **kw):
            captured.update(kw)
            captured["workspace"] = workspace

    async def fake_avail(_): return True
    monkeypatch.setattr(factory, "docker_available", fake_avail)
    monkeypatch.setattr(factory, "DockerSandbox", FakeDockerSandbox)
    s = make_settings(tmp_path, HJ_DOCKER_HOST="unix:///run/user/1001/docker.sock")
    await factory.create_sandbox_backend(tmp_path / "ws", s, project_id=7)
    assert captured["docker_env"] == {"DOCKER_HOST": "unix:///run/user/1001/docker.sock"}


# ======================= Bug 3: montaje por proyecto =========================


def test_resolve_host_workspace_devuelve_el_workspace_del_proyecto(tmp_path):
    """Sin traduccion: la ruta EXACTA del proyecto (nunca la raiz general)."""
    s = make_settings(tmp_path)
    proj = tmp_path / "workspaces" / "111" / "demo"
    proj.mkdir(parents=True)
    assert factory.resolve_host_workspace(proj, s) == str(proj)


def test_resolve_host_workspace_aplica_traduccion_conservando_subruta(tmp_path):
    """Con HJ_WORKSPACES_HOST_DIR, se traduce la raiz pero se conserva <uid>/<proyecto>."""
    s = make_settings(tmp_path, HJ_WORKSPACES_HOST_DIR="/mnt/hostws")
    proj = tmp_path / "workspaces" / "111" / "demo"
    proj.mkdir(parents=True)
    got = factory.resolve_host_workspace(proj, s)
    assert got == "/mnt/hostws/111/demo"
    assert got != "/mnt/hostws" and got != str(tmp_path / "workspaces")


def test_flags_docker_montan_solo_el_proyecto(tmp_path):
    """Las flags de docker contienen el mount del workspace del proyecto y nada mas."""
    proj = tmp_path / "workspaces" / "111" / "demo"
    proj.mkdir(parents=True)
    (tmp_path / "workspaces" / "222" / "otro").mkdir(parents=True)  # proyecto ajeno
    sb = DockerSandbox(proj, project_id=1, network=False, host_workspace=str(proj))
    flags = sb._create_flags()
    mounts = [flags[i + 1] for i, f in enumerate(flags) if f == "-v"]
    assert mounts == [f"{proj}:/workspace"]
    assert all("222" not in m for m in mounts)  # jamas otro usuario/proyecto


async def test_fabrica_pasa_workspace_del_proyecto_a_docker(tmp_path, monkeypatch):
    """Regression directa del bug: la fabrica NUNCA pasa la raiz general."""
    captured: dict = {}

    class FakeDockerSandbox:
        def __init__(self, workspace, **kw):
            captured.update(kw)

    async def fake_avail(_): return True
    monkeypatch.setattr(factory, "docker_available", fake_avail)
    monkeypatch.setattr(factory, "DockerSandbox", FakeDockerSandbox)
    s = make_settings(tmp_path, HJ_DOCKER_HOST="unix:///run/user/1001/docker.sock")
    proj = tmp_path / "workspaces" / "111" / "demo"
    proj.mkdir(parents=True)
    await factory.create_sandbox_backend(proj, s, project_id=3)
    assert captured["host_workspace"] == str(proj)


# ===================== Bug 4: backup SQLite coherente ========================


def test_wal_checkpoint_vacia_el_wal(tmp_path):
    """Tras checkpoint(TRUNCATE) con WAL, el fichero -wal queda a 0 bytes y la
    base principal contiene TODO lo comprometido (backup tar coherente)."""
    db = tmp_path / "hj.db"
    con = sqlite3.connect(str(db))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t(x TEXT)")
    con.execute("INSERT INTO t VALUES('dato-importante')")
    con.commit()
    # dejamos transacciones en el WAL SIN cerrar bien:
    con.execute("INSERT INTO t VALUES('otro-dato')")
    con.commit()
    wal = Path(str(db) + "-wal")
    assert wal.exists() and wal.stat().st_size > 0  # hay contenido sin checkpoint
    con.close()

    import sys
    sys.path.insert(0, str(REPO / "scripts"))
    try:
        import db_tools
        info = db_tools.wal_checkpoint(str(db))
        assert info["wal_remaining"] == 0
        # TRUNCATE deja el -wal a 0 bytes; SQLite incluso puede eliminarlo:
        assert not wal.exists() or wal.stat().st_size == 0
        assert db_tools.check_integrity(str(db)) == "ok"
        # y los datos comprometidos estan en el fichero principal:
        con = sqlite3.connect(str(db))
        rows = con.execute("SELECT x FROM t").fetchall()
        con.close()
        assert ("dato-importante",) in rows and ("otro-dato",) in rows
    finally:
        sys.path.pop(0)


# =================== Bug 1: usuario del servicio en update.sh ================


def _script() -> str:
    return (REPO / "scripts" / "update.sh").read_text()


def test_update_no_inventa_usuario_ni_chown_cegudo():
    script = _script()
    assert "chown -R hjagent" not in script            # el bug original
    assert "useradd" not in script                     # no crea usuarios
    assert 'systemctl show "$SERVICE" -p User --value' in script   # usuario EFECTIVO


def test_update_preserva_usuario_detectado_y_solo_chown_si_diverge():
    script = _script()
    # el chown de datos esta condicionado a que el propietario difiera
    assert 'if [ -n "$prev" ] && [ "$prev" != "$WANT" ]' in script
    # sin usuario no-root detectado: no se toca nada
    assert "NO se alteraran permisos" in script
    # los propietarios originales se registran ANTES de tocar nada
    for var in ("OWNER_DATA=", "OWNER_WS=", "OWNER_BK="):
        assert var in script


def test_update_detiene_antes_de_copiar_y_hace_checkpoint_wal():
    script = _script()
    stop_idx = script.index('systemctl stop "$SERVICE"')
    tar_idx = script.index('tar -czf "$BACKUP_DIR/data.tar.gz"')
    # el checkpoint REAL (invocacion a db_tools.py), no las menciones del comentario
    ck_idx = script.index('db_tools.py" "$DB_PATH" checkpoint', stop_idx)
    assert stop_idx < ck_idx < tar_idx  # stop -> checkpoint WAL -> backup
    int_idx = script.index('db_tools.py" "$DB_PATH" integrity', stop_idx)
    assert int_idx < tar_idx            # integrity_check antes de copiar


def test_update_rollback_restaura_codigo_datos_y_permisos():
    script = _script()
    rb = script[script.index("rollback() {"):script.index("step \"4/8")]
    for required in ("app-anterior.tar.gz", "data.tar.gz",        # codigo + datos
                     "OWNER_DATA", "chown -R",                    # permisos
                     "systemctl start", "pip install -e"):        # servicio + deps
        assert required in rb, f"falta en rollback: {required}"
    # cada paso destructivo llama a rollback si falla
    for step_call in ('|| rollback "rsync del codigo nuevo"', '|| rollback "pip install"',
                      '|| rollback "migraciones"', "|| rollback \"systemctl start\""):
        assert step_call in script
