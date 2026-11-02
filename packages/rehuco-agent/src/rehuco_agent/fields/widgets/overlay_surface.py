"""A view maximized over the document, the main window or the screen -- what the image lightbox and the maximized
player both sit on ([[plugins#tutorial-plugin]], [[plugins#player-maximized]], #160, #574).

The enum lives here, next to the widget that implements it, and the settings sections
(:mod:`rehuco_agent.settings.image_viewer_settings`, :mod:`rehuco_agent.settings.videos_settings`) import it.
"""

from collections.abc import Callable
from enum import StrEnum
from typing import Final, cast, override

from PySide6.QtCore import QEvent, QMetaObject, QObject, Qt, Signal, SignalInstance
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget


class OverlayMode(StrEnum):
    """Which surface a maximized view is shown on ([[plugins#tutorial-plugin]], #160, #574).

    A ``StrEnum`` so the persisted value is the member's own readable name -- an ``.ini`` written by
    this app stays legible.
    """

    DOCUMENT_OVERLAY = "document_overlay"
    """Covers the open document's own client area, leaving the surrounding dock chrome (its tab, the
    app's menus and toolbars) visible."""

    APP_WINDOW_OVERLAY = "app_window_overlay"
    """Covers the whole main window's client area, leaving only its menu/tool/status bars visible."""

    FULL_SCREEN = "full_screen"
    """A frameless window over the entire screen -- the classic photo-viewer lightbox."""


def viewer_mode_for(modifiers: Qt.KeyboardModifier, configured: OverlayMode) -> OverlayMode:
    """Which surface a maximized view opens on, given the keys held as it was activated (#221).

    The activation's modifiers override the setting for that one view: **Shift** opens it over the
    document, **Ctrl** over the whole app window, **Ctrl+Shift** over the whole screen -- so any surface
    is one gesture away whatever the setting says -- and no modifier means the setting.

    :param modifiers: the keyboard modifiers held at the activation.
    :param configured: the surface the settings name.
    :returns: the surface to open on.
    """
    shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
    ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
    if ctrl and shift:
        return OverlayMode.FULL_SCREEN
    if ctrl:
        return OverlayMode.APP_WINDOW_OVERLAY
    if shift:
        return OverlayMode.DOCUMENT_OVERLAY
    return configured


