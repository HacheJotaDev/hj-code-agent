"""Boveda de credenciales: cifrado simetrico con clave maestra separada del la BD.

Los secretos (API keys, tokens) se guardan cifrados con Fernet. La clave maestra
nunca se guarda en la base de datos: llega por variable de entorno o por un
archivo con permisos 0600.
"""
from __future__ import annotations

import base64
import os
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class VaultError(Exception):
    pass


class Vault:
    def __init__(self, key: bytes) -> None:
        try:
            self._fernet = Fernet(key)
        except Exception as e:  # clave malformada
            raise VaultError(f"Clave maestra invalida: {e}") from e

    @classmethod
    def generate_key(cls) -> bytes:
        return Fernet.generate_key()

    @classmethod
    def from_passphrase(cls, passphrase: str) -> "Vault":
        import hashlib

        digest = hashlib.sha256(passphrase.encode("utf-8")).digest()
        return cls(base64.urlsafe_b64encode(digest))

    @classmethod
    def load(cls, master_key: str = "", key_file: Path | None = None) -> "Vault":
        if master_key:
            try:
                # Acepta claves urlsafe-b64 de 32 bytes o cualquier passphrase
                base64.urlsafe_b64decode(master_key.encode())
                return cls(master_key.encode())
            except Exception:
                return cls.from_passphrase(master_key)
        if key_file:
            if key_file.exists():
                data = key_file.read_text(encoding="utf-8").strip()
                if not data:
                    raise VaultError(f"El archivo de clave {key_file} esta vacio")
                try:
                    return cls(data.encode())
                except Exception:
                    return cls.from_passphrase(data)
            # Crear clave nueva con permisos restrictivos
            key = Fernet.generate_key()
            key_file.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(key)
            os.chmod(key_file, stat.S_IRUSR | stat.S_IWUSR)
            return cls(key)
        raise VaultError(
            "No hay clave maestra configurada: define HJ_MASTER_KEY o HJ_MASTER_KEY_FILE"
        )

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, blob: bytes) -> str:
        try:
            return self._fernet.decrypt(bytes(blob)).decode("utf-8")
        except InvalidToken as e:
            raise VaultError(
                "No se pudo descifrar una credencial: la clave maestra no coincide"
            ) from e

    @staticmethod
    def mask(secret: str) -> str:
        if not secret:
            return "(vacio)"
        if len(secret) <= 8:
            return secret[0] + "***"
        return f"{secret[:4]}***{secret[-4:]}"
