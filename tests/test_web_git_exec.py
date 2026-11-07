"""Pruebas Git/GitHub web (autorizacion en DOS pasos) y ejecucion sandbox."""
from __future__ import annotations

import pytest

from tests.web_utils import FakeWebProvider, build_env, make_web_settings

pytestmark = pytest.mark.asyncio


async def _setup(tmp_path, name="git-web"):
    s = make_web_settings(tmp_path)
    ctxmgr = build_env(s, FakeWebProvider([]))
    env = await ctxmgr.__aenter__()
    await env.login()
    r = await env.post("/api/projects", {"name": name})
    pid = r.json()["project"]["id"]
    return s, ctxmgr, env, pid


async def test_git_status_y_commit(tmp_path):
    s, ctxmgr, env, pid = await _setup(tmp_path)
    try:
        await env.put(f"/api/projects/{pid}/file", {"path": "nuevo.py", "content": "x=1\n"})
        r = await env.get(f"/api/projects/{pid}/git/status")
        st = r.json()
        assert st["is_repo"] is True
        assert "nuevo.py" in st["status"]
        r = await env.post(f"/api/projects/{pid}/git/commit", {"message": "primer commit web"})
        assert r.status_code == 200, r.text
        assert r.json()["commit"]
        r = await env.get(f"/api/projects/{pid}/git/status")
        assert r.json()["status"].strip().endswith("main") or "nothing to commit" not in r.json()["status"]
        r = await env.get(f"/api/projects/{pid}/git/log")
        commits = r.json()["commits"]
        assert len(commits) >= 1
        assert commits[0]["subject"] == "primer commit web"
        # diff vacio tras commit
        r = await env.get(f"/api/projects/{pid}/git/diff")
        assert r.status_code == 200
    finally:
        await ctxmgr.__aexit__(None, None, None)


async def test_git_ramas_validacion(tmp_path):
    s, ctxmgr, env, pid = await _setup(tmp_path)
    try:
        r = await env.post(f"/api/projects/{pid}/git/branch", {"name": "feature/v4"})
        assert r.status_code == 200
        r = await env.post(f"/api/projects/{pid}/git/branch", {"name": "-maliciosa"})
        assert r.status_code == 400
        r = await env.post(f"/api/projects/{pid}/git/branch", {"name": "a..b"})
        assert r.status_code == 400
        # stage con path traversal rechazado
        r = await env.post(f"/api/projects/{pid}/git/stage", {"paths": ["../../x"]})
        assert r.status_code == 400
    finally:
        await ctxmgr.__aexit__(None, None, None)


async def test_push_requiere_dos_pasos(tmp_path):
    """push-request genera vista previa+token; push-confirm ejecuta autorizado."""
    s, ctxmgr, env, pid = await _setup(tmp_path)
    try:
        # sin repo conectado: push-request rechazado
        r = await env.post(f"/api/projects/{pid}/git/push-request", {})
        assert r.status_code == 400
        # conectar repo (sin credencial github todavia)
        r = await env.post(f"/api/projects/{pid}/git/repo",
                           {"url": "https://github.com/dummy/repo.git"})
        assert r.status_code == 200
        r = await env.post(f"/api/projects/{pid}/git/push-request", {})
        assert r.status_code == 400  # falta credencial 'github' cifrada
        # sembrar credencial github (cifrada con la vault real del env)
        vault = env.app.state.ctx.vault
        await env.app.state.ctx.store.set_credential(
            111, "github", vault.encrypt("ghp_falso_de_prueba"))
        # commit para tener algo que publicar
        await env.put(f"/api/projects/{pid}/file", {"path": "a.txt", "content": "hola"})
        await env.post(f"/api/projects/{pid}/git/commit", {"message": "cambio"})
        r = await env.post(f"/api/projects/{pid}/git/push-request", {})
        assert r.status_code == 200, r.text
        previa = r.json()
        assert previa["repo_url"] == "https://github.com/dummy/repo.git"
        assert previa["branch"]
        assert isinstance(previa["commits"], list)
        assert previa["push_token"]
        # token invalido -> 400 y NINGUN push
        r = await env.post(f"/api/projects/{pid}/git/push-confirm",
                           {"token": "token-inventado-123456"})
        assert r.status_code == 400
        # confirmacion correcta: el broker real se invoca con authorized=True
        pushes = []
        real_push = env.app.state.ctx.broker.push

        async def spy_push(project, branch=None, *, authorized=False):
            pushes.append({"project": project["id"], "branch": branch,
                           "authorized": authorized})
            return "push ok (simulado)"

        env.app.state.ctx.broker.push = spy_push
        r = await env.post(f"/api/projects/{pid}/git/push-confirm",
                           {"token": previa["push_token"]})
        assert r.status_code == 200, r.text
        assert pushes == [{"project": pid, "branch": previa["branch"],
                           "authorized": True}]
        # el token se consume (un solo uso)
        r = await env.post(f"/api/projects/{pid}/git/push-confirm",
                           {"token": previa["push_token"]})
        assert r.status_code == 400
    finally:
        await ctxmgr.__aexit__(None, None, None)


async def test_repo_url_con_credenciales_rechazada(tmp_path):
    s, ctxmgr, env, pid = await _setup(tmp_path)
    try:
        r = await env.post(f"/api/projects/{pid}/git/repo",
                           {"url": "https://user:ghp_secreto@github.com/x/y.git"})
        assert r.status_code == 400
        assert "credenciales" in r.json()["detail"].lower()
    finally:
        await ctxmgr.__aexit__(None, None, None)


async def test_exec_sandbox_real_y_bloqueos(tmp_path):
    """Ejecucion REAL en sandbox local de pruebas + politica de seguridad."""
    s, ctxmgr, env, pid = await _setup(tmp_path, name="exec-web")
    try:
        r = await env.post(f"/api/projects/{pid}/exec",
                           {"command": "echo hola-web && python3 -c 'print(2+2)'"})
        assert r.status_code == 200, r.text
        out = r.json()["output"]
        assert "hola-web" in out and "4" in out
        # comando prohibido por command_guard -> 400, no se ejecuta nada
        r = await env.post(f"/api/projects/{pid}/exec", {"command": "docker ps"})
        assert r.status_code == 400
        r = await env.post(f"/api/projects/{pid}/exec", {"command": "sudo rm -rf /"})
        assert r.status_code == 400
        # el navegador no envia instrucciones Docker: solo un comando shell
        # (no existe endpoint que acepte params de docker)
    finally:
        await ctxmgr.__aexit__(None, None, None)


async def test_exec_sin_sandbox_falla_seguro(tmp_path):
    """Politica V3: sin sandbox aislado no se ejecuta codigo (fail-safe)."""
    s = make_web_settings(tmp_path, HJ_ALLOW_LOCAL_SANDBOX="0", HJ_SANDBOX_BACKEND="auto")
    ctxmgr = build_env(s, FakeWebProvider([]))
    env = await ctxmgr.__aenter__()
    try:
        await env.login()
        r = await env.post("/api/projects", {"name": "sin-sandbox"})
        pid = r.json()["project"]["id"]
        r = await env.post(f"/api/projects/{pid}/exec", {"command": "echo no-debe"})
        assert r.status_code == 409
        assert "sandbox" in r.json()["detail"].lower()
    finally:
        await ctxmgr.__aexit__(None, None, None)
