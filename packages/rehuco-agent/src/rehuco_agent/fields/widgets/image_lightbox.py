"""The maximized screenshot viewer -- the lightbox's spine ([[plugins#tutorial-plugin]], #160).

Shows one screenshot scaled to fit, on a dimmed backdrop, over one of three surfaces the user picks
in the settings (:class:`ImageViewerMode`). The mode is the only thing that varies: the content, the
dismiss paths, and the focus discipline are identical on all three, so there is one widget rather
than three.

The enum lives here, next to the widget that implements it, and the settings section
(:mod:`rehuco_agent.settings.image_viewer_settings`) imports it -- the same direction
`markdown_rendering_settings` already reads its ``DEFAULT_ENGINE`` from ``markdown_view``.
"""

from enum import StrEnum
from pathlib import Path
from typing import Final, cast, override

from borco_pyside.theming import glyph_icon
from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import QCloseEvent, QColor, QKeyEvent, QPainter, QPaintEvent, QPixmap
from PySide6.QtWidgets import QApplication, QGridLayout, QMainWindow, QToolButton, QWidget

from ...glyphs import LIGHTBOX_CLOSE_GLYPH
from .image_selector import PreviewLabel


class ImageViewerMode(StrEnum):
    """Which surface a maximized screenshot is shown on ([[plugins#tutorial-plugin]], #160).

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


OVERLAY_BACKDROP: Final = QColor(0, 0, 0, 216)
"""Backdrop painted behind an overlay: near-opaque, but translucent enough that the covered editors
stay faintly readable, which is what tells the user this is a layer over their document rather than a
navigation away from it."""

FULL_SCREEN_BACKDROP: Final = QColor(0, 0, 0)
"""Backdrop painted behind the full-screen viewer -- fully opaque: there is nothing underneath worth
showing through, and a top-level window can only composite alpha where the platform supports
translucency at all."""

CLOSE_GLYPH_COLOR: Final = QColor(Qt.GlobalColor.white)
"""The close affordance is drawn white in every theme, not palette-themed like the rest of the app's
icons: it always sits on this widget's own dark backdrop, so the app's light theme would otherwise
paint it near-black on near-black."""

CONTENT_MARGIN: Final = 16
"""Breathing room, in pixels, between the scaled screenshot and the viewer's edge."""


CLOSE_ICON_SIZE: Final = QSize(24, 24)
"""The close affordance's icon size -- larger than a toolbar button's default, since it is the only
control on a surface that can fill the whole screen."""

CLOSE_BUTTON_STYLE: Final = """
QToolButton { background: transparent; border: none; border-radius: 4px; padding: 4px; }
QToolButton:hover { background-color: palette(highlight); }
QToolButton:pressed { background-color: palette(dark); }
"""
"""Hover/pressed feedback for the close affordance, drawn from the **palette** (``palette(highlight)``
/ ``palette(dark)``) rather than fixed colors, so it follows a theme switch like every other control
-- unlike the glyph itself (:data:`CLOSE_GLYPH_COLOR`), which is pinned white because it sits on this
widget's own always-dark backdrop. A stylesheet, not ``setAutoRaise``: auto-raise gives no
distinguishable pressed state on a backdrop the style knows nothing about."""


