"""Auxiliares de periodos (dias/mes) en UTC."""
from __future__ import annotations

from datetime import datetime, timezone


def today_start() -> str:
    d = datetime.now(timezone.utc)
    return d.strftime("%Y-%m-%d 00:00:00")


def month_start() -> str:
    d = datetime.now(timezone.utc)
    return d.strftime("%Y-%m-01 00:00:00")
