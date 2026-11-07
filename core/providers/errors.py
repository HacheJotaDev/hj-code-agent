"""Excepciones de proveedores con clasificacion de errores de API."""
from __future__ import annotations


class ProviderError(Exception):
    kind = "other"

    def __init__(self, message: str, kind: str | None = None, status: int | None = None):
        super().__init__(message)
        if kind:
            self.kind = kind
        self.status = status

    @property
    def user_message(self) -> str:
        return {
            "no_api_key": "Este proveedor no tiene API key configurada. Usa /setapi.",
            "auth": "Error de autenticacion con el proveedor. Revisa la API key (/setapi).",
            "insufficient_balance": "Saldo insuficiente en el proveedor. Recarga tu cuenta.",
            "rate_limit": "El proveedor esta limitando las peticiones. Espera e intentalo de nuevo.",
            "overloaded": "El proveedor esta sobrecargado. Intentalo de nuevo en unos minutos.",
            "bad_request": "Peticion rechazada por el proveedor (parametros o modelo invalido).",
            "not_found": "Modelo o recurso no encontrado en el proveedor.",
            "network": "No hay conexion con el proveedor. Revisa la red del VPS.",
            "other": "Error del proveedor.",
        }.get(self.kind, f"Error del proveedor: {self}")


class NoApiKey(ProviderError):
    kind = "no_api_key"
