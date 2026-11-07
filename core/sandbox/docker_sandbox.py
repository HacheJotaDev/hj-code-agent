"""Sandbox Docker: contenedor NO privilegiado por proyecto.

- Sin acceso al socket Docker del host, sin montajes del host salvo el workspace.
- --cap-drop ALL, no-new-privileges, usuario no root, pids/memory/cpus limitados.
- Red configurable (por defecto con salida a Internet para instalar dependencias;
  se puede poner 'none' o una red dedicada via HJ_DOCKER_NETWORK).
- Los comandos corren con timeout interno y externo; el entorno NO hereda
  secretos del bot (lista blanca).
"""
from __future__ import annotations

import asyncio
import os
import shlex
import time
import uuid
from pathlib import Path

from security.command_guard import clean_env, screen_command
from .base import ExecResult, ProcessInfo, Sandbox, SandboxError


class DockerSandbox(Sandbox):
    kind = "docker"

    def __init__(self, workspace: Path, *, project_id: int | None = None,
                 image: str = "python:3.12-slim", container_name: str | None = None,
                 memory_mb: int = 512, cpus: float = 1.0, pids: int = 128,
                 timeout_s: int = 120, network: bool = True, docker_network: str = "",
                 host_workspace: str | None = None, disk_mb: int = 512,
                 docker_env: dict[str, str] | None = None):
        super().__init__(workspace, project_id=project_id)
        self.image = image
        self.container = container_name or f"hj-sbx-{project_id or uuid.uuid4().hex[:10]}"
        self.memory_mb = memory_mb
        self.cpus = cpus
        self.pids = pids
        self.timeout_s = timeout_s
        self.network = network
        self.docker_network = docker_network
        self.docker_env = dict(docker_env or {})  # ej: DOCKER_HOST rootless
        self.host_workspace = host_workspace or str(self.workspace)
        self.disk_mb = disk_mb
        self._ready = False

    # ---------------- docker helpers ----------------
    async def _run(self, *args: str, timeout: int = 120, input_text: str | None = None) -> ExecResult:
        env = {**os.environ, **self.docker_env} if self.docker_env else None
        proc = await asyncio.create_subprocess_exec(
            "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if input_text is not None else None, env=env)
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(input_text.encode() if input_text is not None else None),
                timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            raise SandboxError(f"docker {' '.join(args[:3])} agoto el tiempo de espera")
        return ExecResult(exit_code=proc.returncode or 0,
                          stdout=out.decode("utf-8", "replace"),
                          stderr=err.decode("utf-8", "replace"))

    def _create_flags(self) -> list[str]:
        flags = [
            "--name", self.container,
            "--user", "1000:1000",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--memory", f"{self.memory_mb}m",
            "--memory-swap", f"{self.memory_mb}m",
            "--cpus", str(self.cpus),
            "--pids-limit", str(self.pids),
            "--ulimit", f"fsize={self.disk_mb * 1024 * 1024}",
            "--ulimit", "core=0",
            "-v", f"{self.host_workspace}:/workspace",
            "-w", "/workspace",
            "--label", "hj-code-agent=sandbox",
            "-d",
        ]
        if self.docker_network:
            flags += ["--network", self.docker_network]
        elif not self.network:
            flags += ["--network", "none"]
        return flags

    # ---------------- ciclo de vida ----------------
    async def setup(self) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)
        try:
            os_uid = "1000:1000"
            check = await self._run("inspect", "-f",
                                    "{{.State.Running}} {{json .HostConfig.CapDrop}}",
                                    self.container, timeout=20)
            if check.exit_code == 0 and check.stdout.strip().startswith("true"):
                caps = check.stdout.strip().split(" ", 1)[-1]
                if "ALL" in caps:
                    self._ready = True
                    return
            await self._remove()
            pull = await self._run("pull", self.image, timeout=600)
            if pull.exit_code != 0:
                raise SandboxError(f"No se pudo obtener la imagen {self.image}: {pull.stderr[:300]}")
            res = await self._run("run", *self._create_flags(), self.image,
                                  "sh", "-lc", "umask 077; exec sleep infinity", timeout=120)
            if res.exit_code != 0:
                raise SandboxError(f"No se pudo crear el contenedor: {res.stderr[:300]}")
            # El montaje es EXCLUSIVO de este proyecto (factory.
            # resolve_host_workspace), asi que cualquier ajuste de permisos solo
            # puede afectar a los archivos de ESTE workspace. Aun asi, el chown
            # es de ultima instancia: primero comprobamos si 1000:1000 ya puede
            # escribir (caso habitual rootless) para no tocar nada.
            can_write = await self._run("exec", "-u", "1000:1000", self.container,
                                        "sh", "-lc", "test -w /workspace", timeout=30)
            if can_write.exit_code != 0:
                await self._run("exec", "-u", "0:0", self.container, "sh", "-lc",
                                "chown -R 1000:1000 /workspace 2>/dev/null || true",
                                timeout=60)
            self._ready = True
        except FileNotFoundError:
            raise SandboxError("Docker no esta disponible en el host")

    async def _remove(self) -> None:
        await self._run("rm", "-f", self.container, timeout=30)

    async def exec(self, cmd: str, *, cwd: str = ".", timeout: int = 120,
                   env_extra: dict[str, str] | None = None,
                   key: str = "cmd", task_id: int | None = None) -> ExecResult:
        screen_command(cmd)
        if not self._ready:
            await self.setup()
        timeout = min(max(timeout, 1), 3600)
        workdir = f"/workspace/{cwd.strip('./')}" if cwd not in (".", "/") else "/workspace"
        args = ["exec", "-w", workdir]
        env = clean_env(env_extra)
        for k, v in env.items():
            args += ["-e", f"{k}={v}"]
        args += [self.container, "sh", "-lc",
                 f"exec timeout -s KILL {int(timeout)} {cmd}"]
        start = time.monotonic()
        env = {**os.environ, **self.docker_env} if self.docker_env else None
        proc = await asyncio.create_subprocess_exec(
            "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=env)
        self.processes[key] = ProcessInfo(pid=proc.pid, command=cmd[:200],
                                          started_at=time.time(), container=self.container,
                                          project_id=self.project_id, task_id=task_id)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout + 15)
            res = ExecResult(exit_code=proc.returncode or 0,
                             stdout=out.decode("utf-8", "replace"),
                             stderr=err.decode("utf-8", "replace"),
                             duration_s=time.monotonic() - start)
            if b"Killed" in err and "timeout" in cmd:
                res.timed_out = True
        except asyncio.TimeoutError:
            await self._run("kill", self.container, timeout=20)  # no: mata PID 1; mejor pkill
            await self._pkill_matching(cmd)
            res = ExecResult(exit_code=-9, timed_out=True,
                             stderr="Proceso terminado por timeout",
                             duration_s=time.monotonic() - start)
        except asyncio.CancelledError:
            await self._pkill_matching(cmd)
            self.processes.pop(key, None)
            raise
        self.processes.pop(key, None)
        return res

    async def _pkill_matching(self, cmd: str) -> None:
        marker = cmd[:60].replace("'", "")
        await self._run("exec", self.container, "sh", "-lc",
                        f"pkill -9 -f {shlex.quote(marker[:20])} 2>/dev/null || true", timeout=20)

    async def kill(self, key: str) -> bool:
        info = self.processes.get(key)
        if not info:
            return False
        await self._pkill_matching(info.command)
        self.processes.pop(key, None)
        return True

    async def reset(self) -> None:
        await self._remove()
        self._ready = False
        await self.setup()

    async def cleanup(self) -> None:
        await self._remove()

    def info(self) -> dict:
        return {"kind": self.kind, "container": self.container, "image": self.image,
                "memory_mb": self.memory_mb, "cpus": self.cpus, "pids": self.pids,
                "timeout_s": self.timeout_s, "network": self.network,
                "docker_network": self.docker_network or ("none" if not self.network else "bridge"),
                "workspace_mount": f"{self.host_workspace}:/workspace",
                "running": [vars(p) for p in self.processes.values()]}

    @staticmethod
    def security_flags_for_test() -> list[str]:
        """Expone las banderas para pruebas de aislamiento (sin docker real)."""
        s = DockerSandbox(Path("/tmp/x"), project_id=1, network=False)
        return s._create_flags()
