"""Seleccion de backend de sandbox con politica de produccion ESTRICTA.

Reglas (V3):
- `docker`  : solo Docker aislado (rootless recomendado). Si no esta
  disponible -> ExecutionUnavailable (NUNCA fallback local).
- `auto`    : Docker si esta disponible; si no, local SOLO si
  HJ_ALLOW_LOCAL_SANDBOX=1 (desarrollo/tests). En otro caso ->
  ExecutionUnavailable y el usuario recibe un aviso claro.
- `local`   : solo con HJ_ALLOW_LOCAL_SANDBOX=1 (dev/tests).

Ademas:
- Docker se contacta con HJ_DOCKER_HOST (daemon rootless del usuario); por
  defecto NUNCA se toca el daemon principal del host.
- Semáforo global de trabajos simultaneos (HJ_MAX_CONCURRENT_SANDBOXES, 1).
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from .base import ExecutionUnavailable, Sandbox
from .docker_sandbox import DockerSandbox
from .local_sandbox import LocalSandbox

_SEMAPHORES: dict[str, asyncio.Semaphore] = {}


def sandbox_semaphore(max_concurrent: int) -> asyncio.Semaphore:
    """Semáforo global por proceso que limita los sandboxes simultaneos."""
    key = str(max(int(max_concurrent), 1))
    if key not in _SEMAPHORES:
        _SEMAPHORES[key] = asyncio.Semaphore(int(key))
    return _SEMAPHORES[key]


def docker_env(settings) -> dict[str, str]:
    """Entorno para invocar el CLI de docker (daemon rootless si se configura)."""
    env = {}
    host = (getattr(settings, "docker_host", "") or "").strip()
    if host:
        env["DOCKER_HOST"] = host
    return env


async def docker_available(settings=None) -> bool:
    env = docker_env(settings) if settings is not None else {}
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "info", "--format", "{{.ServerVersion}}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **env} if env else None)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        return proc.returncode == 0 and bool(out.strip())
    except (FileNotFoundError, asyncio.TimeoutError):
        return False


def sandbox_kind(backend: str, docker_ok: bool, *, allow_local: bool = False) -> str:
    """Resuelve el backend REAL o lanza ExecutionUnavailable (sin fallback silencioso)."""
    backend = (backend or "auto").lower()
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
        "No hay entorno de ejecucion aislado disponible (Docker no accesible). "
        "Por seguridad NO se ejecuta codigo sin sandbox. "
        "Configura Docker rootless en el VPS: docs/INSTALL.md#sandbox-rootless")


async def create_sandbox_backend(workspace: Path, settings, project_id: int | None = None,
                                 project_network: bool | None = None) -> Sandbox:
    """Fabrica de sandboxes. `project_network` permite desactivar la red por proyecto."""
    docker_ok = await docker_available(settings)
    kind = sandbox_kind(settings.sandbox_backend, docker_ok,
                        allow_local=bool(getattr(settings, "allow_local_sandbox", False)))
    network = settings.sandbox_network if project_network is None else bool(project_network)
    common = dict(project_id=project_id, memory_mb=settings.sandbox_memory_mb,
                  cpus=settings.sandbox_cpus, pids=settings.sandbox_pids,
                  timeout_s=settings.sandbox_timeout_s, disk_mb=512)
    if kind == "docker":
        return DockerSandbox(workspace, image=settings.sandbox_image, network=network,
                             docker_network=settings.docker_network,
                             docker_env=docker_env(settings),
                             host_workspace=settings.workspace_host_path(), **common)
    return LocalSandbox(workspace, network=network, **common)
