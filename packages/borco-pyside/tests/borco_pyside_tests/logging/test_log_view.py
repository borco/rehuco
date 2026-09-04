"""Tests for LogView."""

import logging

from borco_pyside.logging.log_entry import LogEntry
from borco_pyside.logging.log_filter_model import LogFilterModel
from borco_pyside.logging.log_level_band import LogLevelBand
from borco_pyside.logging.log_level_delegate import LogLevelDelegate
from borco_pyside.logging.log_message_delegate import LogMessageDelegate
from borco_pyside.logging.log_model import LEVEL_COLUMN, MESSAGE_COLUMN, LogModel
from borco_pyside.logging.log_view import COPY_COLUMN_SEPARATOR, LogView
from borco_pyside.widgets import StringItemListModel
from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtGui import QColor, QGuiApplication
from pytest import fixture
from pytestqt.qtbot import QtBot

VIEWPORT_HEIGHT = 60
"""Short enough that a few dozen wrapped rows overflow it, which is what gives the scrollbar a range
to be at the bottom of."""

ROW_COUNT = 60


# region helpers


def make_entry(serial: int, level: int = logging.INFO) -> LogEntry:
    """Build one entry the way the bridge would.

    :param serial: its position in the run, also used in the message so rows are told apart.
    :param level: the record's level.
    :returns: the entry.
    """
    message = f"record {serial}"
    record = logging.LogRecord("test", level, __file__, 1, message, None, None)
    return LogEntry(record, message, (), serial)


def fill(model: LogModel, count: int = ROW_COUNT) -> None:
    """Put enough rows in ``model`` that the view has to scroll.

    :param model: the model to fill.
    :param count: how many rows to add.
    """
    model.handle_log_records([make_entry(serial) for serial in range(count)])


# endregion


# region fixtures


@fixture
def model(qtbot: QtBot) -> LogModel:
    """Provide an empty model with room for every row these tests add.

    :param qtbot: pytest-qt bot, ensuring a QApplication exists.
    :returns: the model.
    """
    del qtbot  # only needed so a QApplication exists
    return LogModel(limit=1000)


@fixture
def view(qtbot: QtBot, model: LogModel) -> LogView:
    """Provide a shown view over that model, sized so its content overflows.

    :param qtbot: pytest-qt bot.
    :param model: the model to show.
    :returns: the view, shown and exposed.
    """
    log_view = LogView()
    log_view.setModel(model)
    qtbot.addWidget(log_view)
    log_view.resize(300, VIEWPORT_HEIGHT)
    log_view.show()
    qtbot.waitExposed(log_view)
    return log_view


# endregion


# region construction


def test_installs_a_delegate_per_column(view: LogView) -> None:
    """The level column is painted by the level delegate and the message column by the message one.

    **Test steps:**

    * Read the delegate installed for each column.
    * Assert each is the right class.
    """
    assert isinstance(view.itemDelegateForColumn(LEVEL_COLUMN), LogLevelDelegate)
    assert isinstance(view.itemDelegateForColumn(MESSAGE_COLUMN), LogMessageDelegate)


def test_band_colors_reach_the_level_delegate(view: LogView) -> None:
    """Tints set on the view are what its level delegate paints from.

    The view is where they are set because Designer constructs the promoted view with a parent and
    nothing else -- the tints cannot arrive through its constructor.

    **Test steps:**

    * Set a tint for the errors band on the view.
    * Assert the level delegate now has a tint for that band.
    """
    view.band_colors = {LogLevelBand.ERRORS: QColor("#C62828")}
    delegate = view.itemDelegateForColumn(LEVEL_COLUMN)
    assert isinstance(delegate, LogLevelDelegate)
    assert delegate.tint_for(LogLevelBand.ERRORS) is not None
    assert view.band_colors == delegate.band_colors


def test_replacing_the_model_stops_following_the_old_one(qtbot: QtBot, model: LogModel) -> None:
    """A view handed a second model no longer scrolls for rows arriving in the first.

    Without the disconnect, the abandoned model would still be able to scroll a view showing something
    else entirely.

    **Test steps:**

    * Show one model, then replace it with another.
    * Add a row to the abandoned model.
    * Assert the view still shows the second model, and did not scroll.
    """
    view = LogView()
    view.setModel(model)
    qtbot.addWidget(view)
    view.resize(300, VIEWPORT_HEIGHT)
    view.show()
    qtbot.waitExposed(view)

    replacement = LogModel(limit=1000)
    view.setModel(replacement)
    fill(model)
    qtbot.wait(10)

    assert view.model() is replacement
    assert view.verticalScrollBar().maximum() == 0


