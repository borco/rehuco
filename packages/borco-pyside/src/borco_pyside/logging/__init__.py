"""Logging for a GUI app: console setup, and the bridge and models behind an in-app log surface."""

from .console_logging import setup_console_logging
from .log_bridge import DEFAULT_LOG_LIMIT, LogBridge
from .log_entry import LogEntry
from .log_filter_model import LogFilterModel
from .log_level_band import LogLevelBand
from .log_model import LEVEL_COLUMN, MESSAGE_COLUMN, LogModel
from .log_record_sink import LogRecordSink
from .log_scope import LOG_SCOPE_ATTRIBUTE, LogScope

__all__ = [
    "DEFAULT_LOG_LIMIT",
    "LEVEL_COLUMN",
    "LOG_SCOPE_ATTRIBUTE",
    "MESSAGE_COLUMN",
    "LogBridge",
    "LogEntry",
    "LogFilterModel",
    "LogLevelBand",
    "LogModel",
    "LogRecordSink",
    "LogScope",
    "setup_console_logging",
]
