"""A strip of screenshot thumbnails -- the lightbox viewer ([[plugins#field-toolkit]], #27).

The read-only counterpart of :class:`~rehuco_agent.fields.widgets.image_selector.ImageSelector`: it shows
the *curated* set of screenshots (all siblings minus the hidden exceptions) as thumbnails, either on one
horizontal, scrollable row (the default) or wrapped over as many rows as the width needs (#70). Each
thumbnail's height is the user's own choice ("Viewers > Images"), and so is which of the two layouts a
document's strip uses.
"""

from pathlib import Path
from typing import Final, override

from borco_pyside.core import SimpleProperty
from borco_pyside.widgets import FlowLayout
from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPalette, QPixmap, QResizeEvent, QWheelEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLayout, QScrollArea, QWidget

from ..image_scanner import ImageScanner

THUMBNAIL_BORDER: Final = 3
"""Width, in pixels, of the frame marking the current thumbnail (#161). Painted **over** the
screenshot's own edge rather than around it: a border that reserved its own space would inset every
thumbnail by this much on every side, which is padding the strip is not supposed to have, and would
leave each image short of the height it was given."""

THUMBNAIL_SPACING: Final = 0
"""Gap, in pixels, between thumbnails, in either layout. Set explicitly because a layout's default
spacing comes from the style and is several pixels, which reads as stray padding in a row this dense."""


