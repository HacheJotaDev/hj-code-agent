"""API Git/GitHub autorizada.

- Estado, log, diff, ramas, stage y commit se ejecutan en el HOST con git local
  (los workspaces son repos reales; el broker V3 gestiona credenciales).
- El push exige DOS pasos: `push-request` (genera vista previa de repo/rama/
  commits y un token efimero de 10 min) y `push-confirm` (ejecuta el push via
  GitHubBroker con authorized=True). Nunca hay push sin confirmacion explicita.
- Los tokens jamas aparecen en URLs, comandos, logs ni respuestas.
"""
from __future__ import annotations

import asyncio
import re
import secrets
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.github.broker import GitBrokerError, PushNotAuthorized
from security.path_guard import PathDenied, PathGuard

from ..deps import require_auth

router = APIRouter(prefix="/api/projects/{pid}/git", tags=["git"])

PUSH_TOKEN_TTL_S = 600
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,80}$")


async def _own_project(auth, pid: int) -> dict:
    proj = await auth.ctx.store.get_project(int(pid))
    if not proj or int(proj["user_id"]) != auth.agent_uid or proj["archived"]:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    return proj


async def _git(cwd: Path, *args: str, timeout: int = 60) -> tuple[int, str]:
    env = {"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1",
           "HOME": str(cwd / ".hj-git-home")}
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *args, cwd=str(cwd), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return 124, "timeout"
        return proc.returncode or 0, (out.decode("utf-8", "replace") +
                                      err.decode("utf-8", "replace")).strip()
    except FileNotFoundError:
        return 127, "git no esta instalado"


def _need_repo(cwd: Path) -> None:
    if not (cwd / ".git").exists():
        raise HTTPException(status_code=400, detail="El proyecto no es un repositorio git")


# --------------------------- consulta -------------------------------------


@router.get("/status")
async def git_status(pid: int, auth=Depends(require_auth)):
    proj = await _own_project(auth, pid)
    cwd = Path(proj["path"])
    if not (cwd / ".git").exists():
        return {"is_repo": False, "status": "", "branch": "", "repo_url": ""}
    code, out = await _git(cwd, "status", "--porcelain", "-b")
    _, remotes = await _git(cwd, "remote", "-v")
    state = await auth.ctx.store.get_git_state(pid)
    return {"is_repo": code == 0, "status": out, "remotes": remotes,
            "branch": state.get("current_branch") or "",
            "repo_url": state.get("repo_url") or "",
            "autopush": bool(state.get("autopush")),
            "allowed_branches": state.get("allowed_branches") or []}


@router.get("/log")
async def git_log(pid: int, limit: int = 30, auth=Depends(require_auth)):
    proj = await _own_project(auth, pid)
    cwd = Path(proj["path"])
    _need_repo(cwd)
    limit = max(1, min(limit, 100))
    code, out = await _git(cwd, "log", "--date=iso", "-n", str(limit),
                           "--pretty=%H%x1f%an%x1f%aI%x1f%s")
    if code != 0:
        return {"commits": [], "error": out[:300]}
    commits = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            commits.append({"hash": parts[0][:12], "author": parts[1],
                            "date": parts[2], "subject": parts[3][:200]})
    return {"commits": commits}


@router.get("/diff")
async def git_diff(pid: int, path: str | None = None, auth=Depends(require_auth)):
    proj = await _own_project(auth, pid)
    cwd = Path(proj["path"])
    _need_repo(cwd)
    extra = []
    if path:
        try:
            PathGuard(cwd).resolve(path, must_exist=False)
        except PathDenied as e:
            raise HTTPException(status_code=400, detail=f"Ruta rechazada: {e}")
        extra = ["--", path]
    code, out = await _git(cwd, "diff", "HEAD", *extra)
    _, staged = await _git(cwd, "diff", "--cached", *extra)
    body = out + (("\n--- staged ---\n" + staged) if staged.strip() else "")
    return {"diff": body[:120000] or "(sin cambios)"}


