"""Control de rutas: todo acceso del agente queda dentro del workspace del proyecto.

Se resuelven enlaces simbolicos para evitar fugas fuera del directorio autorizado.
Esta capa funciona aunque el modelo pida rutas maliciosas.
"""
from __future__ import annotations

from pathlib import Path


class PathDenied(Exception):
    pass


class PathGuard:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, rel: str, *, must_exist: bool = False) -> Path:
        p = Path(rel)
        if p.is_absolute():
            # Se permite si apunta dentro del root (p.ej. el propio root)
            candidate = p
        else:
            candidate = (self.root / p).resolve()
        try:
            candidate = candidate.resolve(strict=False)
        except OSError as e:
            raise PathDenied(f"Ruta no resoluble: {rel}") from e
        if candidate != self.root and self.root not in candidate.parents:
            raise PathDenied(f"Ruta fuera del workspace: {rel}")
        if must_exist and not candidate.exists():
            raise PathDenied(f"No existe: {rel}")
        return candidate

    def rel_to_root(self, p: Path) -> str:
        try:
            return str(Path(p).resolve().relative_to(self.root))
        except ValueError:
            raise PathDenied(f"Ruta fuera del workspace: {p}")
