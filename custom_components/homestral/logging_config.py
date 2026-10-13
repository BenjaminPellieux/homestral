"""
Module pour la configuration des logs dans HomeStral.
"""

import json
import logging
from datetime import datetime


class JSONFormatter(logging.Formatter):
    """Formateur de logs au format JSON."""

    def format(self, record):
        log_record = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record)


def setup_logging(level=logging.INFO, format="json"):
    """Configure les logs pour HomeStral."""
    logger = logging.getLogger("homestral")
    logger.setLevel(level)

    # Supprimer les handlers existants
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Ajouter un handler pour la console
    handler = logging.StreamHandler()
    if format == "json":
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


def get_logger(name="homestral"):
    """Récupère un logger configuré pour HomeStral."""
    return logging.getLogger(name)
