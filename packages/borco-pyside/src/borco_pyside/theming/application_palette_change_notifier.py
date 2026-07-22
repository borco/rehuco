"""A single application-wide source of ``QApplication`` palette-change notifications."""

from typing import Final, override

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import QApplication


class ApplicationPaletteChangeNotifier(QObject):
    """Re-exposes ``QApplication``'s palette changes as a plain :attr:`palette_changed` signal,
    backed by **one** application-wide event filter shared by every listener.

    Replaces connecting to ``QApplication.paletteChanged`` (deprecated since Qt 6.0) with handling
    ``QEvent.Type.ApplicationPaletteChange``. That event is the authoritative point at which a theme
    switch's new colours are actually readable from the palette -- unlike
    ``QStyleHints.colorSchemeChanged``, which can fire while the palette is still the pre-switch one.

    The event filter is installed on the application object, so it sees events for *every* object in
    the app. Three things shape this design:

    * **One switch, one emit.** Qt fires ``ApplicationPaletteChange`` *several times* for a single
      theme switch (measured: four times on Windows, all carrying the identical new palette). The old
      ``paletteChanged`` signal fired once; matching that matters because each emit rebuilds every
      themed icon (an SVG re-render). :meth:`eventFilter` coalesces by :meth:`QPalette.cacheKey`,
      emitting only when the palette actually differs from the last one emitted for -- so the repeated
      events collapse back to a single rebuild per switch.
    * **One filter, not one per listener.** An app-wide filter is invoked for *every* event, so its
      cost is paid by the whole application. Each listener installing its own filter would make that
      cost O(listeners); instead all listeners share this **single** notifier (one per
      ``QApplication``, via :meth:`for_application`) and connect to its signal.
    * **Right moment.** ``ApplicationPaletteChange`` is the point at which a theme switch's new colors
      are actually readable -- unlike ``QStyleHints.colorSchemeChanged``, which fires while the palette
      is still the pre-switch one (measured, and the reason it is not used).

    Parented to the application, so Qt drops the installed filter and destroys the notifier when the
    application goes away. Listeners connect a bound method to :attr:`palette_changed`; Qt severs the
    connection when the listener is destroyed, so nothing needs explicit teardown.
    """

    palette_changed = Signal()
    """Emitted once each time the application's palette actually changes (a theme switch)."""

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self.__app: Final = app
        self.__last_palette_key = app.palette().cacheKey()

    @classmethod
    def for_application(cls, app: QApplication) -> ApplicationPaletteChangeNotifier:
        """Return ``app``'s shared notifier, creating and installing it on first use.

        Scoped to ``app`` (found among its direct children), not a process-wide singleton, so a
        fresh ``QApplication`` -- e.g. a later test -- gets its own notifier rather than a dangling
        one bound to a destroyed application.

        :param app: the running application to share a notifier across.
        :returns: the one notifier for ``app``, its event filter already installed.
        """
        # A direct child of the app (parented in __init__), so scope the lookup to direct children
        # -- a recursive walk of the whole object tree on every handler construction is needless.
        existing = app.findChild(cls, options=Qt.FindChildOption.FindDirectChildrenOnly)
        if existing is not None:
            return existing
        notifier = cls(app)
        app.installEventFilter(notifier)
        return notifier

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        # `watched is app` early-outs cheaply for the flood of events aimed at other objects. On an
        # ApplicationPaletteChange, coalesce by cacheKey: Qt fires this event several times per switch
        # (all with the same new palette), so emit only when the palette genuinely differs from the
        # last one emitted for -- collapsing the repeats to a single rebuild, as `paletteChanged` did.
        if watched is self.__app and event.type() == QEvent.Type.ApplicationPaletteChange:
            key = self.__app.palette().cacheKey()
            if key != self.__last_palette_key:
                self.__last_palette_key = key
                self.palette_changed.emit()
        return super().eventFilter(watched, event)