class ThumbnailLabel(QLabel):
    """One clickable thumbnail in the strip: a plain pixmap label that reports its own screenshot.

    Carries the path it was built for, so the strip never has to map a clicked widget back to a
    position in a list it may since have rebuilt.

    :param path: the screenshot this thumbnail stands for, re-emitted on click.
    :param parent: optional Qt parent.
    """

    clicked = Signal(Path)
    """Fires with :attr:`path` when the thumbnail is left-clicked."""

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__path: Final = path
        self.__current = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @property
    def current(self) -> bool:
        """Whether this thumbnail stands for the screenshot currently shown maximized."""
        return self.__current

    def set_current(self, *, current: bool) -> None:
        """Frame this thumbnail as the one being shown maximized, or unframe it (#161).

        :param current: whether this thumbnail stands for the current screenshot.
        """
        if current == self.__current:
            return
        self.__current = current
        self.update()

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint the screenshot, then frame it when it is the current one.

        Drawn over the screenshot's own edge and **wholly inside** the thumbnail: it takes no space of
        its own, so marking a thumbnail neither shifts the row nor shrinks the image
        ([[plugins#tutorial-plugin]]). Palette-themed rather than a fixed color, since this strip
        serves both a document's own surface and the maximized viewer's dark backdrop.

        Filled as a ring -- the thumbnail's rect with the inset rect punched out of it -- rather than
        stroked with a pen. A stroke is centred on the path it follows, so half of it falls outside the
        thumbnail: the frame rasterized a pixel wider on two sides than the other two, and its corners
        came out cut off (a pen's default join is a bevel), letting the screenshot -- or, once the row's
        thumbnails sit flush, the neighbour -- bleed through all four corners. A ring has no centring
        and no joins, so every side is exactly :data:`THUMBNAIL_BORDER` and the corners close.

        :param event: the Qt paint event, forwarded to the base class.
        """
        super().paintEvent(event)
        if not self.__current:
            return
        border = THUMBNAIL_BORDER
        ring = QPainterPath()
        ring.addRect(QRectF(self.rect()))
        ring.addRect(QRectF(self.rect().adjusted(border, border, -border, -border)))
        # the default odd-even fill leaves the punched-out middle -- the screenshot -- untouched
        QPainter(self).fillPath(ring, self.palette().color(QPalette.ColorRole.Highlight))

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Take the press, so the click never also reaches whatever this thumbnail sits on.

        A `QLabel` ignores mouse events, which propagates them to its ancestors -- so a thumbnail
        click doubled as a click on the surface hosting the strip, and whatever *that* means happened
        too (#161).

        :param event: the Qt mouse-press event, forwarded to the base class.
        """
        super().mousePressEvent(event)
        event.accept()

    @override
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Emit :attr:`clicked` when a left-button press *and* release both land on this thumbnail.

        Release, not press: Qt grabs the mouse on press, so a release still inside the widget is the
        standard "this was a click, not a drag away" test -- pressing here and letting go elsewhere
        must not open anything. Accepted for the same reason the press is.

        :param event: the Qt mouse-release event, forwarded to the base class.
        """
        super().mouseReleaseEvent(event)
        event.accept()
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.__path)


class ImageStrip(QScrollArea):  # pylint: disable=too-many-instance-attributes
    """A row -- or, wrapped, a block -- of screenshot thumbnails ([[plugins#field-toolkit]], #27, #70).

    Every image is scaled to ``height`` (preserving aspect ratio) and laid out left-to-right. The two
    layouts differ only in what happens at the right edge:

    - **row** (the default): the thumbnails run on past it and the strip stays exactly ``height`` tall,
      so an over-long set cannot force the surface hosting it tall. Overflow is reached by the wheel.
    - **wrapped** (``wrap``, #70): the thumbnails fold onto a new line instead, and the strip is fixed
      to however tall the block that makes is at its current width -- ``height`` at its shortest.
      Nothing scrolls inside it; the form around it does, which is where a document's own vertical
      scrolling already lives.

    Either way the height is **declared**, never merely hinted at (:meth:`__apply_height`): a hint has
    to survive being re-read through every layout between here and the dock, and one of them caches it,
    so a wrapped strip that had grown stayed at its old height with its lower rows clipped away.

    Holds its own :attr:`image_scanner`, so it can re-fetch its screenshots and rebuild itself whenever
    that changes (e.g. a `.tc` -> `.rehu` conversion switching naming conventions,
    [[acquisition-tooling#tc-to-rehu]]) without its owner having to push a fresh file list explicitly.

    :param parent: optional Qt parent.
    :param height: the height each thumbnail is scaled to, and the strip's own fixed height while it
        is a single row.
    :param wheel_scrolls: whether a plain vertical wheel scrolls this row sideways (keyword-only).
        Off by default: a strip embedded in a scrollable form must leave the wheel to the form, so
        only a strip that is a control in its own right -- the maximized viewer's -- turns it on.
        A horizontal wheel scrolls the row either way.
    :param wrap: whether to start wrapped rather than as a single row (keyword-only, #70). The user's
        own choice for a document's strip; the maximized viewer's row is never wrapped, since it is an
        index alongside the screenshot rather than the content itself.
    """

    image_activated = Signal(Path)
    """Fires with the screenshot a user clicked. The strip stays a dumb presenter: it reports *which*
    image was activated and nothing more -- what opens is the owner's decision (#160)."""

    images_changed = Signal(list)
    """Fires with the screenshots now painted, whenever the row is rebuilt -- a curation edit, a
    scanner swap, or a direct :meth:`set_images`. This is what makes an already-open maximized viewer
    follow the *same* source of truth as the strip rather than the snapshot it opened on (#161)."""

    image_scanner = SimpleProperty[ImageScanner | None](None)
    """The strategy resolving this resource's screenshots; ``None`` shows nothing."""

    def __init__(
        self, parent: QWidget | None = None, height: int = 150, *, wheel_scrolls: bool = False, wrap: bool = False
    ) -> None:
        super().__init__(parent)
        self.__height = height
        self.__wrap = wrap
        self.__wheel_scrolls: Final = wheel_scrolls
        self.__hidden: list[str] = []
        self.__thumbnails: dict[Path, ThumbnailLabel] = {}
        self.__current: Path | None = None
        self.__requested_visible = True
        self.__row: QLayout
        self.setWidgetResizable(True)
        # nothing but the thumbnails: a scroll area's default sunken panel would draw a border around
        # the row and inset it by the frame width, which reads as stray padding around the images on
        # a document's own surface and as chrome on the maximized viewer's backdrop
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setContentsMargins(0, 0, 0, 0)
        self.setViewportMargins(0, 0, 0, 0)
        # neither bar is ever painted: the strip is a fixed-height row of thumbnails, and a scrollbar
        # eating part of that height (or sitting on the maximized viewer's backdrop) is chrome this
        # design does not want. Overflow is reached by the wheel, and the current thumbnail is
        # scrolled into view programmatically (:meth:`set_current`), neither of which needs a bar.
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.__build_content()
        self.__apply_height()

        self.image_scanner_changed.connect(lambda _scanner: self.__refresh())  # type: ignore[attr-defined]

    def set_hidden(self, hidden: list[str]) -> None:
        """Update which screenshots are curated out of the lightbox, and rebuild the strip.

        :param hidden: filenames to leave out; every other current-scanner screenshot is shown.
        """
        self.__hidden = hidden
        self.__refresh()

    def set_current(self, path: Path | None) -> None:
        """Frame ``path``'s thumbnail as the one being shown maximized, and scroll it into view (#161).

        Remembered rather than merely applied, so a later rebuild (a curation edit, a scanner swap)
        re-marks the same screenshot in the freshly-built row instead of losing the mark. A ``path``
        with no thumbnail -- ``None``, or one curated away -- simply leaves the row unmarked.

        :param path: the screenshot to mark as current, or ``None`` to mark none.
        """
        self.__current = path
        for thumbnail_path, thumbnail in self.__thumbnails.items():
            thumbnail.set_current(current=thumbnail_path == path)
        current = self.__thumbnails.get(path) if path is not None else None
        if current is not None:
            self.ensureWidgetVisible(current)

    def set_requested_visible(self, visible: bool) -> None:
        """Say whether the owner wants this strip on screen at all (#161).

        The owner's intent, not the last word: a strip with **nothing to show** stays hidden either
        way, so a resource with no screenshots (or with every one curated out) leaves no empty band
        where a row would be. Defaults to wanting to be shown, so an owner with no opinion -- the
        document's own viewer -- gets exactly the empty-hides-itself rule and nothing else.

        :param visible: whether the owner wants the strip shown when it has thumbnails.
        """
        self.__requested_visible = visible
        self.__apply_visibility()

    def set_height(self, height: int) -> None:
        """Resize the strip, rescaling its thumbnails to the new height (#161).

        Lets an already-built strip follow the user's configured thumbnail height the moment they
        apply it, rather than only on the next document opened.

        :param height: the new pixel height of a thumbnail (and, unwrapped, of the strip itself).
        """
        if height == self.__height:
            return
        self.__height = height
        self.__apply_height()
        # the thumbnails are scaled at build time, so the row has to be rebuilt to rescale them
        self.set_images(list(self.__thumbnails))

    def set_wrap(self, wrap: bool) -> None:
        """Lay the thumbnails out on one row, or wrapped over as many as the width needs (#70).

        The two layouts are different `QLayout` types and a widget only ever has one, so the content
        widget is rebuilt rather than reconfigured -- taking its thumbnails with it, which is why the
        screenshots are read off first and repainted into the new layout afterwards.

        :param wrap: whether the thumbnails wrap.
        """
        if wrap == self.__wrap:
            return
        self.__wrap = wrap
        paths = list(self.__thumbnails)
        # the labels themselves are about to be destroyed with the content widget holding them
        self.__thumbnails.clear()
        self.__build_content()
        self.__apply_height()
        self.set_images(paths)

    def __build_content(self) -> None:
        """Install a fresh content widget laid out the way :attr:`__wrap` currently asks for.

        Replacing a scroll area's widget destroys the previous one, so this is also what disposes of
        the outgoing layout and everything in it.
        """
        content = QWidget()
        if self.__wrap:
            # an explicit gap, not the layout's own plus the style's recommendation: these thumbnails
            # sit flush in either layout, and the style's spacing would read as stray padding
            self.__row = FlowLayout(content, spacing=THUMBNAIL_SPACING)
        else:
            self.__row = QHBoxLayout(content)
            self.__row.setContentsMargins(0, 0, 0, 0)
            self.__row.setSpacing(THUMBNAIL_SPACING)
            self.__row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.setWidget(content)

    def __apply_height(self) -> None:
        """Fix the strip to the height its current layout needs (#70).

        One thumbnail as a single row, whatever it holds; the whole block's height when wrapped, with
        one thumbnail as the floor so an empty strip is still a legible band rather than a sliver.

        **Fixed, not hinted.** A size hint has to be re-read by every layout between this widget and
        its dock, and the plain container each full-width form row sits in caches its own -- so a
        wrapped strip that grew a row kept the height it had, with the new row drawn below the visible
        rectangle and its thumbnails simply gone (#70). Setting the height outright changes this
        widget's minimum *and* maximum, which is what Qt propagates all the way up; it is also how the
        configured thumbnail height has always reached the screen (#161).
        """
        wanted = self.__wanted_height()
        if (self.minimumHeight(), self.maximumHeight()) != (wanted, wanted):
            self.setFixedHeight(wanted)

    def __wanted_height(self) -> int:
        """The height this strip needs right now.

        :returns: one thumbnail as a single row; the wrapped block's own height at the strip's current
            width otherwise, never less than one thumbnail.
        """
        if not self.__wrap:
            return self.__height
        return max(self.__height, self.__row.heightForWidth(self.width()))

    def __wants_visible(self) -> bool:
        """Whether the strip should be on screen: its owner wants it, and it has something to show."""
        return self.__requested_visible and bool(self.__thumbnails)

    def __apply_visibility(self) -> None:
        """Show or hide the strip to match :meth:`__wants_visible`, unless it has no parent yet.

        A parentless strip is left alone: showing one flashes it as a bare top-level window of its
        own -- app icon, title bar and all -- and a field builds *and seeds* its strip before the form
        adds it to a layout, so every document open did exactly that. :meth:`changeEvent` settles it
        once it is given a parent.
        """
        if self.parentWidget() is None:
            return
        self.setVisible(self.__wants_visible())

    @override
    def wheelEvent(self, event: QWheelEvent) -> None:
        """Scroll the row sideways on the wheel -- but only where the wheel is the strip's to take.

        A one-row strip only ever scrolls horizontally, while a plain wheel reports a *vertical*
        delta, which the inherited handler spends on a vertical scrollbar this widget does not have.
        So a **horizontal** delta (a tilt wheel, or the platform's shift-wheel) always scrolls the row:
        nothing else wants it.

        A plain vertical wheel is the strip's only when ``wheel_scrolls`` says so -- the maximized
        viewer's row, which is a control in its own right. Inside a document the strip is one row of a
        scrollable form, and taking the wheel there would stop the form scrolling whenever the pointer
        happened to be over the screenshots.

        :param event: the Qt wheel event.
        """
        horizontal = event.angleDelta().x()
        delta = horizontal or (event.angleDelta().y() if self.__wheel_scrolls else 0)
        if not delta:
            # ignored, not merely unhandled: that is what hands the wheel to whatever scrolls around us
            event.ignore()
            return
        scrollbar = self.horizontalScrollBar()
        scrollbar.setValue(scrollbar.value() - delta)
        event.accept()

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:
        """Re-fix the strip's height whenever its width changes, since that is what wrapping folds on (#70).

        Deliberately blind to a height change: applying the new height *is* one, so answering those
        too would be a loop.

        :param event: the Qt resize event, forwarded to the base class.
        """
        super().resizeEvent(event)
        if self.__wrap and event.size().width() != event.oldSize().width():
            self.__apply_height()

    @override
    def changeEvent(self, event: QEvent) -> None:
        """Settle a strip that was seeded before it had a parent, as it is given one.

        Only ever **hides** here, never shows: Qt is mid-reparent, and a ``show()`` at this point is
        undone as the reparent completes (confirmed empirically) -- while a widget carrying no
        explicit hide is shown by Qt along with its new parent anyway, which is exactly what a strip
        with thumbnails needs. Hiding is also the only half that has to be deferred, since not hiding
        is what leaves an empty band behind.

        :param event: the Qt change event, forwarded to the base class.
        """
        super().changeEvent(event)
        if event.type() == QEvent.Type.ParentChange and not self.__wants_visible():
            self.hide()

    def refresh(self) -> None:
        """Re-read the current scanner and repaint, for a change this strip cannot see coming (#72).

        The scanner is a *live* view of a directory, so it can start reporting different files with
        nothing about this strip having changed -- which is exactly what a curation edit that renames
        screenshots on disk does. Every other rebuild trigger is a value this strip is handed
        (:meth:`set_hidden`, a new scanner); this one is an owner saying the disk moved underneath it.
        """
        self.__refresh()

    def __refresh(self) -> None:
        """Recompute the visible screenshot set from the current scanner and hidden list."""
        scanner = self.image_scanner
        files = scanner.files() if scanner is not None else []
        hidden = set(self.__hidden)
        self.set_images([path for path in files if path.name not in hidden])

    def set_images(self, paths: list[Path]) -> None:
        """Replace the strip's thumbnails with the given screenshot paths, in order.

        Reports the result through :attr:`images_changed` -- the paths that actually painted, not the
        ones asked for -- so a maximized viewer following this strip navigates exactly the set the
        user can see and click (#161).

        :param paths: the curated (visible) screenshot paths to show; an empty list clears the strip.
        """
        while (item := self.__row.takeAt(0)) is not None:
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.__thumbnails.clear()

        # the whole strip height: the current-item frame is painted over the screenshot rather
        # than around it, so it costs the thumbnail nothing
        thumbnail_height = self.__height
        for path in paths:
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                continue
            label = ThumbnailLabel(path)
            label.clicked.connect(self.image_activated)
            label.setPixmap(pixmap.scaledToHeight(thumbnail_height, Qt.TransformationMode.SmoothTransformation))
            self.__row.addWidget(label)
            # shown here rather than left to the layout to show along with the row: a child that has
            # never been shown counts as an *empty* layout item, whose size hint is nothing at all --
            # so the wrapped block measured zero high until something else happened to lay the row out
            # (#70). Safe for a strip that is itself hidden or parentless: this is a child of the
            # scrolled content, so showing it can never flash a window of its own.
            label.show()
            self.__thumbnails[path] = label  # pylint: disable=unsupported-assignment-operation

        # re-mark whatever was current before the rebuild, so a curation edit under an open viewer
        # doesn't silently lose the mark on a screenshot that survived it
        self.set_current(self.__current)
        # a wrapped strip's height is its block's, so a rebuild is exactly when it can change (#70)
        self.__apply_height()
        self.__apply_visibility()
        self.images_changed.emit(list(self.__thumbnails))
