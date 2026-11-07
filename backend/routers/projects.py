"""API de proyectos: CRUD, explorador de archivos, subida/exportacion ZIP.

Toda operacion de archivos pasa por PathGuard del proyecto (proteccion contra
path traversal) y por los limites de ziputils (zip bombs, symlinks, etc.).
Solo el propietario del proyecto (agent_uid vinculado al usuario web) accede.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from core.projects.manager import ProjectError
from core.projects.ziputils import ZipUnsafe, create_zip, extract_archive
from core.tools.registry import IGNORED_DIRS
from security.path_guard import PathDenied, PathGuard

from ..deps import require_auth

router = APIRouter(prefix="/api/projects", tags=["projects"])

MAX_TREE_ENTRIES = 2000
MAX_TREE_DEPTH = 14
MAX_READ_BYTES = 256 * 1024
MAX_RAW_BYTES = 64 * 1024 * 1024
BINARY_SNIFF = 8192
TEXT_SUFFIXES_KEEP = (".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".md", ".txt",
                      ".yml", ".yaml", ".toml", ".cfg", ".ini", ".sh", ".css",
                      ".html", ".sql", ".env", ".gitignore")


async def _own_project(auth, pid: int) -> dict:
    proj = await auth.ctx.store.get_project(int(pid))
    if not proj or int(proj["user_id"]) != auth.agent_uid or proj["archived"]:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    return proj


def _workspace(proj: dict) -> Path:
    ws = Path(proj["path"])
    if not ws.exists():
        ws.mkdir(parents=True, exist_ok=True)
    return ws


# ------------------------------- CRUD ------------------------------------


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    init_git: bool = True


@router.get("")
async def list_projects(auth=Depends(require_auth)):
    rows = await auth.ctx.store.list_projects(auth.agent_uid)
    out = []
    for r in rows:
        p = Path(r["path"])
        out.append({"id": r["id"], "name": r["name"], "created_at": r.get("created_at"),
                    "exists": p.exists()})
    return {"projects": out}


@router.post("")
async def create_project(body: ProjectIn, auth=Depends(require_auth)):
    try:
        proj = await auth.ctx.projects.create(auth.agent_uid, body.name.strip(),
                                              init_git=body.init_git)
    except ProjectError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "project": proj}


@router.get("/{pid}")
async def project_info(pid: int, auth=Depends(require_auth)):
    proj = await _own_project(auth, pid)
    info = await auth.ctx.projects.info(pid)
    git = info.get("git") or {}
    return {"project": proj, "exists": info["exists"], "files": info["files"],
            "size_bytes": info["size_bytes"],
            "git": {"repo_url": git.get("repo_url"),
                    "current_branch": git.get("current_branch"),
                    "default_branch": git.get("default_branch")}}


@router.delete("/{pid}")
async def delete_project(pid: int, confirm: bool = False, auth=Depends(require_auth)):
    """Archiva un ZIP de seguridad en backups/ y despues elimina."""
    if not confirm:
        raise HTTPException(status_code=400, detail="DELETE_REQUIRES_CONFIRMATION")
    try:
        backup = await auth.ctx.projects.archive(auth.agent_uid, pid)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e))
    try:
        await auth.ctx.projects.delete(auth.agent_uid, pid, confirmed=True)
    except ProjectError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await auth.store.audit(auth.agent_uid, "web.project_delete", f"#{pid} backup={backup.name}")
    return {"ok": True, "backup": backup.name}


# --------------------------- importar / exportar -------------------------


async def _save_upload(upload: UploadFile, dest: Path, max_mb: int) -> None:
    limit = max_mb * 1024 * 1024
    written = 0
    with open(dest, "wb") as out:
        while chunk := await upload.read(1024 * 512):
            written += len(chunk)
            if written > limit:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=413,
                                    detail=f"El archivo supera {max_mb} MB")
            out.write(chunk)


@router.post("/import")
async def import_project(name: str = Form(...), file: UploadFile = File(...),
                         init_git: bool = Form(True), auth=Depends(require_auth)):
    """Crea un proyecto y descomprime el ZIP/tar.gz subido en su workspace."""
    fname = (file.filename or "").lower()
    if not fname.endswith((".zip", ".tar.gz", ".tgz", ".tar")):
        raise HTTPException(status_code=400, detail="Formato no soportado (zip/tar.gz/tar)")
    try:
        proj = await auth.ctx.projects.create(auth.agent_uid, name.strip(), init_git=False)
    except ProjectError as e:
        raise HTTPException(status_code=400, detail=str(e))
    ws = _workspace(proj)
    suffix = ".zip" if fname.endswith(".zip") else (".tar.gz" if fname.endswith((".tar.gz", ".tgz")) else ".tar")
    tmp = ws.parent / f".upload-{proj['id']}-{int(time.time())}{suffix}"
    try:
        await _save_upload(file, tmp, int(auth.settings.max_file_mb))
        stats = extract_archive(tmp, ws,
                                max_files=int(auth.settings.max_zip_files),
                                max_unpacked_mb=int(auth.settings.max_zip_unpacked_mb))
    except (ZipUnsafe, HTTPException) as e:
        shutil.rmtree(ws, ignore_errors=True)
        await auth.ctx.store.delete_project(proj["id"])
        detail = getattr(e, "detail", str(e))
        raise HTTPException(status_code=400, detail=f"Archivo rechazado: {detail}")
    finally:
        tmp.unlink(missing_ok=True)
    if init_git and not (ws / ".git").exists():
        import asyncio
        proc = await asyncio.create_subprocess_exec(
            "git", "init", "-b", "main", cwd=str(ws),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await proc.wait()
        await auth.ctx.store.set_git_state(proj["id"], current_branch="main",
                                           default_branch="main")
    await auth.store.audit(auth.agent_uid, "web.project_import",
                           f"{proj['name']} files={stats.get('files')}")
    return {"ok": True, "project": proj, "stats": stats}


@router.post("/{pid}/upload")
async def upload_to_project(pid: int, file: UploadFile = File(...),
                            auth=Depends(require_auth)):
    """Extrae un ZIP/tar.gz dentro del workspace existente (fusión)."""
    proj = await _own_project(auth, pid)
    fname = (file.filename or "").lower()
    if not fname.endswith((".zip", ".tar.gz", ".tgz", ".tar")):
        raise HTTPException(status_code=400, detail="Formato no soportado (zip/tar.gz/tar)")
    ws = _workspace(proj)
    suffix = ".zip" if fname.endswith(".zip") else (".tar.gz" if fname.endswith((".tar.gz", ".tgz")) else ".tar")
    tmp = ws.parent / f".upload-{pid}-{int(time.time())}{suffix}"
    try:
        await _save_upload(file, tmp, int(auth.settings.max_file_mb))
        stats = extract_archive(tmp, ws,
                                max_files=int(auth.settings.max_zip_files),
                                max_unpacked_mb=int(auth.settings.max_zip_unpacked_mb))
    except (ZipUnsafe, HTTPException) as e:
        detail = getattr(e, "detail", str(e))
        raise HTTPException(status_code=400, detail=f"Archivo rechazado: {detail}")
    finally:
        tmp.unlink(missing_ok=True)
    await auth.store.audit(auth.agent_uid, "web.project_upload",
                           f"#{pid} files={stats.get('files')}")
    return {"ok": True, "stats": stats}


@router.get("/{pid}/export")
async def export_project(pid: int, auth=Depends(require_auth)):
    proj = await _own_project(auth, pid)
    try:
        out = await auth.ctx.projects.export_zip(pid)
    except (ZipUnsafe, OSError) as e:
        raise HTTPException(status_code=500, detail=f"No se pudo exportar: {e}")
    if not out.exists():
        raise HTTPException(status_code=500, detail="El ZIP no se genero")
    await auth.store.audit(auth.agent_uid, "web.project_export", proj["name"])
    return FileResponse(out, media_type="application/zip", filename=out.name)


# --------------------------- explorador ----------------------------------


def _tree(ws: Path) -> dict:
    count = 0

    def build(dirp: Path, depth: int) -> dict:
        nonlocal count
        node = {"name": dirp.name or "/", "type": "dir", "children": []}
        if depth > MAX_TREE_DEPTH or count > MAX_TREE_ENTRIES:
            return node
        try:
            entries = sorted(dirp.iterdir(),
                             key=lambda p: (p.is_file(), p.name.lower()))
        except OSError:
            return node
        for p in entries:
            if count >= MAX_TREE_ENTRIES:
                node["truncated"] = True
                break
            if p.is_dir():
                if p.name in IGNORED_DIRS or p.name.startswith(".git"):
                    continue
                count += 1
                node["children"].append(build(p, depth + 1))
            else:
                count += 1
                try:
                    node["children"].append({"name": p.name, "type": "file",
                                             "size": p.stat().st_size})
                except OSError:
                    continue
        return node

    return build(ws, 0)


@router.get("/{pid}/tree")
async def project_tree(pid: int, auth=Depends(require_auth)):
    proj = await _own_project(auth, pid)
    ws = _workspace(proj)
    return {"tree": _tree(ws)}


def _guard_for(proj: dict) -> PathGuard:
    return PathGuard(Path(proj["path"]))


def _resolve(auth, proj: dict, path: str, must_exist: bool = False) -> Path:
    if not path or path in (".", "/") or "\x00" in path:
        raise HTTPException(status_code=400, detail="Ruta invalida")
    try:
        return _guard_for(proj).resolve(path, must_exist=must_exist)
    except PathDenied as e:
        raise HTTPException(status_code=400, detail=f"Ruta rechazada: {e}")


@router.get("/{pid}/file")
async def read_file(pid: int, path: str, auth=Depends(require_auth)):
    proj = await _own_project(auth, pid)
    f = _resolve(auth, proj, path, must_exist=True)
    if not f.is_file():
        raise HTTPException(status_code=400, detail="No es un archivo")
    data = f.read_bytes()
    truncated = len(data) > MAX_READ_BYTES
    if truncated:
        data = data[:MAX_READ_BYTES]
    binary = b"\x00" in data[:BINARY_SNIFF]
    if binary:
        import base64
        return {"path": path, "binary": True,
                "content_base64": base64.b64encode(data).decode(),
                "size": f.stat().st_size, "truncated": truncated}
    return {"path": path, "binary": False, "content": data.decode("utf-8", "replace"),
            "size": f.stat().st_size, "truncated": truncated}


class FileWrite(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    content: str = Field(default="")
    encoding: str = Field(default="utf-8")


@router.put("/{pid}/file")
async def write_file(pid: int, body: FileWrite, auth=Depends(require_auth)):
    proj = await _own_project(auth, pid)
    f = _resolve(auth, proj, body.path)
    payload = body.content.encode(body.encoding, "replace")
    if len(payload) > 1024 * 1024:
        raise HTTPException(status_code=413, detail="El contenido supera 1 MB")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(payload)
    await auth.store.audit(auth.agent_uid, "web.file_write",
                           f"#{pid} {body.path[:200]} ({len(payload)}B)")
    return {"ok": True, "bytes": len(payload)}


@router.delete("/{pid}/file")
async def delete_file(pid: int, path: str, auth=Depends(require_auth)):
    proj = await _own_project(auth, pid)
    f = _resolve(auth, proj, path, must_exist=True)
    if f == Path(proj["path"]).resolve():
        raise HTTPException(status_code=400, detail="No se puede borrar la raiz")
    if f.is_dir():
        shutil.rmtree(f)
    else:
        f.unlink()
    await auth.store.audit(auth.agent_uid, "web.file_delete", f"#{pid} {path[:200]}")
    return {"ok": True}


@router.get("/{pid}/raw")
async def raw_file(pid: int, path: str, auth=Depends(require_auth)):
    proj = await _own_project(auth, pid)
    f = _resolve(auth, proj, path, must_exist=True)
    if not f.is_file():
        raise HTTPException(status_code=400, detail="No es un archivo")
    if f.stat().st_size > MAX_RAW_BYTES:
        raise HTTPException(status_code=413, detail="Archivo demasiado grande")
    return FileResponse(f, filename=f.name)
