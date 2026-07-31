"""A `QListWidget` that grows to fit its rows instead of scrolling them."""

from typing import override

from PySide6.QtCore import QModelIndex, QSize, Qt
from PySide6.QtWidgets import QListWidget, QSizePolicy, QWidget


class ContentSizedListWidget(QListWidget):
    """A `QListWidget` sized to the rows it holds, so an enclosing scroll area does the scrolling.

    A list inside a scrolling page is a scroll area inside a scroll area: two vertical scrollbars, and
    a list the user has to scroll *to* before they can scroll *in*. This reports its rows' total height
    as its size instead and never scrolls vertically -- the page grows, and the one scrollbar around it
    moves the whole page, the same trade `RichTextView` makes for a rendered document.

    The floor is a single row, so an emptied list stays a legible band rather than collapsing to a
    sliver with nowhere to drop a first entry. Horizontal scrolling is left alone: the page around it
    scrolls vertically only, so a bar for over-wide content is the list's own to show.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # what one row measured, last time there was a row to measure -- an emptied list's floor. The
        # font's line height stands in until then; a list emptied of rows it once had is sized by them
        # rather than by an estimate that can differ from what the style actually draws.
        self.__row_height = 0
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        policy = self.sizePolicy()
        # Fixed, not Minimum: a list given more height than its rows need is blank space below the last
        # one, which reads as the list having entries the user cannot see
        policy.setVerticalPolicy(QSizePolicy.Policy.Fixed)
        self.setSizePolicy(policy)
        # the rows are what this widget's height is made of, so every change to them re-advertises it
        model = self.model()
        model.rowsInserted.connect(self.__on_rows_changed)
        model.rowsRemoved.connect(self.__on_rows_changed)
        model.modelReset.connect(self.updateGeometry)

    @override
    def sizeHint(self) -> QSize:  # noqa: N802  (Qt API name)
        return QSize(super().sizeHint().width(), self.__rows_height())

    @override
    def minimumSizeHint(self) -> QSize:  # noqa: N802  (Qt API name)
        return QSize(super().minimumSizeHint().width(), self.__rows_height())

    def __on_rows_changed(self, parent: QModelIndex, first: int, last: int) -> None:
        """Re-advertise this list's height after rows were added or removed.

        :param parent: the parent index the rows changed under; unused, a list model is flat.
        :param first: the first row's position; unused.
        :param last: the last row's position; unused.
        """
        del parent, first, last
        self.updateGeometry()

    def __rows_height(self) -> int:
        """The height this list needs to show every row it holds, with one row as the floor.

        :returns: the rows' total height plus the frame and any horizontal scrollbar.
        """
        heights = [self.sizeHintForRow(row) for row in range(self.count())]
        if heights:
            self.__row_height = heights[0]
        else:
            heights = [self.__row_height or self.fontMetrics().height()]
        spacing = 2 * self.spacing() * len(heights)
        return sum(heights) + spacing + self.__chrome_height()

    def __chrome_height(self) -> int:
        """The height this list spends on anything that is not a row.

        :returns: the frame's two borders, plus the horizontal scrollbar while it is shown.
        """
        scrollbar = self.horizontalScrollBar()
        scrollbar_height = scrollbar.sizeHint().height() if scrollbar.isVisible() else 0
        return 2 * self.frameWidth() + scrollbar_height
