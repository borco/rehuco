"""A horizontal, fixed-height strip of screenshot thumbnails -- the lightbox viewer ([[plugins#field-toolkit]], #27).

The read-only counterpart of :class:`~rehuco_agent.fields.widgets.image_selector.ImageSelector`: it shows
the *curated* set of screenshots (all siblings minus the hidden exceptions) as thumbnails on one
horizontal, scrollable row. Content-sizing is deliberately capped in height (§13.5's image strip); a
future preferences slice makes that height configurable ([[appendices.open-questions#still-open]]).
"""

from pathlib import Path
from typing import Final, override

from borco_pyside.core import SimpleProperty
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QWidget

from ..image_scanner import ImageScanner


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

    image_scanner = SimpleProperty[ImageScanner | None](None)
    """The strategy resolving this resource's screenshots; ``None`` shows nothing."""

    def __init__(self, parent: QWidget | None = None, height: int = 150) -> None:
        super().__init__(parent)
        self.__height: Final = height
        self.__hidden: list[str] = []
        self.setFixedHeight(height)
        self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

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

    def __refresh(self) -> None:
        """Recompute the visible screenshot set from the current scanner and hidden list."""
        scanner = self.image_scanner
        files = scanner.files() if scanner is not None else []
        hidden = set(self.__hidden)
        self.set_images([path for path in files if path.name not in hidden])

    def set_images(self, paths: list[Path]) -> None:
        """Replace the strip's thumbnails with the given screenshot paths, in order.

        :param paths: the curated (visible) screenshot paths to show; an empty list clears the strip.
        """
        while (item := self.__row.takeAt(0)) is not None:
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        # the scrollbar eats a few pixels of viewport height; scale to that so a thumbnail never
        # triggers a vertical scrollbar of its own
        thumbnail_height = self.__height - self.horizontalScrollBar().sizeHint().height()
        for path in paths:
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                continue
            label = ThumbnailLabel(path)
            label.clicked.connect(self.image_activated)
            label.setPixmap(pixmap.scaledToHeight(thumbnail_height, Qt.TransformationMode.SmoothTransformation))
            self.__row.addWidget(label)
