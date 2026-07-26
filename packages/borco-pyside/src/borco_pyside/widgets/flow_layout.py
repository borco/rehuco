# https://doc.qt.io/qtforpython-6/examples/example_widgets_layouts_flowlayout.html
# Copyright (C) 2013 Riverbank Computing Limited.
# Copyright (C) 2022 The Qt Company Ltd.
# SPDX-License-Identifier: BSD-3-Clause

"""A reflowing horizontal `QLayout`: items wrap to a new row instead of overflowing, unlike `QHBoxLayout`."""

from typing import Final, override

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QSizePolicy, QWidget


class FlowLayout(QLayout):
    """Lays child widgets left to right, wrapping to a new row when the next one would overflow the
    available width -- Qt's own Flow Layout example
    (https://doc.qt.io/qtforpython-6/examples/example_widgets_layouts_flowlayout.html), adapted to
    this repo's conventions.

    :param parent: optional parent widget; when given, installs this layout on it directly (the
        `QLayout(parent)` constructor form) and zeroes its content margins.
    :param spacing: the exact gap, in pixels, to leave after every item in both directions
        (keyword-only). Omitted, the gap is the layout's own :meth:`spacing` *plus* the style's
        recommended control spacing -- which is what a form of controls wants, and what Qt's own
        example does. Named explicitly, the style has no say at all, which is the only way to reach a
        gap the style would not have chosen -- notably ``0``, for items meant to sit flush.
    """

    def __init__(self, parent: QWidget | None = None, *, spacing: int | None = None) -> None:
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(QMargins(0, 0, 0, 0))
        self.__items: Final[list[QLayoutItem]] = []
        self.__spacing: Final = spacing
        if spacing is not None:
            self.setSpacing(spacing)

    @override
    def addItem(self, item: QLayoutItem) -> None:
        self.__items.append(item)

    @override
    def count(self) -> int:
        return len(self.__items)

    @override
    def itemAt(self, index: int) -> QLayoutItem | None:
        return self.__items[index] if 0 <= index < len(self.__items) else None

    @override
    def takeAt(self, index: int) -> QLayoutItem | None:  # type: ignore[override]
        return self.__items.pop(index) if 0 <= index < len(self.__items) else None

    @override
    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation.Horizontal

    @override
    def hasHeightForWidth(self) -> bool:
        return True

    @override
    def heightForWidth(self, width: int) -> int:
        return self.__apply_layout(QRect(0, 0, width, 0), test_only=True)

    @override
    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self.__apply_layout(rect, test_only=False)

    @override
    def sizeHint(self) -> QSize:
        return self.minimumSize()

    @override
    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self.__items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def __apply_layout(self, rect: QRect, test_only: bool) -> int:
        """Position every item within `rect`, wrapping to a new row as needed.

        :param rect: the area to lay out into.
        :param test_only: when true, only computes the resulting height (`heightForWidth`'s use)
            without moving any item; when false, actually calls `setGeometry` on each item.
        :returns: the total height the layout occupies.
        """
        margins = self.contentsMargins()
        effective_rect = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x = effective_rect.x()
        y = effective_rect.y()
        line_height = 0

        for item in self.__items:
            space_x = self.__spacing_after(item, Qt.Orientation.Horizontal)
            space_y = self.__spacing_after(item, Qt.Orientation.Vertical)
            next_x = x + item.sizeHint().width() + space_x
            # `next_x - space_x` is the column just *past* the item, while `right()` is the last column
            # inside the rect -- so the two are compared one apart, or an item ending exactly on the
            # right edge wraps with nothing overflowing. Visible whenever the items are all one width
            # (a row of thumbnails): every row then leaves a whole item's worth of unused space.
            if next_x - space_x > effective_rect.right() + 1 and line_height > 0:
                x = effective_rect.x()
                y += line_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))

            x = next_x
            line_height = max(line_height, item.sizeHint().height())

        return y + line_height - rect.y() + margins.bottom()

    def __spacing_after(self, item: QLayoutItem, orientation: Qt.Orientation) -> int:
        """The gap to leave after `item` in `orientation`.

        The constructor's ``spacing`` wins outright when it was given: it is the caller stating the
        exact gap, and adding the style's recommendation on top would make ``0`` unreachable.
        Otherwise the gap is this layout's own spacing plus that recommendation, as Qt's example has it.

        :param item: the layout item about to be followed by another.
        :param orientation: which gap to compute.
        :returns: the gap in pixels.
        """
        if self.__spacing is not None:
            return self.__spacing
        return self.spacing() + self.__item_layout_spacing(item, orientation)

    @staticmethod
    def __item_layout_spacing(item: QLayoutItem, orientation: Qt.Orientation) -> int:
        """The style-recommended spacing after `item` in `orientation`, or ``0`` for a non-widget
        item (e.g. a spacer) with no style to ask.

        :param item: the layout item about to be followed by another.
        :param orientation: which spacing to query.
        :returns: the recommended spacing in pixels.
        """
        widget = item.widget()
        if widget is None:
            return 0
        return widget.style().layoutSpacing(
            QSizePolicy.ControlType.PushButton, QSizePolicy.ControlType.PushButton, orientation
        )
