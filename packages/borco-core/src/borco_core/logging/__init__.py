"""Logging for any app, GUI or headless: what a record is about, carried ambiently, and which parts are links."""

from .log_link import LOG_LINKS_ATTRIBUTE, LogLink
from .log_scope import LOG_SCOPE_ATTRIBUTE, LogScope
from .shared_rotating_file_handler import SharedRotatingFileHandler

__all__ = ["LOG_LINKS_ATTRIBUTE", "LOG_SCOPE_ATTRIBUTE", "LogLink", "LogScope", "SharedRotatingFileHandler"]
