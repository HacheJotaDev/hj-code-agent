"""Pruebas del explorador de proyectos/archivos web: seguridad y ZIP reales."""
from __future__ import annotations

import io
import zipfile

import pytest

from tests.web_utils import FakeWebProvider, build_env, make_web_settings

pytestmark = pytest.mark.asyncio


def _zip_bytes(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


async def _login_with_project(tmp_path, project_name="demo-web"):
    s = make_web_settings(tmp_path)
    ctxmgr = build_env(s, FakeWebProvider())
    env = await ctxmgr.__aenter__()
    await env.login()
    r = await env.post("/api/projects", {"name": project_name})
    assert r.status_code == 200, r.text
    pid = r.json()["project"]["id"]
    return s, ctxmgr, env, pid


async def test_crear_listar_info_proyecto(tmp_path):
    s = make_web_settings(tmp_path)
    async with build_env(s, FakeWebProvider()) as env:
        await env.login()
        r = await env.post("/api/projects", {"name": "Mi Proyecto"})
        assert r.status_code == 200
        pid = r.json()["project"]["id"]
        r = await env.get("/api/projects")
        names = [p["name"] for p in r.json()["projects"]]
        assert "Mi Proyecto" in names
        r = await env.get(f"/api/projects/{pid}")
        info = r.json()
        assert info["project"]["name"] == "Mi Proyecto"
        assert info["exists"] is True
        # duplicado -> 400
        r = await env.post("/api/projects", {"name": "Mi Proyecto"})
        assert r.status_code == 400


async def test_archivos_read_write_delete_y_arbol(tmp_path):
    s, ctxmgr, env, pid = await _login_with_project(tmp_path)
    try:
        r = await env.put(f"/api/projects/{pid}/file",
                          {"path": "src/app.py", "content": "print('hola v4')\n"})
        assert r.status_code == 200, r.text
        r = await env.get(f"/api/projects/{pid}/file", params={"path": "src/app.py"})
        assert r.status_code == 200
        assert r.json()["content"] == "print('hola v4')\n"
        r = await env.get(f"/api/projects/{pid}/tree")
        tree = r.json()["tree"]
        names = [c["name"] for c in tree["children"]]
        assert "src" in names
        src = next(c for c in tree["children"] if c["name"] == "src")
        assert any(f["name"] == "app.py" for f in src["children"])
        r = await env.delete(f"/api/projects/{pid}/file", params={"path": "src/app.py"})
        assert r.status_code == 200
        r = await env.get(f"/api/projects/{pid}/file", params={"path": "src/app.py"})
        assert r.status_code == 400  # ya no existe
    finally:
        await ctxmgr.__aexit__(None, None, None)


async def test_path_traversal_bloqueado(tmp_path):
    s, ctxmgr, env, pid = await _login_with_project(tmp_path)
    try:
        # lectura fuera del workspace
        r = await env.get(f"/api/projects/{pid}/file", params={"path": "../../etc/passwd"})
        assert r.status_code == 400
        # escritura fuera del workspace
        r = await env.put(f"/api/projects/{pid}/file",
                          {"path": "../escape.txt", "content": "x"})
        assert r.status_code == 400
        # borrado fuera del workspace
        r = await env.delete(f"/api/projects/{pid}/file", params={"path": "/etc/passwd"})
        assert r.status_code == 400
        # confirmar que nada se escribio fuera
        assert not (tmp_path / "workspaces" / "111" / "escape.txt").exists()
    finally:
        await ctxmgr.__aexit__(None, None, None)


async def test_import_zip_aplana_raiz_y_exige_nombre(tmp_path):
    s = make_web_settings(tmp_path)
    async with build_env(s, FakeWebProvider()) as env:
        await env.login()
        content = _zip_bytes({"repo-main/main.py": "print('x')",
                              "repo-main/lib/util.py": "v=1"})
        r = await env.client.post(
            "/api/projects/import",
            data={"name": "importado", "init_git": "false"},
            files={"file": ("repo-main.zip", content, "application/zip")},
            headers=env.headers())
        assert r.status_code == 200, r.text
        stats = r.json()["stats"]
        assert stats["flattened_root"] == "repo-main"
        pid = r.json()["project"]["id"]
        r = await env.get(f"/api/projects/{pid}/file", params={"path": "main.py"})
        assert r.status_code == 200
        assert "print('x')" in r.json()["content"]


async def test_import_zip_con_zip_slip_rechazado(tmp_path):
    s = make_web_settings(tmp_path)
    async with build_env(s, FakeWebProvider()) as env:
        await env.login()
        # ZIP con traversal: zipfile permite nombres arbitrarios
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("../evil.txt", "malware")
        r = await env.client.post(
            "/api/projects/import",
            data={"name": "malo", "init_git": "false"},
            files={"file": ("malo.zip", buf.getvalue(), "application/zip")},
            headers=env.headers())
        assert r.status_code == 400
        # el proyecto fallido se revirtio (no queda ni en BD ni en disco)
        r = await env.get("/api/projects")
        assert "malo" not in [p["name"] for p in r.json()["projects"]]
        assert not (tmp_path / "workspaces" / "evil.txt").exists()


async def test_upload_zip_a_proyecto_existente(tmp_path):
    s, ctxmgr, env, pid = await _login_with_project(tmp_path)
    try:
        content = _zip_bytes({"datos.csv": "a,b\n1,2\n", "docs/readme.md": "# Hola"})
        r = await env.client.post(
            f"/api/projects/{pid}/upload",
            files={"file": ("datos.zip", content, "application/zip")},
            headers=env.headers())
        assert r.status_code == 200, r.text
        r = await env.get(f"/api/projects/{pid}/file", params={"path": "datos.csv"})
        assert r.status_code == 200
    finally:
        await ctxmgr.__aexit__(None, None, None)


async def test_export_zip_devuelve_zip_real(tmp_path):
    s, ctxmgr, env, pid = await _login_with_project(tmp_path)
    try:
        await env.put(f"/api/projects/{pid}/file",
                      {"path": "exportable.py", "content": "x = 1\n"})
        r = await env.get(f"/api/projects/{pid}/export")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/zip")
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        assert "exportable.py" in zf.namelist()
        assert zf.read("exportable.py") == b"x = 1\n"
    finally:
        await ctxmgr.__aexit__(None, None, None)


async def test_proyecto_de_otro_usuario_no_visible(tmp_path):
    """El isolation por agente_uid: proyectos ajenos devuelven 404."""
    s, ctxmgr, env, pid = await _login_with_project(tmp_path)
    try:
        # cambiar el owner del proyecto a otro uid en la BD directamente
        await env.app.state.ctx.store.update_project(pid, user_id=999)
        r = await env.get(f"/api/projects/{pid}")
        assert r.status_code == 404
        r = await env.get(f"/api/projects/{pid}/tree")
        assert r.status_code == 404
    finally:
        await ctxmgr.__aexit__(None, None, None)
