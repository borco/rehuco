"""Logging for a GUI app: console setup, the bridge and models, and the surface a reader reads."""

from .console_logging import DEFAULT_CONSOLE_LEVEL, setup_console_logging
from .log_bridge import DEFAULT_LOG_LIMIT, LogBridge
from .log_entry import LogEntry
from .log_filter_model import LogFilterModel
from .log_level_band import LogLevelBand
from .log_level_delegate import BAND_TINT_ALPHA, LogLevelDelegate
from .log_message_delegate import LogMessageDelegate
from .log_model import LEVEL_COLUMN, MESSAGE_COLUMN, LogModel
from .log_record_sink import LogRecordSink
from .log_view import LogView
from .log_widget import LogWidget, LogWidgetIcons

__all__ = [
    "BAND_TINT_ALPHA",
    "DEFAULT_CONSOLE_LEVEL",
    "DEFAULT_LOG_LIMIT",
    "LEVEL_COLUMN",
    "MESSAGE_COLUMN",
    "LogBridge",
    "LogEntry",
    "LogFilterModel",
    "LogLevelBand",
    "LogLevelDelegate",
    "LogMessageDelegate",
    "LogModel",
    "LogRecordSink",
    "LogView",
    "LogWidget",
    "LogWidgetIcons",
    "setup_console_logging",
]
