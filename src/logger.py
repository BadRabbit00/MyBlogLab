"""Centralized structured logging module for blog-agent.

Provides multi-level logging (DEBUG, INFO, WARNING, ERROR, CRITICAL)
with console coloring and persistent file logging to logs/app.log.
Controlled by LOG_LEVEL environment variable (default: INFO).
"""

import logging
import os
import re
from pathlib import Path
import sys

from src.paths import DATA_DIR

BASE_DIR: Path = DATA_DIR
LOGS_DIR: Path = BASE_DIR / "logs"

# ANSI color codes for terminal output
COLOR_RESET = "\033[0m"
COLOR_DEBUG = "\033[36m"     # Cyan
COLOR_INFO = "\033[32m"      # Green
COLOR_WARNING = "\033[33m"   # Yellow
COLOR_ERROR = "\033[31m"     # Red
COLOR_CRITICAL = "\033[1;31m" # Bold Red


def redact_secrets(text: str) -> str:
    """Hide Telegram tokens, including those embedded in HTTP error URLs."""
    return re.sub(r"\b(?:bot)?\d{5,}:[A-Za-z0-9_-]{20,}", "[REDACTED]", text)


class SecretRedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_secrets(super().format(record))


class ColoredFormatter(SecretRedactingFormatter):
    """Custom logging formatter that injects ANSI colors based on level."""

    LEVEL_COLORS = {
        logging.DEBUG: COLOR_DEBUG,
        logging.INFO: COLOR_INFO,
        logging.WARNING: COLOR_WARNING,
        logging.ERROR: COLOR_ERROR,
        logging.CRITICAL: COLOR_CRITICAL,
    }

    def format(self, record: logging.LogRecord) -> str:
        color = self.LEVEL_COLORS.get(record.levelno, COLOR_RESET)
        record.levelname_colored = f"{color}{record.levelname:<8}{COLOR_RESET}"
        return super().format(record)


def setup_logging(
    level: str | None = None,
    log_to_file: bool = True,
    file_path: Path | None = None,
) -> logging.Logger:
    """Configure and return the root application logger."""
    env_level = os.getenv("LOG_LEVEL", "INFO").upper()
    active_level_name = (level or env_level).upper()
    numeric_level = getattr(logging, active_level_name, logging.INFO)

    root_logger = logging.getLogger("blog_agent")
    root_logger.setLevel(numeric_level)

    # Clear existing handlers to prevent duplication on multiple setups
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # Console handler with colors
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_format = "%(asctime)s [%(levelname_colored)s] [%(name)s] %(message)s"
    console_formatter = ColoredFormatter(console_format, datefmt="%Y-%m-%d %H:%M:%S")
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File handler with plain format (no ANSI escape codes)
    if log_to_file:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        target_log_file = file_path or (LOGS_DIR / "app.log")
        file_handler = logging.FileHandler(target_log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)  # File always logs all details from DEBUG up
        file_format = "%(asctime)s [%(levelname)-8s] [%(name)s] (%(filename)s:%(lineno)d) %(message)s"
        file_formatter = SecretRedactingFormatter(file_format, datefmt="%Y-%m-%d %H:%M:%S")
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

    return root_logger


def get_logger(module_name: str) -> logging.Logger:
    """Get a child logger configured under the blog_agent namespace."""
    return logging.getLogger(f"blog_agent.{module_name}")


# Initialize global default logger upon module import
logger: logging.Logger = setup_logging()
