"""Safe provider diagnostics: never persist exception text, bodies or credentials."""

from openai import APIConnectionError, APITimeoutError

from .models import DomainError


class IdentificationProviderError(DomainError):
    def __init__(self, exc):
        status = getattr(exc, "status_code", None)
        status = status if type(status) is int and 400 <= status <= 599 else None
        if status == 401:
            category, retryable = "authentication", False
            message = "OpenAI rechazó la clave. Revisa la configuración antes de reintentar."
        elif status == 403:
            category, retryable = "permission", False
            message = "OpenAI rechazó el acceso. Revisa los permisos del proyecto y del modelo."
        elif status == 429:
            category, retryable = "rate_limit_or_quota", True
            message = "OpenAI indicó un límite de uso o cuota. Revisa la cuota antes de reintentar."
        elif isinstance(exc, APITimeoutError):
            category, retryable = "timeout", True
            message = "OpenAI tardó demasiado. El avance se conserva; puedes reintentar."
        elif isinstance(exc, APIConnectionError):
            category, retryable = "connection", True
            message = "No se pudo conectar con OpenAI. Revisa la conexión y vuelve a intentar."
        elif status and status >= 500:
            category, retryable = "provider_unavailable", True
            message = "OpenAI no está disponible temporalmente. Puedes reintentar después."
        else:
            category, retryable = "provider_request", False
            message = (
                "OpenAI no pudo procesar la identificación. Revisa el modelo y la configuración."
            )
        super().__init__(message)
        self.diagnostic = {
            "provider": "openai",
            "stage": "identification",
            "category": category,
            "http_status": status,
            "retryable": retryable,
        }
