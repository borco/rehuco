"""A two-line menu entry for a `.rehu` document: its title above its dimmed, right-elided path."""

from pathlib import Path
from typing import Final

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics, QPalette
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

MAX_WIDTH: Final = 600
"""Maximum pixel width of a single entry, so a long title or path elides instead of growing its
menu without bound."""

MARGIN: Final = 6
"""Horizontal margin (each side) around both labels; subtracted from :data:`MAX_WIDTH` when
eliding, or the elided text would still overflow the entry by ``2 * MARGIN``."""


class RehuDocumentMenuEntry(QWidget):
    """A menu entry for a `.rehu` document: its title in normal text, its full path beneath it in
    smaller, dimmed text -- both right-elided to fit :data:`MAX_WIDTH`. Built as a plain
    (non-interactive) widget -- neither label grabs mouse events, so a click still falls through to
    the wrapping `QMenu`, which triggers the entry's `QWidgetAction` for free. Shared by the `View`
    menu's open-documents list (#61) and the `File` menu's `Open recents` list (#64).

    :param title: the document's display title (`RehuDocumentModel.label`, or the same
        `info.rehu`-aware derivation for a not-currently-open path).
    :param path: the document's full path, or ``None`` for a not-yet-saved document.
    :param parent: optional Qt parent.
    """

    def __init__(self, title: str, path: Path | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMaximumWidth(MAX_WIDTH)
        available_width = MAX_WIDTH - 2 * MARGIN

        title_label = QLabel(self)
        title_font = title_label.font()
        title_label.setText(QFontMetrics(title_font).elidedText(title, Qt.TextElideMode.ElideRight, available_width))

        path_label = QLabel(self)
        path_label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        path_font = path_label.font()
        path_font.setPointSizeF(path_font.pointSizeF() * 0.80)
        path_label.setFont(path_font)
        path_text = str(path) if path is not None else ""
        path_label.setText(QFontMetrics(path_font).elidedText(path_text, Qt.TextElideMode.ElideRight, available_width))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN, 4, MARGIN, 4)
        layout.setSpacing(0)
        layout.addWidget(title_label)
        layout.addWidget(path_label)
