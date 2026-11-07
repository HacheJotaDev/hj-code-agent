"""Configuracion central por variables de entorno (sin secretos por defecto)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _to_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on", "sí", "si")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # Telegram
    telegram_bot_token: str = Field(default="", validation_alias="HJ_TELEGRAM_BOT_TOKEN")
    admin_user_ids: list[int] = Field(default_factory=list, validation_alias="HJ_ADMIN_USER_IDS")
    # 1 = ni un aviso a IDs no autorizados (silencio total);
    # 0 = un unico aviso con su user_id y luego silencio.
    silent_reject: bool = Field(default=False, validation_alias="HJ_SILENT_REJECT")

    # Rutas
    data_dir: Path = Field(default=Path("/opt/hj-code-agent/data"), validation_alias="HJ_DATA_DIR")
    workspaces_dir: Path = Field(
        default=Path("/opt/hj-code-agent/workspaces"), validation_alias="HJ_WORKSPACES_DIR"
    )
    backups_dir: Path = Field(
        default=Path("/opt/hj-code-agent/backups"), validation_alias="HJ_BACKUPS_DIR"
    )
    db_path: Optional[Path] = Field(default=None, validation_alias="HJ_DB_PATH")
    log_file: Optional[Path] = Field(default=None, validation_alias="HJ_LOG_FILE")
    log_level: str = Field(default="INFO", validation_alias="HJ_LOG_LEVEL")

    # Cifrado
    master_key: str = Field(default="", validation_alias="HJ_MASTER_KEY")
    master_key_file: Optional[Path] = Field(default=None, validation_alias="HJ_MASTER_KEY_FILE")

    # Proveedores
    default_provider: str = Field(default="deepseek", validation_alias="HJ_DEFAULT_PROVIDER")
    deepseek_base_url: str = Field(
        default="https://api.deepseek.com", validation_alias="HJ_DEEPSEEK_BASE_URL"
    )
    deepseek_api_key: str = Field(default="", validation_alias="HJ_DEEPSEEK_API_KEY")
    github_token: str = Field(default="", validation_alias="HJ_GITHUB_TOKEN")

    # Sandbox
    sandbox_backend: str = Field(default="auto", validation_alias="HJ_SANDBOX_BACKEND")
    sandbox_image: str = Field(default="python:3.12-slim", validation_alias="HJ_SANDBOX_IMAGE")
    sandbox_memory_mb: int = Field(default=1024, validation_alias="HJ_SANDBOX_MEMORY_MB")
    sandbox_cpus: float = Field(default=1.0, validation_alias="HJ_SANDBOX_CPUS")
    sandbox_pids: int = Field(default=128, validation_alias="HJ_SANDBOX_PIDS")
    sandbox_timeout_s: int = Field(default=120, validation_alias="HJ_SANDBOX_TIMEOUT_S")
    sandbox_network: bool = Field(default=True, validation_alias="HJ_SANDBOX_NETWORK")
    docker_network: str = Field(default="", validation_alias="HJ_DOCKER_NETWORK")
    # Docker rootless independiente (NUNCA el daemon principal del host):
    # ej: unix:///run/user/1001/docker.sock
    docker_host: str = Field(default="", validation_alias="HJ_DOCKER_HOST")
    # Politica estricta: si no hay sandbox aislado, NO se ejecuta codigo.
    # El backend local (inseguro) requiere este interruptor explicito (dev/tests).
    allow_local_sandbox: bool = Field(default=False, validation_alias="HJ_ALLOW_LOCAL_SANDBOX")
    max_concurrent_sandboxes: int = Field(default=1, validation_alias="HJ_MAX_CONCURRENT_SANDBOXES")
    workspaces_host_dir: Optional[str] = Field(
        default=None, validation_alias="HJ_WORKSPACES_HOST_DIR"
    )

    # Limites del agente
    max_task_steps: int = Field(default=24, validation_alias="HJ_MAX_TASK_STEPS")
    max_concurrent_tasks: int = Field(default=2, validation_alias="HJ_MAX_CONCURRENT_TASKS")

    # Limites de subidas
    max_file_mb: int = Field(default=20, validation_alias="HJ_MAX_FILE_MB")
    max_zip_files: int = Field(default=2000, validation_alias="HJ_MAX_ZIP_FILES")
    max_zip_unpacked_mb: int = Field(default=200, validation_alias="HJ_MAX_ZIP_UNPACKED_MB")

    # Formulario /setapi
    form_host: str = Field(default="127.0.0.1", validation_alias="HJ_FORM_HOST")
    form_port: int = Field(default=8977, validation_alias="HJ_FORM_PORT")
    form_base_url: str = Field(default="", validation_alias="HJ_FORM_BASE_URL")

    # ---- V4 Web (panel web; Telegram sigue funcionando en paralelo) ----
    web_host: str = Field(default="127.0.0.1", validation_alias="HJ_WEB_HOST")
    web_port: int = Field(default=8900, validation_alias="HJ_WEB_PORT")
    # Origen del frontend desplegado (Vercel) para CORS; sin proxy no se permite nada.
    frontend_origin: str = Field(default="", validation_alias="FRONTEND_ORIGIN")
    # Usuario web de arranque (solo se crea si la tabla web_users esta vacia).
    web_username: str = Field(default="admin", validation_alias="HJ_WEB_USERNAME")
    web_password: str = Field(default="", validation_alias="HJ_WEB_PASSWORD")
    # UID de HJ (usuario de Telegram existente) con el que trabaja el motor.
    web_agent_uid: int = Field(default=0, validation_alias="HJ_WEB_AGENT_UID")
    web_session_ttl_h: int = Field(default=72, validation_alias="HJ_WEB_SESSION_TTL_H")
    # None = automatico (Secure salvo localhost); true/false fuerza.
    web_secure_cookies: Optional[bool] = Field(default=None, validation_alias="HJ_WEB_SECURE_COOKIES")
    web_default_model: str = Field(default="deepseek-chat", validation_alias="HJ_WEB_DEFAULT_MODEL")
    web_rate_limit_per_min: int = Field(default=240, validation_alias="HJ_WEB_RATE_LIMIT_PER_MIN")

    @field_validator("admin_user_ids", mode="before")
    @classmethod
    def _parse_ids(cls, v):
        # Acepta: int suelto (424242), str "424242", listas [1,2], "1,2" y "1; 2".
        # Bug A: list(int) lanzaba TypeError; ahora es tolerante a todos los formatos.
        if v in (None, ""):
            return []
        if isinstance(v, int):
            return [v]
        if isinstance(v, float) and float(v).is_integer():
            return [int(v)]
        if isinstance(v, str):
            out = []
            for x in v.replace(";", ",").split(","):
                x = x.strip().strip('"\'')
                if not x:
                    continue
                try:
                    out.append(int(x))
                except ValueError:
                    import logging
                    logging.getLogger(__name__).warning(
                        "HJ_ADMIN_USER_IDS: valor ignorado (no numerico): %r", x)
            return out
        try:
            return [int(x) for x in v]
        except (TypeError, ValueError):
            return []

    @field_validator("sandbox_network", "silent_reject", "allow_local_sandbox", mode="before")
    @classmethod
    def _parse_bool(cls, v):
        return _to_bool(v)

    @property
    def db_file(self) -> Path:
        return self.db_path or (self.data_dir / "hj.db")

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)

    # NOTA: la traduccion de rutas para el sandbox Docker vive en
    # core/sandbox/factory.py::resolve_host_workspace, que aplica
    # workspaces_host_dir a la subruta EXACTA del proyecto (nunca a la raiz
    # general de workspaces: cada sandbox monta solo su propio proyecto).


def load_settings(env_file: str | os.PathLike | None = None) -> Settings:
    s = Settings(_env_file=env_file) if env_file else Settings()
    s.ensure_dirs()
    return s