@router.get("/branches")
async def git_branches(pid: int, auth=Depends(require_auth)):
    proj = await _own_project(auth, pid)
    cwd = Path(proj["path"])
    _need_repo(cwd)
    code, out = await _git(cwd, "branch", "-a")
    return {"branches": [l.strip().lstrip("* ").replace("remotes/", "")
                         for l in out.splitlines() if l.strip()]}


# --------------------------- mutaciones -----------------------------------


class BranchIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


@router.post("/branch")
async def create_branch(pid: int, body: BranchIn, auth=Depends(require_auth)):
    proj = await _own_project(auth, pid)
    cwd = Path(proj["path"])
    _need_repo(cwd)
    name = body.name.strip()
    if not _BRANCH_RE.match(name) or ".." in name or name.startswith("-") or name.endswith(".lock"):
        raise HTTPException(status_code=400, detail="Nombre de rama invalido")
    code, out = await _git(cwd, "checkout", "-b", name)
    if code != 0:
        if "already exists" in out or "ya existe" in out:
            code, out = await _git(cwd, "checkout", name)
        if code != 0:
            raise HTTPException(status_code=400, detail=out[:400])
    await auth.ctx.store.set_git_state(pid, current_branch=name)
    await auth.store.audit(auth.agent_uid, "web.git_branch", f"#{pid} {name}")
    return {"ok": True, "branch": name}


class StageIn(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=50)


@router.post("/stage")
async def stage_files(pid: int, body: StageIn, auth=Depends(require_auth)):
    proj = await _own_project(auth, pid)
    cwd = Path(proj["path"])
    _need_repo(cwd)
    guard = PathGuard(cwd)
    for p in body.paths:
        if p in (".", "/") or not p:
            raise HTTPException(status_code=400, detail="Ruta invalida")
        try:
            guard.resolve(p)
        except PathDenied as e:
            raise HTTPException(status_code=400, detail=f"Ruta rechazada: {e}")
    code, out = await _git(cwd, "add", "--", *body.paths)
    if code != 0:
        raise HTTPException(status_code=400, detail=out[:400])
    return {"ok": True}


class CommitIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)


@router.post("/commit")
async def commit(pid: int, body: CommitIn, auth=Depends(require_auth)):
    proj = await _own_project(auth, pid)
    cwd = Path(proj["path"])
    _need_repo(cwd)
    code, out = await _git(cwd, "add", "-A")
    code2, out2 = await _git(cwd, "commit", "-m", body.message.strip())
    combined = (out + "\n" + out2).strip()
    if code2 != 0 and "nothing to commit" not in out2:
        raise HTTPException(status_code=400, detail=combined[:500])
    await auth.ctx.store.audit(auth.agent_uid, "web.git_commit",
                               f"#{pid}: {body.message[:120]}")
    _, head = await _git(cwd, "rev-parse", "--short", "HEAD")
    return {"ok": True, "output": combined[:2000], "commit": head.strip()}


class RepoIn(BaseModel):
    url: str = Field(min_length=1, max_length=300)


@router.post("/repo")
async def set_repo(pid: int, body: RepoIn, auth=Depends(require_auth)):
    proj = await _own_project(auth, pid)
    url = body.url.strip()
    if url.startswith("http") and ("@" in url or "token" in url.lower()):
        raise HTTPException(status_code=400,
                            detail="No se aceptan URLs con credenciales; el token lo gestiona el broker")
    await auth.ctx.store.set_git_state(pid, repo_url=url)
    await auth.store.audit(auth.agent_uid, "web.git_repo", f"#{pid} {url[:150]}")
    return {"ok": True, "repo_url": url}


