"""Extraccion segura de ZIP/TAR con validacion estricta.

Bloquea: path traversal (../, rutas absolutas, unidades de Windows), enlaces
simbolicos y especiales, bombas de descompresion, exceso de archivos y
tamano descomprimido. Nunca escribe fuera del directorio destino.
"""
from __future__ import annotations

import os
import shutil
import stat
import tarfile
import zipfile
from pathlib import Path


class ZipUnsafe(Exception):
    pass


def _check_name(name: str) -> None:
    if not name or name.endswith("/"):
        return
    if name.startswith("/") or name.startswith("\\"):
        raise ZipUnsafe(f"Ruta absoluta prohibida en el archivo: {name}")
    if ":" in name.split("/")[0] and len(name.split("/")[0]) <= 3:
        raise ZipUnsafe(f"Ruta con unidad de Windows prohibida: {name}")
    parts = name.replace("\\", "/").split("/")
    for p in parts:
        if p == "..":
            raise ZipUnsafe(f"Path traversal prohibido: {name}")
    if "\x00" in name:
        raise ZipUnsafe("Nombre con byte nulo")


def _safe_dest(dest: Path, name: str) -> Path:
    _check_name(name)
    target = (dest / name).resolve()
    dest_r = dest.resolve()
    if dest_r != target and dest_r not in target.parents:
        raise ZipUnsafe(f"Salida fuera del destino: {name}")
    return target


def inspect_zip(zip_path: Path, *, max_files: int, max_unpacked_mb: int) -> dict:
    """Inspeccion previa: numero de archivos, tamano descomprimido, riesgos."""
    total = 0
    n_files = 0
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            _check_name(info.filename)
            mode = (info.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK:
                raise ZipUnsafe(f"Enlace simbolico prohibido: {info.filename}")
            if mode in (stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO):
                raise ZipUnsafe(f"Archivo especial prohibido: {info.filename}")
            total += info.file_size
            if not info.is_dir():
                n_files += 1
            if total > max_unpacked_mb * 1024 * 1024:
                raise ZipUnsafe(
                    f"Contenido descomprimido supera el limite de {max_unpacked_mb} MB")
            if n_files > max_files:
                raise ZipUnsafe(f"El archivo contiene mas de {max_files} entradas")
    ratio = total / max(zip_path.stat().st_size, 1)
    return {"files": n_files, "unpacked_bytes": total, "ratio": round(ratio, 1)}


def extract_zip(zip_path: Path, dest: Path, *, max_files: int, max_unpacked_mb: int) -> dict:
    dest.mkdir(parents=True, exist_ok=True)
    stats = inspect_zip(zip_path, max_files=max_files, max_unpacked_mb=max_unpacked_mb)
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            target = _safe_dest(dest, info.filename)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            os.chmod(target, 0o600)
    return stats


def extract_tar(tar_path: Path, dest: Path, *, max_files: int, max_unpacked_mb: int) -> dict:
    """tar/tar.gz/tgz usando el filtro 'data' de Python 3.12 (seguro por diseno)."""
    dest.mkdir(parents=True, exist_ok=True)
    total, n_files = 0, 0
    with tarfile.open(tar_path, "r:*") as t:
        members = t.getmembers()
        for m in members:
            if m.issym() or m.islnk():
                raise ZipUnsafe(f"Enlace prohibido dentro del tar: {m.name}")
            total += max(m.size, 0)
            if not m.isfile():
                continue
            n_files += 1
            if total > max_unpacked_mb * 1024 * 1024:
                raise ZipUnsafe(f"Contenido supera el limite de {max_unpacked_mb} MB")
            if n_files > max_files:
                raise ZipUnsafe(f"Mas de {max_files} entradas")
        t.extractall(dest, filter="data")
    return {"files": n_files, "unpacked_bytes": total, "ratio": 0.0}


def extract_archive(path: Path, dest: Path, *, max_files: int, max_unpacked_mb: int) -> dict:
    name = path.name.lower()
    if name.endswith(".zip"):
        return extract_zip(path, dest, max_files=max_files, max_unpacked_mb=max_unpacked_mb)
    if name.endswith((".tar.gz", ".tgz", ".tar")):
        return extract_tar(path, dest, max_files=max_files, max_unpacked_mb=max_unpacked_mb)
    raise ZipUnsafe("Formato de archivo no soportado (usa .zip, .tar.gz o .tar)")


def create_zip(source_dir: Path, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(source_dir):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "node_modules", ".venv")]
            for f in files:
                full = Path(root) / f
                rel = full.relative_to(source_dir)
                z.write(full, str(rel))
    return out_path
