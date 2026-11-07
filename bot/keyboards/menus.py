"""Teclados inline profesionales con navegacion y paginacion."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

MENU_SECTIONS = [
    ("chat", "💬 Chat con IA"),
    ("newproject", "📁 Nuevo proyecto"),
    ("projects", "🗂 Mis proyectos"),
    ("upload", "📤 Subir archivos"),
    ("github", "🐙 GitHub"),
    ("providers", "🧠 Modelos y proveedores"),
    ("sysprompt", "🧩 System prompts"),
    ("billing", "💳 Saldo y tokens"),
    ("tasks", "⚙️ Trabajos activos"),
    ("terminal", "🖥 Terminal y herramientas"),
    ("stats", "📊 Estadísticas"),
    ("settings", "🔧 Configuración"),
    ("help", "❓ Ayuda"),
]


def main_menu_kb(status: str = "") -> InlineKeyboardMarkup:
    """Menú principal V3: sencillo; GitHub vive en Configuración."""
    kb = InlineKeyboardBuilder()
    kb.button(text="💬 Chat con IA", callback_data="menu:chatinfo")
    kb.button(text="📎 Enviar proyecto", callback_data="menu:upload")
    kb.button(text="📁 Mis proyectos", callback_data="menu:projects")
    kb.button(text="🛠 Tareas activas", callback_data="menu:tasks")
    kb.button(text="🧠 Modelo", callback_data="menu:providers")
    kb.button(text="💳 Saldo y tokens", callback_data="menu:billing")
    kb.button(text="⚙️ Configuración", callback_data="menu:settings")
    kb.button(text="🐙 GitHub (opcional)", callback_data="menu:github")
    kb.button(text="❓ Ayuda", callback_data="menu:help")
    kb.adjust(2, 2, 2, 2, 2, 1)
    return kb.as_markup()


def back_kb(target: str = "menu") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Volver", callback_data=f"menu:{target}")
    return kb.as_markup()


def confirm_kb(prefix: str, item_id: str, yes_label: str = "✅ Confirmar",
               no_label: str = "❌ Cancelar") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=yes_label, callback_data=f"{prefix}:yes:{item_id}")
    kb.button(text=no_label, callback_data=f"{prefix}:no:{item_id}")
    return kb.as_markup()


def providers_kb(providers: list[dict], active: str | None = None,
                 creds: list[str] | None = None) -> InlineKeyboardMarkup:
    creds = creds or []
    kb = InlineKeyboardBuilder()
    for p in providers:
        mark = "● " if p["name"] == active else ""
        key = "🔑 " if p["name"] in creds else ""
        kb.button(text=f"{mark}{key}{p['name']}", callback_data=f"prov:sel:{p['name']}")
    kb.button(text="➕ Añadir proveedor", callback_data="prov:add")
    kb.button(text="🗑 Eliminar proveedor", callback_data="prov:rm")
    kb.button(text="⬅️ Volver", callback_data="menu:settings")
    kb.adjust(2, 2, 2, 1, 1)
    return kb.as_markup()


def models_kb(models: list[str], page: int = 0, per_page: int = 8) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    chunk = models[page * per_page:(page + 1) * per_page]
    for i, m in enumerate(chunk):
        # callback por INDICE: los ids largos no caben en 64 bytes
        kb.button(text=m[:40], callback_data=f"mdl:sel:{page}:{page * per_page + i}")
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"mdl:page:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{max(1, (len(models) + per_page - 1) // per_page)}",
                                    callback_data="noop"))
    if (page + 1) * per_page < len(models):
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"mdl:page:{page + 1}"))
    kb.button(text="🔄 Actualizar lista", callback_data="mdl:refresh")
    kb.adjust(2)
    rows = kb.as_markup()
    if nav:
        rows.inline_keyboard.append(nav)
    rows.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Volver", callback_data="menu:providers")])
    return rows


def projects_kb(projects: list[dict], active_id: int | None = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in projects:
        mark = "● " if p["id"] == active_id else ""
        kb.button(text=f"{mark}{p['name']}", callback_data=f"proj:sel:{p['id']}")
    kb.button(text="➕ Nuevo", callback_data="menu:newproject")
    kb.button(text="⬅️ Volver", callback_data="menu")
    kb.adjust(2, 2)
    return kb.as_markup()


def project_actions_kb(pid: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="ℹ️ Info", callback_data=f"proj:info:{pid}")
    kb.button(text="📤 Exportar ZIP", callback_data=f"proj:export:{pid}")
    kb.button(text="💾 Archivar", callback_data=f"proj:archive:{pid}")
    kb.button(text="🗑 Borrar", callback_data=f"proj:del:{pid}")
    kb.button(text="⬅️ Proyectos", callback_data="menu:projects")
    kb.adjust(2, 2, 1)
    return kb.as_markup()


def tasks_kb(tasks: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for t in tasks:
        icon = {"queued": "⏳", "running": "🏃", "done": "✅", "failed": "❌",
                "cancelled": "🛑", "interrupted": "⚡"}.get(t["status"], "•")
        kb.button(text=f"{icon} #{t['id']} {t['title'][:24]}", callback_data=f"task:info:{t['id']}")
    kb.button(text="⬅️ Volver", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()


def system_prompt_kb(mode: str, has_content: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✍️ Definir/Editar", callback_data="sysp:set")
    kb.button(text="👁 Ver", callback_data="sysp:show")
    kb.button(text="📴 Desactivar", callback_data="sysp:off")
    kb.button(text="🗑 Eliminar", callback_data="sysp:clear")
    kb.button(text="♻️ Modo nativo", callback_data="sysp:reset")
    kb.button(text="📤 Exportar", callback_data="sysp:export")
    kb.button(text="📥 Importar", callback_data="sysp:import")
    kb.button(text="📁 Prompt de proyecto", callback_data="sysp:project")
    kb.adjust(2)
    return kb.as_markup()


def github_kb(connected: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔌 Conectar" if not connected else "✅ Conectado (ver estado)",
              callback_data="gh:connect" if not connected else "gh:status")
    kb.button(text="📂 Añadir repositorio", callback_data="gh:repoadd")
    kb.button(text="⬇️ Clonar", callback_data="gh:clone")
    kb.button(text="🌿 Ramas", callback_data="gh:branches")
    kb.button(text="📜 Historial", callback_data="gh:history")
    kb.button(text="⬆️ Push", callback_data="gh:push")
    kb.button(text="🔀 Pull", callback_data="gh:pull")
    kb.button(text="🚀 Auto-push", callback_data="gh:autopush")
    kb.button(text="⛔ Desconectar", callback_data="gh:disconnect")
    kb.button(text="⬅️ Volver", callback_data="menu")
    kb.adjust(2, 2, 2, 2, 2)
    return kb.as_markup()


def settings_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔑 API keys (/setapi)", callback_data="cfg:setapi")
    kb.button(text="🌡 Parámetros (/params)", callback_data="cfg:params")
    kb.button(text="💰 Presupuesto (/budget)", callback_data="cfg:budget")
    kb.button(text="🔔 Alertas (/alerts)", callback_data="cfg:alerts")
    kb.button(text="🧪 Sandbox (/sandbox)", callback_data="cfg:sandbox")
    kb.button(text="📤 Exportar config", callback_data="cfg:export")
    kb.button(text="📥 Importar config", callback_data="cfg:import")
    kb.button(text="⬅️ Volver", callback_data="menu")
    kb.adjust(2, 2, 2, 1, 1)
    return kb.as_markup()


def agents_kb(enabled: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=("⏹ Desactivar" if enabled else "▶️ Activar"), callback_data="agents:toggle")
    kb.button(text="➕ Añadir perfil", callback_data="agents:add")
    kb.button(text="🗑 Quitar perfil", callback_data="agents:remove")
    kb.button(text="⚙️ Configurar", callback_data="agents:config")
    kb.button(text="📈 Estado", callback_data="agents:status")
    kb.button(text="⬅️ Volver", callback_data="menu")
    kb.adjust(2, 2, 2)
    return kb.as_markup()


def approval_kb(req_id: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Autorizar", callback_data=f"auth:yes:{req_id}")
    kb.button(text="❌ Rechazar", callback_data=f"auth:no:{req_id}")
    return kb.as_markup()


def chat_or_task_kb(token: str) -> InlineKeyboardMarkup:
    """Elección sencilla cuando hay ambigüedad (V3)."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🛠 Trabajar en el código", callback_data=f"choice:task:{token}")
    kb.button(text="💬 Solo es una pregunta", callback_data=f"choice:chat:{token}")
    kb.adjust(1)
    return kb.as_markup()
