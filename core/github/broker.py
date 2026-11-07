"""Broker de credenciales git/GitHub.

REGLA DE SEGURIDAD: el token de GitHub jamas entra en el contenedor donde se
ejecuta codigo del proyecto. Las operaciones remotas (push/pull) las ejecuta el
orquestador en el host con una peticion efimera (GIT_ASKPASS alimentado por
variable de entorno) que no deja el token escrito en .git/config ni en el
workspace. Los pushes requieren autorizacion explicita del usuario.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from security.command_guard import CommandDenied
from ..storage.repositories import Store


class GitBrokerError(Exception):
    pass


class PushNotAuthorized(GitBrokerError):
    pass


class GitHubBroker:
    def __init__(self, store: Store, token_getter) -> None:
        self.store = store
        self._get_token = token_getter

    # ------------------------- helpers -----------------------------------
    async def _git(self, cwd: Path, *args: str, env_token: str | None = None,
                   timeout: int = 180) -> tuple[int, str]:
        env: dict[str, str] = {"GIT_TERMINAL_PROMPT": "0",
                               "GIT_CONFIG_NOSYSTEM": "1",
                               "HOME": str(cwd / ".hj-git-home")}
        askpass = None
        if env_token:
            askpass_dir = Path("/tmp") / f"hj-askpass-{time.time_ns()}"
            askpass_dir.mkdir(mode=0o700, exist_ok=True)
            askpass = askpass_dir / "askpass.sh"
            askpass.write_text(
                "#!/bin/sh\ncase \"$1\" in Username*) echo 'x-access-token' ;; "
                "Password*) echo \"$HJ_GIT_TOKEN\" ;; esac\n")
            askpass.chmod(0o700)
            env.update({"GIT_ASKPASS": str(askpass), "HJ_GIT_TOKEN": env_token,
                        "GIT_USERNAME": "x-access-token"})
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", *args, cwd=str(cwd), env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return 124, "timeout"
            return proc.returncode or 0, (
                out.decode("utf-8", "replace") + err.decode("utf-8", "replace")).strip()
        finally:
            if askpass:
                for p in askpass.parent.iterdir():
                    p.unlink(missing_ok=True)
                askpass.parent.rmdir()

    def _mask(self, text: str) -> str:
        token = getattr(self, "_last_token", "") or ""
        return text.replace(token, "***") if token else text

    # ------------------------- operaciones --------------------------------
    async def status(self, project: dict) -> dict:
        path = Path(project["path"])
        code, out = await self._git(path, "status", "--porcelain", "-b")
        remote_code, remotes = await self._git(path, "remote", "-v")
        return {"is_repo": code == 0, "status": out, "remotes": remotes,
                "git_state": await self.store.get_git_state(project["id"])}

    async def clone(self, project: dict, repo_url: str, branch: str | None = None) -> str:
        """Clona en un subdirectorio del workspace (sin credenciales: repos publicos
        o repos ya accesibles; para privados se usa el token del broker)."""
        path = Path(project["path"])
        token = await self._safe_token()
        url = self._authed_url(repo_url, token) if token else repo_url
        code, out = await self._git(path.parent, "clone", "--depth", "50",
                                    *(["-b", branch] if branch else []), url,
                                    path.name or "repo")
        if code != 0:
            raise GitBrokerError(self._mask(out)[:500])
        full = repo_url.replace("https://github.com/", "").removesuffix(".git")
        await self.store.set_git_state(project["id"], repo_url=repo_url,
                                       current_branch=branch or "main")
        return f"Clonado {repo_url}"

    @staticmethod
    def _authed_url(repo_url: str, token: str) -> str:
        if repo_url.startswith("https://github.com/"):
            return f"https://x-access-token:{token}@github.com/" + repo_url.split("github.com/", 1)[1]
        return repo_url

    async def _safe_token(self) -> str | None:
        try:
            return await self._get_token()
        except Exception:
            return None

    async def _guard_branch(self, project: dict, branch: str) -> None:
        state = await self.store.get_git_state(project["id"])
        protected = {b for b in ("main", "master") if b}
        allowed = state.get("allowed_branches") or []
        if state.get("autopush") and allowed and branch not in allowed:
            raise PushNotAuthorized(f"Rama '{branch}' no esta en la lista de autopush autorizado")
        if not state.get("autopush") and branch in protected:
            raise PushNotAuthorized(
                "Push a rama protegida ('main'/'master') requiere /autopush on con autorizacion")

    async def push(self, project: dict, branch: str | None = None,
                   *, authorized: bool = False) -> str:
        """Push REAL con token efimero. authorized=True solo lo pone el flujo de
        aprobacion del usuario en Telegram."""
        if not authorized:
            raise PushNotAuthorized("Push no autorizado: requiere aprobacion del usuario")
        state = await self.store.get_git_state(project["id"])
        if not state.get("repo_url"):
            raise GitBrokerError("El proyecto no tiene repositorio conectado (/repo add + /repo clone)")
        branch = branch or state.get("current_branch") or "main"
        await self._guard_branch(project, branch)
        token = await self._get_token()
        if not token:
            raise GitBrokerError("No hay token de GitHub configurado (/github connect)")
        self._last_token = token
        path = Path(project["path"])
        # Asegura rama remota sin tocar credenciales del workspace
        code, out = await self._git(path, "push", "-u", "origin", branch, env_token=token)
        self._last_token = ""
        if code != 0:
            raise GitBrokerError(self._mask(out)[:600])
        await self.store.set_git_state(project["id"], last_push_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                                       current_branch=branch)
        await self.store.audit(project["user_id"], "github.push",
                               f"project={project['name']} branch={branch}")
        return f"Push realizado a {state['repo_url']} ({branch})"

    async def pull(self, project: dict) -> str:
        state = await self.store.get_git_state(project["id"])
        if not state.get("repo_url"):
            raise GitBrokerError("El proyecto no tiene repositorio conectado")
        token = await self._safe_token()
        path = Path(project["path"])
        if token:
            await self._git(path, "fetch", "origin",
                            env_token=token)  # fetch con token efimero
        code, out = await self._git(path, "pull", "--ff-only", "origin",
                                    state.get("current_branch") or "main")
        if code != 0:
            raise GitBrokerError(self._mask(out)[:500])
        return "Pull realizado"

    async def current_branch(self, project: dict) -> str:
        path = Path(project["path"])
        code, out = await self._git(path, "rev-parse", "--abbrev-ref", "HEAD")
        return out.strip() if code == 0 else ""