def test_detaching_the_model_leaves_the_view_showing_nothing(qtbot: QtBot, model: LogModel) -> None:
    """A view handed no model at all detaches cleanly rather than wiring up to nothing.

    **Test steps:**

    * show a model, then clear it.
    * Add rows to the abandoned model.
    * Assert the view has no model and nothing raised.
    """
    view = LogView()
    view.setModel(model)
    qtbot.addWidget(view)

    view.setModel(None)
    fill(model)
    qtbot.wait(10)

    assert view.model() is None


def test_finds_the_log_model_through_a_proxy(qtbot: QtBot, model: LogModel) -> None:
    """The view can name the model actually holding the entries, however many proxies are in between.

    **Test steps:**

    * Put the model behind a filter proxy and show it.
    * Assert the view reports the model, not the proxy.
    """
    proxy = LogFilterModel()
    proxy.setSourceModel(model)
    view = LogView()
    view.setModel(proxy)
    qtbot.addWidget(view)
    assert view.source_log_model() is model


def test_reports_no_log_model_over_something_else(qtbot: QtBot) -> None:
    """Over a model that is not a log, there is no log model to report.

    **Test steps:**

    * Show a plain string model.
    * Assert the view reports none.
    """
    model = StringItemListModel()
    view = LogView()
    view.setModel(model)
    qtbot.addWidget(view)
    assert view.source_log_model() is None


# endregion


# region following the tail


def test_starts_following(view: LogView) -> None:
    """A freshly built view follows, because a log opened during a job should show the job.

    **Test steps:**

    * Assert the view follows before anything is scrolled.
    """
    assert view.follow_tail


def test_a_new_row_scrolls_into_view_while_following(view: LogView, model: LogModel, qtbot: QtBot) -> None:
    """Records arriving during a job scroll into view, which is what the whole feature is for.

    **Test steps:**

    * Fill the model past the viewport.
    * Assert the view is at the bottom.
    """
    fill(model)
    qtbot.wait(10)
    assert view.at_tail()


def test_scrolling_up_stops_following(view: LogView, model: LogModel, qtbot: QtBot) -> None:
    """A reader who scrolls back to read something is not yanked to the bottom by the next record.

    **Test steps:**

    * Fill the model, then move the scrollbar off the bottom.
    * Assert following stopped.
    """
    fill(model)
    qtbot.wait(10)
    view.verticalScrollBar().setValue(0)
    assert not view.follow_tail


def test_a_new_row_does_not_scroll_while_not_following(view: LogView, model: LogModel, qtbot: QtBot) -> None:
    """Once the reader has scrolled away, arriving records leave the view where they left it.

    **Test steps:**

    * Fill the model and scroll to the top.
    * Add another record.
    * Assert the view is still at the top.
    """
    fill(model)
    qtbot.wait(10)
    view.verticalScrollBar().setValue(0)
    model.handle_log_records([make_entry(ROW_COUNT)])
    qtbot.wait(10)
    assert view.verticalScrollBar().value() == 0


def test_scrolling_back_to_the_bottom_resumes_following(view: LogView, model: LogModel, qtbot: QtBot) -> None:
    """Returning to the bottom is how a reader says "carry on" -- no button required.

    **Test steps:**

    * Fill the model, scroll to the top, then scroll back to the bottom.
    * Assert following resumed.
    """
    fill(model)
    qtbot.wait(10)
    scroll_bar = view.verticalScrollBar()
    scroll_bar.setValue(0)
    assert not view.follow_tail
    scroll_bar.setValue(scroll_bar.maximum())
    assert view.follow_tail


def test_turning_following_back_on_jumps_to_the_tail(view: LogView, model: LogModel, qtbot: QtBot) -> None:
    """A reader turning it on is asking to see the end of the log now, not at the next record.

    **Test steps:**

    * Fill the model and scroll to the top.
    * Set ``follow_tail``.
    * Assert the view is at the bottom.
    """
    fill(model)
    qtbot.wait(10)
    view.verticalScrollBar().setValue(0)
    view.follow_tail = True
    assert view.at_tail()


def test_reports_when_following_changes(view: LogView, model: LogModel, qtbot: QtBot) -> None:
    """The change is reported however it was decided, so a toolbar toggle can stay in step.

    **Test steps:**

    * Fill the model, then scroll away with the signal watched.
    * Assert it fired with ``False``.
    """
    fill(model)
    qtbot.wait(10)
    with qtbot.waitSignal(view.follow_tail_changed) as blocker:
        view.verticalScrollBar().setValue(0)
    assert blocker.args == [False]


def test_setting_following_to_what_it_already_is_reports_nothing(view: LogView, qtbot: QtBot) -> None:
    """A no-op setter is a no-op, so a two-way binding to a toolbar toggle cannot loop.

    **Test steps:**

    * Set ``follow_tail`` to its current value with the signal watched.
    * Assert nothing was emitted.
    """
    with qtbot.assertNotEmitted(view.follow_tail_changed):
        view.follow_tail = True


