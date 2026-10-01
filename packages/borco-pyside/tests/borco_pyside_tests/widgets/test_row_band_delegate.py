"""Tests for `RowBandDelegate`: a selected row painted as one band (#383).

**Fills are read back from a painted image; text is not**, the same split the dock delegates' tests keep:
an icon font loaded elsewhere in the session can turn plain text into tofu, so every text claim mocks
:meth:`QPainter.drawText` instead of trusting the glyphs it asks for to rasterize.
"""

from math import ceil
from typing import Any, Final, override

from borco_pyside.widgets import ItemListEditor, RowBandDelegate, StringListEditor
from borco_pyside.widgets.row_band_delegate import TEXT_PADDING
from PySide6.QtCore import QAbstractTableModel, QEvent, QModelIndex, QPersistentModelIndex, QPointF, QRect, Qt
from PySide6.QtGui import QBrush, QColor, QFontMetricsF, QImage, QMouseEvent, QPainter, QPalette
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem, QTableView, QWidget
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot

CELL: Final = QRect(0, 0, 100, 24)
INK: Final = QColor("red")
HIGHLIGHT: Final = QColor("green")
HIGHLIGHTED_TEXT: Final = QColor("yellow")
TINT: Final = QColor("blue")
DISABLED_INK: Final = QColor("gray")
BACKGROUND: Final = QColor("purple")

# region Sample classes


