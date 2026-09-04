"""Tests for LogLevelDelegate."""

import logging

from borco_pyside.logging.log_entry import LogEntry
from borco_pyside.logging.log_level_band import LogLevelBand
from borco_pyside.logging.log_level_delegate import BAND_TINT_ALPHA, LEVEL_COLUMN_WIDTH_HINT, LogLevelDelegate
from borco_pyside.logging.log_model import LEVEL_COLUMN, LogModel
from borco_pyside.widgets import StringItemListModel
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot

WARNING_COLOR = QColor("#F4511E")
ERROR_COLOR = QColor("#C62828")

BAND_COLORS = {LogLevelBand.WARNINGS: WARNING_COLOR, LogLevelBand.ERRORS: ERROR_COLOR}
"""Two of the four bands colored, so the untinted case is covered by the same fixture."""

CELL = QRect(0, 0, 120, 24)


# region helpers


def make_entry(level: int, serial: int = 0, message: str = "a message") -> LogEntry:
    """Build one entry the way the bridge would.

    :param level: the record's level.
    :param serial: its position in the run.
    :param message: the formatted message.
    :returns: the entry.
    """
    record = logging.LogRecord("test", level, __file__, 1, message, None, None)
    return LogEntry(record, message, (), serial)


def paint_onto_image(delegate: LogLevelDelegate, option: QStyleOptionViewItem, index: object) -> QImage:
    """Paint one cell onto a white image and hand it back for inspection.

    Painting for real rather than mocking the painter: what this delegate is *for* is the color that
    ends up on the pixels, and a recorded call to ``fillRect`` proves only that it was asked for.

    :param delegate: the delegate to paint with.
    :param option: the item option to paint under.
    :param index: the index to paint.
    :returns: the painted image.
    """
    image = QImage(option.rect.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    delegate.paint(painter, option, index)  # type: ignore[arg-type]  # a real QModelIndex in every caller
    painter.end()
    return image


def drawn_texts(
    delegate: LogLevelDelegate, option: QStyleOptionViewItem, index: object, mocker: MockerFixture
) -> list[str]:
    """Paint one cell with a real, active painter and report every string it was asked to draw.

    A real painter rather than a bare ``QPainter()``: the delegate saves state and reads the current
    font off it, and an inactive painter answers all of that with warnings and defaults.

    :param delegate: the delegate to paint with.
    :param option: the item option to paint under.
    :param index: the index to paint.
    :param mocker: pytest-mock fixture.
    :returns: the drawn strings, in the order they were drawn.
    """
    drawn = mocker.patch.object(QPainter, "drawText")
    image = QImage(option.rect.size(), QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    delegate.paint(painter, option, index)  # type: ignore[arg-type]  # a real QModelIndex in every caller
    painter.end()
    return [call.args[-1] for call in drawn.call_args_list]


def blended_over_white(color: QColor) -> QColor:
    """The color a tint of ``color`` leaves on a white pixel.

    :param color: the caller's untinted color.
    :returns: the expected painted color.
    """
    alpha = BAND_TINT_ALPHA / 255
    return QColor(
        round(color.red() * alpha + 255 * (1 - alpha)),
        round(color.green() * alpha + 255 * (1 - alpha)),
        round(color.blue() * alpha + 255 * (1 - alpha)),
    )


# endregion


# region fixtures


@fixture
def delegate(qtbot: QtBot) -> LogLevelDelegate:
    """Provide a delegate with two of the four bands colored.

    :param qtbot: pytest-qt bot, ensuring a QApplication exists.
    :returns: the delegate.
    """
    del qtbot  # only needed so a QApplication exists
    return LogLevelDelegate(band_colors=BAND_COLORS)


@fixture
def option() -> QStyleOptionViewItem:
    """Provide an unselected item option over a fixed cell rect.

    :returns: the option.
    """
    item = QStyleOptionViewItem()
    item.rect = CELL
    return item


@fixture
def model(qtbot: QtBot) -> LogModel:
    """Provide a model holding one record per named level, criticals included.

    :param qtbot: pytest-qt bot, ensuring a QApplication exists.
    :returns: the model.
    """
    del qtbot  # only needed so a QApplication exists
    log_model = LogModel()
    log_model.handle_log_records(
        [
            make_entry(logging.DEBUG, 0),
            make_entry(logging.INFO, 1),
            make_entry(logging.WARNING, 2),
            make_entry(logging.ERROR, 3),
        ]
    )
    return log_model


# endregion


# region the tint per band


@mark.parametrize(
    ("band", "color"),
    [(LogLevelBand.WARNINGS, WARNING_COLOR), (LogLevelBand.ERRORS, ERROR_COLOR)],
)
def test_tint_for_applies_the_alpha_to_a_colored_band(
    delegate: LogLevelDelegate, band: LogLevelBand, color: QColor
) -> None:
    """A colored band's tint is the caller's color at this class's own alpha.

    **Test steps:**

    * Ask the delegate for the band's tint.
    * Assert the hue is the caller's and the alpha is the delegate's.
    """
    tint = delegate.tint_for(band)
    assert tint is not None
    assert tint.rgb() == color.rgb()
    assert tint.alpha() == BAND_TINT_ALPHA


@mark.parametrize("band", [LogLevelBand.DEBUGS, LogLevelBand.INFOS])
def test_a_band_with_no_color_has_no_tint(delegate: LogLevelDelegate, band: LogLevelBand) -> None:
    """A band absent from the map is drawn plain rather than in some invented color.

    **Test steps:**

    * Ask the delegate for a band the map does not mention.
    * Assert there is no tint.
    """
    assert delegate.tint_for(band) is None


def test_band_colors_can_be_replaced_after_construction(delegate: LogLevelDelegate) -> None:
    """The tints are settable, which is what lets a host follow a theme change.

    **Test steps:**

    * Replace the map with one coloring the infos band.
    * Assert the new band is tinted and a previously-colored one is not.
    """
    delegate.band_colors = {LogLevelBand.INFOS: WARNING_COLOR}
    assert delegate.tint_for(LogLevelBand.INFOS) is not None
    assert delegate.tint_for(LogLevelBand.ERRORS) is None


def test_band_colors_returns_a_copy(delegate: LogLevelDelegate) -> None:
    """Mutating what the getter returned changes nothing the delegate paints from.

    **Test steps:**

    * Read the map and clear the copy.
    * Assert the delegate still tints its bands.
    """
    delegate.band_colors.clear()
    assert delegate.tint_for(LogLevelBand.ERRORS) is not None


# endregion


# region painting


def test_paints_a_warning_in_its_bands_tint(
    delegate: LogLevelDelegate, option: QStyleOptionViewItem, model: LogModel
) -> None:
    """A warning row's background is the warnings color, blended over what was underneath.

    **Test steps:**

    * Paint the warning row's level cell over white.
    * Assert a background pixel matches the tint blended over white.
    """
    index = model.index(2, LEVEL_COLUMN)
    image = paint_onto_image(delegate, option, index)
    expected = blended_over_white(WARNING_COLOR)
    assert QColor(image.pixelColor(CELL.width() - 2, CELL.height() - 2)).rgb() == expected.rgb()


def test_paints_an_uncolored_band_without_a_tint(
    delegate: LogLevelDelegate, option: QStyleOptionViewItem, model: LogModel
) -> None:
    """A debug row is left on whatever the view already painted.

    **Test steps:**

    * Paint the debug row's level cell over white.
    * Assert a background pixel is still white.
    """
    index = model.index(0, LEVEL_COLUMN)
    image = paint_onto_image(delegate, option, index)
    assert QColor(image.pixelColor(CELL.width() - 2, CELL.height() - 2)).rgb() == QColor(Qt.GlobalColor.white).rgb()


def test_a_level_nobody_named_is_painted_by_its_band(
    delegate: LogLevelDelegate, option: QStyleOptionViewItem, qtbot: QtBot
) -> None:
    """A record logged past CRITICAL still paints, because the band is a range and not a constant.

    This is the whole reason the delegate classifies through ``LogLevelBand.of`` rather than comparing
    against the four named levels: a ladder over them would leave this row in whichever branch fell
    through, or in none.

    **Test steps:**

    * Put a record logged at ``CRITICAL + 10`` in a model.
    * Paint its level cell.
    * Assert the background is the errors tint.
    """
    del qtbot  # only needed so a QApplication exists
    model = LogModel()
    model.handle_log_records([make_entry(logging.CRITICAL + 10, 0)])
    image = paint_onto_image(delegate, option, model.index(0, LEVEL_COLUMN))
    assert QColor(image.pixelColor(CELL.width() - 2, CELL.height() - 2)).rgb() == blended_over_white(ERROR_COLOR).rgb()


def test_a_selected_row_keeps_its_band_tint(
    delegate: LogLevelDelegate, option: QStyleOptionViewItem, model: LogModel
) -> None:
    """Selecting a row does not take away the color the reader picked it out by.

    **Test steps:**

    * Paint the error row with the selected state set.
    * Assert the painted background is neither plain white nor the untinted highlight.
    """
    option.state |= QStyle.StateFlag.State_Selected
    image = paint_onto_image(delegate, option, model.index(3, LEVEL_COLUMN))
    painted = QColor(image.pixelColor(CELL.width() - 3, CELL.height() - 3))
    highlight = option.palette.highlight().color()
    assert painted.rgb() != QColor(Qt.GlobalColor.white).rgb()
    assert painted.rgb() != highlight.rgb()


def test_draws_the_records_serial_not_its_row(
    delegate: LogLevelDelegate, option: QStyleOptionViewItem, mocker: MockerFixture, model: LogModel
) -> None:
    """The corner annotation is the run-long serial, so it survives the ring buffer dropping rows.

    A row index would renumber every record above a dropped one, and could not be lined up against
    *"N earlier records dropped"*.

    **Test steps:**

    * Put an entry whose serial differs from its row in a model.
    * Record what text is drawn.
    * Assert the serial is drawn and the row index is not.
    """
    model.handle_log_records([make_entry(logging.INFO, 427)])
    texts = drawn_texts(delegate, option, model.index(4, LEVEL_COLUMN), mocker)
    assert "427" in texts
    assert "4" not in texts


def test_draws_the_level_name(
    delegate: LogLevelDelegate, option: QStyleOptionViewItem, mocker: MockerFixture, model: LogModel
) -> None:
    """The cell says which level it is, in the spelling ``logging`` uses.

    **Test steps:**

    * Record what text is drawn for the warning row.
    * Assert the level name is among it.
    """
    assert "WARNING" in drawn_texts(delegate, option, model.index(2, LEVEL_COLUMN), mocker)


# endregion


# region not a log


def test_a_row_that_is_not_a_log_entry_is_left_to_the_base_delegate(
    delegate: LogLevelDelegate, option: QStyleOptionViewItem, mocker: MockerFixture, qtbot: QtBot
) -> None:
    """Over a model that is not a log, this delegate defers instead of painting nonsense.

    The same deference ``LogFilterModel.filterAcceptsRow`` shows, so neither breaks when put over
    something else.

    **Test steps:**

    * Build a plain string model.
    * Paint one of its indexes.
    * Assert the base implementation was handed the call, and nothing was tinted.
    """
    del qtbot  # only needed so a QApplication exists
    model = StringItemListModel()
    model.set_entries(["not a log row"])
    base = mocker.patch.object(QStyledItemDelegate, "paint")
    filled = mocker.patch.object(QPainter, "fillRect")
    image = QImage(CELL.size(), QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    delegate.paint(painter, option, model.index(0, 0))
    painter.end()
    base.assert_called_once()
    filled.assert_not_called()


# endregion


# region the size hint


def test_asks_for_a_fixed_width_for_the_level_column(
    delegate: LogLevelDelegate, option: QStyleOptionViewItem, model: LogModel
) -> None:
    """The level column asks for room for the longest level name and its serial, and no height of its own.

    **Test steps:**

    * Ask for the size hint.
    * Assert the width is the constant and the height is left to the message column.
    """
    hint = delegate.sizeHint(option, model.index(0, LEVEL_COLUMN))
    assert hint.width() == LEVEL_COLUMN_WIDTH_HINT
    assert hint.height() == 0


# endregion
