"""Tests for LogMessageDelegate."""

# The cell fixture and the paint-onto-an-image setup mirror test_log_level_delegate's -- the two
# delegates draw the two halves of the same row, so testing them takes the same rect and the same
# painter. Kept as a copy per module, the convention every settings test's own FakeSettings already
# follows here: a shared helper module would couple the two delegates' tests to each other, and each is
# free to change what it draws into.
# pylint: disable=duplicate-code

import logging

from borco_pyside.logging.log_entry import LogEntry
from borco_pyside.logging.log_message_delegate import LogMessageDelegate
from borco_pyside.logging.log_metrics import TEXT_HPADDING, TEXT_VPADDING
from borco_pyside.logging.log_model import MESSAGE_COLUMN, LogModel
from borco_pyside.widgets import StringItemListModel
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot

SHORT_MESSAGE = "saved"
LONG_MESSAGE = " ".join(["a rather wordy message about a file that could not be read"] * 4)
"""Long enough to wrap several times inside :data:`CELL`, so the reported height must exceed one line."""

CELL = QRect(0, 0, 200, 20)


# region helpers


def make_entry(message: str, serial: int = 0) -> LogEntry:
    """Build one entry the way the bridge would.

    :param message: the formatted message.
    :param serial: its position in the run.
    :returns: the entry.
    """
    record = logging.LogRecord("test", logging.INFO, __file__, 1, message, None, None)
    return LogEntry(record, message, (), serial)


# endregion


# region fixtures


@fixture
def delegate(qtbot: QtBot) -> LogMessageDelegate:
    """Provide the delegate.

    :param qtbot: pytest-qt bot, ensuring a QApplication exists.
    :returns: the delegate.
    """
    del qtbot  # only needed so a QApplication exists
    return LogMessageDelegate()


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
    """Provide a model holding a short message and a long one.

    :param qtbot: pytest-qt bot, ensuring a QApplication exists.
    :returns: the model.
    """
    del qtbot  # only needed so a QApplication exists
    log_model = LogModel()
    log_model.handle_log_records([make_entry(SHORT_MESSAGE, 0), make_entry(LONG_MESSAGE, 1)])
    return log_model


# endregion


# region painting


