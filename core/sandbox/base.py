"""Contrato del sandbox y tipos de resultado."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ExecResult:
    exit_code: int = -1
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    killed: bool = False
    duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def truncated(self, limit: int = 8000) -> str:
        out, err = self.stdout or "", self.stderr or ""
        if len(out) > limit:
            out = out[:limit] + f"\n...[stdout truncado, {len(self.stdout)} bytes]"
        if len(err) > limit:
            err = err[:limit] + f"\n...[stderr truncado, {len(self.stderr)} bytes]"
        s = f"exit={self.exit_code}"
        if self.timed_out:
            s += " (TIMEOUT)"
        if self.killed:
            s += " (CANCELADO)"
        if out:
            s += f"\n--- stdout ---\n{out}"
        if err:
            s += f"\n--- stderr ---\n{err}"
        return s or "(sin salida)"


@dataclass
class ProcessInfo:
    pid: int | None
    command: str
    started_at: float
    project_id: int | None = None
    task_id: int | None = None
    container: str | None = None


class SandboxError(Exception):
    pass


class ExecutionUnavailable(SandboxError):
    """No hay un entorno de ejecucion seguro disponible.

    Politica de produccion: si no existe sandbox aislado (Docker rootless),
    el codigo del proyecto NO se ejecuta y el usuario es informado. Nunca se
    recurre silenciosamente a un sandbox local inseguro.
    """


class Sandbox(ABC):
    """Un sandbox por proyecto: ejecuta comandos con recursos limitados."""

    def __init__(self, workspace: Path, *, project_id: int | None = None):
        self.workspace = Path(workspace)
        self.project_id = project_id
        self.processes: dict[str, ProcessInfo] = {}

    @abstractmethod
    async def setup(self) -> None: ...

    @abstractmethod
    async def exec(self, cmd: str, *, cwd: str = ".", timeout: int = 120,
                   env_extra: dict[str, str] | None = None,
                   key: str = "cmd", task_id: int | None = None) -> ExecResult: ...

    @abstractmethod
    async def kill(self, key: str) -> bool: ...

    @abstractmethod
    async def reset(self) -> None: ...

    @abstractmethod
    async def cleanup(self) -> None: ...

    @abstractmethod
    def info(self) -> dict: ...

    @staticmethod
    def cap(text: str, limit: int = 64_000) -> str:
        return text if len(text) <= limit else text[:limit] + "\n...[salida truncada]"