def test_resizing_re_measures_the_rows(view: LogView, model: LogModel, qtbot: QtBot) -> None:
    """A narrower column wraps onto more lines, so the rows are re-measured rather than left clipped.

    ``ResizeToContents`` alone does not re-ask on a viewport resize.

    **Test steps:**

    * Put one long message in the model and note its row height.
    * Halve the view's width.
    * Assert the row got taller.
    """
    long_message = " ".join(["a wordy message about a file that could not be read"] * 3)
    record = logging.LogRecord("test", logging.INFO, __file__, 1, long_message, None, None)
    model.handle_log_records([LogEntry(record, long_message, (), 0)])
    view.resize(400, VIEWPORT_HEIGHT)
    qtbot.wait(10)
    wide = view.rowHeight(0)

    view.resize(150, VIEWPORT_HEIGHT)
    qtbot.wait(10)

    assert view.rowHeight(0) > wide


def test_resizing_while_not_following_leaves_the_position_alone(view: LogView, model: LogModel, qtbot: QtBot) -> None:
    """A reader who scrolled back keeps their place when the window is resized.

    **Test steps:**

    * Fill the model and scroll to the top.
    * Resize the view.
    * Assert it is still at the top.
    """
    fill(model)
    qtbot.wait(10)
    view.verticalScrollBar().setValue(0)
    view.resize(250, VIEWPORT_HEIGHT)
    qtbot.wait(10)
    assert view.verticalScrollBar().value() == 0


def test_an_empty_log_counts_as_being_at_the_tail(view: LogView) -> None:
    """A log short enough to need no scrolling is at its own bottom, which is where the next record lands.

    **Test steps:**

    * Assert a view with nothing in it reports being at the tail.
    """
    assert view.at_tail()


# endregion


# region copying


def test_copies_the_selected_rows(view: LogView, model: LogModel) -> None:
    """A selected row is copied as its level and its message, tab-separated.

    **Test steps:**

    * Fill the model and select two rows.
    * Copy.
    * Assert the clipboard holds both rows, level then message.
    """
    fill(model, 3)
    view.selectRow(0)
    flags = QItemSelectionModel.SelectionFlag
    view.selectionModel().select(model.index(2, 0), flags.Select | flags.Rows)
    view.copy_selected()
    assert QGuiApplication.clipboard().text() == (
        f"INFO{COPY_COLUMN_SEPARATOR}record 0\nINFO{COPY_COLUMN_SEPARATOR}record 2"
    )


def test_copying_nothing_leaves_the_clipboard_alone(view: LogView, model: LogModel) -> None:
    """With no selection nothing is copied -- deliberately not "everything", which would silently
    replace a clipboard the reader filled elsewhere.

    **Test steps:**

    * Put known text on the clipboard.
    * Copy with nothing selected.
    * Assert the clipboard is untouched.
    """
    fill(model, 3)
    QGuiApplication.clipboard().setText("something the reader put there")
    view.copy_selected()
    assert QGuiApplication.clipboard().text() == "something the reader put there"


def test_the_copy_shortcut_copies_the_selection(view: LogView, model: LogModel, qtbot: QtBot) -> None:
    """The platform's copy shortcut works on the view itself, with no action for a host to add.

    **Test steps:**

    * Fill the model, select a row, and press the copy shortcut.
    * Assert the clipboard holds that row.
    """
    fill(model, 3)
    QGuiApplication.clipboard().clear()
    view.selectRow(1)
    qtbot.keyClick(view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert QGuiApplication.clipboard().text() == f"INFO{COPY_COLUMN_SEPARATOR}record 1"


def test_the_context_menu_offers_copy(view: LogView, model: LogModel) -> None:
    """Copying has a visible affordance -- a right-click menu -- not just a shortcut to know about.

    **Test steps:**

    * Assert the view's context menu is its own actions, and the copy action is among them.
    * Assert triggering that action copies the selection.
    """
    fill(model, 3)
    view.selectRow(1)
    QGuiApplication.clipboard().clear()

    assert view.contextMenuPolicy() == Qt.ContextMenuPolicy.ActionsContextMenu
    assert view.copy_action in view.actions()
    view.copy_action.trigger()
    assert QGuiApplication.clipboard().text() == f"INFO{COPY_COLUMN_SEPARATOR}record 1"


def test_another_key_is_left_to_the_base_view(view: LogView, model: LogModel, qtbot: QtBot) -> None:
    """Every other key still does what a table view does with it.

    **Test steps:**

    * Fill the model, select the first row, and press Down.
    * Assert the selection moved.
    """
    fill(model, 3)
    view.selectRow(0)
    qtbot.keyClick(view, Qt.Key.Key_Down)
    assert view.currentIndex().row() == 1


# endregion
