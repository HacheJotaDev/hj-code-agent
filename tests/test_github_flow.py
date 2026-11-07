"""14) y 15) GitHub: control de versiones y bloqueo de push no autorizado."""
import asyncio
import subprocess
from pathlib import Path

import pytest

from core.github.broker import GitHubBroker, PushNotAuthorized


async def _git(cwd: Path, *args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=str(cwd), stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate()
    return proc.returncode or 0, (out + err).decode("utf-8", "replace").strip()


@pytest.fixture
async def repo_proyecto(tmp_path, store):
    """Proyecto con git local y remoto 'origin' apuntando a un bare local."""
    project_dir = tmp_path / "workspaces" / "111" / "repo"
    project_dir.mkdir(parents=True)
    bare = tmp_path / "remoto-bare.git"
    await _git(bare.parent, "init", "--bare", "-b", "main", str(bare))
    await _git(project_dir, "init", "-b", "main")
    await _git(project_dir, "config", "user.name", "Test")
    await _git(project_dir, "config", "user.email", "t@t")
    (project_dir / "README.md").write_text("# demo\n")
    await _git(project_dir, "add", "-A")
    await _git(project_dir, "commit", "-m", "init")
    await _git(project_dir, "remote", "add", "origin", str(bare))
    pid = await store.create_project(111, "repo", str(project_dir))
    proj = await store.get_project(pid)
    await store.set_git_state(pid, repo_url=str(bare), current_branch="main")
    return proj, bare


async def _token():
    return "ghp_dummy"


@pytest.fixture
def broker(store):
    return GitHubBroker(store, _token)


async def test_push_sin_autorizacion_bloqueado(broker, repo_proyecto):
    proj, _ = repo_proyecto
    with pytest.raises(PushNotAuthorized):
        await broker.push(proj, "main", authorized=False)


async def test_push_rama_protegida_requiere_autopush(broker, repo_proyecto):
    proj, _ = repo_proyecto
    # authorized=True pero autopush OFF y rama protegida -> bloqueado igualmente
    with pytest.raises(PushNotAuthorized):
        await broker.push(proj, "main", authorized=True)


async def test_push_autorizado_en_rama_feature(broker, repo_proyecto):
    proj, bare = repo_proyecto
    await _git(Path(proj["path"]), "checkout", "-b", "feature/x")
    (Path(proj["path"]) / "nuevo.txt").write_text("v2")
    await _git(Path(proj["path"]), "add", "-A")
    await _git(Path(proj["path"]), "commit", "-m", "feat")
    msg = await broker.push(proj, "feature/x", authorized=True)
    assert "Push realizado" in msg
    # el remoto recibio la rama
    code, out = await _git(bare, "branch", "--list", "feature/x")
    assert "feature/x" in out
    # el token NO quedo escrito en el config del repo
    cfg = (Path(proj["path"]) / ".git" / "config").read_text()
    assert "ghp_dummy" not in cfg and "x-access-token" not in cfg


async def test_push_sin_repo_conectado(broker, store, tmp_path):
    pdir = tmp_path / "p2"
    pdir.mkdir()
    pid = await store.create_project(111, "p2", str(pdir))
    proj = await store.get_project(pid)
    with pytest.raises(Exception):
        await broker.push(proj, "feature", authorized=True)


async def test_githu_client_pr_mask():
    from core.github.client import mask_token
    assert mask_token("ghp_1234567890abcdef") == "ghp_***cdef"
    assert mask_token("") == "(sin token)"
