"""How the Add Roots dialog's list draws and edits its rows: a ``.rehuroot`` painted with what it holds, a folder in
editors that stay open (#578)."""

from collections.abc import Callable, Sequence
from typing import Final, cast, override

from PySide6.QtCore import (
    QAbstractItemModel,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QMouseEvent, QPainter, QPalette
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QWidget
from rehuco_core import CandidateKind, RootCandidate, RootPick, layout_rows

from ..fields.colors import WARNING_COLOR
from ..settings.root_catalog_settings import RootLayout
from ..svg_icon_cache import SvgIconCache
from .new_root_item_editor import CHECKING, REMOVE_ICON, NewRootItemEditor
from .root_candidates_model import CandidateRole

MARGIN: Final = 6
"""The space around a painted row's lines, in pixels -- the folder editor's own margin."""

UNMAPPED: Final = "Not on this machine: it is added unmapped, and Map\N{HORIZONTAL ELLIPSIS} finds it later."
"""What a root file whose location this machine cannot resolve says."""

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a delegate method."""


class RootCandidateDelegate(QStyledItemDelegate):
    """Draws a ``.rehuroot``'s row -- its file, label and location, layouts, where this machine finds it, and why it
    cannot be added if it cannot, or that it is being checked -- with a remove button; gives a folder's row a
    :class:`~.new_root_item_editor.NewRootItemEditor` that the owner keeps open, checked or not.

    :param presets: asked for every preset, in the order a folder's combo offers them.
    :param parent: optional Qt parent.
    """

    remove_requested = Signal(object)
    """Emitted with the :class:`~PySide6.QtCore.QPersistentModelIndex` of a row to take out."""

    new_layout_requested = Signal(object)
    """Emitted with the :class:`~PySide6.QtCore.QPersistentModelIndex` of a folder whose combo asked for a new
    preset."""

    def __init__(self, presets: Callable[[], Sequence[RootLayout]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__presets: Final = presets
        self.__icons: Final = SvgIconCache()
        self.__prototype: NewRootItemEditor | None = None
        """An editor never shown, which measures how tall a folder's row is."""

    # region painted rows

    @staticmethod
    def lines_of(line: RootCandidate | None, pick: RootPick) -> list[tuple[str, bool]]:
        """What a painted row says, line by line.

        :param line: the row's plan, or ``None`` while it is being checked.
        :param pick: the row's pick.
        :returns: each line's text and whether it is a warning.
        """
        if line is None:
            return [(str(pick.path), False), (CHECKING, False)]
        lines = [(str(line.root_file), False)]
        if line.location:
            lines.append((f"{line.label} \N{MIDDLE DOT} {line.location}", False))
        if line.layouts:
            joined = "; ".join(f"{key} \N{RIGHTWARDS ARROW} {value}" for key, value in layout_rows(line.layouts))
            lines.append((f"Layouts: {joined}", False))
        if line.addable:
            lines.append((UNMAPPED if line.folder is None else f"On this machine: {line.folder}", False))
        else:
            lines.append((line.problem, True))
        return lines

    def remove_rect(self, rect: QRect) -> QRect:
        """Where a painted row's remove button is.

        :param rect: the row.
        :returns: a square at its top right corner.
        """
        side = QFontMetrics(QFont()).lineSpacing() + 4
        return QRect(rect.right() - side - MARGIN + 1, rect.top() + MARGIN, side, side)

    @override
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: ModelIndex) -> None:
        if index.data(CandidateRole.KIND) == CandidateKind.FOLDER:
            return
        rect: QRect = option.rect  # type: ignore[attr-defined]
        palette: QPalette = option.palette  # type: ignore[attr-defined]
        painter.save()
        try:
            text = palette.color(QPalette.ColorRole.Text)
            lines = RootCandidateDelegate.lines_of(index.data(CandidateRole.LINE), index.data(CandidateRole.PICK))
            button = self.remove_rect(rect)
            area = QRect(rect.left() + MARGIN, rect.top() + MARGIN, button.left() - rect.left() - 2 * MARGIN, 0)
            RootCandidateDelegate.__draw_lines(painter, area, lines, text)
            self.__icons.icon(REMOVE_ICON, text).paint(painter, button.adjusted(2, 2, -2, -2))
            painter.setPen(palette.color(QPalette.ColorRole.Mid))
            painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        finally:
            painter.restore()

    @staticmethod
    def __draw_lines(painter: QPainter, area: QRect, lines: list[tuple[str, bool]], text: QColor) -> None:
        """Draw a painted row's lines one under the other, the first bold, a warning in its colour, each elided in the
        middle to the width it has.

        :param painter: the painter, its state the caller's to restore.
        :param area: where the first line starts, and how wide every line may be.
        :param lines: each line's text and whether it is a warning.
        :param text: the colour of a line that is no warning.
        """
        spacing = painter.fontMetrics().lineSpacing()
        for row, (line, warning) in enumerate(lines):
            font = QFont(painter.font())
            font.setBold(row == 0)
            painter.setFont(font)
            painter.setPen(QColor(WARNING_COLOR) if warning else text)
            elided = QFontMetrics(font).elidedText(line, Qt.TextElideMode.ElideMiddle, area.width())
            painter.drawText(
                QRect(area.left(), area.top() + row * spacing, area.width(), spacing),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                elided,
            )

    @override
    def sizeHint(self, option: QStyleOptionViewItem, index: ModelIndex) -> QSize:  # noqa: N802  (Qt API name)
        pick = cast(RootPick, index.data(CandidateRole.PICK))
        line = cast(RootCandidate | None, index.data(CandidateRole.LINE))
        if index.data(CandidateRole.KIND) == CandidateKind.FOLDER:
            prototype = self.__measure()
            prototype.show_row(pick, line, index.data(CandidateRole.LAYOUT), self.__presets())
            return QSize(0, prototype.sizeHint().height() + 1)
        count = len(RootCandidateDelegate.lines_of(line, pick))
        return QSize(0, count * QFontMetrics(option.font).lineSpacing() + 2 * MARGIN + 1)  # type: ignore[attr-defined]

    @override
    def editorEvent(  # noqa: N802  (Qt API name)
        self, event: QEvent, model: QAbstractItemModel, option: QStyleOptionViewItem, index: ModelIndex
    ) -> bool:
        if (
            event.type() == QEvent.Type.MouseButtonRelease
            and isinstance(event, QMouseEvent)
            and event.button() == Qt.MouseButton.LeftButton
            and self.remove_rect(option.rect).contains(event.position().toPoint())  # type: ignore[attr-defined]
        ):
            self.remove_requested.emit(QPersistentModelIndex(index))
            return True
        return super().editorEvent(event, model, option, index)

    def __measure(self) -> NewRootItemEditor:
        """The editor that measures a folder's row, made once.

        :returns: it.
        """
        if self.__prototype is None:
            self.__prototype = NewRootItemEditor()
            self.__prototype.setParent(cast(QWidget, self.parent()), Qt.WindowType.Widget)
            self.__prototype.hide()
        return self.__prototype

    # endregion

    # region a folder's editors

    @override
    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem, index: ModelIndex) -> QWidget:  # noqa: N802
        del option
        editor = NewRootItemEditor(parent)
        held = QPersistentModelIndex(index)
        editor.edited.connect(lambda: self.commitData.emit(editor))
        editor.layout_chosen.connect(lambda layout: held.model().setData(held, layout, CandidateRole.LAYOUT))
        editor.remove_requested.connect(lambda: self.remove_requested.emit(held))
        editor.new_layout_requested.connect(lambda: self.new_layout_requested.emit(held))
        return editor

    @override
    def setEditorData(self, editor: QWidget, index: ModelIndex) -> None:  # noqa: N802  (Qt API name)
        if isinstance(editor, NewRootItemEditor):
            editor.show_row(
                index.data(CandidateRole.PICK),
                index.data(CandidateRole.LINE),
                index.data(CandidateRole.LAYOUT),
                self.__presets(),
            )

    @override
    def setModelData(  # noqa: N802  (Qt API name)
        self, editor: QWidget, model: QAbstractItemModel, index: ModelIndex
    ) -> None:
        if isinstance(editor, NewRootItemEditor):
            # both at once: one edit of the row plans the list again once
            model.setData(index, (editor.label_edit.text(), editor.root_file_edit.text()), CandidateRole.TYPED)

    @override
    def updateEditorGeometry(  # noqa: N802  (Qt API name)
        self, editor: QWidget, option: QStyleOptionViewItem, index: ModelIndex
    ) -> None:
        del index
        rect: QRect = option.rect  # type: ignore[attr-defined]
        editor.setGeometry(rect.adjusted(0, 0, 0, -1))

    # endregion
