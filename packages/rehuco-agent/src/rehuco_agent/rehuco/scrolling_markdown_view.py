"""The description dock's Markdown view, but filling the space it is given and scrolling inside it (#458)."""

from typing import Final, override

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..fields.widgets.markdown_view import MarkdownView

MINIMUM_HEIGHT: Final = 60
"""The least height, in pixels, the view keeps when the space around it runs out."""


class ScrollingMarkdownView(MarkdownView):
    """A `MarkdownView` -- same renderer, stylesheet, images and transparent background -- that does not size itself to
    its text: it takes whatever height its layout gives it and shows a scrollbar when the text is longer. Its width is
    the layout's to give, so what it shows never changes the width its parent needs.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # the text lines up with the rows above it, which have no padding of their own
        self.document().setDocumentMargin(0)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)

    @override
    def hasHeightForWidth(self) -> bool:  # noqa: N802  (Qt API name)
        return False

    @override
    def sizeHint(self) -> QSize:  # noqa: N802  (Qt API name)
        return QSize(0, MINIMUM_HEIGHT)

    @override
    def minimumSizeHint(self) -> QSize:  # noqa: N802  (Qt API name)
        return QSize(0, MINIMUM_HEIGHT)
