"""9) Procesamiento seguro de ZIP/TAR."""
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from core.projects.ziputils import ZipUnsafe, create_zip, extract_archive, extract_zip, inspect_zip


def _zip_bytes(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            if isinstance(data, (int,)):  # external_attr custom
                continue
            z.writestr(name, data)
    return buf.getvalue()


def _write_zip(tmp_path: Path, entries: dict) -> Path:
    p = tmp_path / "subida.zip"
    p.write_bytes(_zip_bytes(entries))
    return p


def test_zip_normal_ok(tmp_path):
    src = _write_zip(tmp_path, {"main.py": "print('hi')", "app/util.py": "x=1"})
    dest = tmp_path / "out"
    stats = extract_zip(src, dest, max_files=100, max_unpacked_mb=10)
    assert (dest / "main.py").read_text() == "print('hi')"
    assert (dest / "app" / "util.py").exists()
    assert stats["files"] == 2


def test_zip_path_traversal_bloqueado(tmp_path):
    src = _write_zip(tmp_path, {"../../evil.txt": "malware"})
    with pytest.raises(ZipUnsafe):
        extract_zip(src, tmp_path / "out", max_files=10, max_unpacked_mb=10)


def test_zip_ruta_absoluta_bloqueada(tmp_path):
    src = _write_zip(tmp_path, {"/etc/passwd": "x"})
    with pytest.raises(ZipUnsafe):
        extract_zip(src, tmp_path / "out", max_files=10, max_unpacked_mb=10)


def test_zip_symlink_bloqueado(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        info = zipfile.ZipInfo("enlace.py")
        info.external_attr = (0o120777 << 16)  # symlink
        z.writestr(info, "/etc/passwd")
    src = tmp_path / "symlink.zip"
    src.write_bytes(buf.getvalue())
    with pytest.raises(ZipUnsafe):
        extract_zip(src, tmp_path / "out", max_files=10, max_unpacked_mb=10)


def test_zip_bomba_bloqueada(tmp_path):
    # 200 MB declarados, supera el limite
    src = _write_zip(tmp_path, {"grande.bin": "A" * (50 * 1024)})
    with pytest.raises(ZipUnsafe):
        inspect_zip(src, max_files=10, max_unpacked_mb=0)  # 0 MB -> imposible


def test_zip_demasiados_archivos(tmp_path):
    entries = {f"f{i}.txt": "x" for i in range(50)}
    src = _write_zip(tmp_path, entries)
    with pytest.raises(ZipUnsafe):
        extract_zip(src, tmp_path / "out", max_files=10, max_unpacked_mb=10)


def test_tar_symlink_bloqueado(tmp_path):
    src = tmp_path / "bad.tar.gz"
    with tarfile.open(src, "w:gz") as t:
        info = tarfile.TarInfo("enlace")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        t.addfile(info)
    with pytest.raises(ZipUnsafe):
        extract_archive(src, tmp_path / "out", max_files=10, max_unpacked_mb=10)


def test_formato_no_soportado(tmp_path):
    src = tmp_path / "virus.exe"
    src.write_bytes(b"MZ")
    with pytest.raises(ZipUnsafe):
        extract_archive(src, tmp_path / "out", max_files=10, max_unpacked_mb=10)


def test_create_zip_excluye_git(tmp_path):
    proj = tmp_path / "proj"
    (proj / ".git").mkdir(parents=True)
    (proj / ".git" / "HEAD").write_text("ref")
    (proj / "ok.py").write_text("print(1)")
    out = tmp_path / "export.zip"
    create_zip(proj, out)
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
    assert "ok.py" in names and not any(n.startswith(".git") for n in names)