class SampleModel(QAbstractTableModel):
    """Two columns: text with a tint on row 1, and a user-checkable cell; row 2 is disabled."""

    def __init__(self) -> None:
        super().__init__()
        self.checked = False

    @override
    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else 3

    @override
    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else 2

    @override
    def flags(self, index: QModelIndex | Any) -> Qt.ItemFlag:
        if index.row() == 2:
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        return flags | Qt.ItemFlag.ItemIsUserCheckable if index.column() == 1 else flags | Qt.ItemFlag.ItemIsEditable

    @override
    def data(self, index: QModelIndex | Any, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and index.column() == 0:
            return "a long text " * 20 if index.row() == 0 else "text"
        if role == Qt.ItemDataRole.ForegroundRole and index.row() == 1 and index.column() == 0:
            return QBrush(TINT)
        if role == Qt.ItemDataRole.BackgroundRole and index.row() == 1 and index.column() == 1:
            return QBrush(BACKGROUND)
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 1:
            if index.row() == 1:
                return Qt.CheckState.PartiallyChecked
            return Qt.CheckState.Checked if self.checked else Qt.CheckState.Unchecked
        return None

    @override
    def setData(self, index: QModelIndex | Any, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 1:
            self.checked = Qt.CheckState(value) == Qt.CheckState.Checked
            return True
        return False


# endregion


@fixture(name="palette")
def fixture_palette() -> QPalette:
    """A palette whose relevant roles are colours nothing else draws."""
    palette = QPalette()
    palette.setColor(QPalette.ColorGroup.Normal, QPalette.ColorRole.Text, INK)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, DISABLED_INK)
    palette.setColor(QPalette.ColorRole.Highlight, HIGHLIGHT)
    palette.setColor(QPalette.ColorRole.HighlightedText, HIGHLIGHTED_TEXT)
    return palette


@fixture(name="model")
def fixture_model(qapp: object) -> SampleModel:
    """The sample model; takes ``qapp`` because the delegate measures fonts and draws with a style."""
    del qapp
    return SampleModel()


@fixture(name="delegate")
def fixture_delegate(qapp: object) -> RowBandDelegate:
    """The delegate under test."""
    del qapp
    return RowBandDelegate()


def option_for(palette: QPalette, *, selected: bool = False, hovered: bool = False) -> QStyleOptionViewItem:
    """A style option over :data:`CELL`.

    :param palette: the palette to draw with.
    :param selected: whether to mark it selected.
    :param hovered: whether to mark it under the mouse.
    :returns: the option.
    """
    option = QStyleOptionViewItem()
    option.rect = CELL
    option.palette = palette
    if selected:
        option.state |= QStyle.StateFlag.State_Selected
    if hovered:
        option.state |= QStyle.StateFlag.State_MouseOver
    return option


def paint(
    delegate: RowBandDelegate, option: QStyleOptionViewItem, index: QModelIndex, mocker: MockerFixture | None = None
) -> tuple[QImage, list[tuple[QColor, QRect, Qt.AlignmentFlag, str]]]:
    """Paint one cell, returning the image and (when ``mocker`` is given) every ``drawText`` call.

    :param delegate: the delegate under test.
    :param option: the style option.
    :param index: the cell.
    :param mocker: pytest-mock fixture, to capture ``drawText``.
    :returns: ``(image, calls)`` with ``(pen colour, rect, flags, text)`` per call.
    """
    image = QImage(option.rect.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    calls: list[tuple[QColor, QRect, Qt.AlignmentFlag, str]] = []
    if mocker is not None:
        mocker.patch.object(
            QPainter,
            "drawText",
            side_effect=lambda rect, flags, text: calls.append((painter.pen().color(), rect, flags, text)),
        )
    try:
        delegate.paint(painter, option, index)
    finally:
        painter.end()
    return image, calls


# region The band


def test_a_selected_row_is_one_band_across_its_columns(
    delegate: RowBandDelegate, model: SampleModel, palette: QPalette
) -> None:
    """The defect: the style draws a selected row cell by cell, leaving gaps between boxes.

    **Test steps:**

    * paint both cells of a selected row into adjacent rects of one image
    * verify the highlight is on the top and bottom line of the whole row, with no gap at the seam
    """
    image = QImage(2 * CELL.width(), CELL.height(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        for column in range(2):
            option = option_for(palette, selected=True)
            option.rect = CELL.translated(column * CELL.width(), 0)
            delegate.paint(painter, option, model.index(0, column))
    finally:
        painter.end()

    for x in range(image.width()):
        assert image.pixelColor(x, 0).name() == HIGHLIGHT.name()
        assert image.pixelColor(x, CELL.height() - 1).name() == HIGHLIGHT.name()


def test_an_unselected_cell_fills_nothing(delegate: RowBandDelegate, model: SampleModel, palette: QPalette) -> None:
    """The view's own background shows through, which keeps the alternating bands.

    **Test steps:**

    * paint an unselected cell
    * verify the corner is untouched
    """
    image, _ = paint(delegate, option_for(palette), model.index(0, 0))

    assert image.pixelColor(0, 0).alpha() == 0


def test_a_selected_cell_is_drawn_in_the_highlighted_pen(
    delegate: RowBandDelegate, model: SampleModel, palette: QPalette, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * paint a selected and an unselected cell, capturing the pen at the moment text is drawn
    * verify the highlighted-text colour for the first and the ordinary ink for the second
    """
    _, selected = paint(delegate, option_for(palette, selected=True), model.index(0, 0), mocker)
    mocker.stopall()
    _, plain = paint(delegate, option_for(palette), model.index(0, 0), mocker)

    assert [pen for pen, *_ in selected] == [HIGHLIGHTED_TEXT]
    assert [pen for pen, *_ in plain] == [INK]


def test_the_models_foreground_tint_survives(
    delegate: RowBandDelegate, model: SampleModel, palette: QPalette, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * paint the cell of a row whose model answers a ``ForegroundRole`` brush
    * verify its text is drawn in that colour
    """
    _, calls = paint(delegate, option_for(palette), model.index(1, 0), mocker)

    assert [pen for pen, *_ in calls] == [TINT]


def test_a_disabled_row_is_drawn_in_the_disabled_group(
    delegate: RowBandDelegate, model: SampleModel, palette: QPalette, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * paint a cell of a row whose flags carry no ``ItemIsEnabled``
    * verify its text is drawn in the palette's disabled colour
    """
    _, calls = paint(delegate, option_for(palette), model.index(2, 0), mocker)

    assert [pen for pen, *_ in calls] == [DISABLED_INK]


def test_a_hovered_cell_draws_nothing_extra(delegate: RowBandDelegate, model: SampleModel, palette: QPalette) -> None:
    """A table with no concept of hovering a row must not grow a grey box under the mouse.

    **Test steps:**

    * paint a hovered, unselected cell
    * verify nothing was filled
    """
    image, _ = paint(delegate, option_for(palette, hovered=True), model.index(0, 0))

    assert image.pixelColor(0, 0).alpha() == 0


# endregion


# region Text and sizing


def test_text_is_inset_and_elided(
    delegate: RowBandDelegate, model: SampleModel, palette: QPalette, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * paint a cell whose text is far longer than its width
    * verify the text rect is inset by the padding on both sides and the string was elided
    """
    _, calls = paint(delegate, option_for(palette), model.index(0, 0), mocker)

    assert len(calls) == 1
    _, rect, _, text = calls[0]
    assert rect.left() == CELL.left() + TEXT_PADDING
    assert rect.right() == CELL.right() - TEXT_PADDING
    assert text != model.index(0, 0).data()
    assert len(text) < len(str(model.index(0, 0).data()))


def test_the_hint_covers_the_text_and_its_padding(delegate: RowBandDelegate, model: SampleModel) -> None:
    """The base class sizes text against the style's margin, so a column sized from it elides the last
    character; this one measures what :meth:`paint` draws.

    **Test steps:**

    * ask for the hint of a text cell
    * verify the hint minus both paddings covers the fractional advance
    """
    option = QStyleOptionViewItem()
    index = model.index(1, 0)

    hint = delegate.sizeHint(option, index)

    available = hint.width() - 2 * TEXT_PADDING
    assert available >= ceil(QFontMetricsF(option.font).horizontalAdvance("text"))


# endregion


# region Check cells


def check_indicator_rect(option: QStyleOptionViewItem) -> QRect:
    """Where the style puts a check indicator, which is where the base ``editorEvent`` hit-tests."""
    style = QApplication.style()
    return style.subElementRect(QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, None)


def test_a_check_cell_draws_its_indicator_where_the_base_hit_tests(
    delegate: RowBandDelegate, model: SampleModel, palette: QPalette, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * paint a check cell with ``QStyle.drawPrimitive`` spied on
    * verify the indicator primitive was drawn inside the cell
    """
    draw_primitive = mocker.patch.object(QApplication.style(), "drawPrimitive")

    paint(delegate, option_for(palette), model.index(0, 1))

    draw_primitive.assert_called_once()
    element, style_option = draw_primitive.call_args.args[:2]
    assert element == QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck
    assert CELL.contains(style_option.rect)  # pylint: disable=no-member


def test_a_click_on_the_indicator_toggles_the_check_state(
    delegate: RowBandDelegate, model: SampleModel, palette: QPalette
) -> None:
    """The base ``editorEvent`` still handles the toggle, since this delegate leaves it alone.

    **Test steps:**

    * release the mouse over the indicator's rect
    * verify the model's check state flipped
    """
    option = option_for(palette)
    # the base `editorEvent` refuses a cell whose option is not enabled
    option.state |= QStyle.StateFlag.State_Enabled
    index = model.index(0, 1)
    delegate.initStyleOption(option, index)
    point = QPointF(check_indicator_rect(option).center())
    event = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        point,
        point,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    handled = delegate.editorEvent(event, model, option, index)

    assert handled is True
    assert model.checked is True


# endregion


def indicator_image(*, radio: bool, state: Qt.CheckState) -> QImage:
    """A selected-row indicator painted alone.

    :param radio: whether to draw a radio button rather than a check box.
    :param state: the check state to show.
    :returns: the image, transparent where nothing was drawn.
    """
    image = QImage(16, 16, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        RowBandDelegate.paint_selected_indicator(painter, QRect(0, 0, 16, 16), INK, state, radio=radio)
    finally:
        painter.end()
    return image


def test_a_selected_radio_shows_a_dot_only_when_checked(qapp: object) -> None:
    """On the highlight the style's radio cannot be told checked from unchecked, so it is drawn here.

    **Test steps:**

    * draw a checked and an unchecked radio
    * verify both have a ring, and only the checked one has ink at its centre
    """
    del qapp
    checked = indicator_image(radio=True, state=Qt.CheckState.Checked)
    unchecked = indicator_image(radio=True, state=Qt.CheckState.Unchecked)

    assert checked.pixelColor(8, 0).alpha() > 0
    assert unchecked.pixelColor(8, 0).alpha() > 0
    assert checked.pixelColor(8, 8).alpha() > 0
    assert unchecked.pixelColor(8, 8).alpha() == 0


def test_a_selected_check_box_marks_checked_and_partial_states(qapp: object) -> None:
    """**Test steps:**

    * draw a check box in each of its three states
    * verify each has an outline, and the checked and partial ones differ from the unchecked one
    """
    del qapp
    images = {state: indicator_image(radio=False, state=state) for state in Qt.CheckState}

    assert all(image.pixelColor(8, 0).alpha() > 0 for image in images.values())
    assert images[Qt.CheckState.Unchecked].pixelColor(8, 8).alpha() == 0
    assert images[Qt.CheckState.PartiallyChecked].pixelColor(8, 8).alpha() > 0
    assert images[Qt.CheckState.Checked] != images[Qt.CheckState.Unchecked]


def test_a_selected_check_cell_draws_its_indicator_in_the_highlighted_pen(
    delegate: RowBandDelegate, model: SampleModel, palette: QPalette
) -> None:
    """**Test steps:**

    * paint a selected check cell
    * verify the highlighted-text colour appears, which the band alone never draws
    """
    image, _ = paint(delegate, option_for(palette, selected=True), model.index(0, 1))

    assert HIGHLIGHTED_TEXT.name() in {
        image.pixelColor(x, y).name() for x in range(image.width()) for y in range(image.height())
    }


def test_a_partially_checked_cell_is_painted_with_the_no_change_state(
    delegate: RowBandDelegate, model: SampleModel, palette: QPalette, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * paint an unselected partially-checked cell with ``QStyle.drawPrimitive`` spied on
    * verify the option it was handed carries ``State_NoChange``
    """
    draw_primitive = mocker.patch.object(QApplication.style(), "drawPrimitive")

    paint(delegate, option_for(palette), model.index(1, 1))

    style_option = draw_primitive.call_args.args[1]
    assert QStyle.StateFlag.State_NoChange in style_option.state  # pylint: disable=no-member


def test_a_models_background_brush_fills_an_unselected_cell(
    delegate: RowBandDelegate, model: SampleModel, palette: QPalette
) -> None:
    """**Test steps:**

    * paint an unselected cell whose model answers a ``BackgroundRole`` brush
    * verify the corner is that colour
    """
    image, _ = paint(delegate, option_for(palette), model.index(1, 1))

    assert image.pixelColor(0, 0).name() == BACKGROUND.name()


def test_a_cell_being_edited_is_not_painted(
    delegate: RowBandDelegate, model: SampleModel, palette: QPalette, qtbot: QtBot
) -> None:
    """The editor owns the cell: a band behind it shows around its frame.

    **Test steps:**

    * open a cell in a table view and paint it as selected, with that view as the option's widget
    * verify nothing was drawn
    """
    view = QTableView()
    qtbot.addWidget(view)
    view.setModel(model)
    view.setItemDelegate(delegate)
    index = model.index(0, 0)
    view.setCurrentIndex(index)
    view.show()
    view.edit(index)
    option = option_for(palette, selected=True)
    option.widget = view

    image, _ = paint(delegate, option, index)

    assert image.pixelColor(0, 0).alpha() == 0


def test_the_editor_is_placed_on_the_cells_own_rect(
    delegate: RowBandDelegate, model: SampleModel, palette: QPalette
) -> None:
    """**Test steps:**

    * place an editor with an option whose rect is known
    * verify its geometry is that rect
    """
    editor = QWidget()

    delegate.updateEditorGeometry(editor, option_for(palette), model.index(0, 0))

    assert editor.geometry() == CELL


# region ItemListEditor


def test_an_item_list_editor_installs_the_delegate(qtbot: QtBot) -> None:
    """**Test steps:**

    * build an editor
    * verify its view's delegate is a `RowBandDelegate`
    """
    editor: ItemListEditor = StringListEditor()
    qtbot.addWidget(editor)

    assert isinstance(editor.view.itemDelegate(), RowBandDelegate)


def test_an_abandoned_insert_is_still_removed(qtbot: QtBot) -> None:
    """The abandoned-insert rule listens to the view's general delegate, so it must be the installed one.

    **Test steps:**

    * insert a blank row and open it, then cancel its editor
    * verify the row is gone again
    """
    editor = StringListEditor()
    qtbot.addWidget(editor)
    with qtbot.waitExposed(editor):
        editor.show()
    editor.item_actions.insert_action.trigger()
    assert editor.model.rowCount() == 1

    editor.view.itemDelegate().closeEditor.emit(
        editor.view.indexWidget(editor.model.index(0, 0)) or editor,
        RowBandDelegate.EndEditHint.RevertModelCache,
    )

    assert editor.model.rowCount() == 0


# endregion
