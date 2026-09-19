"""The maximized screenshot viewer -- the lightbox ([[plugins#tutorial-plugin]], #160, #161).

Shows one screenshot of a curated set scaled to fit, on an opaque backdrop, over one of three surfaces
the user picks in the settings (:class:`ImageViewerMode`). The mode is the only thing that varies: the
content, the navigation, the dismiss paths, and the focus discipline are identical on all three, so
there is one widget rather than three.

The enum lives here, next to the widget that implements it, and the settings section
(:mod:`rehuco_agent.settings.image_viewer_settings`) imports it -- the same direction
`markdown_rendering_settings` already reads its ``DEFAULT_ENGINE`` from ``markdown_view``.
"""

# One widget and the small controls only it uses (the hover bands, the corner buttons, the info
# overlay): splitting them off would scatter one surface's chrome over several modules
# pylint: disable=too-many-lines

from collections.abc import Hashable
from enum import StrEnum
from typing import Final, cast, override

import humanize
from borco_pyside.theming import glyph_icon, read_resource_bytes, recolored_svg_icon
from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QEnterEvent,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPixmap,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QGridLayout,
    QLabel,
    QMainWindow,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...glyphs import LIGHTBOX_CLOSE_GLYPH
from .image_selector import PreviewLabel
from .image_source import ImageSource
from .thumbnail_loader import ThumbnailLoader
from .thumbnail_row import ThumbnailRow


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


DEFAULT_BACKDROP: Final = "#1e1e1e"
"""The backdrop painted behind the image when the owner names none (#221): a neutral dark grey, fully
opaque on every surface -- a translucent overlay let the covered document bleed through the image's
own edges. The user's choice reaches this widget from the owner as a colour; the settings section
reads this default from here, the way it reads :data:`DEFAULT_STRIP_HEIGHT`."""

OVERLAY_GLYPH_COLOR: Final = QColor(Qt.GlobalColor.white)
"""Every affordance on this viewer is drawn white in every theme, not palette-themed like the rest of
the app's icons: they all sit on this widget's own dark backdrop, so the app's light theme would
otherwise paint them near-black on near-black."""

CORNER_MARGIN: Final = 16
"""Breathing room, in pixels, between a corner control and the viewer's edge. The **screenshot itself
has no margin at all** -- it fills every pixel the thumbnail row leaves, which is the whole point of
maximizing it -- so this is applied to the two corner controls alone, as a stylesheet margin, rather
than as a layout margin that would inset the screenshot with them."""


CORNER_ICON_SIZE: Final = 24
"""The corner controls' icon size -- larger than a toolbar button's default, since this is a surface
that can fill the whole screen."""

DEFAULT_STRIP_HEIGHT: Final = 96
"""The in-viewer thumbnail row's height in pixels when the owner names none (#161) -- shorter than the
document's own strip (``IMAGE_STRIP_HEIGHT``), since here the row is an index alongside the screenshot
rather than the content itself. The user's own choice reaches this widget from the owner, the same way
the surface does; the number lives next to the widget that implements it, and the settings section
reads it from here as its default."""

CLOSE_BUTTON_NAME: Final = "lightbox_close"
PREVIOUS_BUTTON_NAME: Final = "lightbox_previous"
NEXT_BUTTON_NAME: Final = "lightbox_next"
STRIP_TOGGLE_BUTTON_NAME: Final = "lightbox_strip_toggle"
INFO_TOGGLE_BUTTON_NAME: Final = "lightbox_info_toggle"
INFO_OVERLAY_NAME: Final = "lightbox_info"
HOVER_INFO_NAME: Final = "lightbox_hover_info"
"""Object names of the viewer's five controls and its info overlay. Named because they are otherwise
indistinguishable from one another by type alone -- every control is some kind of ``QToolButton`` -- so
anything reaching for a particular one has to ask for it by name."""

INFO_OVERLAY_BACKDROP: Final = QColor(0, 0, 0, 102)
"""The info box's backdrop: black at 40 % (#221). Asked for at 20 %, which whitish text washes out on
under a bright image; 40 % stays a quiet box and reads on anything."""

INFO_OVERLAY_TEXT: Final = QColor(0xEE, 0xEE, 0xEE)
"""The info box's text: whitish, pinned like every other affordance on this backdrop."""

INFO_OVERLAY_POINT_SIZE_STEP: Final = 2
"""How many points smaller than the viewer's own font the info box is set in."""

INFO_OVERLAY_PADDING: Final = 8
INFO_OVERLAY_RADIUS: Final = 4
INFO_OVERLAY_SPACING: Final = 4
"""The info box's inner padding and corner radius, and the gap between it and its toggle, in pixels."""

PREVIOUS_ICON_RESOURCE: Final = ":/icons/lightbox_prev.svg"
NEXT_ICON_RESOURCE: Final = ":/icons/lightbox_next.svg"
STRIP_TOGGLE_ICON_RESOURCE: Final = ":/icons/lightbox_list.svg"
INFO_TOGGLE_ICON_RESOURCE: Final = ":/icons/lightbox_info.svg"

