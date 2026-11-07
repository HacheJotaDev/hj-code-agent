"""Auxiliares de presentacion: escape HTML, envio seguro, textos largos.

`send_safe` es la RED DE SEGURIDAD contra TelegramBadRequest: si el HTML es
invalido (p. ej. contenido generado por el modelo con etiquetas tipo
&lt;tarea&gt;), reintenta en texto plano en lugar de perder la respuesta.
"""
from __future__ import annotations

import html
import logging
from datetime import datetime, timezone

from aiogram.exceptions import TelegramBadRequest

log = logging.getLogger(__name__)


def esc(text) -> str:
    return html.escape(str(text if text is not None else ""), quote=False)


def fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n} B"


def fmt_money(v, currency: str = "USD") -> str:
    if v is None:
        return "n/d"
    return f"{v:.4f} {currency}"


def fmt_cost(v, currency: str = "USD") -> str:
    if v is None:
        return "n/d (sin tarifa configurada)"
    return f"{v:.4f} {currency}"


def fmt_dt(value: str | None) -> str:
    if not value:
        return "-"
    try:
        dt = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return dt.strftime("%d/%m %H:%M UTC")
    except ValueError:
        return str(value)[:16]


def trunc(s, n: int = 300) -> str:
    s = str(s or "")
    return s if len(s) <= n else s[: n - 1] + "…"


def _strip_html_tags(text: str) -> str:
    """Convierte un mensaje HTML roto en texto legible sin etiquetas."""
    import re
    txt = re.sub(r"</?(b|i|u|s|code|pre|a|blockquote|tg-spoiler|tg-emoji)[^>]*>", "", text)
    txt = txt.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return txt


async def send_safe(message, text: str, parse_mode: str | None = "HTML",
                    reply_markup=None) -> object:
    """Envia un mensaje; si Telegram rechaza el HTML lo reenvia en texto plano."""
    if parse_mode != "HTML":
        return await message.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)
    try:
        return await message.answer(text, parse_mode="HTML", reply_markup=reply_markup)
    except TelegramBadRequest as e:
        log.warning("HTML invalido ( %s ); reenviando en texto plano", str(e)[:120])
        return await message.answer(_strip_html_tags(text), reply_markup=reply_markup)


async def send_long(message, text: str, parse_mode: str | None = "HTML") -> None:
    """Envia un texto troceado al limite de Telegram (4096), con fallback seguro."""
    limit = 3900
    chunk = text
    first = True
    while chunk:
        piece, chunk = chunk[:limit], chunk[limit:]
        # no cortar una etiqueta HTML abierta por la mitad
        if parse_mode == "HTML" and chunk and piece.count("<") != piece.count(">"):
            cut = piece.rfind("<")
            if cut > limit // 2:
                chunk = piece[cut:] + chunk
                piece = piece[:cut]
        try:
            await message.answer(piece, parse_mode=parse_mode)
        except TelegramBadRequest:
            if parse_mode == "HTML":
                await message.answer(_strip_html_tags(piece))
            else:
                raise
        first = False
