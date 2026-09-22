"""This app's maximize toggle on every dock tab (#341).

`borco_pyside.qtads.QtAdsMaximizeHandler` ships no glyph: it takes one and leaves the icon set to
whoever uses it, which keeps a generic dock library out of rehuco's. This is the other half of that
arrangement -- the one place naming what the button wears, so every manager in the app (the window's
own, the documents area's, each document's, the task queue's) gets the same button from one call.
"""

from borco_pyside.qtads import QtAdsMaximizeHandler
from PySide6QtAds import CDockManager

from .glyphs import TAB_MAXIMIZE_GLYPH, TAB_RESTORE_GLYPH


def attach_maximize_handler(dock_manager: CDockManager) -> QtAdsMaximizeHandler:
    """Put the app's maximize toggle on every dock tab of ``dock_manager``.

    The handler parents itself to the manager; the return value is for a host that captures layouts
    and needs :meth:`~borco_pyside.qtads.QtAdsMaximizeHandler.unmaximized` around them.

    :param dock_manager: the manager whose docks get the button.
    :returns: the handler.
    """
    return QtAdsMaximizeHandler(dock_manager, TAB_MAXIMIZE_GLYPH, TAB_RESTORE_GLYPH)
