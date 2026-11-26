"""Tests for LogMessageDelegate."""

# The cell fixture and the paint-onto-an-image setup mirror test_log_level_delegate's -- the two
# delegates draw the two halves of the same row, so testing them takes the same rect and the same
# painter. Kept as a copy per module, the convention every settings test's own FakeSettings already
# follows here: a shared helper module would couple the two delegates' tests to each other, and each is
# free to change what it draws into.
# pylint: disable=duplicate-code

import logging

from borco_pyside.logging.log_entry import LogEntry
from borco_pyside.logging.log_link_span import LogLinkSpan
from borco_pyside.logging.log_message_delegate import LogMessageDelegate
from borco_pyside.logging.log_metrics import TEXT_HPADDING, TEXT_VPADDING
from borco_pyside.logging.log_model import MESSAGE_COLUMN, LogModel
from borco_pyside.widgets import StringItemListModel
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFontMetrics, QImage, QPainter, QPalette
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


def test_a_selected_row_is_drawn_in_the_highlight_colors(
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

    * Note the painter's pen color, paint a selected row, and note it again.
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


# region links

LINKED_MESSAGE = "Pack \N{EM DASH} https://store.example/pack: added"
"""A title, the address after it, and plain words around both."""

TITLE_LINK = LogLinkSpan(0, 4, "record")
URL_LINK = LogLinkSpan(7, 33, "page")


def make_linked_entry(message: str = LINKED_MESSAGE) -> LogEntry:
    """Build an entry with a title link and an address link.

    :param message: the formatted message; the two links sit at the start of the default.
    :returns: the entry.
    """
    record = logging.LogRecord("test", logging.INFO, __file__, 1, message, None, None)
    return LogEntry(record, message, (), 0, (TITLE_LINK, URL_LINK))


def linked_cell(delegate: LogMessageDelegate, entry: LogEntry, width: int = 400) -> tuple[QStyleOptionViewItem, object]:
    """A one-row model holding ``entry`` and an option over a cell of ``width``, as a view would paint it.

    :param delegate: the delegate, whose size hint gives the cell its height.
    :param entry: the entry.
    :param width: the cell's width.
    :returns: the option and the model, which the caller keeps alive.
    """
    model = LogModel()
    model.handle_log_records([entry])
    item = QStyleOptionViewItem()
    item.rect = QRect(0, 0, width, 20)
    item.rect.setHeight(delegate.sizeHint(item, model.index(0, MESSAGE_COLUMN)).height())
    return item, model


def test_a_row_without_links_is_measured_as_it_was(delegate: LogMessageDelegate, option: QStyleOptionViewItem) -> None:
    """The plain path is unchanged: a record with no links is still sized by the word-wrapped text.

    **Test steps:**

    * Measure a long message through the delegate.
    * Assert it is the font metrics' own wrapped height plus the padding.
    """
    model = LogModel()
    model.handle_log_records([make_entry(LONG_MESSAGE)])

    size = delegate.sizeHint(option, model.index(0, MESSAGE_COLUMN))

    wrapped = option.fontMetrics.boundingRect(delegate.text_rect(option), Qt.TextFlag.TextWordWrap, LONG_MESSAGE)
    assert size.height() == wrapped.height() + 2 * TEXT_VPADDING


def test_a_linked_row_wraps_and_grows_when_narrow(delegate: LogMessageDelegate) -> None:
    """A linked row is measured from its own layout: narrower means more lines, so taller.

    **Test steps:**

    * Measure the same linked record in a wide cell and in a narrow one.
    * Assert the narrow one is taller.
    """
    wide = QStyleOptionViewItem()
    wide.rect = QRect(0, 0, 600, 20)
    narrow = QStyleOptionViewItem()
    narrow.rect = QRect(0, 0, 90, 20)
    model = LogModel()
    model.handle_log_records([make_linked_entry()])
    index = model.index(0, MESSAGE_COLUMN)

    assert delegate.sizeHint(narrow, index).height() > delegate.sizeHint(wide, index).height()


def test_link_at_finds_the_link_under_a_point(delegate: LogMessageDelegate) -> None:
    """The title and the address each answer with their own target.

    **Test steps:**

    * Lay a linked row out in a wide cell.
    * Ask for the link at the title's first character and at the address's.
    * Assert each target, with a point on the plain words answering ``None``.
    """
    option, model = linked_cell(delegate, make_linked_entry())
    index = model.index(0, MESSAGE_COLUMN)  # type: ignore[attr-defined]
    metrics = QFontMetrics(option.font)
    y = TEXT_VPADDING + 3

    def at(characters: int) -> object:
        return delegate.link_at(
            option, index, QPoint(TEXT_HPADDING + metrics.horizontalAdvance(LINKED_MESSAGE[:characters]) + 2, y)
        )

    assert at(0) == "record"
    assert at(8) == "page"
    assert at(5) is None  # the dash between the two


def test_link_at_misses_outside_the_text(delegate: LogMessageDelegate) -> None:
    """Empty space past the last character, above the text or in a row without links is no link.

    **Test steps:**

    * Ask at a point far right of a short linked message, above the first line, and over a plain row.
    * Assert each answers ``None``.
    """
    option, model = linked_cell(delegate, make_linked_entry())
    index = model.index(0, MESSAGE_COLUMN)  # type: ignore[attr-defined]
    assert delegate.link_at(option, index, QPoint(option.rect.width() - 1, TEXT_VPADDING + 3)) is None
    assert delegate.link_at(option, index, QPoint(TEXT_HPADDING + 2, -5)) is None

    plain = LogModel()
    plain.handle_log_records([make_entry(SHORT_MESSAGE)])
    assert (
        delegate.link_at(option, plain.index(0, MESSAGE_COLUMN), QPoint(TEXT_HPADDING + 2, TEXT_VPADDING + 3)) is None
    )


def test_a_linked_row_paints_its_links_in_the_link_color(delegate: LogMessageDelegate) -> None:
    """The link is drawn in the palette's link color, and the plain text is not.

    **Test steps:**

    * Paint a linked row onto an image with a distinctive link color.
    * Assert pixels of that color are present.
    """
    option, model = linked_cell(delegate, make_linked_entry())
    link_color = QColor(200, 0, 200)
    palette = QPalette(option.palette)
    palette.setColor(QPalette.ColorRole.Link, link_color)
    option.palette = palette
    image = QImage(option.rect.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    delegate.paint(painter, option, model.index(0, MESSAGE_COLUMN))  # type: ignore[attr-defined]
    painter.end()

    colors = {image.pixelColor(x, y).rgb() for x in range(image.width()) for y in range(image.height())}
    assert link_color.rgb() in colors


# endregion


def test_a_linked_row_keeps_the_line_breaks_of_its_message(delegate: LogMessageDelegate) -> None:
    """A record with links and a traceback under its first line is laid out on as many lines as it has, and its link
    is still found where it is drawn.

    **Test steps:**

    * Measure a three-line message with a link on its last line, and a one-line message with a link.
    * Assert the first has three times the text height of the second.
    * Ask for the link in the middle of the third line, and assert its target.
    """
    message = "first line\nsecond line\nlink here"
    record = logging.LogRecord("test", logging.INFO, __file__, 1, message, None, None)
    option, model = linked_cell(delegate, LogEntry(record, message, (), 0, (LogLinkSpan(23, 27, "record"),)))
    short = logging.LogRecord("test", logging.INFO, __file__, 1, "link", None, None)
    one_line, _kept = linked_cell(delegate, LogEntry(short, "link", (), 0, (LogLinkSpan(0, 4, "record"),)))
    line_height = one_line.rect.height() - 2 * TEXT_VPADDING

    assert option.rect.height() - 2 * TEXT_VPADDING == 3 * line_height
    third_line = QPoint(TEXT_HPADDING + 2, TEXT_VPADDING + 2 * line_height + line_height // 2)
    index = model.index(0, MESSAGE_COLUMN)  # type: ignore[attr-defined]
    assert delegate.link_at(option, index, third_line) == "record"
