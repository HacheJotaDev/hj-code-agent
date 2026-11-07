"""Deteccion de intencion V3: chat normal vs. tarea de programacion.

Heuristica LOCAL y explicable (sin llamadas al modelo ni system prompts
ocultos). Si la puntuacion supera el umbral y hay proyecto activo, el texto se
trata como tarea del agente (equivalente a /run); si es ambiguo, se ofrece una
eleccion con botones.
"""
from __future__ import annotations

import re
import unicodedata


def _norm(text: str) -> str:
    """minúsculas sin acentos para la comparación."""
    t = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


# Verbos/acciones tipicas de una peticion de codigo (ES/EN)
_STRONG = [
    "crea", "creame", "cread", "crear", "haz", "hacer", "implementa", "implementar",
    "corrige", "corregir", "arregla", "arreglar", "repara", "refactoriza",
    "refactorizar", "reestructura", "mejora", "optimiza", "anade", "añade",
    "agrega", "agregar", "modifica", "modificar", "cambia", "eliminar",
    "elimina", "borra", "escribe", "genera", "generar", "construye", "monta",
    "programa", "desarrolla", "convierte", "migra", "pasa los tests",
    "ejecuta", "lanza los tests", "compila", "build", "deploy",
    "create", "implement", "fix", "refactor", "write", "build me", "make",
]
_SOFT = [
    "proyecto", "codigo", "funcion", "clase", "modulo", "archivo", "tests",
    "test", "pytest", "bug", "error", "api", "script", "servidor", "bot",
    "cli", "endpoint", "requirements", "package.json", "python", "javascript",
    "typescript", "java", "html", "prueba", "pruebas",
]
# Preguntas conversacionales que NO son tareas aunque contengan verbos blandos
_QUESTION = re.compile(
    r"^\s*[^a-z0-9]*(que|cual|como|quien|cuando|por que|puedes explic|explicame"
    r"|dime que|what|how|why|who)\b", re.IGNORECASE)
_CODE_HINT = re.compile(r"```\w*\n|def |class |import |function |print\(|git |pip |npm ", re.MULTILINE)


def looks_like_code_task(text: str) -> bool:
    """True = claramente una peticion de programacion."""
    t = (text or "").strip()
    if not t or _QUESTION.match(_norm(t)):
        return False
    low = _norm(t)
    if _CODE_HINT.search(t):
        return True
    strong = sum(1 for w in _STRONG if re.search(rf"\b{re.escape(_norm(w))}\b", low))
    soft = sum(1 for w in _SOFT if _norm(w) in low)
    return strong >= 1 and (soft >= 1 or len(t.split()) >= 4)


def is_ambiguous(text: str) -> bool:
    """True = hay verbo de accion pero parece conversacional (mejor preguntar)."""
    t = (text or "").strip()
    if not t or _QUESTION.match(_norm(t)):
        return False
    low = _norm(t)
    strong = sum(1 for w in _STRONG if re.search(rf"\b{re.escape(_norm(w))}\b", low))
    soft = sum(1 for w in _SOFT if _norm(w) in low)
    return strong >= 1 and soft == 0 and len(t.split()) < 6
