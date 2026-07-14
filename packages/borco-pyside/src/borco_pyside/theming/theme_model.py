"""The app's theme mode: a single source of truth distinct from the OS-resolved color scheme."""

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication


class ThemeModel(QObject):
    """Owns the app's chosen theme **mode** -- ``Qt.ColorScheme.Unknown`` (follow system), ``Light``,
    or ``Dark`` -- kept as its own piece of state, deliberately distinct from
    ``QApplication.styleHints().colorScheme()`` itself.

    That distinction is the whole point of this class: ``colorScheme()`` reports the *resolved*
    appearance, and Qt resolves ``Unknown`` to whatever the OS actually is (``Light`` or ``Dark``)
    the moment it's queried on a platform that can detect it -- it does **not** echo ``Unknown``
    back. Reading it as "the current mode" -- which an earlier version of this feature did -- cannot
    tell "explicitly ``Light``" apart from "``Unknown``, currently resolving to ``Light`` because the
    OS happens to be in light mode" (#57): a toolbar cycling forward from that state would skip
    ``Unknown`` entirely, a ``View`` menu would check the wrong entry, and persisting "the current
    scheme" at shutdown would silently downgrade a genuine "follow system" choice to a pinned one.

    Every mode-driven view -- a toolbar's 3-state cycling action
    (:class:`~borco_pyside.theming.ThemeManager`), a ``View`` menu's three checkable entries
    (:class:`~borco_pyside.theming.ThemeMenu`) -- reads/writes :attr:`mode` and listens to
    :attr:`mode_changed` instead, both independent of one another and of Qt's own
    ``QStyleHints.colorSchemeChanged`` (left alone here for whatever else cares about the *resolved*
    appearance, e.g. :class:`~borco_pyside.theming.ActionIconThemeHandler`'s own repaint via
    ``QApplication.paletteChanged``).

    ``mode`` is applied to ``QApplication.styleHints().setColorScheme()`` immediately on
    construction and again on every subsequent change. ``Unknown`` is itself what asks Qt to keep
    live-tracking the OS's own theme changes -- nothing further is needed here for that tracking to
    keep working, since :attr:`mode` only ever changes in response to an explicit pick (a click on
    either view, or a persisted choice restored on launch), never in reaction to the OS changing
    what ``Unknown`` currently resolves to.

    :param mode: the initial mode, e.g. a persisted choice restored on launch.
    :param parent: optional Qt parent.
    """

    mode_changed = Signal(Qt.ColorScheme)

    def __init__(self, mode: Qt.ColorScheme = Qt.ColorScheme.Unknown, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__mode = mode
        QApplication.styleHints().setColorScheme(mode)

    @property
    def mode(self) -> Qt.ColorScheme:
        """The currently chosen theme mode."""
        return self.__mode

    @mode.setter
    def mode(self, mode: Qt.ColorScheme) -> None:
        if mode == self.__mode:
            return
        self.__mode = mode
        QApplication.styleHints().setColorScheme(mode)
        self.mode_changed.emit(mode)