class OverlaySurface(QWidget):
    """A view over one of three surfaces, holding the keyboard while it is up and handing it back within its document
    when it goes. Designed for inheritance: `~rehuco_agent.fields.widgets.image_lightbox.ImageLightbox` and the
    maximized player (`~rehuco_agent.documents.player_overlay.PlayerOverlay`) add what they show.

    **Where it paints** is :class:`OverlayMode`'s choice. The two overlay modes make this a plain
    child widget of the surface it covers, tracking that surface's size through an event filter --
    not a window, so it cannot be alt-tabbed away from its document, and QtAds never sees a new
    top-level to manage. Full-screen makes it a frameless window instead, parented to the document
    all the same, so it is destroyed with it and can never outlive the document as an orphan the user
    has no way back from.

    **Focus** is held for as long as an overlay is up: Qt gives a plain child widget no modality, so
    clicking another document's dock tab would otherwise hand the keyboard to whatever sits underneath
    and leave ESC reaching nothing. Focus landing anywhere on the covered surface is pulled straight
    back (:meth:`__on_focus_changed`), while focus moving to a document this view does *not* cover --
    including one with a view of its own -- is left alone, so each open view answers ESC exactly
    while its own document is the active one.

    On dismiss, focus returns where it came from -- but **only within this view's own document**. The
    widget holding focus when the view opened is remembered and re-focused, so dismissing lands the
    user back where they were rather than nowhere; a remembered widget that belongs to some *other*
    document (or to none -- the app's chrome, another view that happened to hold focus at the moment
    this one opened) is deliberately left alone, since restoring it would yank the user out of the
    document they are actually looking at and into an unrelated dock. Both the remembered widget and
    the owning document are tracked through their own ``destroyed`` signals, so a form rebuild (a type
    switch) or a closing document leaves nothing to restore instead of reaching into a dead object.

    **ESC dismisses**, as does whatever a subclass adds. Every path funnels through ``close()``, and the
    widget deletes itself afterwards (``WA_DeleteOnClose``).

    :param mode: which surface to paint on.
    :param document: the open document this view belongs to -- its Qt parent in every mode, the
        surface it covers in :attr:`~OverlayMode.DOCUMENT_OVERLAY`, and the window it resolves
        for :attr:`~OverlayMode.APP_WINDOW_OVERLAY`.
    """

    closed = Signal()
    """Fires once the view has been dismissed, whichever way it was."""

    def __init__(self, mode: OverlayMode, document: QWidget) -> None:
        host = None if mode is OverlayMode.FULL_SCREEN else self.__overlay_host(mode, document)
        flags = Qt.WindowType.Widget if host is not None else Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        super().__init__(host if host is not None else document, flags)
        self.__host: Final = host
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        connections: list[QMetaObject.Connection] = []
        self.__connections: Final = connections
        """Every connection to another object's signal, let go by hand (:meth:`__let_go`): PySide drops a bound
        method's connection with its widget only when the method is of the widget's own class, and to a subclass
        these are inherited (measured, #574), so left alone they would reach this view once it is deleted. Closing
        lets go, since a closed view needs none; so does being destroyed unclosed, with a document. A handle, unlike
        the method, is a no-op to disconnect twice."""
        self.destroyed.connect(lambda: OverlaySurface.__let_go(connections))

        if host is not None:
            self.__cover(host, document)

        self.__owner: QWidget | None = document
        # dropped the moment Qt reports the document gone, so a dismissal after that restores nothing;
        # the app-window overlay's close-on-destroy path drops it explicitly even earlier
        # (`__on_document_destroyed`), since its own close runs during the destruction itself
        self.__connect(document.destroyed, self.__forget_owner)

        self.__previous_focus: QWidget | None = QApplication.focusWidget()
        if self.__previous_focus is not None:
            # tracked through Qt's own destroyed signal rather than held blindly: a form rebuild can
            # delete the focused editor while the view is up, and re-focusing a deleted widget on
            # dismiss would raise
            self.__connect(self.__previous_focus.destroyed, self.__forget_previous_focus)

    def __connect(self, signal: SignalInstance, slot: Callable[..., None]) -> None:
        """Connect a slot of this view's to another object's signal, remembering the connection to let go of.

        :param signal: the signal.
        :param slot: the slot.
        """
        self.__connections.append(signal.connect(slot))

    @staticmethod
    def __let_go(connections: list[QMetaObject.Connection]) -> None:
        """Disconnect every remembered connection; a static method, so the view's own destruction can call it.

        :param connections: the handles.
        """
        for connection in connections:
            QObject.disconnect(connection)
        connections.clear()

    def __cover(self, host: QWidget, document: QWidget) -> None:
        """Track the surface an overlay covers, and keep the keyboard on it.

        :param host: the surface this view covers.
        :param document: the open document this view belongs to.
        """
        host.installEventFilter(self)
        # an app-window overlay is not a descendant of the document it belongs to, so closing that
        # document would otherwise leave the view up, covering the app with a view of a
        # document that no longer exists. The other two modes are parented into the document and
        # are destroyed with it, needing no such guard.
        if host is not document:
            self.__connect(document.destroyed, self.__on_document_destroyed)
        # an overlay is a plain child widget, so Qt offers it no modality: clicking another
        # document's dock tab hands the keyboard to whatever is underneath, and ESC then reaches
        # nothing at all (#160). Focus is pulled back whenever it lands on the surface this view
        # covers, which is exactly the region the user cannot see or click past anyway.
        # cast, not an isinstance guard: a QWidget cannot be constructed without a QApplication,
        # so this widget existing at all is proof instance() is one
        application = cast(QApplication, QApplication.instance())
        self.__connect(application.focusChanged, self.__on_focus_changed)

    def reveal(self) -> None:
        """Show the view on its surface and take the keyboard, so ESC reaches it immediately."""
        if self.__host is None:
            self.showFullScreen()
        else:
            self.setGeometry(self.__host.rect())
            self.show()
            # the surface it covers holds other children (the document's docks, the app's dock
            # manager) that would otherwise paint over an overlay merely added to them
            self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Keep an overlay matched to the surface it covers as that surface is resized.

        An overlay is positioned by hand rather than by a layout (it covers its parent's children
        instead of sitting beside them), so nothing else would follow a resize.

        :param watched: the object the event was sent to.
        :param event: the event.
        :returns: ``False`` always -- the resize is observed, never consumed.
        """
        if watched is self.__host and event.type() == QEvent.Type.Resize and self.__host is not None:
            self.setGeometry(self.__host.rect())
        return super().eventFilter(watched, event)

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Dismiss on ESC, pass everything else on.

        :param event: the Qt key event.
        """
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        """Report the dismissal, then hand focus back to whatever had it when the view opened.

        :param event: the Qt close event, forwarded to the base class.
        """
        super().closeEvent(event)
        # the host's event filter is deliberately not unhooked here: Qt drops a filter when the
        # filtering object is destroyed, and the host itself may already be gone -- a document closed
        # underneath the view closes it on the way out, after its own surface has been deleted
        # announced *before* the focus handover, not after: the owner drops its reference to this
        # view on this signal, and handing focus back while it still held one would send the owner's
        # own become-current handling (`DocumentWidget.take_focus`) straight back into this
        # half-dismissed view, stranding focus on a widget about to be hidden
        self.closed.emit()
        # hidden here rather than left to ``close()``'s own hide afterwards: Qt reassigns focus as a
        # widget disappears, and its choice is the next focusable widget in the whole window -- which
        # lands in some unrelated dock. Hiding first means that reassignment has already happened by
        # the time the focus below is handed back, so it is the last word instead of being overruled.
        self.hide()
        self.__let_go(self.__connections)
        previous = self.__previous_focus
        owner = self.__owner
        if previous is not None and owner is not None and (previous is owner or owner.isAncestorOf(previous)):
            previous.window().activateWindow()
            previous.setFocus(Qt.FocusReason.OtherFocusReason)

    def __on_focus_changed(self, old: QWidget | None, now: QWidget | None) -> None:
        """Reclaim the keyboard whenever focus lands somewhere that isn't a deliberate move away.

        Focus already inside **any** overlay is left alone -- including another document's, which is
        what keeps two open overlays from tearing focus back and forth when both cover the same
        app-window surface.

        Otherwise the test is whether the new focus widget is **on this view's own containment
        line**: the covered surface itself, anything under it, or any of the containers holding it
        (its dock, that dock's area, the splitter, the dock manager). Focus landing on a container is
        nothing claiming it -- the user has not navigated anywhere, so a view covering that document
        must keep answering ESC. Dragging a splitter between two docks is exactly this case, and it is
        why the view went deaf while its tab still read as current: `DocumentsDock` saw no dock
        change either, so only re-selecting the tab brought the keyboard back (#161). Focus going to
        **nothing at all** is reclaimed on the same principle, but only when it was this view's to
        lose, so a background view never snatches at a keyboard it never had.

        Everything genuinely *elsewhere* is left alone: another document, the app's own chrome, a
        settings dialog. None of those is on this document's containment line.

        :param old: the widget losing focus.
        :param now: the widget receiving focus, or ``None`` when nothing holds it.
        """
        if self.__host is None or self.isHidden():
            return
        if now is None:
            if old is self or (old is not None and self.isAncestorOf(old)):
                self.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        if self.__within_an_overlay(now):
            return
        if now is self.__host or self.__host.isAncestorOf(now) or now.isAncestorOf(self.__host):
            self.setFocus(Qt.FocusReason.OtherFocusReason)

    @staticmethod
    def __within_an_overlay(widget: QWidget) -> bool:
        """Whether ``widget`` sits inside some `OverlaySurface`.

        :param widget: the widget to test.
        :returns: whether it, or any of its ancestors, is an overlay.
        """
        node: QWidget | None = widget
        while node is not None:
            if isinstance(node, OverlaySurface):
                return True
            node = node.parentWidget()
        return False

    def __on_document_destroyed(self) -> None:
        """Tear an app-window overlay down as its document is destroyed, restoring no focus.

        Runs *during* the document's own destruction (its ``destroyed`` signal), so the owner
        reference is dropped explicitly before closing rather than left to :meth:`__forget_owner`'s
        own connection: :meth:`closeEvent`'s restore would otherwise ask the half-destroyed document
        whether it still owns the remembered focus widget, which raises on a wrapper whose C++ object
        is already gone. An explicit drop-then-close, not a connection-order guarantee -- slot order
        is real but too easy to break silently in a later edit. Only the app-window overlay needs
        this: the other two modes are children of the document and are destroyed with it, never
        closed.
        """
        self.__owner = None
        self.close()

    def __forget_owner(self) -> None:
        """Drop the owning document once Qt reports it destroyed, so dismiss restores nothing."""
        self.__owner = None

    def __forget_previous_focus(self) -> None:
        """Drop the remembered focus widget once Qt reports it destroyed, so dismiss restores nothing."""
        self.__previous_focus = None

    @staticmethod
    def __overlay_host(mode: OverlayMode, document: QWidget) -> QWidget:
        """The widget an overlay covers, for whichever overlay ``mode`` asks for.

        The app-window surface is the main window's **central widget** -- its client area -- so the
        menu bar, toolbars, and status bar stay reachable, matching what the document overlay does one
        level down. A document whose dock has been torn out into a floating window has no such central
        widget to resolve, so its own window is covered instead.

        :param mode: the overlay mode; :attr:`~OverlayMode.FULL_SCREEN` never reaches here.
        :param document: the open document the view belongs to.
        :returns: the widget to cover and track.
        """
        if mode is OverlayMode.DOCUMENT_OVERLAY:
            return document
        window = document.window()
        central = window.centralWidget() if isinstance(window, QMainWindow) else None
        return central if central is not None else window
