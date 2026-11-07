"""Capa de ejecucion aislada: Docker endurecido (produccion) o local con limites
(fallback de desarrollo, claramente marcado como menos seguro)."""
from .base import Sandbox, ExecResult, SandboxError, ProcessInfo
from .factory import create_sandbox_backend, sandbox_kind

__all__ = ["Sandbox", "ExecResult", "SandboxError", "ProcessInfo",
           "create_sandbox_backend", "sandbox_kind"]
