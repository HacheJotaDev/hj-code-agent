"""Harness de integracion V3: dispatcher REAL + updates de Telegram simulados.

- `RecordingSession`: sustituye la sesion HTTP de aiogram; graba cada llamada
  (send_message, edit, get_file, download...) y devuelve resultados validos.
- `build_dispatcher(services)`: construye el Dispatcher con los routers y
  middlewares REALES de la aplicacion (contexto -> dedup -> auth).
- `feed(bot, services, update)`: inyecta una Update real en el pipeline.
- `assert_valid_html(text)`: valida que el HTML que enviariamos a Telegram no
  contiene etiquetas no soportadas (el fallo real: Unsupported start tag).
"""
from __future__ import annotations

import datetime
import io
import itertools
import re
import time
from types import SimpleNamespace

from aiogram import Bot, Dispatcher
from aiogram.client.telegram import TelegramAPIServer
from aiogram.types import (
    CallbackQuery, Chat, Document, File, Message, PhotoSize, Update, User,
)

_UPDATE_IDS = itertools.count(int(time.time()) * 1000)


def _uid() -> int:
    return next(_UPDATE_IDS)

ALLOWED_TAGS = {"b", "i", "u", "s", "code", "pre", "a", "blockquote",
                "tg-spoiler", "tg-emoji"}
_TAG_RE = re.compile(r"<(/?)([a-zA-Z-]+)[^>]*>")


def assert_valid_html(text: str) -> None:
    """Lanza AssertionError si el HTML usa etiquetas no soportadas por Telegram."""
    for closing, tag in _TAG_RE.findall(text or ""):
        assert tag.lower() in ALLOWED_TAGS, \
            f"Etiqueta HTML invalida <{tag}> (TelegramBadRequest): {text[:120]!r}"


def msg_texts(session) -> list[str]:
    return [m.text or "" for m in session.sent if isinstance(m, Message)]


class RecordingSession:
    """Sesion falsa: registra metodos y sirve archivos de prueba."""

    def __init__(self, downloads: dict[str, bytes] | None = None):
        self.calls: list = []
        self.sent: list[Message] = []
        self.downloads = downloads or {}   # file_path -> bytes
        # Server API real (solo construye URLs; sin red)
        self.api = TelegramAPIServer.from_base("https://api.telegram.org")

    async def __call__(self, bot, method, timeout=None):
        self.calls.append(method)
        name = type(method).__name__
        if name == "SendMessage":
            m = Message(
                message_id=len(self.calls), date=datetime.datetime.now(),
                chat=Chat(id=method.chat_id, type="private"), text=method.text,
            )
            self.sent.append(m)
            return m
        if name in ("EditMessageText", "DeleteMessage", "AnswerCallbackQuery",
                    "SetMyCommands", "DeleteWebhook", "SetWebhook"):
            return True
        if name == "GetFile":
            return File(file_id=method.file_id, file_unique_id=method.file_id,
                        file_size=100, file_path=method.file_id)
        return True

    async def close(self):
        pass

    def stream_content(self, url, *, headers=None, timeout=30,
                       chunk_size=65536, raise_for_status=True):
        """Bot.download_file llama aqui; servimos los bytes de prueba."""
        path = url.rsplit("/", 1)[-1]
        data = self.downloads.get(path, b"")

        async def gen():
            yield data
        return gen()


def make_bot(session: RecordingSession) -> Bot:
    return Bot(token="123456789:AAE-fake-token-1234567890123456789", session=session)


# Los routers de aiogram son singletons: el dispatcher se construye UNA vez y
# el contexto (servicios) se inyecta por test mediante una referencia mutable.
_CURRENT = {"ctx": None}


class _CtxMiddleware:
    def __init__(self, holder):
        self.holder = holder

    async def __call__(self, handler, event, data):
        data["ctx"] = self.holder["ctx"]
        return await handler(event, data)


def set_ctx(services) -> None:
    _CURRENT["ctx"] = services


def build_dispatcher_once() -> Dispatcher:
    """Dispatcher REAL con routers y middlewares de produccion (una sola vez)."""
    from bot.handlers import ALL_ROUTERS
    from bot.middlewares import AuthMiddleware, UpdateDedupMiddleware

    dp = Dispatcher()
    dp.update.middleware(_CtxMiddleware(_CURRENT))
    dp.update.middleware(UpdateDedupMiddleware())
    dp.update.middleware(AuthMiddleware())
    for r in ALL_ROUTERS:
        dp.include_router(r)
    return dp


def tg_user(uid: int = 111) -> User:
    return User(id=uid, is_bot=False, first_name="Admin", username=f"u{uid}")


def make_message(text: str, uid: int = 111, chat_id: int = 100) -> Update:
    return Update(update_id=_uid(),
                  message=Message(message_id=1, date=datetime.datetime.now(),
                                  chat=Chat(id=chat_id, type="private"),
                                  from_user=tg_user(uid), text=text))


def make_document(file_id: str, file_name: str, size: int = 500,
                  uid: int = 111, chat_id: int = 100) -> Update:
    doc = Document(file_id=file_id, file_unique_id=file_id, file_name=file_name,
                   file_size=size, mime_type="application/zip")
    return Update(update_id=_uid(),
                  message=Message(message_id=2, date=datetime.datetime.now(),
                                  chat=Chat(id=chat_id, type="private"),
                                  from_user=tg_user(uid), document=doc))


def make_callback(data: str, uid: int = 111, chat_id: int = 100) -> Update:
    msg = Message(message_id=3, date=datetime.datetime.now(),
                  chat=Chat(id=chat_id, type="private"), from_user=tg_user(uid),
                  text="mensaje original")
    cb = CallbackQuery(id="cb1", from_user=tg_user(uid), data=data,
                       chat_instance="ci", message=msg)
    return Update(update_id=_uid(),
                  callback_query=cb)


async def feed(dp: Dispatcher, bot: Bot, update: Update):
    return await dp.feed_update(bot, update)


def fake_queue() -> SimpleNamespace:
    return SimpleNamespace(running_for_user=lambda uid: [],
                           cancel=lambda tid: False,
                           kick=lambda: None)
