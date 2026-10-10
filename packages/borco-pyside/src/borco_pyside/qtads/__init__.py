"""Generic helpers for `pyside6-qtads` (QtAds), not tied to any particular application."""

from .qtads_auto_hide_button_suppressor import QtAdsAutoHideButtonSuppressor
from .qtads_dock_removal import remove_dock_widget
from .qtads_floating_show_guard import QtAdsFloatingShowGuard
from .qtads_focus_tracker import QtAdsFocusTracker
from .qtads_layout import QtAdsLayout
from .qtads_lone_tab_hider import QtAdsLoneTabHider
from .qtads_maximize_handler import QtAdsMaximizeHandler
from .qtads_pin_guard import QtAdsPinGuard
from .qtads_pin_side_handler import QtAdsPinSideHandler
from .qtads_tab_context_actions import QtAdsTabContextActions
from .qtads_widgets import tab_close_button, tab_label, tab_maximize_button

__all__ = [
    "QtAdsAutoHideButtonSuppressor",
    "QtAdsFloatingShowGuard",
    "QtAdsFocusTracker",
    "QtAdsLayout",
    "QtAdsLoneTabHider",
    "QtAdsMaximizeHandler",
    "QtAdsPinGuard",
    "QtAdsPinSideHandler",
    "QtAdsTabContextActions",
    "remove_dock_widget",
    "tab_close_button",
    "tab_label",
    "tab_maximize_button",
]
