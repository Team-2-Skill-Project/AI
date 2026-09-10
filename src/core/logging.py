import logging
import sys
from typing import Optional
from src.core.config import settings

LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s]: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_logging_configured = False

def setup_logging(log_level: Optional[str] = None) -> None:
    """
    Initializes centralized structured logging across SkillMatch AI.
    Sets consistent formatting, date representation, and default logging levels.
    """
    global _logging_configured
    level_name = (log_level or settings.LOG_LEVEL or "INFO").upper().strip()
    level = getattr(logging, level_name, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Avoid duplicate handlers if setup_logging is invoked multiple times
    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT)
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
    else:
        for handler in root_logger.handlers:
            handler.setLevel(level)
            formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT)
            handler.setFormatter(formatter)

    # Suppress excessive chatter from underlying HTTP and async libraries unless in DEBUG
    if level > logging.DEBUG:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("asyncio").setLevel(logging.WARNING)
        logging.getLogger("watchfiles").setLevel(logging.WARNING)

    _logging_configured = True
    logging.getLogger(__name__).debug(f"Logging initialized at level: {level_name}")

def get_logger(name: str) -> logging.Logger:
    """Retrieves a named logger instance."""
    if not _logging_configured:
        setup_logging()
    return logging.getLogger(name)
