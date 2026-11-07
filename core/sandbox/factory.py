"""Seleccion de backend de sandbox con politica de produccion ESTRICTA.

Reglas (V3, endurecidas tras auditoria):
- `docker`  : SOLO con un HJ_DOCKER_HOST rootless AUTORIZADO y explicito.
  * Sin HJ_DOCKER_HOST          -> NUNCA se usa el daemon principal del host
    (la CLI de docker no llega a invocarse) -> ExecutionUnavailable.
  * HJ_DOCKER_HOST apuntando al socket del daemon principal
    (unix:///var/run/docker.sock, unix:///run/docker.sock) -> rechazado.
  * Si no hay sandbox aislado -> ExecutionUnavailable (NUNCA fallback local).
- `auto`    : Docker solo si hay host rootless autorizado; si no, local SOLO si
  HJ_ALLOW_LOCAL_SANDBOX=1 (desarrollo/tests). En otro caso -> fallo seguro.
- `local`   : solo con HJ_ALLOW_LOCAL_SANDBOX=1 (dev/tests).

Montaje (Bug 3): cada sandbox monta EXCLUSIVAMENTE el workspace del proyecto
(resolve_host_workspace); nunca el directorio general de workspaces.

Semáforo global de trabajos simultaneos (HJ_MAX_CONCURRENT_SANDBOXES, 1).
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from .base import ExecutionUnavailable, Sandbox
from .docker_sandbox import DockerSandbox
from .local_sandbox import LocalSandbox

_SEMAPHORES: dict[str, asyncio.Semaphore] = {}

# Sockets del daemon Docker PRINCIPAL del host: prohibidos para el sandbox.
_FORBIDDEN_DOCKER_HOSTS = {
    "unix:///var/run/docker.sock",
    "unix:///run/docker.sock",
}


def sandbox_semaphore(max_concurrent: int) -> asyncio.Semaphore:
    """Semáforo global por proceso que limita los sandboxes simultaneos."""
    key = str(max(int(max_concurrent), 1))
    if key not in _SEMAPHORES:
        _SEMAPHORES[key] = asyncio.Semaphore(int(key))
    return _SEMAPHORES[key]


def normalize_docker_host(host: str | None) -> str:
    return (host or "").strip().rstrip("/")


def docker_host_authorized(settings) -> bool:
    """True SOLO si hay un HJ_DOCKER_HOST explicito y no es el socket principal.

    La ausencia de HJ_DOCKER_HOST NO autoriza el daemon por defecto: sin esta
    variable la CLI de docker tocaria el daemon principal del VPS.
    """
    host = normalize_docker_host(getattr(settings, "docker_host", ""))
    if not host:
        return False
    if host.lower() in _FORBIDDEN_DOCKER_HOSTS:
        return False
    return True


def docker_env(settings) -> dict[str, str]:
    """Entorno para invocar el CLI de docker (daemon rootless del usuario).

    Sin HJ_DOCKER_HOST autorizado devuelve {} y las funciones de esta fabrica
    jamas invocan docker, asi que la CLI no puede caer en el daemon por defecto.
    """
    if not docker_host_authorized(settings):
        return {}
    return {"DOCKER_HOST": normalize_docker_host(getattr(settings, "docker_host", ""))}


async def docker_available(settings=None) -> bool:
    """Comprueba `docker info` contra el host rootless AUTORIZADO.

    Sin settings o sin HJ_DOCKER_HOST autorizado devuelve False SIN ejecutar
    el binario docker (de este modo nunca se contacta el daemon del host).
    """
    if settings is None or not docker_host_authorized(settings):
        return False
    env = docker_env(settings)
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "info", "--format", "{{.ServerVersion}}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **env})
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        return proc.returncode == 0 and bool(out.strip())
    except (FileNotFoundError, asyncio.TimeoutError):
        return False


def sandbox_kind(backend: str, docker_ok: bool, *, allow_local: bool = False,
                 docker_host_ok: bool = True) -> str:
    """Resuelve el backend REAL o lanza ExecutionUnavailable (sin fallback silencioso)."""
    backend = (backend or "auto").lower()
    if docker_ok and not docker_host_ok:
        # Defensa en profundidad: docker "disponible" pero sin host rootless
        # autorizado (p. ej. docker_ok calculado por otra via).
        raise ExecutionUnavailable(
            "Docker detectado pero SIN HJ_DOCKER_HOST rootless autorizado: no se "
            "usa el daemon principal del host. Configura HJ_DOCKER_HOST "
            "(ej: unix:///run/user/1001/docker.sock) o docs/INSTALL.md#sandbox-rootless")
    if docker_ok:
        return "docker"
    if backend == "local" or allow_local:
        if not allow_local:
            raise ExecutionUnavailable(
                "Sandbox aislado no disponible y HJ_ALLOW_LOCAL_SANDBOX=0: "
                "no se ejecuta codigo (politica de produccion). "
                "Configura Docker rootless (HJ_DOCKER_HOST) o activa el modo dev.")
        return "local"
    raise ExecutionUnavailable(
        "No hay entorno de ejecucion aislado disponible: falta Docker rootless "
        "AUTORIZADO (HJ_DOCKER_HOST). Por seguridad NO se ejecuta codigo sin "
        "sandbox y NO se usa el daemon Docker principal del host. "
        "Configura HJ_DOCKER_HOST: docs/INSTALL.md#sandbox-rootless")


def resolve_host_workspace(workspace: Path, settings) -> str:
    """Ruta EXACTA del workspace DE ESTE PROYECTO vista por el daemon rootless.

    Cada sandbox monta solo su proyecto. Si HJ_WORKSPACES_HOST_DIR define como
    ve el demonio la raiz de workspaces (path translation rootless), se aplica
    conservando la subruta <usuario>/<proyecto>; NUNCA se devuelve la raiz
    general (eso montaria los proyectos de todos los usuarios).
    """
    ws = Path(workspace)
    host_root = (getattr(settings, "workspaces_host_dir", "") or "").strip()
    if not host_root:
        return str(ws)
    try:
        general = Path(getattr(settings, "workspaces_dir")).resolve()
        rel = ws.resolve().relative_to(general)
    except (ValueError, AttributeError, TypeError):
        return str(ws)  # workspace fuera de workspaces_dir: path literal
    return str(Path(host_root) / rel)


async def create_sandbox_backend(workspace: Path, settings, project_id: int | None = None,
                                 project_network: bool | None = None) -> Sandbox:
    """Fabrica de sandboxes. `project_network` permite desactivar la red por proyecto."""
    docker_ok = await docker_available(settings)
    kind = sandbox_kind(settings.sandbox_backend, docker_ok,
                        allow_local=bool(getattr(settings, "allow_local_sandbox", False)),
                        docker_host_ok=docker_host_authorized(settings))
    network = settings.sandbox_network if project_network is None else bool(project_network)
    common = dict(project_id=project_id, memory_mb=settings.sandbox_memory_mb,
                  cpus=settings.sandbox_cpus, pids=settings.sandbox_pids,
                  timeout_s=settings.sandbox_timeout_s, disk_mb=512)
    if kind == "docker":
        return DockerSandbox(workspace, image=settings.sandbox_image, network=network,
                             docker_network=settings.docker_network,
                             docker_env=docker_env(settings),
                             host_workspace=resolve_host_workspace(workspace, settings),
                             **common)
    return LocalSandbox(workspace, network=network, **common)
