"""Seleccion de backend de sandbox: docker si esta disponible, local como fallback."""
from __future__ import annotations

import asyncio
from pathlib import Path

from .base import Sandbox
from .docker_sandbox import DockerSandbox
from .local_sandbox import LocalSandbox


async def docker_available() -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "info", "--format", "{{.ServerVersion}}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        return proc.returncode == 0 and bool(out.strip())
    except (FileNotFoundError, asyncio.TimeoutError):
        return False


def sandbox_kind(backend: str, docker_ok: bool) -> str:
    if backend == "docker":
        return "docker" if docker_ok else "local"
    if backend == "local":
        return "local"
    return "docker" if docker_ok else "local"


async def create_sandbox_backend(workspace: Path, settings, project_id: int | None = None,
                                 project_network: bool | None = None) -> Sandbox:
    """Fabrica de sandboxes. `project_network` permite desactivar la red por proyecto."""
    docker_ok = await docker_available()
    kind = sandbox_kind(settings.sandbox_backend, docker_ok)
    network = settings.sandbox_network if project_network is None else bool(project_network)
    common = dict(project_id=project_id, memory_mb=settings.sandbox_memory_mb,
                  cpus=settings.sandbox_cpus, pids=settings.sandbox_pids,
                  timeout_s=settings.sandbox_timeout_s, disk_mb=512)
    if kind == "docker":
        return DockerSandbox(workspace, image=settings.sandbox_image, network=network,
                             docker_network=settings.docker_network,
                             host_workspace=settings.workspace_host_path(), **common)
    return LocalSandbox(workspace, network=network, **common)