def test_draws_the_formatted_message(
    delegate: LogMessageDelegate, option: QStyleOptionViewItem, model: LogModel, mocker: MockerFixture
) -> None:
    """The cell shows the message the bridge formatted, not the record's raw template.

    **Test steps:**

    * Record what text is drawn for the short row.
    * Assert it is the formatted message.
    """
    drawn = mocker.patch.object(QPainter, "drawText")
    image = QImage(CELL.size(), QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    delegate.paint(painter, option, model.index(0, MESSAGE_COLUMN))
    painter.end()
    assert SHORT_MESSAGE in [call.args[-1] for call in drawn.call_args_list]


def test_draws_into_the_padded_rect(
    delegate: LogMessageDelegate, option: QStyleOptionViewItem, model: LogModel, mocker: MockerFixture
) -> None:
    """The text is inset by the shared padding -- the same rect the size hint measures against.

    Painting and measuring against different rects is how a wrapped last line gets clipped: the height
    would be computed for a wider text than the one actually laid out.

    **Test steps:**

    * Record the rect the text is drawn into.
    * Assert it is the cell inset by the shared padding.
    """
    drawn = mocker.patch.object(QPainter, "drawText")
    image = QImage(CELL.size(), QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    delegate.paint(painter, option, model.index(0, MESSAGE_COLUMN))
    painter.end()
    assert drawn.call_args.args[0] == CELL.adjusted(TEXT_HPADDING, TEXT_VPADDING, -TEXT_HPADDING, -TEXT_VPADDING)


def test_a_selected_row_is_drawn_in_the_highlight_colours(
    delegate: LogMessageDelegate, option: QStyleOptionViewItem, model: LogModel, mocker: MockerFixture
) -> None:
    """A selected row gets the palette's highlight behind it and its highlighted-text pen.

    **Test steps:**

    * Paint the short row with the selected state set.
    * Assert the highlight brush was filled over the whole cell.
    """
    option.state |= QStyle.StateFlag.State_Selected
    filled = mocker.patch.object(QPainter, "fillRect")
    image = QImage(CELL.size(), QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    delegate.paint(painter, option, model.index(0, MESSAGE_COLUMN))
    painter.end()
    filled.assert_called_once_with(CELL, option.palette.highlight())


def test_leaves_the_painter_as_it_found_it(
    delegate: LogMessageDelegate, option: QStyleOptionViewItem, model: LogModel
) -> None:
    """The painter Qt handed over is saved and restored, not replaced by a second one on its device.

    A second painter is not clipped to the item, does not inherit the view's font, and leaves whatever
    it changed behind for the next cell.

    **Test steps:**

    * Note the painter's pen colour, paint a selected row, and note it again.
    * Assert the pen came back unchanged.
    """
    option.state |= QStyle.StateFlag.State_Selected
    image = QImage(CELL.size(), QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    before = painter.pen().color().rgb()
    delegate.paint(painter, option, model.index(0, MESSAGE_COLUMN))
    after = painter.pen().color().rgb()
    painter.end()
    assert after == before


def test_a_row_that_is_not_a_log_entry_is_left_to_the_base_delegate(
    delegate: LogMessageDelegate, option: QStyleOptionViewItem, mocker: MockerFixture, qtbot: QtBot
) -> None:
    """Over a model that is not a log, this delegate defers instead of drawing nothing.

    **Test steps:**

    * Build a plain string model.
    * Paint one of its indexes.
    * Assert the base implementation was handed the call.
    """
    del qtbot  # only needed so a QApplication exists
    model = StringItemListModel()
    model.set_entries(["not a log row"])
    base = mocker.patch.object(QStyledItemDelegate, "paint")
    image = QImage(CELL.size(), QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    delegate.paint(painter, option, model.index(0, 0))
    painter.end()
    base.assert_called_once()


# endregion


# region the size hint


def test_a_wrapped_message_reports_more_than_one_lines_height(
    delegate: LogMessageDelegate, option: QStyleOptionViewItem, model: LogModel
) -> None:
    """A message too long for the column asks for the height its wrapping actually needs.

    Which is the whole point of reporting a height at all: the view resizes rows to it, so a message
    is read in full instead of elided.

    **Test steps:**

    * Ask for both rows' size hints.
    * Assert the long one is taller than the short one, and than the cell itself.
    """
    short = delegate.sizeHint(option, model.index(0, MESSAGE_COLUMN))
    long = delegate.sizeHint(option, model.index(1, MESSAGE_COLUMN))
    assert long.height() > short.height()
    assert long.height() > CELL.height()


def test_the_reported_size_includes_the_padding(
    delegate: LogMessageDelegate, option: QStyleOptionViewItem, model: LogModel
) -> None:
    """The height asked for leaves room for the inset the text is drawn with.

    **Test steps:**

    * Measure the short message's wrap in the padded rect directly.
    * Assert the hint is that plus the padding on both sides.
    """
    text_rect = delegate.text_rect(option)
    wrapped = option.fontMetrics.boundingRect(text_rect, Qt.TextFlag.TextWordWrap, SHORT_MESSAGE)
    hint = delegate.sizeHint(option, model.index(0, MESSAGE_COLUMN))
    assert hint.height() == wrapped.height() + 2 * TEXT_VPADDING
    assert hint.width() == wrapped.width() + 2 * TEXT_HPADDING


def test_a_column_with_no_width_yet_falls_back_to_the_base_hint(delegate: LogMessageDelegate, model: LogModel) -> None:
    """A cell narrower than its own padding is not measured -- it would report an absurd height.

    The first layout pass hands out zero-width rects; wrapping against one makes the text break at
    every character, and the row would be asked to be hundreds of pixels tall.

    **Test steps:**

    * Ask for a size hint with a cell no wider than the padding.
    * Assert it is the base delegate's answer, not a wrapped measurement.
    """
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, TEXT_HPADDING, 20)
    hint = delegate.sizeHint(option, model.index(1, MESSAGE_COLUMN))
    assert hint == QStyledItemDelegate.sizeHint(delegate, option, model.index(1, MESSAGE_COLUMN))


def test_a_row_that_is_not_a_log_entry_falls_back_to_the_base_hint(
    delegate: LogMessageDelegate, option: QStyleOptionViewItem, qtbot: QtBot
) -> None:
    """A non-log row is measured by the base delegate, which knows how to size a plain string.

    **Test steps:**

    * Ask for the size hint over a plain string model.
    * Assert it matches the base implementation's.
    """
    del qtbot  # only needed so a QApplication exists
    model = StringItemListModel()
    model.set_entries(["not a log row"])
    index = model.index(0, 0)
    assert delegate.sizeHint(option, index) == QStyledItemDelegate.sizeHint(delegate, option, index)


# endregion
