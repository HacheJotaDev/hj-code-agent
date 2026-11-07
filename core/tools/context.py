"""Contexto de ejecucion de herramientas del agente."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from security.path_guard import PathGuard


@dataclass
class AgentContext:
    user_id: int
    chat_id: int
    project: dict
    workspace: Path
    guard: PathGuard
    sandbox: Any                    # Sandbox ya configurado
    services: Any                   # AppContext
    cancel_event: asyncio.Event
    task_id: int | None = None
    conversation_id: int | None = None
    max_steps: int = 24
    steps: int = 0
    files_touched: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    tests_run: list[str] = field(default_factory=list)
    notify: Callable[[str], Awaitable[None]] | None = None
    approvals: dict[str, Any] = field(default_factory=dict)  # canal de autorizaciones
    exported_zip: str | None = None  # ruta del ZIP entregable (flujo V3)

    def touch(self, relpath: str) -> None:
        if relpath not in self.files_touched:
            self.files_touched.append(relpath)

    def elapsed(self) -> float:
        return time.time() - (self.approvals.get("started_at") or time.time())
