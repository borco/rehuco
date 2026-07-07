"""Generic helpers for `pyside6-qtads` (QtAds), not tied to any particular application."""

from borco_pyside.qtads.qtads_focus_tracker import QtAdsFocusTracker
from borco_pyside.qtads.qtads_widgets import tab_close_button, tab_label

__all__ = [
    "QtAdsFocusTracker",
    "tab_close_button",
    "tab_label",
]
