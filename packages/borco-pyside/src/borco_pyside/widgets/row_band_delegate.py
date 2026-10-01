"""Paints a table's selected row as one band instead of a run of per-cell boxes (#383)."""

from math import ceil
from typing import Final, override

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

TEXT_PADDING: Final = 6
"""Horizontal inset of a cell's text from its rect, in pixels -- the same width the dock tables use."""

type ModelIndex = QModelIndex | QPersistentModelIndex


class RowBandDelegate(QStyledItemDelegate):
    """Draws what the default delegate draws -- text, check state, the model's colours -- but fills a
    selected cell's whole rect, so one selected row reads as one band.

    The style draws a selected row cell by cell, and with no grid between the cells a selection becomes a
    run of separate rounded boxes with the text flush against each edge. Filling the item's whole rect and
    drawing padded content over it is what the file and checksum docks do
    (`FilesRowDelegate`, `ChecksumRowDelegate`); those are their own classes because they draw row types
    and glyphs of their own, where this one is for a table that holds ordinary model data and only wants
    the look.

    Painting is still per cell: with the grid off the cells' rects tile the row, so every column of a row
    filling its own rect is what makes one band. A column delegate set on top (a spin box, a centred
    checkbox) subclasses this and calls :meth:`paint_band` first, so its cell takes part.

    Editing is the base class's: the editor lands on the cell's own rect, and a check-state cell is
    toggled by the base ``editorEvent``, which hit-tests the same indicator rect :meth:`paint` draws.
    Neither the hover box nor the focus frame is drawn; the band alone shows the current row.

    :param parent: optional Qt parent.
    """

    def paint_band(self, painter: QPainter, option: QStyleOptionViewItem, index: ModelIndex) -> QColor:
        """Fill a selected cell and set the pen its content is drawn with.

        Call between ``painter.save()`` and ``painter.restore()``: the pen is left changed.

        :param painter: the painter to draw with.
        :param option: the item's rect, palette and state.
        :param index: the cell, for its flags.
        :returns: the colour content should be drawn in.
        """
        if QStyle.StateFlag.State_Selected in option.state:
            painter.fillRect(option.rect, option.palette.highlight())
            color = option.palette.color(QPalette.ColorRole.HighlightedText)
        else:
            if option.backgroundBrush.style() != Qt.BrushStyle.NoBrush:
                painter.fillRect(option.rect, option.backgroundBrush)
            enabled = bool(index.flags() & Qt.ItemFlag.ItemIsEnabled)
            group = QPalette.ColorGroup.Normal if enabled else QPalette.ColorGroup.Disabled
            color = option.palette.color(group, QPalette.ColorRole.Text)
        pen = painter.pen()
        pen.setColor(color)
        painter.setPen(pen)
        return color

    @staticmethod
    def paint_selected_indicator(
        painter: QPainter, rect: QRect, color: QColor, state: Qt.CheckState, *, radio: bool = False
    ) -> None:
        """Draw a check box or radio button in ``color`` over the selection band.

        The style's own indicators are tuned for a plain background: on the highlight their outline
        all but vanishes, and a selected radio cannot be told from an unselected one.

        :param painter: the painter to draw with.
        :param rect: the indicator's rect.
        :param color: the colour to draw it in -- the highlighted-text colour.
        :param state: the check state to show.
        :param radio: whether to draw a radio button rather than a check box.
        """
        painter.save()
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(color, 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            box = QRectF(rect).adjusted(0.75, 0.75, -0.75, -0.75)
            if radio:
                painter.drawEllipse(box)
                if state == Qt.CheckState.Checked:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(color)
                    dot = box.width() * 0.25
                    painter.drawEllipse(box.center(), dot, dot)
                return
            painter.drawRoundedRect(box, 3, 3)
            x, y, w, h = box.x(), box.y(), box.width(), box.height()
            if state == Qt.CheckState.Checked:
                painter.drawPolyline(
                    [
                        QPointF(x + w * 0.22, y + h * 0.52),
                        QPointF(x + w * 0.42, y + h * 0.72),
                        QPointF(x + w * 0.78, y + h * 0.3),
                    ]
                )
            elif state == Qt.CheckState.PartiallyChecked:
                painter.drawLine(QPointF(x + w * 0.25, y + h * 0.5), QPointF(x + w * 0.75, y + h * 0.5))
        finally:
            painter.restore()

    @override
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: ModelIndex) -> None:
        view = option.widget
        if isinstance(view, QAbstractItemView) and view.indexWidget(index) is not None:
            # a cell being edited is the editor's alone: a band behind it shows around its frame, and
            # the old text shows through
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        # save/restore the painter Qt handed over rather than opening a second one on its device
        painter.save()
        try:
            self.paint_band(painter, opt, index)
            painter.setFont(opt.font)  # the model's FontRole (a bold changed row) reaches the text drawn below
            cell = opt.rect
            if opt.features & QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator:
                cell = self.__paint_check(painter, opt)
            rect = cell.adjusted(TEXT_PADDING, 0, -TEXT_PADDING, 0)
            elided = painter.fontMetrics().elidedText(opt.text, opt.textElideMode, rect.width())
            horizontal = opt.displayAlignment & Qt.AlignmentFlag.AlignHorizontal_Mask
            painter.drawText(rect, horizontal | Qt.AlignmentFlag.AlignVCenter, elided)
        finally:
            painter.restore()

    @staticmethod
    def __paint_check(painter: QPainter, opt: QStyleOptionViewItem) -> QRect:
        """Draw the check indicator where the base delegate hit-tests it.

        :param painter: the painter to draw with.
        :param opt: the initialised option of a cell that has an indicator.
        :returns: the part of the cell left for text, after the indicator.
        """
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        indicator = style.subElementRect(QStyle.SubElement.SE_ItemViewItemCheckIndicator, opt, opt.widget)
        if QStyle.StateFlag.State_Selected in opt.state:
            RowBandDelegate.paint_selected_indicator(
                painter, indicator, opt.palette.color(QPalette.ColorRole.HighlightedText), opt.checkState
            )
            return opt.rect.adjusted(indicator.right() - opt.rect.left() + 1, 0, 0, 0)
        check = QStyleOptionViewItem(opt)
        check.rect = indicator
        check.state &= ~QStyle.StateFlag.State_HasFocus
        check.state &= ~(QStyle.StateFlag.State_On | QStyle.StateFlag.State_Off | QStyle.StateFlag.State_NoChange)
        match opt.checkState:
            case Qt.CheckState.Checked:
                check.state |= QStyle.StateFlag.State_On
            case Qt.CheckState.PartiallyChecked:
                check.state |= QStyle.StateFlag.State_NoChange
            case _:
                check.state |= QStyle.StateFlag.State_Off
        style.drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck, check, painter, opt.widget)
        return opt.rect.adjusted(indicator.right() - opt.rect.left() + 1, 0, 0, 0)

    @override
    def updateEditorGeometry(  # noqa: N802  (Qt API name)
        self, editor: QWidget, option: QStyleOptionViewItem, index: ModelIndex
    ) -> None:
        """Put the editor on the cell's own rect.

        The base class uses the style's *text* rect, which a list view insets by a margin the table views
        do not apply -- so an editor opened in a list sat to the right of the text it was editing.

        :param editor: the editor to place.
        :param option: the item's option.
        :param index: the cell; unused.
        """
        del index
        editor.setGeometry(option.rect)

    @override
    def sizeHint(self, option: QStyleOptionViewItem, index: ModelIndex) -> QSize:  # noqa: N802  (Qt API name)
        """Measure a cell the way it is drawn.

        The base class measures text against the *style*'s margin and with whole-pixel metrics, so a
        column sized from it elides the last character of every row whose advance rounds down. This
        measures in fractional pixels, rounded up, plus the padding :meth:`paint` insets by.

        The font is the cell's own -- the model's ``FontRole`` laid over the view's, as :meth:`paint` draws
        it -- so a row the model bolds widens its column instead of being elided.

        :param option: the item's option, for the view's font.
        :param index: the cell.
        :returns: the hint.
        """
        base = super().sizeHint(option, index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        metrics = QFontMetricsF(opt.font)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        width = ceil(metrics.horizontalAdvance(text)) + 2 * TEXT_PADDING
        if index.data(Qt.ItemDataRole.CheckStateRole) is not None:
            style = option.widget.style() if option.widget is not None else QApplication.style()
            width += style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth) + TEXT_PADDING
        return QSize(width, max(base.height(), ceil(metrics.height())))
