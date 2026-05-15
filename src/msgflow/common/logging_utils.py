from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


DEFAULT_LOG_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_LOG_BACKUP_COUNT = 5
LOG_FILE_ENV = "MSGFLOW_LOG_FILE"


def _int_env(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if not raw_value:
        return default
    try:
        parsed = int(raw_value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def create_rotating_file_handler(path: Path, formatter: logging.Formatter, level: int) -> logging.Handler:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        path,
        maxBytes=_int_env("MSGFLOW_LOG_MAX_BYTES", DEFAULT_LOG_MAX_BYTES),
        backupCount=_int_env("MSGFLOW_LOG_BACKUP_COUNT", DEFAULT_LOG_BACKUP_COUNT),
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(formatter)
    return handler


def configure_root_logging(*, level: int, formatter: logging.Formatter, log_path: Path | None = None) -> None:
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        handler.close()
    root_logger.setLevel(level)
    if log_path is not None:
        root_logger.addHandler(create_rotating_file_handler(log_path, formatter, level))
    else:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setLevel(level)
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)
    logging.captureWarnings(True)


def install_unhandled_exception_logging(logger: logging.Logger) -> None:
    def _handle_exception(exc_type, exc_value, exc_traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = _handle_exception