NAVIGATION_ZONE_WIDTH: Final = 50
NAVIGATION_ZONE_DIVISIONS: Final = 8
"""How far in from the left/right edge a prev/next band reaches (#161):
``min(NAVIGATION_ZONE_WIDTH, width // NAVIGATION_ZONE_DIVISIONS)``. A fixed 50 px would swallow most
of a narrow viewer, leaving almost no plain screenshot between the two bands, so below 400 px wide
each band is an eighth of the viewer instead -- the two rules meet exactly at that width, with no
step. This is the whole clickable area for a step: the band **is** the affordance."""

NAVIGATION_ICON_SIZE: Final = 48
NAVIGATION_ICON_PADDING: Final = 8
"""The prev/next glyph's size, and the pixels of its zone kept clear around it. On a narrow viewer the
glyph shrinks to whatever the zone leaves, rather than being clipped by it."""

NAVIGATION_IDLE_OPACITY: Final = 0.0
NAVIGATION_HOVER_OPACITY: Final = 0.25
NAVIGATION_PRESSED_OPACITY: Final = 0.8
"""How present a prev/next affordance is: absent until the mouse enters its zone, then a faint hint
over the screenshot, and briefly near-solid while pressed (#161). Opacity is its *whole* visible
state -- the zone itself stays where it is, so the glyph never moves or resizes as it appears."""

CORNER_HOVER_OPACITY: Final = 0.8
CORNER_PRESSED_OPACITY: Final = 1.0
"""How present a corner control -- close, the row toggle, the info toggle -- is under the mouse and
while pressed (#221). Absent otherwise, like the prev/next zones, so nothing sits on the image until
the pointer goes looking; but a 24 px glyph needs to be far more solid than a band's hint when it
does appear, or it reads as a smudge."""

OVERLAY_BUTTON_STYLE: Final = """
QToolButton { background: transparent; border: none; }
"""
"""An affordance whose visible state is opacity alone (:class:`OverlayButton`) draws no chrome of its
own -- no border, and no hover/pressed background. The style's own would fight the opacity that is
carrying the state, and a zone-sized button's backdrop would be a 50 px slab over the screenshot."""

CORNER_BUTTON_STYLE: Final = f"""
QToolButton {{ background: transparent; border: none; margin: {CORNER_MARGIN}px; }}
"""
"""A corner control is an :class:`OverlayButton` held off the corner by a **stylesheet** margin: the
layout it sits in has none at all, so that the screenshot beneath it can reach the viewer's every
edge."""


