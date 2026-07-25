"""A horizontal, fixed-height strip of screenshot thumbnails -- the lightbox viewer ([[plugins#field-toolkit]], #27).

The read-only counterpart of :class:`~rehuco_agent.fields.widgets.image_selector.ImageSelector`: it shows
the *curated* set of screenshots (all siblings minus the hidden exceptions) as thumbnails on one
horizontal, scrollable row. Content-sizing is deliberately capped in height (§13.5's image strip); a
future preferences slice makes that height configurable ([[appendices.open-questions#still-open]]).
"""

from pathlib import Path
from typing import Final, override

from borco_pyside.core import SimpleProperty
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QWidget

from ..image_scanner import ImageScanner

THUMBNAIL_BORDER: Final = 2
"""Width, in pixels, of the frame drawn around every thumbnail. Always reserved -- transparent on the
others, colored on the current one (#161) -- so marking the current thumbnail cannot shift the row's
layout by a pixel."""

THUMBNAIL_STYLE: Final = f"border: {THUMBNAIL_BORDER}px solid transparent;"
CURRENT_THUMBNAIL_STYLE: Final = f"border: {THUMBNAIL_BORDER}px solid palette(highlight);"
"""How a thumbnail is drawn plain and as the current one (#161). Palette-themed rather than a fixed
color: the strip serves both the document's own viewer dock and the maximized viewer's dark backdrop,
and ``highlight`` is legible on either."""


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
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_current(current=False)

    def set_current(self, *, current: bool) -> None:
        """Frame this thumbnail as the one being shown maximized, or unframe it (#161).

        :param current: whether this thumbnail stands for the current screenshot.
        """
        self.setStyleSheet(CURRENT_THUMBNAIL_STYLE if current else THUMBNAIL_STYLE)

    @override
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Emit :attr:`clicked` when a left-button press *and* release both land on this thumbnail.

        Release, not press: Qt grabs the mouse on press, so a release still inside the widget is the
        standard "this was a click, not a drag away" test -- pressing here and letting go elsewhere
        must not open anything.

        :param event: the Qt mouse-release event, forwarded to the base class.
        """
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.__path)


class ImageStrip(QScrollArea):
    """A single horizontal row of fixed-height screenshot thumbnails ([[plugins#field-toolkit]], #27).

    Each image is scaled to the strip's height (preserving aspect ratio) and laid out left-to-right; a
    horizontal scrollbar appears when they overflow. The strip never grows vertically -- it is fixed to
    ``height`` -- so an over-tall image cannot force the viewer tall.

    Holds its own :attr:`image_scanner`, so it can re-fetch its screenshots and rebuild itself whenever
    that changes (e.g. a `.tc` -> `.rehu` conversion switching naming conventions,
    [[acquisition-tooling#tc-to-rehu]]) without its owner having to push a fresh file list explicitly.

    :param parent: optional Qt parent.
    :param height: the strip's fixed pixel height, and the height each thumbnail is scaled to.
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

    def __init__(self, parent: QWidget | None = None, height: int = 150) -> None:
        super().__init__(parent)
        self.__height = height
        self.__hidden: list[str] = []
        self.__thumbnails: dict[Path, ThumbnailLabel] = {}
        self.__current: Path | None = None
        self.__requested_visible = True
        self.setFixedHeight(height)
        self.setWidgetResizable(True)
        # nothing but the thumbnails: a scroll area's default sunken panel would draw a border around
        # the row and inset it by the frame width, which reads as stray padding around the images on
        # a document's own surface and as chrome on the maximized viewer's backdrop
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setContentsMargins(0, 0, 0, 0)
        self.setViewportMargins(0, 0, 0, 0)
        # neither bar is ever painted: the strip is a fixed-height row of thumbnails, and a scrollbar
        # eating part of that height (or sitting on the maximized viewer's backdrop) is chrome this
        # design does not want. Overflow is reached by wheel/drag, and the current thumbnail is
        # scrolled into view programmatically (:meth:`set_current`), neither of which needs a bar.
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        self.__row: Final = QHBoxLayout(content)
        self.__row.setContentsMargins(0, 0, 0, 0)
        self.__row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.setWidget(content)

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

        :param height: the strip's new fixed pixel height.
        """
        if height == self.__height:
            return
        self.__height = height
        self.setFixedHeight(height)
        # the thumbnails are scaled at build time, so the row has to be rebuilt to rescale them
        self.set_images(list(self.__thumbnails))

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

        # the frame is always drawn, so it never eats into the thumbnail it surrounds
        thumbnail_height = self.__height - 2 * THUMBNAIL_BORDER
        for path in paths:
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                continue
            label = ThumbnailLabel(path)
            label.clicked.connect(self.image_activated)
            label.setPixmap(pixmap.scaledToHeight(thumbnail_height, Qt.TransformationMode.SmoothTransformation))
            self.__row.addWidget(label)
            self.__thumbnails[path] = label  # pylint: disable=unsupported-assignment-operation

        # re-mark whatever was current before the rebuild, so a curation edit under an open viewer
        # doesn't silently lose the mark on a screenshot that survived it
        self.set_current(self.__current)
        self.__apply_visibility()
        self.images_changed.emit(list(self.__thumbnails))
