"""Manager de proyectos: directorios bajo workspaces/<user>/<slug>, seleccion,
exportacion, archivado y borrado con confirmacion."""
from __future__ import annotations

import re
import shutil
import time
import unicodedata
from pathlib import Path

from security.path_guard import PathDenied
from ..storage.repositories import Store
from .ziputils import create_zip

_SLUG_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = _SLUG_RE.sub("-", s).strip("-.")
    return (s or "proyecto").lower()[:48]


class ProjectError(Exception):
    pass


class ProjectManager:
    def __init__(self, store: Store, workspaces_dir: Path, backups_dir: Path) -> None:
        self.store = store
        self.workspaces = Path(workspaces_dir)
        self.backups = Path(backups_dir)

    def _root(self, user_id: int) -> Path:
        d = self.workspaces / str(user_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    async def create(self, user_id: int, name: str, init_git: bool = True) -> dict:
        existing = await self.store.get_project_by_name(user_id, name)
        if existing:
            raise ProjectError(f"Ya existe un proyecto llamado '{name}'")
        slug = slugify(name)
        path = self._root(user_id) / slug
        idx = 1
        while path.exists():
            idx += 1
            path = self._root(user_id) / f"{slug}-{idx}"
        path.mkdir(parents=True, exist_ok=False)
        pid = await self.store.create_project(user_id, name, str(path))
        if init_git:
            proc = await _run_git(path, ["init", "-b", "main"])
            if proc.returncode == 0:
                await _run_git(path, ["config", "user.name", "HJ Code Agent"])
                await _run_git(path, ["config", "user.email", "agent@hj-code-agent.local"])
                await self.store.set_git_state(pid, current_branch="main", default_branch="main")
        await self.store.audit(user_id, "project.create", f"{name} -> {path}")
        return await self.store.get_project(pid)

    async def get(self, pid: int) -> dict | None:
        return await self.store.get_project(pid)

    async def active(self, user_id: int) -> dict | None:
        raw = await self.store.get_pref(user_id, "active_project")
        if not raw:
            return None
        proj = await self.store.get_project(int(raw))
        if not proj or proj["user_id"] != user_id or proj["archived"]:
            return None
        return proj

    async def select(self, user_id: int, project_ref: str) -> dict:
        proj = None
        if project_ref.isdigit():
            proj = await self.store.get_project(int(project_ref))
        if not proj:
            proj = await self.store.get_project_by_name(user_id, project_ref)
        if not proj or proj["user_id"] != user_id:
            raise ProjectError("Proyecto no encontrado")
        await self.store.set_pref(user_id, "active_project", proj["id"])
        await self.store.audit(user_id, "project.select", proj["name"])
        return proj

    async def list(self, user_id: int) -> list[dict]:
        return await self.store.list_projects(user_id)

    async def rename(self, user_id: int, pid: int, new_name: str) -> dict:
        proj = await self.store.get_project(pid)
        if not proj or proj["user_id"] != user_id:
            raise ProjectError("Proyecto no encontrado")
        await self.store.update_project(pid, name=new_name)
        await self.store.audit(user_id, "project.rename", f"{proj['name']} -> {new_name}")
        return await self.store.get_project(pid)

    async def info(self, pid: int) -> dict:
        proj = await self.store.get_project(pid)
        if not proj:
            raise ProjectError("Proyecto no encontrado")
        path = Path(proj["path"])
        n_files, size = 0, 0
        if path.exists():
            for p in path.rglob("*"):
                if p.is_file() and ".git" not in p.parts:
                    n_files += 1
                    try:
                        size += p.stat().st_size
                    except OSError:
                        pass
        git = await self.store.get_git_state(pid)
        return {"project": proj, "exists": path.exists(), "files": n_files,
                "size_bytes": size, "git": git}

    async def archive(self, user_id: int, pid: int, audit: bool = True) -> Path:
        proj = await self.store.get_project(pid)
        if not proj:
            raise ProjectError("Proyecto no encontrado")
        ts = time.strftime("%Y%m%d-%H%M%S")
        out = self.backups / f"project-{proj['id']}-{slugify(proj['name'])}-{ts}.zip"
        create_zip(Path(proj["path"]), out)
        if audit:
            await self.store.audit(user_id, "project.archive", proj["name"])
        return out

    async def export_zip(self, pid: int) -> Path:
        return await self.archive(0, pid, audit=False)

    async def delete(self, user_id: int, pid: int, confirmed: bool = False) -> None:
        proj = await self.store.get_project(pid)
        if not proj or proj["user_id"] != user_id:
            raise ProjectError("Proyecto no encontrado")
        if not confirmed:
            raise ProjectError("DELETE_REQUIRES_CONFIRMATION")
        path = Path(proj["path"])
        if path.exists():
            try:
                resolved = path.resolve()
                if self.workspaces.resolve() in resolved.parents:
                    shutil.rmtree(resolved, ignore_errors=True)
                else:
                    raise PathDenied("Ruta de proyecto fuera del area de workspaces")
            except OSError:
                pass
        await self.store.delete_project(pid)
        active = await self.store.get_pref(user_id, "active_project")
        if active and int(active) == pid:
            await self.store.set_pref(user_id, "active_project", None)
        await self.store.audit(user_id, "project.delete", proj["name"])


async def _run_git(cwd: Path, args: list[str]):
    import asyncio
    return await asyncio.create_subprocess_exec(
        "git", *args, cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