class ImageLightbox(QWidget):
    """One screenshot shown maximized, dismissed with ESC ([[plugins#tutorial-plugin]], #160).

    **Where it paints** is :class:`ImageViewerMode`'s choice. The two overlay modes make this a plain
    child widget of the surface it covers, tracking that surface's size through an event filter --
    not a window, so it cannot be alt-tabbed away from its document, and QtAds never sees a new
    top-level to manage. Full-screen makes it a frameless window instead, parented to the document
    all the same, so it is destroyed with it and can never outlive the document as an orphan the user
    has no way back from.

    **Focus** is held for as long as an overlay is up: Qt gives a plain child widget no modality, so
    clicking another document's dock tab would otherwise hand the keyboard to whatever sits underneath
    and leave ESC reaching nothing. Focus landing anywhere on the covered surface is pulled straight
    back (:meth:`__on_focus_changed`), while focus moving to a document this viewer does *not* cover --
    including one with a viewer of its own -- is left alone, so each open viewer answers ESC exactly
    while its own document is the active one.

    On dismiss, focus returns where it came from -- but **only within this viewer's own document**. The
    widget holding focus when the viewer opened is remembered and re-focused, so dismissing lands the
    user back where they were rather than nowhere; a remembered widget that belongs to some *other*
    document (or to none -- the app's chrome, another viewer that happened to hold focus at the moment
    this one opened) is deliberately left alone, since restoring it would yank the user out of the
    document they are actually looking at and into an unrelated dock. Both the remembered widget and
    the owning document are tracked through their own ``destroyed`` signals, so a form rebuild (a type
    switch) or a closing document leaves nothing to restore instead of reaching into a dead object.

    **Dismiss is ESC or the close button, and nothing else** -- deliberately not a click on the image:
    the two halves of the image are the prev/next affordance, so a click there must never be able to
    mean "close" as well. Both paths funnel through ``close()``, and the widget deletes itself
    afterwards (``WA_DeleteOnClose``).

    :param path: the screenshot to show.
    :param mode: which surface to paint on.
    :param document: the open document this viewer belongs to -- its Qt parent in every mode, the
        surface it covers in :attr:`~ImageViewerMode.DOCUMENT_OVERLAY`, and the window it resolves
        for :attr:`~ImageViewerMode.APP_WINDOW_OVERLAY`.
    """

    closed = Signal()
    """Fires once the viewer has been dismissed, whichever way it was."""

    def __init__(self, path: Path, mode: ImageViewerMode, document: QWidget) -> None:
        host = None if mode is ImageViewerMode.FULL_SCREEN else self.__overlay_host(mode, document)
        flags = Qt.WindowType.Widget if host is not None else Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        super().__init__(host if host is not None else document, flags)
        self.__host: Final = host
        self.__backdrop: Final = OVERLAY_BACKDROP if host is not None else FULL_SCREEN_BACKDROP
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setWindowTitle(path.name)

        layout = QGridLayout(self)
        layout.setContentsMargins(CONTENT_MARGIN, CONTENT_MARGIN, CONTENT_MARGIN, CONTENT_MARGIN)
        self.__preview: Final = PreviewLabel()
        # transparent to the mouse: the label is a passive presenter, so every press over it lands on
        # the viewer that owns it rather than being swallowed by the widget that covers the whole surface
        self.__preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.__preview.set_source(QPixmap(str(path)))
        layout.addWidget(self.__preview, 0, 0)
        layout.addWidget(self.__make_close_button(), 0, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)

        if host is not None:
            host.installEventFilter(self)
            # an app-window overlay is not a descendant of the document it belongs to, so closing that
            # document would otherwise leave the viewer up, covering the app with a screenshot of a
            # document that no longer exists. The other two modes are parented into the document and
            # are destroyed with it, needing no such guard.
            if host is not document:
                document.destroyed.connect(self.__on_document_destroyed)
            # an overlay is a plain child widget, so Qt offers it no modality: clicking another
            # document's dock tab hands the keyboard to whatever is underneath, and ESC then reaches
            # nothing at all (#160). Focus is pulled back whenever it lands on the surface this viewer
            # covers, which is exactly the region the user cannot see or click past anyway.
            # cast, not an isinstance guard: a QWidget cannot be constructed without a QApplication,
            # so this widget existing at all is proof instance() is one
            application = cast(QApplication, QApplication.instance())
            application.focusChanged.connect(self.__on_focus_changed)

        self.__owner: QWidget | None = document
        # dropped the moment Qt reports the document gone, so a dismissal after that restores nothing;
        # the app-window overlay's close-on-destroy path drops it explicitly even earlier
        # (`__on_document_destroyed`), since its own close runs during the destruction itself
        document.destroyed.connect(self.__forget_owner)

        self.__previous_focus: QWidget | None = QApplication.focusWidget()
        if self.__previous_focus is not None:
            # tracked through Qt's own destroyed signal rather than held blindly: a form rebuild can
            # delete the focused editor while the viewer is up, and re-focusing a deleted widget on
            # dismiss would raise
            self.__previous_focus.destroyed.connect(self.__forget_previous_focus)

    def reveal(self) -> None:
        """Show the viewer on its surface and take the keyboard, so ESC reaches it immediately."""
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
    def paintEvent(self, event: QPaintEvent) -> None:
        """Fill the viewer with its backdrop, under the scaled screenshot.

        Painted rather than set as a palette/stylesheet background so the overlay modes can dim what
        they cover: a child widget that isn't opaque composites its alpha over whatever its parent
        already painted.

        :param event: the Qt paint event; unused -- the whole widget is repainted either way.
        """
        del event
        QPainter(self).fillRect(self.rect(), self.__backdrop)

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Dismiss on ESC, passing every other key on.

        :param event: the Qt key event.
        """
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        """Report the dismissal, then hand focus back to whatever had it when the viewer opened.

        :param event: the Qt close event, forwarded to the base class.
        """
        super().closeEvent(event)
        # the host's event filter is deliberately not unhooked here: Qt drops a filter when the
        # filtering object is destroyed, and the host itself may already be gone -- a document closed
        # underneath the viewer closes it on the way out, after its own surface has been deleted
        # announced *before* the focus handover, not after: the owner drops its reference to this
        # viewer on this signal, and handing focus back while it still held one would send the owner's
        # own become-current handling (`DocumentWidget.take_focus`) straight back into this
        # half-dismissed viewer, stranding focus on a widget about to be hidden
        self.closed.emit()
        # hidden here rather than left to ``close()``'s own hide afterwards: Qt reassigns focus as a
        # widget disappears, and its choice is the next focusable widget in the whole window -- which
        # lands in some unrelated dock. Hiding first means that reassignment has already happened by
        # the time the focus below is handed back, so it is the last word instead of being overruled.
        self.hide()
        previous = self.__previous_focus
        owner = self.__owner
        if previous is not None and owner is not None and (previous is owner or owner.isAncestorOf(previous)):
            previous.window().activateWindow()
            previous.setFocus(Qt.FocusReason.OtherFocusReason)

    def __on_focus_changed(self, old: QWidget | None, now: QWidget | None) -> None:
        """Reclaim the keyboard whenever focus lands on the surface this overlay covers.

        Focus already inside **any** viewer is left alone -- including another document's, which is
        what keeps two open overlays from tearing focus back and forth when both cover the same
        app-window surface.

        :param old: the widget losing focus; unused -- only where focus landed matters.
        :param now: the widget receiving focus, or ``None`` when the app lost it entirely.
        """
        del old
        if now is None or self.__host is None or self.isHidden():
            return
        if self.__within_a_viewer(now):
            return
        if now is self.__host or self.__host.isAncestorOf(now):
            self.setFocus(Qt.FocusReason.OtherFocusReason)

    @staticmethod
    def __within_a_viewer(widget: QWidget) -> bool:
        """Whether ``widget`` sits inside some `ImageLightbox`.

        :param widget: the widget to test.
        :returns: whether it, or any of its ancestors, is a viewer.
        """
        node: QWidget | None = widget
        while node is not None:
            if isinstance(node, ImageLightbox):
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

    def __make_close_button(self) -> QToolButton:
        """Build the corner close affordance, drawn white on this viewer's own dark backdrop.

        :returns: the close button, already wired to dismiss the viewer.
        """
        button = QToolButton(self)
        button.setIcon(glyph_icon(LIGHTBOX_CLOSE_GLYPH.codepoint, LIGHTBOX_CLOSE_GLYPH.family, CLOSE_GLYPH_COLOR))
        button.setToolTip("Close (Esc)")
        button.setIconSize(CLOSE_ICON_SIZE)
        button.setStyleSheet(CLOSE_BUTTON_STYLE)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(self.close)
        return button

    @staticmethod
    def __overlay_host(mode: ImageViewerMode, document: QWidget) -> QWidget:
        """The widget an overlay covers, for whichever overlay ``mode`` asks for.

        The app-window surface is the main window's **central widget** -- its client area -- so the
        menu bar, toolbars, and status bar stay reachable, matching what the document overlay does one
        level down. A document whose dock has been torn out into a floating window has no such central
        widget to resolve, so its own window is covered instead.

        :param mode: the overlay mode; :attr:`~ImageViewerMode.FULL_SCREEN` never reaches here.
        :param document: the open document the viewer belongs to.
        :returns: the widget to cover and track.
        """
        if mode is ImageViewerMode.DOCUMENT_OVERLAY:
            return document
        window = document.window()
        central = window.centralWidget() if isinstance(window, QMainWindow) else None
        return central if central is not None else window
