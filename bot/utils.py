"""Auxiliares de presentacion: escape HTML, textos largos, formatos."""
from __future__ import annotations

import html
from datetime import datetime, timezone


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
    return f"{v:.4f} {currency}".rstrip("0").rstrip(".") + ("" if v else "")


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


async def send_long(message, text: str, parse_mode: str | None = "HTML") -> None:
    """Envia un texto troceado al limite de Telegram (4096)."""
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
        target = message if first and hasattr(message, "answer") else message
        if first and hasattr(message, "answer"):
            await message.answer(piece, parse_mode=parse_mode)
        else:
            await message.answer(piece, parse_mode=parse_mode)
        first = False
