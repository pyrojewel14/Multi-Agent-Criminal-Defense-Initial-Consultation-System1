import logging
import os
import re
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

_MODULE_LEVELS: dict[str, int] = {}
_raw_module_levels = os.getenv("LOG_LEVEL_MODULES", "")
if _raw_module_levels:
    for item in _raw_module_levels.split(","):
        item = item.strip()
        if "=" in item:
            name, level_str = item.split("=", 1)
            level_val = getattr(logging, level_str.strip().upper(), None)
            if level_val is not None:
                _MODULE_LEVELS[name.strip()] = level_val

_PII_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\d{15}(\d{2}[\dXx])?"), "[ID-MASKED]"),
    (re.compile(r"1[3-9]\d{9}"), "[PHONE-MASKED]"),
    (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "[EMAIL-MASKED]"),
    (re.compile(r"\d{6}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]"), "[ID-MASKED]"),
]


class SensitiveFilter(logging.Filter):
    """Logging filter that masks PII (ID cards, phones, emails) in messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Apply all PII regex replacements to the log message."""
        msg = record.getMessage()
        for pattern, replacement in _PII_PATTERNS:
            msg = pattern.sub(replacement, msg)
        record.msg = msg
        record.args = None
        return True


_LOG_FORMAT = (
    "%(asctime)s | %(levelname)-5s | %(name)s | %(message)s"
)
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_file_handler = TimedRotatingFileHandler(
    filename=LOG_DIR / "consultation.log",
    when="midnight",
    interval=1,
    backupCount=30,
    encoding="utf-8",
)
_file_handler.suffix = "%Y%m%d"
_file_handler.setLevel(logging.DEBUG)
_file_handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
_file_handler.addFilter(SensitiveFilter())

_console_handler = logging.StreamHandler()
_console_handler.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
_console_handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
_console_handler.addFilter(SensitiveFilter())


def get_logger(name: str, level: int | str | None = None) -> logging.Logger:
    """Create or retrieve a logger with file + console handlers.

    Loggers are cached by name (stdlib behavior). Handlers are shared
    across all loggers and include PII filtering on every record.

    Args:
        name: Logger name, typically the module or class name.
        level: Optional override for this logger's effective level.
               Falls back to LOG_LEVEL_MODULES env → LOG_LEVEL env → INFO.

    Returns:
        A configured logging.Logger instance.
    """
    logger = logging.getLogger(name)
    resolved = (
        level
        or _MODULE_LEVELS.get(name)
        or getattr(logging, LOG_LEVEL, logging.INFO)
    )
    logger.setLevel(resolved)
    logger.propagate = False

    if not logger.handlers:
        logger.addHandler(_file_handler)
        logger.addHandler(_console_handler)

    return logger
