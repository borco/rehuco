"""Generic helpers for `pyside6-qtads` (QtAds), not tied to any particular application."""

from .qtads_auto_hide_button_suppressor import QtAdsAutoHideButtonSuppressor
from .qtads_focus_tracker import QtAdsFocusTracker
from .qtads_widgets import tab_close_button, tab_label

__all__ = [
    "QtAdsAutoHideButtonSuppressor",
    "QtAdsFocusTracker",
    "tab_close_button",
    "tab_label",
]
