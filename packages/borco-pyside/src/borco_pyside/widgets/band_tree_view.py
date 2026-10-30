"""A tree view whose selected and hovered rows are each one band, indentation and arrow included (#572)."""

from typing import Final, override

from PySide6.QtCore import QEvent, QModelIndex, QPersistentModelIndex, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QHoverEvent, QPainter, QPalette, QPen
from PySide6.QtWidgets import QStyleOptionViewItem, QTreeView, QWidget

ARROW_HALF: Final = 3.5
"""Half the length of an arrow's arms, in pixels."""

ARROW_PEN: Final = 1.5
"""How thick an arrow is drawn."""

HOVER_SHARE: Final = 0.2
"""How much of the highlight colour the hover band mixes into the base colour."""


class BandTreeView(QTreeView):
    """A :class:`~PySide6.QtWidgets.QTreeView` that draws its own branch area and hover band, to go with
    :class:`~borco_pyside.widgets.RowBandDelegate`.

    The delegate fills each selected *cell*, and a tree's indentation belongs to no cell: the style paints it, with
    its own idea of a selection and of a hover, and draws the expand arrow in the plain text colour whatever the row's
    state. Here the branch area of a selected row is filled with the same highlight, and the arrow is drawn in the
    colour the row's text is -- the highlighted-text colour on the band -- so the row reads as one band from edge to
    edge. The row under the mouse is filled the same way, edge to edge, with :attr:`hover_color`, and the base view
    never hears of the hover, so the style paints none of its own -- it covered the branch area alone.

    Draw it with ``allColumnsShowFocus`` off, as by default: on, the view frames the current row with the style's focus
    rectangle, which some styles draw as a rounded box inside the band.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__hovered = QPersistentModelIndex()
        """The first cell of the row under the mouse, invalid for none."""
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover)

    @property
    def hover_color(self) -> QColor:
        """The hover band's colour: the base colour with a share of the highlight, opaque, in whole channel values so it
        is exactly the colour painted."""
        palette = self.palette()
        base = palette.color(QPalette.ColorRole.Base)
        highlight = palette.color(QPalette.ColorRole.Highlight)
        return QColor(
            *(
                round(under + (over - under) * HOVER_SHARE)
                for under, over in (
                    (base.red(), highlight.red()),
                    (base.green(), highlight.green()),
                    (base.blue(), highlight.blue()),
                )
            )
        )

    @override
    def viewportEvent(self, event: QEvent) -> bool:  # noqa: N802  (Qt API name)
        # the hover is this view's alone: passed on, the base view would also have the style paint its own, a
        # translucent panel over parts of the row that doubles the band where it lands
        if isinstance(event, QHoverEvent) and event.type() in (QEvent.Type.HoverEnter, QEvent.Type.HoverMove):
            self.__hover(self.indexAt(event.position().toPoint()))
            return True
        if event.type() == QEvent.Type.HoverLeave:
            self.__hover(QModelIndex())
            return True
        if event.type() == QEvent.Type.Leave:
            self.__hover(QModelIndex())
        return super().viewportEvent(event)

    def __hover(self, index: QModelIndex) -> None:
        """Make a row the hovered one, repainting it and the one hovered before.

        :param index: any cell of the row, or an invalid index for none.
        """
        first = QPersistentModelIndex(index.siblingAtColumn(0) if index.isValid() else QModelIndex())
        if first == self.__hovered:
            return
        before, self.__hovered = self.__hovered, first
        for row in (before, first):
            if row.isValid():
                rect = self.visualRect(row.sibling(row.row(), 0))
                self.viewport().update(QRect(0, rect.top(), self.viewport().width(), rect.height()))

    def __is_selected(self, index: QModelIndex | QPersistentModelIndex) -> bool:
        """Whether a row is selected.

        :param index: a cell of the row.
        :returns: whether it is.
        """
        selection = self.selectionModel()
        return selection is not None and selection.isSelected(index)

    def __is_hovered(self, index: QModelIndex | QPersistentModelIndex) -> bool:
        """Whether a row is the one under the mouse, and not selected -- the selection band wins.

        :param index: a cell of the row.
        :returns: whether its hover band is drawn.
        """
        return (
            self.__hovered.isValid()
            and QPersistentModelIndex(index.sibling(index.row(), 0)) == self.__hovered
            and not self.__is_selected(index)
        )

    @override
    def drawRow(  # noqa: N802  (Qt API name)
        self, painter: QPainter, options: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        if self.__is_hovered(index):
            band = QRect(0, options.rect.top(), self.viewport().width(), options.rect.height())
            painter.fillRect(band, self.hover_color)
        super().drawRow(painter, options, index)

    @override
    def drawBranches(  # noqa: N802  (Qt API name)
        self, painter: QPainter, rect: QRect, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        selected = self.__is_selected(index)
        palette = self.palette()
        if selected:
            painter.fillRect(rect, palette.highlight())
        elif self.__is_hovered(index):
            painter.fillRect(rect, self.hover_color)
        model = self.model()
        if model is None or not model.hasChildren(index):
            return
        role = QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text
        # the row's own arrow sits in the last indentation step, the one beside the row's first cell
        box = QRect(rect.right() - self.indentation() + 1, rect.top(), self.indentation(), rect.height())
        self.__paint_arrow(painter, box, palette.color(role), expanded=self.isExpanded(index))

    @staticmethod
    def __paint_arrow(painter: QPainter, box: QRect, color: QColor, *, expanded: bool) -> None:
        """Draw a chevron, pointing down for an open row and right for a closed one.

        :param painter: the painter to draw with.
        :param box: where the arrow is centred.
        :param color: the colour to draw it in.
        :param expanded: whether the row is open.
        """
        center = QPointF(box.center()) + QPointF(0.5, 0.5)
        half = ARROW_HALF
        if expanded:
            points = [
                center + QPointF(-half, -half / 2),
                center + QPointF(0, half / 2),
                center + QPointF(half, -half / 2),
            ]
        else:
            points = [
                center + QPointF(-half / 2, -half),
                center + QPointF(half / 2, 0),
                center + QPointF(-half / 2, half),
            ]
        painter.save()
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(color, ARROW_PEN)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPolyline(points)
        finally:
            painter.restore()
