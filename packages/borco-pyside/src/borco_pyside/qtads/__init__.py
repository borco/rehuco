"""Generic helpers for `pyside6-qtads` (QtAds), not tied to any particular application."""

from .qtads_auto_hide_button_suppressor import QtAdsAutoHideButtonSuppressor
from .qtads_dock_removal import remove_dock_widget
from .qtads_emptying_guard import QtAdsEmptyingGuard
from .qtads_floating_show_guard import QtAdsFloatingShowGuard
from .qtads_focus_tracker import QtAdsFocusTracker
from .qtads_layout import QtAdsLayout
from .qtads_lone_tab_hider import QtAdsLoneTabHider
from .qtads_maximize_handler import QtAdsMaximizeHandler
from .qtads_pin_guard import QtAdsPinGuard
from .qtads_pin_side_handler import QtAdsPinSideHandler
from .qtads_tab_context_actions import QtAdsTabContextActions
from .qtads_title_bar_action_visibility import QtAdsTitleBarActionVisibility
from .qtads_widgets import tab_close_button, tab_label, tab_maximize_button

__all__ = [
    "QtAdsAutoHideButtonSuppressor",
    "QtAdsEmptyingGuard",
    "QtAdsFloatingShowGuard",
    "QtAdsFocusTracker",
    "QtAdsLayout",
    "QtAdsLoneTabHider",
    "QtAdsMaximizeHandler",
    "QtAdsPinGuard",
    "QtAdsPinSideHandler",
    "QtAdsTabContextActions",
    "QtAdsTitleBarActionVisibility",
    "remove_dock_widget",
    "tab_close_button",
    "tab_label",
    "tab_maximize_button",
]
