"""Sandbox local con limites de recursos (solo desarrollo/pruebas).

ADVERTENCIA: comparte usuario y kernel con el host. Adecuado para desarrollo y
para la suite de tests. En produccion (VPS) usar docker_sandbox.
"""
from __future__ import annotations

import asyncio
import os
import resource
import signal
import time
import uuid
from pathlib import Path

from security.command_guard import clean_env, screen_command
from .base import ExecResult, ProcessInfo, Sandbox, SandboxError


def _preexec(memory_mb: int, disk_mb: int, cpu_s: int, pids: int):
    def apply():
        os.setsid()
        limit = memory_mb * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        except (ValueError, OSError):
            pass
        try:
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except (ValueError, OSError):
            pass
        try:
            fsize = disk_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
        except (ValueError, OSError):
            pass
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (pids, pids))
        except (ValueError, OSError):
            pass
        try:
            cpu = max(cpu_s + 10, 10)
            resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 5))
        except (ValueError, OSError):
            pass
    return apply


class LocalSandbox(Sandbox):
    kind = "local"

    def __init__(self, workspace: Path, *, project_id: int | None = None,
                 memory_mb: int = 512, cpus: float = 1.0, pids: int = 128,
                 timeout_s: int = 120, disk_mb: int = 512, network: bool = True):
        super().__init__(workspace, project_id=project_id)
        self.memory_mb = memory_mb
        self.cpus = cpus
        self.pids = pids
        self.timeout_s = timeout_s
        self.disk_mb = disk_mb
        self.network = network

    async def setup(self) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)

    async def exec(self, cmd: str, *, cwd: str = ".", timeout: int = 120,
                   env_extra: dict[str, str] | None = None,
                   key: str = "cmd", task_id: int | None = None) -> ExecResult:
        screen_command(cmd)
        workdir = (self.workspace / cwd).resolve()
        if self.workspace not in workdir.parents and workdir != self.workspace:
            raise SandboxError(f"cwd fuera del workspace: {cwd}")
        workdir.mkdir(parents=True, exist_ok=True)
        env = clean_env(env_extra)
        start = time.monotonic()
        proc = await asyncio.create_subprocess_shell(
            cmd, cwd=str(workdir), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            preexec_fn=_preexec(self.memory_mb, self.disk_mb,
                                max(timeout, self.timeout_s), self.pids),
        )
        self.processes[key] = ProcessInfo(pid=proc.pid, command=cmd[:200],
                                          started_at=time.time(),
                                          project_id=self.project_id, task_id=task_id)
        try:
            out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            rc = proc.returncode if proc.returncode is not None else -1
            res = ExecResult(exit_code=rc,
                             stdout=out_b.decode("utf-8", "replace"),
                             stderr=err_b.decode("utf-8", "replace"),
                             killed=(rc == -9),
                             duration_s=time.monotonic() - start)
        except asyncio.TimeoutError:
            self._kill_pid(proc.pid)
            try:
                await asyncio.wait_for(proc.communicate(), timeout=5)
            except (asyncio.TimeoutError, ProcessLookupError):
                pass
            res = ExecResult(exit_code=-9, timed_out=True,
                             stderr="Proceso terminado por timeout",
                             duration_s=time.monotonic() - start)
        except asyncio.CancelledError:
            self._kill_pid(proc.pid)
            try:
                await asyncio.wait_for(proc.communicate(), timeout=5)
            except (asyncio.TimeoutError, ProcessLookupError):
                pass
            res = ExecResult(exit_code=-9, killed=True,
                             stderr="Proceso cancelado por el usuario",
                             duration_s=time.monotonic() - start)
            self.processes.pop(key, None)
            raise
        self.processes.pop(key, None)
        return res

    @staticmethod
    def _kill_pid(pid: int | None) -> None:
        if not pid:
            return
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    async def kill(self, key: str) -> bool:
        info = self.processes.get(key)
        if not info:
            return False
        self._kill_pid(info.pid)
        self.processes.pop(key, None)
        return True

    async def reset(self) -> None:
        for key in list(self.processes):
            await self.kill(key)

    async def cleanup(self) -> None:
        await self.reset()

    def info(self) -> dict:
        return {"kind": self.kind, "workspace": str(self.workspace),
                "memory_mb": self.memory_mb, "cpus": self.cpus, "pids": self.pids,
                "timeout_s": self.timeout_s, "disk_mb": self.disk_mb,
                "network": self.network,
                "warning": "Sandbox local: menor aislamiento; usar Docker en produccion",
                "running": [vars(p) for p in self.processes.values()]}
