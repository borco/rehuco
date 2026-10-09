"""Keeps QtAds floating dock windows off the screen while the window that owns them is not up yet."""

from typing import Final, override

import PySide6QtAds as QtAds
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication


class QtAdsFloatingShowGuard(QObject):
    """Stops any `CFloatingDockContainer` shown while this guard is armed from reaching the screen.

    For the one window in a dock-shell app that restores its layout during construction. QtAds'
    ``CDockManager.addDockWidgetFloating`` defers a freshly floated dock's window until its owner is shown (it parks
    the container in QtAds' own uninitialised-floating-widgets list), but only while it holds that one dock: adding a
    second dock to its area -- what a layout restore does to rebuild a floating window of several (`QtAdsLayout`,
    #102), as ``CDockManager.restoreState`` did for any floating-and-open dock -- shows it at once, regardless of
    whether the owning window exists on screen yet. Since the restore has to happen before that window is first shown
    -- restoring afterwards visibly resettles a layout the user is already looking at -- the dialog would otherwise
    appear, alone, a moment ahead of the window it belongs to.

    **Hiding the container again afterwards is not enough**, which is what this class exists for: the
    native window is mapped and painted synchronously inside the ``show()``, measured on a real
    platform plugin, so a hide on the next line shortens the flash rather than removing it.

    **What it does instead is stop the map.** ``QWidgetPrivate::show_sys`` -- the step that creates and
    maps the native window -- returns early for a widget carrying ``WA_DontShowOnScreen``, and Qt
    delivers ``QEvent.Show`` to the widget *before* calling it. So an application-wide filter that sets
    the attribute while handling that event leaves the container "shown" as far as Qt's bookkeeping is
    concerned, with nothing ever presented: verified on a real plugin, where the container's `Paint`
    before the owning window's disappears entirely ([[appendices.qt-ads#restore-shows-floating]]).

    Held containers are handed back by :meth:`release`, hidden and cleared of the attribute, ready for
    an ordinary ``show()`` once the caller's window is up. A held container is *visible* to Qt but
    unmapped, so it has to be hidden before the attribute goes, or a later ``show()`` is a no-op --
    and hidden **exactly once**: a second ``hide()`` on one already hidden was seen to crash the
    process, which is why the release, not its caller, is the one place that decides it.

    Armed from construction and disarmed by :meth:`release`, which is also the only way to get the
    containers back -- a guard never released leaves them invisible for good.

    **No container's Python wrapper is kept** between the two: a container shown in the middle of a QtAds
    call -- a second dock tabbed into a floating window by a structural restore (#102) -- has the wrapper the
    filter saw invalidated before that call returns, while the window lives on. :meth:`release` finds the
    held containers again by the attribute the filter set, which nothing else in the app sets.
    """

    def __init__(self) -> None:
        super().__init__()
        self.__armed = True
        self.__app: Final = QApplication.instance()
        if self.__app is not None:
            self.__app.installEventFilter(self)

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Mark a floating container being shown as not-for-the-screen, and remember it.

        Application-wide rather than installed on one manager: a `CFloatingDockContainer` is a
        top-level window of its own, so there is no parent to watch it through, and a dock-shell app
        nests managers -- a torn-out document's container is as much "ahead of the window" as the
        settings dialog's.

        Never consumes the event (always returns ``False``): the container's own handling of being
        shown still has to run, and so does every other filter's.

        :param watched: the object the event is headed for.
        :param event: the event.
        :returns: ``False``, always.
        """
        if event.type() == QEvent.Type.Show and isinstance(watched, QtAds.CFloatingDockContainer):
            watched.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        return False

    def release(self) -> tuple[QtAds.CFloatingDockContainer, ...]:
        """Disarm, and hand back every container held, hidden and with the attribute cleared.

        Each is hidden first -- once, and only if still visible, see the class docstring for why both
        matter -- then cleared, so a plain ``show()`` maps a real window. Calling this twice is harmless;
        the second call returns nothing.

        :returns: the containers held since construction.
        """
        if not self.__armed:
            return ()
        self.__armed = False
        if self.__app is not None:
            self.__app.removeEventFilter(self)
        held = tuple(
            widget
            for widget in QApplication.topLevelWidgets()
            if isinstance(widget, QtAds.CFloatingDockContainer)
            and widget.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        )
        for container in held:
            if container.isVisible():
                container.hide()
            container.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, False)
        return held
