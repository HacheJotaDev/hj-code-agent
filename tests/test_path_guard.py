"""10) Restriccion de rutas (path guard)."""
import os
from pathlib import Path

import pytest

from security.path_guard import PathDenied, PathGuard


def test_rutas_normales_ok(tmp_path):
    g = PathGuard(tmp_path)
    (tmp_path / "a").mkdir()
    assert g.resolve("a") == tmp_path.resolve() / "a"
    assert g.resolve("a/../a") == tmp_path.resolve() / "a"
    assert g.resolve(".") == tmp_path.resolve()


def test_traversal_bloqueado(tmp_path):
    g = PathGuard(tmp_path)
    with pytest.raises(PathDenied):
        g.resolve("../fuera.txt")
    with pytest.raises(PathDenied):
        g.resolve("a/../../fuera")


def test_absoluta_fuera_bloqueada(tmp_path):
    g = PathGuard(tmp_path)
    with pytest.raises(PathDenied):
        g.resolve("/etc/passwd")
    with pytest.raises(PathDenied):
        g.resolve("/etc")


def test_symlink_escape_bloqueado(tmp_path):
    fuera = tmp_path.parent / f"fuera-{os.getpid()}.txt"
    fuera.write_text("secreto")
    (tmp_path / "link.txt").symlink_to(fuera)
    g = PathGuard(tmp_path)
    with pytest.raises(PathDenied):
        g.resolve("link.txt")
    fuera.unlink(missing_ok=True)


def test_symlink_interno_permitido(tmp_path):
    (tmp_path / "real.txt").write_text("hola")
    (tmp_path / "alias.txt").symlink_to(tmp_path / "real.txt")
    g = PathGuard(tmp_path)
    assert g.resolve("alias.txt").read_text() == "hola"


def test_rel_to_root(tmp_path):
    g = PathGuard(tmp_path)
    assert g.rel_to_root(tmp_path / "x" / "y.py") == "x/y.py"
    with pytest.raises(PathDenied):
        g.rel_to_root(tmp_path.parent / "otro.py")