@router.post("/clone")
async def clone_repo(pid: int, body: RepoIn, auth=Depends(require_auth)):
    proj = await _own_project(auth, pid)
    try:
        msg = await auth.ctx.broker.clone(proj, body.url.strip())
    except GitBrokerError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await auth.store.audit(auth.agent_uid, "web.git_clone", f"#{pid} {body.url[:150]}")
    return {"ok": True, "message": msg}


@router.post("/pull")
async def pull_repo(pid: int, auth=Depends(require_auth)):
    proj = await _own_project(auth, pid)
    try:
        msg = await auth.ctx.broker.pull(proj)
    except GitBrokerError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "message": msg}


# --------------------------- push con autorizacion ------------------------


class PushRequestIn(BaseModel):
    branch: str | None = Field(default=None, max_length=80)


@router.post("/push-request")
async def push_request(pid: int, body: PushRequestIn, auth=Depends(require_auth)):
    """Paso 1: devuelve lo que SE VA a publicar y un token efimero.

    No ejecuta nada remoto. El frontend debe mostrar repo/rama/commits y
    requerir confirmacion del usuario antes de llamar a /push-confirm.
    """
    proj = await _own_project(auth, pid)
    cwd = Path(proj["path"])
    _need_repo(cwd)
    state = await auth.ctx.store.get_git_state(pid)
    if not state.get("repo_url"):
        raise HTTPException(status_code=400,
                            detail="El proyecto no tiene repositorio conectado")
    branch = (body.branch or state.get("current_branch") or "").strip()
    if not branch:
        raise HTTPException(status_code=400, detail="No hay rama actual")
    creds = await auth.ctx.store.list_credential_providers(auth.agent_uid)
    if "github" not in creds:
        raise HTTPException(status_code=400,
                            detail="No hay token de GitHub configurado (credencial cifrada 'github')")
    # Commits que se publicarian: respecto a su upstream si existe
    code, ahead = await _git(cwd, "log", "--oneline",
                             f"origin/{branch}..HEAD", "-n", "20")
    if code != 0:
        code, ahead = await _git(cwd, "log", "--oneline", "-n", "10")
    commits = [{"hash": l.split(" ", 1)[0], "subject": l.split(" ", 1)[1] if " " in l else ""}
               for l in ahead.splitlines() if l.strip()]
    token = secrets.token_urlsafe(24)
    await auth.ctx.store.kv_set(f"pushreq:{token}",
                                {"pid": int(pid), "branch": branch,
                                 "agent_uid": auth.agent_uid}, ttl_s=PUSH_TOKEN_TTL_S)
    await auth.store.audit(auth.agent_uid, "web.git_push_request",
                           f"#{pid} {branch} ({len(commits)} commits)")
    return {"repo_url": state["repo_url"], "branch": branch, "commits": commits,
            "push_token": token, "expires_in_s": PUSH_TOKEN_TTL_S,
            "warning": ("Push a rama protegida: requiere autopush autorizado"
                        if branch in ("main", "master") and not state.get("autopush") else "")}


class PushConfirmIn(BaseModel):
    token: str = Field(min_length=10, max_length=120)


@router.post("/push-confirm")
async def push_confirm(pid: int, body: PushConfirmIn, auth=Depends(require_auth)):
    """Paso 2: push REAL solo con el token emitido por /push-request."""
    proj = await _own_project(auth, pid)
    info = await auth.ctx.store.kv_get(f"pushreq:{body.token}")
    if not info or info.get("pid") != int(pid):
        raise HTTPException(status_code=400, detail="Peticion de push invalida o expirada")
    if info.get("agent_uid") != auth.agent_uid:
        raise HTTPException(status_code=403, detail="Peticion de push de otro usuario")
    try:
        msg = await auth.ctx.broker.push(proj, info["branch"], authorized=True)
    except PushNotAuthorized as e:
        raise HTTPException(status_code=403, detail=str(e))
    except GitBrokerError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        await auth.ctx.store.kv_del(f"pushreq:{body.token}")
    return {"ok": True, "message": msg}
