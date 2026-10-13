"""
Module pour la gestion des erreurs dans HomeStral.
"""


class HomestralError(Exception):
    """Classe de base pour les erreurs HomeStral."""

    def __init__(self, message, code=None, details=None):
        self.message = message
        self.code = code
        self.details = details
        super().__init__(self.message)

    def __str__(self):
        return f"HomestralError: {self.message} (Code: {self.code})"


class APIError(HomestralError):
    """Erreur liée à l'API Mistral."""

    def __init__(self, message, code=None, details=None):
        super().__init__(message, code, details)


class ConfigurationError(HomestralError):
    """Erreur liée à la configuration."""

    def __init__(self, message, code=None, details=None):
        super().__init__(message, code, details)


class AudioProcessingError(HomestralError):
    """Erreur liée au traitement audio."""

    def __init__(self, message, code=None, details=None):
        super().__init__(message, code, details)


class ConversationError(HomestralError):
    """Erreur liée à la gestion des conversations."""

    def __init__(self, message, code=None, details=None):
        super().__init__(message, code, details)


def log_error(logger, error, context=None):
    """Log une erreur avec des détails contextuels."""
    error_message = str(error)
    if context:
        error_message += f" Context: {context}"
    logger.error(error_message)
