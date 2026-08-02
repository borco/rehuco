"""A `QTableView` that grows to fit its rows instead of scrolling them.

Deliberately a **copy** of `ContentSizedListView`'s sizing rather than a base class shared with it:
the two differ only in what chrome they carry, but a mixin holding the shared half would have to sit
between them and `QAbstractItemView`, and Shiboken does not support inheriting from two Qt classes.
The alternative -- a helper `QObject` each view forwards its size hints to -- buys back the twenty
lines at the cost of an indirection in the one method Qt calls on every layout pass.
"""

# pylint: disable=duplicate-code  # the shared half with ContentSizedListView, kept for the reason above

from typing import override

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QSize, Qt
from PySide6.QtWidgets import QHeaderView, QSizePolicy, QTableView, QWidget


class ContentSizedTableView(QTableView):
    """A `QTableView` sized to the rows its model holds, so an enclosing scroll area does the scrolling.

    `ContentSizedListView`'s rule, for the tabular half of the same problem: a table inside a scrolling
    page is a scroll area inside a scroll area -- two vertical scrollbars, and a table the user has to
    scroll *to* before they can scroll *in*. This reports its header plus its rows as its height instead
    and never scrolls vertically; the page grows, and the one scrollbar around it moves the whole page.

    The floor is a single row, so an emptied table stays a legible band rather than collapsing onto its
    header with nowhere to drop a first entry. Horizontal scrolling is left alone: the page around it
    scrolls vertically only, so a bar for over-wide content is the table's own to show.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # what one row measured, last time there was a row to measure -- an emptied table's floor. The
        # vertical header's own uniform section height stands in until then, which is the height the rows
        # are drawn at anyway (they are ``Fixed`` below), so a table that has never held a row is the same
        # height as one emptied of the rows it held: the two states looked different when the stand-in was
        # the font's line height, for no reason a reader could account for.
        self.__row_height = 0
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # rows keep the header's uniform default height rather than each being measured
        # (``ResizeToContents``): every insert would otherwise re-measure *every* row and repaint the
        # whole table, which reads as a flash. The height below is read off the rows as drawn, so the
        # two agree either way -- this is the cheap half of that agreement, not a compromise on it.
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        policy = self.sizePolicy()
        # Fixed, not Minimum: a table given more height than its rows need is blank space below the
        # last one, which reads as the table having entries the user cannot see
        policy.setVerticalPolicy(QSizePolicy.Policy.Fixed)
        self.setSizePolicy(policy)

    @override
    def setModel(self, model: QAbstractItemModel | None) -> None:  # noqa: N802  (Qt API name)
        # the rows are what this widget's height is made of, so every change to them re-advertises it.
        # Wired here rather than in __init__ because a view is handed its model afterwards -- and may be
        # handed a second one, which is why the previous model is let go of first.
        previous = self.model()
        if previous is not None:
            previous.rowsInserted.disconnect(self.__on_rows_changed)
            previous.rowsRemoved.disconnect(self.__on_rows_changed)
            previous.modelReset.disconnect(self.updateGeometry)
        super().setModel(model)
        if model is not None:
            model.rowsInserted.connect(self.__on_rows_changed)
            model.rowsRemoved.connect(self.__on_rows_changed)
            model.modelReset.connect(self.updateGeometry)
        self.updateGeometry()

    @override
    def sizeHint(self) -> QSize:  # noqa: N802  (Qt API name)
        return QSize(super().sizeHint().width(), self.__rows_height())

    @override
    def minimumSizeHint(self) -> QSize:  # noqa: N802  (Qt API name)
        return QSize(super().minimumSizeHint().width(), self.__rows_height())

    def __on_rows_changed(self, parent: QModelIndex, first: int, last: int) -> None:
        """Re-advertise this table's height after rows were added or removed.

        :param parent: the parent index the rows changed under; unused, a table model is flat here.
        :param first: the first row's position; unused.
        :param last: the last row's position; unused.
        """
        del parent, first, last
        self.updateGeometry()

    def __row_count(self) -> int:
        """How many rows there are to be sized by.

        :returns: the model's row count, or zero while there is no model.
        """
        model = self.model()
        return 0 if model is None else model.rowCount()

    def __rows_height(self) -> int:
        """The height this table needs to show every row it holds, with one row as the floor.

        :returns: the rows' total height plus the header, the frame, and any horizontal scrollbar.
        """
        # the height a row is actually drawn at, which is the measured one once it has been laid out
        # and the measurement itself until then
        heights = [self.rowHeight(row) or self.sizeHintForRow(row) for row in range(self.__row_count())]
        if heights:
            self.__row_height = heights[0]
        else:
            heights = [self.__row_height or self.verticalHeader().defaultSectionSize()]
        return sum(heights) + self.__chrome_height()

    def __chrome_height(self) -> int:
        """The height this table spends on anything that is not a row.

        :returns: the horizontal header while it is shown, the frame's two borders, and the horizontal
            scrollbar while *it* is shown.
        """
        header = self.horizontalHeader()
        # isHidden, not isVisible: a widget that has never been shown is not visible yet, and the
        # height it will need once it is shown is exactly what this size hint has to declare
        # max(0, ...): a header with no sections behind it -- no model, or a model with no columns --
        # reports an invalid (-1) hint, which would take a pixel off the height rather than add none
        header_height = 0 if header.isHidden() else max(0, header.sizeHint().height())
        scrollbar = self.horizontalScrollBar()
        scrollbar_height = scrollbar.sizeHint().height() if scrollbar.isVisible() else 0
        return header_height + 2 * self.frameWidth() + scrollbar_height
