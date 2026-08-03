"""The one `LogBridge` every log surface attaches to, and this app's own look for them (#200).

Named ``app_logging`` rather than ``logging``: a module of that name inside this package would shadow
the standard library's for anything importing it absolutely, which the app's entry file does.
"""

import logging
from functools import lru_cache
from typing import Final

from borco_pyside.logging import DEFAULT_LOG_LIMIT, LogBridge, LogLevelBand, LogWidget, LogWidgetIcons
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

from .fields.colors import ERROR_COLOR, INFO_COLOR, WARNING_COLOR
from .settings.logs_settings import shared_logs_settings

LOG_VIEW_ICON_RESOURCE: Final = ":/icons/log_view.svg"
"""Toggles a log dock. The **same icon for both docks** -- the app-wide one on the window's action bar
and each resource's on its own view toolbar -- because they are the same kind of thing about different
subjects, which is what the surrounding toolbar already says."""

LOG_WIDGET_ICONS: Final = LogWidgetIcons(
    clear=":/icons/log_clear.svg",
    follow_tail=":/icons/log_scroll.svg",
    debugs=":/icons/log_debugs.svg",
    infos=":/icons/log_infos.svg",
    warnings=":/icons/log_warnings.svg",
    errors=":/icons/log_errors.svg",
)
"""This app's icons for a `LogWidget`'s controls -- borco-pyside ships none and names no resource
bundle, so every one of them is handed over from here."""

LOG_BAND_COLORS: Final = {
    LogLevelBand.INFOS: QColor(INFO_COLOR),
    LogLevelBand.WARNINGS: QColor(WARNING_COLOR),
    LogLevelBand.ERRORS: QColor(ERROR_COLOR),
}
"""What a log row is tinted by, from the same tokens the inline notice banner's severities use
(`rehuco_agent.fields.colors`) -- so a warning reads as the same color wherever the app draws
attention to one.

:attr:`~borco_pyside.logging.LogLevelBand.DEBUGS` is deliberately absent, which paints it plain: there
is nothing to draw attention to about a debug record, and a fourth tint would make the three that mean
something harder to pick out."""


@lru_cache(maxsize=1)
def shared_log_bridge() -> LogBridge:
    """The single, process-wide `LogBridge`, installed on the root logger on first call.

    **Call it before anything worth logging happens** -- ``run()`` does, right after
    ``setup_console_logging()``. The bridge caches what it receives and replays it to each surface as it
    attaches ([[appendices.logging#replay]]), so everything from that point on is in hand by the time
    there is a dock to show it: the settings read, the singleton check, a failure during startup.

    Capped at :attr:`~rehuco_agent.settings.logs_settings.LogsSettings.app_limit` and re-capped whenever
    that changes, because this cache is exactly what fills the app-wide surface on attach
    ([[appendices.logging#configured-limits]]) -- a bigger one could never be shown, and a smaller one
    would truncate the replay.

    An ``lru_cache`` accessor rather than a constructor parameter threaded through ``Application`` ->
    ``MainWindow`` -> ``DocumentsDock`` -> ``DocumentWidget``: four layers with no other reason to know
    about logging, the same shape :func:`~rehuco_agent.settings.persistent_settings.persistent_settings`
    and the shared settings sections already use.

    :returns: the shared bridge, already handling records.
    """
    settings = shared_logs_settings()
    bridge = LogBridge(limit=settings.app_limit)
    # the plain message, stated rather than inherited from logging's default formatter: a table has its
    # own level column, the entry carries the record for everything else, and the console's own format
    # would put its colorama escape codes into every visible row
    bridge.setFormatter(logging.Formatter("{message}", style="{"))

    def apply_limit(limit: int) -> None:
        """Re-cap the cache when the setting changes.

        :param limit: the newly-configured limit.
        """
        bridge.limit = limit

    settings.app_limit_changed.connect(apply_limit)  # type: ignore[attr-defined]  # synthesized by SimpleProperty
    logging.getLogger().addHandler(bridge)
    return bridge


def build_log_widget(parent: QWidget | None = None, *, limit: int = DEFAULT_LOG_LIMIT) -> LogWidget:
    """Build a `LogWidget` wearing this app's icons and colors.

    One place, so the app-wide dock and every resource's dock are recognisably the same surface -- the
    thing that differs between them is which records they are shown, not how they look.

    :param parent: optional Qt parent.
    :param limit: how many records the surface keeps.
    :returns: the widget, not yet attached to the bridge.
    """
    return LogWidget(parent, icons=LOG_WIDGET_ICONS, band_colors=LOG_BAND_COLORS, limit=limit)
