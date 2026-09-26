"""Logging for any app, GUI or headless: what a record is about, carried ambiently."""

from .log_scope import LOG_SCOPE_ATTRIBUTE, LogScope
from .shared_rotating_file_handler import SharedRotatingFileHandler

__all__ = ["LOG_SCOPE_ATTRIBUTE", "LogScope", "SharedRotatingFileHandler"]
