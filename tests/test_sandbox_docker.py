"""Sandbox Docker: banderas de endurecimiento + ejecucion real si hay Docker."""
from pathlib import Path

import pytest

from core.sandbox.docker_sandbox import DockerSandbox
from core.sandbox.factory import docker_available, sandbox_kind


def _flags(network=True, docker_network=""):
    s = DockerSandbox(Path("/tmp/ws-ejemplo"), project_id=1, network=network,
                      docker_network=docker_network)
    return s._create_flags()


def test_no_monta_socket_docker():
    flags = _flags()
    assert "docker.sock" not in " ".join(flags)


def test_no_monta_rutas_de_produccion():
    joined = " ".join(_flags())
    assert "/opt/hj-code-agent/data" not in joined


def test_usuario_no_root_y_cap_drop():
    flags = _flags()
    assert "1000:1000" in flags
    assert flags[flags.index("--cap-drop") + 1] == "ALL"


def test_no_new_privileges():
    flags = _flags()
    assert flags[flags.index("--security-opt") + 1] == "no-new-privileges"


def test_limites_recursos():
    flags = _flags()
    assert flags[flags.index("--memory") + 1] == "512m"
    assert flags[flags.index("--pids-limit") + 1] == "128"
    assert flags[flags.index("--cpus") + 1] == "1.0"


def test_red_desactivada():
    flags = _flags(network=False)
    assert flags[flags.index("--network") + 1] == "none"


def test_red_dedicada():
    flags = _flags(network=True, docker_network="hj-sbx")
    assert flags[flags.index("--network") + 1] == "hj-sbx"


def test_factory_elige_backend():
    assert sandbox_kind("auto", docker_ok=False) == "local"
    assert sandbox_kind("auto", docker_ok=True) == "docker"
    assert sandbox_kind("local", docker_ok=True) == "local"
    assert sandbox_kind("docker", docker_ok=False) == "local"


import shutil
import subprocess

DOCKER_OK = shutil.which("docker") is not None and \
    subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


# Si hay Docker real en el entorno, esta prueba hace una ejecucion end-to-end.


@pytest.mark.skipif(not DOCKER_OK, reason="Docker no disponible en este entorno")
async def test_ejecucion_real_con_docker(tmp_path):
    sbx = DockerSandbox(tmp_path / "ws", project_id=99, image="python:3.12-slim")
    await sbx.setup()
    res = await sbx.exec("echo docker-ok && whoami")
    assert res.ok and "docker-ok" in res.stdout
    assert "1000" in res.stdout  # usuario no root
    await sbx.cleanup()
