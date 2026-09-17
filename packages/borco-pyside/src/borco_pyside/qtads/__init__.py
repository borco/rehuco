"""Generic helpers for `pyside6-qtads` (QtAds), not tied to any particular application."""

from .qtads_auto_hide_button_suppressor import QtAdsAutoHideButtonSuppressor
from .qtads_floating_show_guard import QtAdsFloatingShowGuard
from .qtads_focus_tracker import QtAdsFocusTracker
from .qtads_pin_side_handler import QtAdsPinSideHandler
from .qtads_widgets import tab_close_button, tab_label

__all__ = [
    "QtAdsAutoHideButtonSuppressor",
    "QtAdsFloatingShowGuard",
    "QtAdsFocusTracker",
    "QtAdsPinSideHandler",
    "tab_close_button",
    "tab_label",
]