class OverlayButton(QToolButton):
    """A chrome-less control over the maximized screenshot whose visible state is its opacity (#161).

    The viewer paints its own dark backdrop, which the widget style knows nothing about, so the usual
    hover/pressed chrome is unavailable *and* unwanted: these controls sit on top of the user's
    screenshot, and the design calls for them to be barely there until they matter. A white glyph and
    a `QGraphicsOpacityEffect` are the whole appearance -- geometry never changes as the state does,
    so nothing shifts under the cursor.

    Takes no focus: a click on one must leave the keyboard with the viewer, which is where ESC and the
    arrow keys are handled.

    :param icon: the SVG resource to draw, recolored to :data:`OVERLAY_GLYPH_COLOR` -- or an icon
        already drawn in it (the close glyph comes from a font, not an SVG).
    :param opacity: the opacity to start at.
    :param parent: optional Qt parent.
    """

    def __init__(self, icon: str | QIcon, opacity: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setIcon(
            recolored_svg_icon(read_resource_bytes(icon), OVERLAY_GLYPH_COLOR) if isinstance(icon, str) else icon
        )
        self.setStyleSheet(OVERLAY_BUTTON_STYLE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.__effect: Final = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.__effect)
        self.set_opacity(opacity)

    def set_opacity(self, opacity: float) -> None:
        """Draw this control at ``opacity``, from fully absent (``0.0``) to fully solid (``1.0``).

        :param opacity: the opacity to draw at.
        """
        self.__effect.setOpacity(opacity)

    def opacity(self) -> float:
        """The opacity this control is currently drawn at."""
        return self.__effect.opacity()


class HoverButton(OverlayButton):
    """An overlay control that is absent until the mouse is over it (#161, #221).

    Drawn at nothing at all until the mouse enters, at ``hover`` while it is over, and at ``pressed``
    while held down. Qt's own enter/leave is the hover test -- no mouse tracking, no hit-testing
    against a rectangle held separately from the one the clicks land in.

    :param icon: the SVG resource to draw (recolored to :data:`OVERLAY_GLYPH_COLOR`), or a ready icon.
    :param hover: the opacity under the mouse.
    :param pressed: the opacity while held down.
    :param parent: optional Qt parent.
    """

    def __init__(self, icon: str | QIcon, hover: float, pressed: float, parent: QWidget | None = None) -> None:
        super().__init__(icon, NAVIGATION_IDLE_OPACITY, parent)
        self.__hover: Final = hover
        self.__pressed: Final = pressed

    @override
    def enterEvent(self, event: QEnterEvent) -> None:
        """Fade the glyph in as the mouse enters.

        :param event: the Qt enter event, forwarded to the base class.
        """
        super().enterEvent(event)
        self.set_opacity(self.__hover)

    @override
    def leaveEvent(self, event: QEvent) -> None:
        """Fade the glyph back out as the mouse leaves.

        :param event: the Qt leave event, forwarded to the base class.
        """
        super().leaveEvent(event)
        self.set_opacity(NAVIGATION_IDLE_OPACITY)

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Brighten the glyph while held down.

        :param event: the Qt mouse-press event, forwarded to the base class.
        """
        super().mousePressEvent(event)
        self.set_opacity(self.__pressed)

    @override
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Settle the glyph back to hovered or absent, depending on where the release landed.

        A press dragged out of the control and released there leaves the mouse outside it, so the
        glyph must go all the way out rather than stay at the hover level with nothing hovering it.

        :param event: the Qt mouse-release event, forwarded to the base class.
        """
        super().mouseReleaseEvent(event)
        self.set_opacity(self.__hover if self.underMouse() else NAVIGATION_IDLE_OPACITY)


class NavigationButton(HoverButton):
    """A prev/next affordance filling a hover band along one edge of the screenshot (#161).

    The button **is** the band: it spans the full height of the screenshot area and
    :data:`NAVIGATION_ZONE_WIDTH` in from its edge, so the whole band is clickable, not just the glyph
    drawn in the middle of it. Hidden outright at either end of the set, so there is no dead band to
    hover over when there is nothing to navigate to.

    :param icon: the SVG resource to draw, recolored to :data:`OVERLAY_GLYPH_COLOR`.
    :param parent: optional Qt parent.
    """

    def __init__(self, icon: str, parent: QWidget | None = None) -> None:
        super().__init__(icon, NAVIGATION_HOVER_OPACITY, NAVIGATION_PRESSED_OPACITY, parent)


class CornerButton(HoverButton):
    """A corner control -- close, the row toggle, the info toggle -- held off the edge by its own
    margin and, like a band, absent until hovered (#221).

    :param icon: the SVG resource to draw, or a ready icon.
    :param name: the control's object name.
    :param tooltip: the control's tooltip.
    :param parent: optional Qt parent.
    """

    def __init__(self, icon: str | QIcon, name: str, tooltip: str, parent: QWidget | None = None) -> None:
        super().__init__(icon, CORNER_HOVER_OPACITY, CORNER_PRESSED_OPACITY, parent)
        self.setObjectName(name)
        self.setToolTip(tooltip)
        self.setStyleSheet(CORNER_BUTTON_STYLE)
        self.setIconSize(QSize(CORNER_ICON_SIZE, CORNER_ICON_SIZE))


class ImageInfoOverlay(QLabel):
    """The image's name, pixel size and file size in a translucent box over the screenshot area (#221).

    Two of them: the current image's, stacked over its toggle in the top-left corner, and the hovered
    thumbnail's, in the bottom-left over the row's toggle -- right on the row the pointer is on, shown
    the moment a thumbnail is entered, where a tooltip would wait and then float over the thumbnails.
    Transparent to the mouse, so the band or toggle underneath keeps its hover and its clicks.
    Painted on its own box rather than the viewer's backdrop, since it sits over the image, which may
    be anything.

    :param parent: the viewer.
    :param name: the object name -- which of the two this is.
    """

    def __init__(self, parent: QWidget | None = None, name: str = INFO_OVERLAY_NAME) -> None:
        super().__init__(parent)
        self.__lines: list[str] = []
        self.__max_width = 0
        self.setObjectName(name)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setTextFormat(Qt.TextFormat.PlainText)
        font = self.font()
        font.setPointSize(max(1, font.pointSize() - INFO_OVERLAY_POINT_SIZE_STEP))
        self.setFont(font)
        backdrop = INFO_OVERLAY_BACKDROP
        self.setStyleSheet(
            f"QLabel {{ color: {INFO_OVERLAY_TEXT.name()};"
            f" background-color: rgba({backdrop.red()}, {backdrop.green()}, {backdrop.blue()}, {backdrop.alpha()});"
            f" border-radius: {INFO_OVERLAY_RADIUS}px; padding: {INFO_OVERLAY_PADDING}px; }}"
        )

    def describe(self, path_text: str, pixel_size: QSize | None, byte_size: int | None) -> None:
        """Set the lines: where the image is, its ``W × H px`` (when that is known at all), and its
        size on disk.

        :param path_text: the image's path as a person would name it.
        :param pixel_size: the image's pixel size; an invalid one reads as unknown, ``None`` leaves
            the line out -- a hovered thumbnail was never decoded at full size.
        :param byte_size: the image's byte size, or ``None`` when unknown.
        """
        lines = [path_text]
        if pixel_size is not None:
            lines.append(f"{pixel_size.width()} × {pixel_size.height()} px" if pixel_size.isValid() else "size unknown")
        lines.append(humanize.naturalsize(byte_size) if byte_size is not None else "file size unknown")
        self.__lines = lines
        self.__render()

    def set_max_width(self, width: int) -> None:
        """Bound the box to ``width`` -- what the viewer has to give, less its margins -- eliding each
        line to fit; the viewer calls this on every resize.

        :param width: the widest the box may be, in pixels; ``0`` for unbounded.
        """
        if width == self.__max_width:
            return
        self.__max_width = width
        self.__render()

    def __render(self) -> None:
        """Show the lines, each middle-elided to the bound: a member path inside a deep archive can be
        far wider than the viewer, and the box must never run off its edge."""
        text_width = self.__max_width - 2 * INFO_OVERLAY_PADDING
        if self.__max_width > 0 and text_width > 0:
            metrics = self.fontMetrics()
            shown = [metrics.elidedText(line, Qt.TextElideMode.ElideMiddle, text_width) for line in self.__lines]
        else:
            shown = self.__lines
        self.setText("\n".join(shown))
        self.adjustSize()


class ImageLightbox(QWidget):  # pylint: disable=too-many-instance-attributes,too-many-public-methods
    """A curated screenshot set shown maximized, one at a time ([[plugins#tutorial-plugin]], #160, #161).

    **Navigation** moves through the curated set in strip order and **stops at both ends** rather than
    wrapping: the ends are where the set's shape is legible, and a wrap makes a two-image set
    indistinguishable from an endless one. Three affordances, all the same step: the LEFT/RIGHT keys
    (with HOME/END for the ends), the wheel over the screenshot, and the prev/next hover bands
    (:class:`NavigationButton`) along the viewer's edges.

    A **click** steps only inside a band -- never on the open screenshot, whose whole left/right halves
    once meant prev/next. Half the viewer is far too large a target for a step the user did not
    necessarily ask for, and it made the affordance's real bounds invisible: the band is exactly the
    area that answers, and it is hidden outright at the end it would point past, so a click can never
    step where there is nowhere to step to.

    **Where the pixels come from** is an :class:`ImageSource` (#221): a curated screenshot set, a
    folder's images, or a reference pack's archive members, which have no path at all. The viewer
    navigates positions in it and decodes the current one at full size on the spot.

    **The thumbnail row** is a `ThumbnailRow` -- a lazy list view over the same source, decoding only
    what is in view through the shared `ThumbnailLoader` -- shown under the image with the current
    one framed and scrolled into view. It is toggled by the corner list affordance, and that choice is
    a *persisted* preference rather than session state: the owner seeds it from the settings and
    stores it back through :attr:`strip_visible_changed`, which keeps this widget free of any settings
    dependency of its own (the settings module imports :class:`ImageViewerMode` from here, so the
    reverse import would be a cycle).

    **The info overlay** (`ImageInfoOverlay`, #221) names the image, its pixel size and its file size
    in the top-left corner, toggled by ``I``. The owner seeds it from the setting and pushes that
    setting's later changes down (:meth:`set_info_visible`), the way the row's height is pushed;
    unlike the row, nothing is reported back up -- ``I`` changes this viewer alone.

    **The set is live.** :meth:`set_source` re-points an open viewer at a rebuilt set -- a curation
    edit in `ImageSelector`, or a scanner swap from a ``.tc`` -> ``.rehu`` conversion
    ([[acquisition-tooling#tc-to-rehu]]) -- keeping the current image if its key survived, falling
    back to whatever now occupies its position if it did not, and dismissing itself outright when the
    set empties. Both reach this widget through the document surface that owns it, the same
    owner-routes-it shape the activation itself follows.

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

    **Dismiss is ESC, the close button, or -- when the owner allows it -- a double-click on the image**
    (#221): the gesture that opened the viewer, undoing it. A single click on the image does nothing at
    all. Every path funnels through ``close()``, and the widget deletes itself afterwards
    (``WA_DeleteOnClose``).

    :param source: the images to navigate, in order; an empty one shows nothing and closes on the
        first navigation.
    :param current: the position to open on, clamped into the source.
    :param mode: which surface to paint on.
    :param document: the open document this viewer belongs to -- its Qt parent in every mode, the
        surface it covers in :attr:`~ImageViewerMode.DOCUMENT_OVERLAY`, and the window it resolves
        for :attr:`~ImageViewerMode.APP_WINDOW_OVERLAY`.
    :param loader: the thumbnail decode pool the row reads through (keyword-only); one of this
        viewer's own when the owner shares none.
    :param strip_visible: whether to open with the thumbnail row shown (keyword-only).
    :param strip_height: the thumbnail row's fixed pixel height (keyword-only).
    :param info_visible: whether to open with the info overlay shown (keyword-only).
    :param backdrop: the colour painted behind the image (keyword-only); :data:`DEFAULT_BACKDROP`
        when the owner names none.
    :param double_click_closes: whether a double-click on the image dismisses the viewer
        (keyword-only).
    """

    closed = Signal()
    """Fires once the viewer has been dismissed, whichever way it was."""

    strip_visible_changed = Signal(bool)
    """Fires with the thumbnail row's new visibility whenever the user toggles it, for the owner to
    remember (#161). This widget never reads or writes any stored state itself."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        source: ImageSource,
        current: int,
        mode: ImageViewerMode,
        document: QWidget,
        *,
        loader: ThumbnailLoader | None = None,
        strip_visible: bool = False,
        strip_height: int = DEFAULT_STRIP_HEIGHT,
        info_visible: bool = False,
        backdrop: QColor | None = None,
        double_click_closes: bool = True,
    ) -> None:
        host = None if mode is ImageViewerMode.FULL_SCREEN else self.__overlay_host(mode, document)
        flags = Qt.WindowType.Widget if host is not None else Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        super().__init__(host if host is not None else document, flags)
        self.__host: Final = host
        self.__backdrop = backdrop if backdrop is not None else QColor(DEFAULT_BACKDROP)
        self.__double_click_closes = double_click_closes
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.__source: ImageSource = source
        self.__index = min(max(current, 0), max(len(source) - 1, 0))
        self.__loader: Final = loader if loader is not None else ThumbnailLoader(self)

        self.__strip_height = strip_height
        layout = QGridLayout(self)
        # no margins and no spacing anywhere: the screenshot reaches every edge the thumbnail row
        # leaves it. The corner controls hold themselves off the edge with a stylesheet margin instead
        # (:data:`CORNER_MARGIN`), which insets them without insetting the screenshot underneath.
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.__preview: Final = PreviewLabel(self)
        # transparent to the mouse: the label is a passive presenter, so every press over it lands on
        # the viewer that owns it rather than being swallowed by the widget that covers the whole surface
        self.__preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.__preview, 0, 0)
        self.__strip: Final = self.__make_strip()
        layout.addWidget(self.__strip, 1, 0)
        # the screenshot takes every pixel the fixed-height thumbnail row leaves
        layout.setRowStretch(0, 1)

        # the hover bands are built before the corner controls, and so sit *below* them in the child
        # stacking order: a band spans the full height of the screenshot area, which includes the
        # corners, and the control drawn there must be the one the click reaches
        self.__previous_button: Final = self.__make_navigation_button(PREVIOUS_ICON_RESOURCE, "Previous (Left)", -1)
        self.__next_button: Final = self.__make_navigation_button(NEXT_ICON_RESOURCE, "Next (Right)", 1)
        self.__strip_toggle: Final = self.__make_strip_toggle(strip_visible=strip_visible)
        # bottom-left of the *screenshot* area, so it sits directly above the thumbnail row it opens
        # and drops to the viewer's own bottom-left corner when that row is hidden -- the control stays
        # with the thing it controls instead of being parked in an unrelated corner
        layout.addWidget(self.__strip_toggle, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        # the hovered thumbnail's info box shares that corner and paints over the toggle: the two are
        # never wanted at once (the toggle shows under the pointer, the box while the pointer is on a
        # thumbnail), and the box sitting right on the row is what ties it to the thumbnail it names
        # parented from the start: a parentless widget is a window, and hiding one before it is
        # reparented is enough for the platform to create -- and flash -- a native window for it
        self.__hover_info: Final = ImageInfoOverlay(self, name=HOVER_INFO_NAME)
        layout.addWidget(self.__make_hover_corner(), 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        self.__hover_info.hide()
        layout.addWidget(self.__make_close_button(), 0, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        # top-left of the image area, after the bands so it paints over the prev one: the info box
        # (mouse-transparent, so that band still answers underneath it) with its toggle below
        self.__info: Final = ImageInfoOverlay(self)
        self.__info_toggle: Final = self.__make_info_toggle(info_visible=info_visible)
        layout.addWidget(self.__make_info_corner(), 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.__strip.set_source(self.__source)
        self.__show_current()

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

    @property
    def current_index(self) -> int:
        """The position currently shown maximized."""
        return self.__index

    @property
    def current_key(self) -> Hashable | None:
        """The key of the image currently shown maximized, or ``None`` on an empty source."""
        return self.__source.key(self.__index) if len(self.__source) > 0 else None

    @property
    def source(self) -> ImageSource:
        """The images this viewer navigates, in order."""
        return self.__source

    @property
    def strip_visible(self) -> bool:
        """Whether the thumbnail row is currently shown."""
        return self.__strip_toggle.isChecked()

    @property
    def info_visible(self) -> bool:
        """Whether the info overlay is currently shown (#221)."""
        return self.__info_toggle.isChecked()

    def set_info_visible(self, visible: bool) -> None:
        """Show or hide the info overlay, exactly as the ``I`` key and its corner toggle do (#221).

        :param visible: whether to show it.
        """
        self.__info_toggle.setChecked(visible)

    @property
    def backdrop(self) -> QColor:
        """The colour painted behind the image."""
        return QColor(self.__backdrop)

    def set_backdrop(self, colour: QColor) -> None:
        """Repaint behind the image in ``colour`` -- the settings page's Apply (#221).

        :param colour: the new backdrop.
        """
        if colour == self.__backdrop:
            return
        self.__backdrop = QColor(colour)
        self.update()

    @property
    def double_click_closes(self) -> bool:
        """Whether a double-click on the image dismisses the viewer (#221)."""
        return self.__double_click_closes

    def set_double_click_closes(self, closes: bool) -> None:
        """Allow or refuse the double-click dismissal -- the settings page's Apply (#221).

        :param closes: whether a double-click on the image closes the viewer.
        """
        self.__double_click_closes = closes

    def set_strip_visible(self, visible: bool) -> None:
        """Show or hide the thumbnail row from outside, exactly as its own toggle does (#161).

        Goes through the toggle rather than the row, so the corner control stays truthful and the
        change is reported through :attr:`strip_visible_changed` like any other -- an owner applying
        the user's setting to an open viewer is indistinguishable from the user clicking it here.

        :param visible: whether to show the row.
        """
        self.__strip_toggle.setChecked(visible)

    def set_strip_height(self, height: int) -> None:
        """Resize the thumbnail row, and give the hover bands back whatever height it no longer needs.

        :param height: the row's new fixed pixel height.
        """
        if height == self.__strip_height:
            return
        self.__strip_height = height
        self.__strip.set_height(height)
        self.__layout_navigation_zones()

    def set_source(self, source: ImageSource) -> None:
        """Re-point this viewer at a rebuilt set (#161).

        The image on screen is kept if its key survived the rebuild. If it did not -- the user
        unchecked it in `ImageSelector`, or a conversion renamed it -- whatever now occupies its
        position is shown instead, which is the nearest thing to "stay where you were" a vanished
        image allows; an emptied set dismisses the viewer, since there is nothing left to look at.

        :param source: the rebuilt set, in order.
        """
        current = self.current_key
        self.__source = source
        self.__strip.set_source(source)
        if len(source) == 0:
            self.close()
            return
        survived = next((index for index in range(len(source)) if source.key(index) == current), None)
        self.__index = survived if survived is not None else min(self.__index, len(source) - 1)
        self.__show_current()

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

        Painted rather than set as a palette/stylesheet background, so a change of colour is one
        repaint and no stylesheet rebuild.

        :param event: the Qt paint event; unused -- the whole widget is repainted either way.
        """
        del event
        QPainter(self).fillRect(self.rect(), self.__backdrop)

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Dismiss on ESC, navigate the set on the arrow/HOME/END keys, toggle the info overlay on ``I``
        and the thumbnail row on ``T`` (#221), pass everything else on.

        :param event: the Qt key event.
        """
        match event.key():
            case Qt.Key.Key_Escape:
                self.close()
            case Qt.Key.Key_Left:
                self.__step(-1)
            case Qt.Key.Key_Right:
                self.__step(1)
            case Qt.Key.Key_Home:
                self.__go_to(0)
            case Qt.Key.Key_End:
                self.__go_to(len(self.__source) - 1)
            case Qt.Key.Key_I:
                self.__info_toggle.toggle()
            case Qt.Key.Key_T:
                # through the toggle, exactly as a click on it: reported for the owner to remember
                self.__strip_toggle.toggle()
            case _:
                super().keyPressEvent(event)

    @override
    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Dismiss on a left double-click over the image, when the owner allows it (#221).

        Only reaches here from the image itself: the preview label is transparent to the mouse, while
        the bands, the corner controls and the thumbnail row take their own double-clicks.

        :param event: the Qt mouse event, forwarded to the base class when it dismisses nothing.
        """
        if self.__double_click_closes and event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            self.close()
            return
        super().mouseDoubleClickEvent(event)

    @override
    def wheelEvent(self, event: QWheelEvent) -> None:
        """Step through the curated set on the wheel over the screenshot (#161).

        Wheeling **down** goes forward, matching the direction every list in the app moves under the
        same gesture. Only reaches here from the screenshot itself: the thumbnail row consumes its own
        wheel to scroll sideways, so the two gestures never fight over the same pointer position.

        :param event: the Qt wheel event.
        """
        delta = event.angleDelta().y() or event.angleDelta().x()
        if delta:
            self.__step(-1 if delta > 0 else 1)
        event.accept()

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:
        """Re-fit the hover bands to the viewer's new size.

        The bands are positioned by hand rather than by the layout -- they overlay the screenshot
        instead of sitting beside it -- so nothing else would follow a resize.

        :param event: the Qt resize event, forwarded to the base class.
        """
        super().resizeEvent(event)
        self.__layout_navigation_zones()

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
        """Reclaim the keyboard whenever focus lands somewhere that isn't a deliberate move away.

        Focus already inside **any** viewer is left alone -- including another document's, which is
        what keeps two open overlays from tearing focus back and forth when both cover the same
        app-window surface.

        Otherwise the test is whether the new focus widget is **on this viewer's own containment
        line**: the covered surface itself, anything under it, or any of the containers holding it
        (its dock, that dock's area, the splitter, the dock manager). Focus landing on a container is
        nothing claiming it -- the user has not navigated anywhere, so a viewer covering that document
        must keep answering ESC. Dragging a splitter between two docks is exactly this case, and it is
        why the viewer went deaf while its tab still read as current: `DocumentsDock` saw no dock
        change either, so only re-selecting the tab brought the keyboard back (#161). Focus going to
        **nothing at all** is reclaimed on the same principle, but only when it was this viewer's to
        lose, so a background viewer never snatches at a keyboard it never had.

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
        if self.__within_a_viewer(now):
            return
        if now is self.__host or self.__host.isAncestorOf(now) or now.isAncestorOf(self.__host):
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

    def __show_current(self) -> None:
        """Paint the screenshot at the current position and resync everything that tracks it.

        The single place the current position becomes visible: the scaled screenshot, the window
        title, the framed thumbnail, and which hover bands exist at all -- so no navigation path can
        update one of them and forget another.
        """
        if len(self.__source) == 0:
            # nothing to show and nowhere to step: no bands, no title
            self.__previous_button.setVisible(False)
            self.__next_button.setVisible(False)
            return
        index = self.__index
        self.setWindowTitle(self.__source.name(index))
        image = self.__source.load(index, None)
        self.__preview.set_source(QPixmap.fromImage(image))
        description = self.__source.describe(index)
        self.__info.describe(description.path_text, image.size(), description.byte_size)
        self.__strip.set_current(index)
        # hidden, not merely faded out, at either end: an always-present band would be a 50 px strip of
        # the screenshot that swallows clicks and answers nothing
        self.__previous_button.setVisible(index > 0)
        self.__next_button.setVisible(index < len(self.__source) - 1)
        self.__layout_navigation_zones()

    def __step(self, delta: int) -> None:
        """Move ``delta`` positions through the curated set, stopping at the ends.

        :param delta: how far to move; negative goes back.
        """
        self.__go_to(self.__index + delta)

    def __go_to(self, index: int) -> None:
        """Show the screenshot at ``index``, ignoring a position outside the set or already current.

        :param index: the position to show.
        """
        if index == self.__index or not 0 <= index < len(self.__source):
            return
        self.__index = index
        self.__show_current()

    def __on_thumbnail_activated(self, index: int) -> None:
        """Jump to the image whose thumbnail was clicked in this viewer's own row (#161).

        :param index: the clicked position.
        """
        self.__go_to(index)

    def __on_strip_toggled(self, visible: bool) -> None:
        """Show or hide the thumbnail row, and report the choice for the owner to persist (#161).

        :param visible: the row's new visibility.
        """
        self.__strip.set_requested_visible(visible)
        # a row that was hidden could not scroll, so an image navigated to meanwhile may sit outside
        # the visible span -- re-marking it scrolls it back into view
        self.__strip.set_current(self.__index)
        self.__layout_navigation_zones()
        self.strip_visible_changed.emit(visible)

    def __layout_navigation_zones(self) -> None:
        """Fit the prev/next hover bands to the screenshot area, and size their glyphs to fit them.

        The bands stop above the thumbnail row when it is shown, so they never cover a thumbnail: the
        row is a real widget that must receive its own clicks. Its height is known from the constants
        rather than read off the laid-out row, since this runs from ``resizeEvent``, before the layout
        has necessarily settled at the new size.
        """
        width = self.width()
        for box in (self.__info, self.__hover_info):
            box.set_max_width(max(0, width - 2 * CORNER_MARGIN))
        zone = min(NAVIGATION_ZONE_WIDTH, width // NAVIGATION_ZONE_DIVISIONS)
        # isHidden(), not isVisible(): the row's own explicit state, which is set before the viewer is
        # ever shown and would read as "not visible" on a widget whose parent is still hidden
        row = 0 if self.__strip.isHidden() else self.__strip_height
        height = max(0, self.height() - row)
        glyph = max(1, min(NAVIGATION_ICON_SIZE, zone - NAVIGATION_ICON_PADDING))
        for button, left in ((self.__previous_button, 0), (self.__next_button, width - zone)):
            button.setIconSize(QSize(glyph, glyph))
            button.setGeometry(left, 0, zone, height)

    def __make_strip(self) -> ThumbnailRow:
        """Build this viewer's own thumbnail row (#161, lazy since #221).

        :returns: the thumbnail row, wired to navigate on a click, hidden or shown by the caller.
        """
        strip = ThumbnailRow(self.__loader, self, height=self.__strip_height)
        strip.activated_index.connect(self.__on_thumbnail_activated)
        strip.hovered_index.connect(self.__on_thumbnail_hovered)
        return strip

    def __on_thumbnail_hovered(self, index: int) -> None:
        """Name the thumbnail under the pointer in the box above the row, or hide the box (#221).

        :param index: the hovered position, or ``-1`` for none.
        """
        if not 0 <= index < len(self.__source):
            self.__hover_info.hide()
            return
        description = self.__source.describe(index)
        self.__hover_info.describe(description.path_text, None, description.byte_size)
        self.__hover_info.show()

    def __make_hover_corner(self) -> QWidget:
        """Hold the hovered thumbnail's info box a corner margin in from the bottom-left (#221) -- the
        same inset the current image's box keeps from the top-left.

        :returns: the holder, for the layout's bottom-left cell.
        """
        corner = QWidget(self)
        # transparent like the box it holds, so the toggle underneath keeps its hover and its clicks
        corner.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        holder = QVBoxLayout(corner)
        holder.setContentsMargins(CORNER_MARGIN, CORNER_MARGIN, CORNER_MARGIN, CORNER_MARGIN)
        holder.addWidget(self.__hover_info, 0, Qt.AlignmentFlag.AlignLeft)
        return corner

    def __make_navigation_button(self, icon: str, tooltip: str, delta: int) -> NavigationButton:
        """Build one prev/next hover band.

        :param icon: the SVG resource to draw.
        :param tooltip: the band's tooltip.
        :param delta: how far it steps through the set.
        :returns: the band, parented to this viewer and wired to step.
        """
        button = NavigationButton(icon, self)
        button.setObjectName(PREVIOUS_BUTTON_NAME if delta < 0 else NEXT_BUTTON_NAME)
        button.setToolTip(tooltip)
        button.clicked.connect(lambda: self.__step(delta))
        return button

    def __make_strip_toggle(self, *, strip_visible: bool) -> CornerButton:
        """Build the corner affordance that shows and hides the thumbnail row (#161).

        The row's initial visibility is applied here rather than through the toggle's own ``toggled``
        handler: seeding a checkable button emits that signal, and a viewer merely *opening* on the
        user's stored preference is not the user changing it -- reporting it would write the
        preference straight back on every opening.

        :param strip_visible: whether to start with the row shown.
        :returns: the toggle, already reflecting ``strip_visible``.
        """
        button = CornerButton(STRIP_TOGGLE_ICON_RESOURCE, STRIP_TOGGLE_BUTTON_NAME, "Thumbnails (T)", self)
        button.setCheckable(True)
        button.setChecked(strip_visible)
        self.__strip.set_requested_visible(strip_visible)
        button.toggled.connect(self.__on_strip_toggled)
        return button

    def __make_info_toggle(self, *, info_visible: bool) -> CornerButton:
        """Build the corner affordance that shows and hides the info overlay (#221).

        Seeded before it is wired, like the row's toggle: opening on the setting is not a change.

        :param info_visible: whether to start with the overlay shown.
        :returns: the toggle, already reflecting ``info_visible``.
        """
        button = CornerButton(INFO_TOGGLE_ICON_RESOURCE, INFO_TOGGLE_BUTTON_NAME, "Image info (I)", self)
        button.setCheckable(True)
        button.setChecked(info_visible)
        self.__info.setVisible(info_visible)
        button.toggled.connect(self.__info.setVisible)
        return button

    def __make_info_corner(self) -> QWidget:
        """Stack the info overlay over its toggle in the top-left corner (#221).

        The toggle sits **below** the box while the box is shown -- where the pointer naturally goes
        to dismiss what it is reading -- and alone in the corner while it is hidden. The stack carries
        the corner margin the other corner controls carry in their own stylesheets.

        :returns: the stack, for the layout's top-left cell.
        """
        corner = QWidget(self)
        stack = QVBoxLayout(corner)
        stack.setContentsMargins(CORNER_MARGIN, CORNER_MARGIN, CORNER_MARGIN, CORNER_MARGIN)
        stack.setSpacing(INFO_OVERLAY_SPACING)
        stack.addWidget(self.__info, 0, Qt.AlignmentFlag.AlignLeft)
        # the toggle's own stylesheet margin is the stack's job here
        self.__info_toggle.setStyleSheet(OVERLAY_BUTTON_STYLE)
        stack.addWidget(self.__info_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        return corner

    def __make_close_button(self) -> CornerButton:
        """Build the corner close affordance, drawn white on this viewer's own dark backdrop.

        :returns: the close button, already wired to dismiss the viewer.
        """
        glyph = glyph_icon(LIGHTBOX_CLOSE_GLYPH.codepoint, LIGHTBOX_CLOSE_GLYPH.family, OVERLAY_GLYPH_COLOR)
        button = CornerButton(glyph, CLOSE_BUTTON_NAME, "Close (Esc)", self)
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
