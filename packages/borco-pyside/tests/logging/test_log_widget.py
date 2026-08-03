"""Tests for LogWidget."""

# The bridge/logger fixtures mirror test_log_bridge's and the one-record-per-band table mirrors
# test_log_filter_model's: a widget over the whole stack needs the same isolated logger and the same
# spread of levels. Kept as a copy per module, the convention every settings test's own FakeSettings
# already follows here.
# pylint: disable=duplicate-code

import logging
from collections.abc import Iterator
from typing import Any

import cbor2
from borco_pyside.logging.log_bridge import DEFAULT_LOG_LIMIT, LogBridge
from borco_pyside.logging.log_entry import LogEntry
from borco_pyside.logging.log_level_band import LogLevelBand
from borco_pyside.logging.log_level_delegate import LogLevelDelegate
from borco_pyside.logging.log_model import LEVEL_COLUMN, MESSAGE_COLUMN
from borco_pyside.logging.log_record_sink import LogRecordSink
from borco_pyside.logging.log_widget import (
    STATE_FOLLOW_TAIL_KEY,
    STATE_SEARCH_KEY,
    STATE_SHOW_DEBUGS_KEY,
    STATE_SHOW_ERRORS_KEY,
    STATE_SHOW_INFOS_KEY,
    STATE_SHOW_WARNINGS_KEY,
    LogWidget,
    LogWidgetIcons,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QToolBar
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot

LEVELS = (
    (logging.DEBUG, "a debug note"),
    (logging.INFO, "an info note"),
    (logging.WARNING, "a warning"),
    (logging.ERROR, "an error"),
)
"""One record per band, so each toggle has exactly one row to hide."""

BAND_COLORS = {LogLevelBand.WARNINGS: QColor("#F4511E"), LogLevelBand.ERRORS: QColor("#C62828")}


# region helpers


def make_entry(level: int, message: str, serial: int) -> LogEntry:
    """Build one entry the way the bridge would.

    :param level: the record's level.
    :param message: the formatted message.
    :param serial: its position in the run.
    :returns: the entry.
    """
    record = logging.LogRecord("test", level, __file__, 1, message, None, None)
    return LogEntry(record, message, None, serial)


def fill(widget: LogWidget) -> None:
    """Give ``widget`` one record per band.

    :param widget: the widget to fill.
    """
    widget.handle_log_records([make_entry(level, message, serial) for serial, (level, message) in enumerate(LEVELS)])


def ui(widget: LogWidget) -> Any:
    """Reach ``widget``'s generated UI object, where its actions and its search box live.

    :param widget: the widget to read.
    :returns: the UI object.
    """
    return widget._LogWidget__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access


def visible_messages(widget: LogWidget) -> list[str]:
    """Read what the widget's view is currently showing, top to bottom.

    Read off the **view's** model rather than the widget's, so it is the filtered rows -- which is
    what a reader sees, and the only thing a filtering test can honestly assert on.

    :param widget: the widget to read.
    :returns: the visible messages.
    """
    model = ui(widget).log_view.model()
    return [model.data(model.index(row, MESSAGE_COLUMN)) for row in range(model.rowCount())]


# endregion


# region fixtures


@fixture
def widget(qtbot: QtBot) -> LogWidget:
    """Provide a widget with two bands colored, added to the bot.

    :param qtbot: pytest-qt bot.
    :returns: the widget.
    """
    log_widget = LogWidget(band_colors=BAND_COLORS)
    qtbot.addWidget(log_widget)
    return log_widget


@fixture
def bridge() -> Iterator[LogBridge]:
    """Provide a bridge with a bare formatter, closed on teardown.

    :returns: the bridge.
    """
    log_bridge = LogBridge()
    log_bridge.setFormatter(logging.Formatter("%(message)s"))
    yield log_bridge
    log_bridge.close()


@fixture
def log(bridge: LogBridge) -> Iterator[logging.Logger]:
    """Provide an isolated logger feeding that bridge and nothing else.

    :param bridge: the handler to attach.
    :returns: the logger.
    """
    logger = logging.getLogger("borco_pyside.tests.log_widget")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.addHandler(bridge)
    yield logger
    logger.removeHandler(bridge)


@fixture
def deliver(qtbot: QtBot) -> Any:
    """Provide a way to let the bridge's queued dispatch run.

    :param qtbot: pytest-qt bot.
    :returns: a callable that turns the event loop.
    """
    return lambda: qtbot.wait(10)


# endregion


# region construction


def test_the_view_shows_the_widgets_own_model_through_a_filter(widget: LogWidget) -> None:
    """The view reads a proxy, and behind it the widget's own history.

    **Test steps:**

    * Assert the view's model is not the widget's model.
    * Assert the log model behind it is.
    """
    view = ui(widget).log_view
    assert view.model() is not widget.model
    assert view.source_log_model() is widget.model


def test_builds_a_toolbar_holding_every_action(widget: LogWidget) -> None:
    """The controls are on a toolbar, which the ``.ui`` cannot host but Designer can still author.

    **Test steps:**

    * Find the toolbar.
    * Assert every declared action is on it.
    """
    toolbar = widget.findChild(QToolBar)
    assert toolbar is not None
    actions = set(toolbar.actions())
    for action in (
        ui(widget).clear_action,
        ui(widget).show_debugs_action,
        ui(widget).show_infos_action,
        ui(widget).show_warnings_action,
        ui(widget).show_errors_action,
        ui(widget).follow_tail_action,
    ):
        assert action in actions


def test_band_colors_reach_the_level_delegate(widget: LogWidget) -> None:
    """The tints passed in are what the level column paints from.

    **Test steps:**

    * Read the level column's delegate.
    * Assert it tints the bands that were passed and not the ones that were not.
    """
    delegate = ui(widget).log_view.itemDelegateForColumn(LEVEL_COLUMN)
    assert isinstance(delegate, LogLevelDelegate)
    assert delegate.tint_for(LogLevelBand.ERRORS) is not None
    assert delegate.tint_for(LogLevelBand.DEBUGS) is None


def test_starts_with_every_band_shown(widget: LogWidget) -> None:
    """All four toggles start on, so a reader's first look at a log is the whole log.

    **Test steps:**

    * Fill the widget with one record per band.
    * Assert every one is visible.
    """
    fill(widget)
    assert len(visible_messages(widget)) == len(LEVELS)


def test_actions_given_no_icon_keep_their_text_alone(widget: LogWidget) -> None:
    """A widget built without icons still runs -- a labelled toolbar is a working toolbar.

    Which is why every :class:`LogWidgetIcons` field defaults to empty: adopting this widget must not
    require drawing six SVGs first.

    **Test steps:**

    * Assert no action carries an icon when none was named.
    * Assert the actions still carry the text the ``.ui`` gave them.
    """
    assert ui(widget).show_debugs_action.icon().isNull()
    assert ui(widget).clear_action.icon().isNull()
    assert ui(widget).clear_action.text() == "Clear"


def test_each_named_icon_is_themed_onto_its_own_action(qtbot: QtBot, mocker: MockerFixture) -> None:
    """An icon that *is* named is handed to the theming handler, so it follows a theme switch.

    The handler is mocked rather than given real SVGs: what this widget is responsible for is pairing
    each action with the caller's icon, and the recoloring itself is the handler's own tested job.

    **Test steps:**

    * Build a widget naming a different path per control.
    * Assert one handler was built per control, each with that control's path.
    """
    handler = mocker.patch("borco_pyside.logging.log_widget.ActionIconThemeHandler")
    icons = LogWidgetIcons(
        clear="clear.svg",
        follow_tail="follow.svg",
        debugs="debugs.svg",
        infos="infos.svg",
        warnings="warnings.svg",
        errors="errors.svg",
    )

    widget = LogWidget(icons=icons)
    qtbot.addWidget(widget)

    themed = {call.args[0]: call.args[1] for call in handler.call_args_list}
    assert themed == {
        ui(widget).clear_action: "clear.svg",
        ui(widget).follow_tail_action: "follow.svg",
        ui(widget).show_debugs_action: "debugs.svg",
        ui(widget).show_infos_action: "infos.svg",
        ui(widget).show_warnings_action: "warnings.svg",
        ui(widget).show_errors_action: "errors.svg",
    }


def test_is_a_log_record_sink(widget: LogWidget) -> None:
    """It satisfies the sink protocol structurally, so a bridge can be handed it directly.

    **Test steps:**

    * Assert the widget is a `LogRecordSink`.
    """
    assert isinstance(widget, LogRecordSink)


# endregion


# region filtering hides, and never discards


@mark.parametrize(
    ("action_name", "hidden"),
    [
        ("show_debugs_action", "a debug note"),
        ("show_infos_action", "an info note"),
        ("show_warnings_action", "a warning"),
        ("show_errors_action", "an error"),
    ],
)
def test_a_band_toggle_hides_only_its_own_band(widget: LogWidget, action_name: str, hidden: str) -> None:
    """Each toggle is independent: turning one off leaves the other three showing.

    A threshold cannot express this -- asking for debugs under one would drag in everything above them,
    which during a loud job is the noise the reader was trying to get out of the way.

    **Test steps:**

    * Fill the widget and turn one band off.
    * Assert that band's record is gone and every other is still there.
    """
    fill(widget)
    getattr(ui(widget), action_name).setChecked(False)
    visible = visible_messages(widget)
    assert hidden not in visible
    assert len(visible) == len(LEVELS) - 1


def test_hiding_a_band_keeps_its_records_in_the_history(widget: LogWidget) -> None:
    """Filtering hides; it never discards -- so widening again brings everything back.

    **Test steps:**

    * Fill the widget and hide the debugs.
    * Assert the model still holds every row.
    * Show them again and assert the view does too.
    """
    fill(widget)
    ui(widget).show_debugs_action.setChecked(False)
    assert widget.model.rowCount() == len(LEVELS)
    ui(widget).show_debugs_action.setChecked(True)
    assert len(visible_messages(widget)) == len(LEVELS)


def test_turning_every_band_off_shows_nothing(widget: LogWidget) -> None:
    """Nothing shown is a state the reader chose, not one to be quietly corrected back.

    **Test steps:**

    * Fill the widget and turn all four toggles off.
    * Assert the view is empty and the history is not.
    """
    fill(widget)
    for name in ("show_debugs_action", "show_infos_action", "show_warnings_action", "show_errors_action"):
        getattr(ui(widget), name).setChecked(False)
    assert visible_messages(widget) == []
    assert widget.model.rowCount() == len(LEVELS)


def test_searching_narrows_to_matching_messages(widget: LogWidget) -> None:
    """The search box narrows by message text, case-insensitively.

    **Test steps:**

    * Fill the widget and type part of one message in a different case.
    * Assert only that record is shown, and the history is untouched.
    """
    fill(widget)
    ui(widget).search_edit.setText("WARN")
    assert visible_messages(widget) == ["a warning"]
    assert widget.model.rowCount() == len(LEVELS)


def test_clearing_the_search_widens_again(widget: LogWidget) -> None:
    """Emptying the box stops searching rather than matching the empty string against nothing.

    **Test steps:**

    * Fill the widget, search, then clear the box.
    * Assert everything is shown again.
    """
    fill(widget)
    ui(widget).search_edit.setText("warning")
    ui(widget).search_edit.setText("")
    assert len(visible_messages(widget)) == len(LEVELS)


# endregion


# region clearing


def test_clear_empties_this_surface(widget: LogWidget) -> None:
    """Clear empties the history this widget holds.

    **Test steps:**

    * Fill the widget and trigger its clear action.
    * Assert nothing is left.
    """
    fill(widget)
    ui(widget).clear_action.trigger()
    assert widget.model.rowCount() == 0


def test_clearing_one_surface_leaves_another_and_the_replay_alone(
    widget: LogWidget, bridge: LogBridge, log: logging.Logger, deliver: Any, qtbot: QtBot
) -> None:
    """Emptying one view says nothing about any other, nor about what a later attach replays.

    This is the departure from the prior art worth protecting: it wired its single view's ``cleared``
    signal back to the bridge's cache, so emptying the view erased the replay -- which with several
    surfaces would mean emptying one resource's log threw away another's history.

    **Test steps:**

    * Attach two widgets to one bridge and log a record.
    * Clear the first.
    * Assert the second still holds it, and a third attached afterwards is still replayed it.
    """
    other = LogWidget()
    qtbot.addWidget(other)
    widget.attach_to(bridge)
    other.attach_to(bridge)
    log.info("something worth keeping")
    deliver()

    widget.clear()

    assert widget.model.rowCount() == 0
    assert other.model.rowCount() == 1
    late = LogWidget()
    qtbot.addWidget(late)
    late.attach_to(bridge)
    assert late.model.rowCount() == 1


# endregion


# region following the tail


def test_the_toggle_drives_the_view(widget: LogWidget) -> None:
    """Turning the toolbar toggle off stops the view following.

    **Test steps:**

    * Turn the follow toggle off.
    * Assert the view is no longer following.
    """
    ui(widget).follow_tail_action.setChecked(False)
    assert not ui(widget).log_view.follow_tail


def test_the_view_drives_the_toggle_back(widget: LogWidget) -> None:
    """The view decides to stop following when the reader scrolls away, and the button follows suit.

    A button claiming to follow while the view does not is worse than no button.

    **Test steps:**

    * Have the view stop following.
    * Assert the toolbar toggle went off with it.
    """
    ui(widget).log_view.follow_tail = False
    assert not ui(widget).follow_tail_action.isChecked()


# endregion


# region the limit


def test_the_limit_is_the_models(widget: LogWidget) -> None:
    """The widget's limit is its history's limit -- there is no second cap in between.

    **Test steps:**

    * Set the widget's limit.
    * Assert the model's changed with it.
    """
    widget.limit = 7
    assert widget.model.limit == 7
    assert widget.limit == 7


def test_the_limit_can_be_taken_off(widget: LogWidget) -> None:
    """No limit is a value the widget forwards like any other, not one it has to interpret.

    **Test steps:**

    * Take the widget's limit off.
    * Assert the model's went with it.
    """
    widget.limit = None
    assert widget.model.limit is None
    assert widget.limit is None


def test_a_widget_with_no_limit_keeps_everything(qtbot: QtBot) -> None:
    """A surface asked to keep everything holds a run longer than the default cap.

    **Test steps:**

    * Build a widget with no limit and give it more than the default one's worth of records.
    * Assert every record is a row.
    """
    widget = LogWidget(limit=None)
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    count = DEFAULT_LOG_LIMIT + 1

    widget.handle_log_records([make_entry(logging.INFO, f"note {serial}", serial) for serial in range(count)])

    assert widget.model.rowCount() == count


def test_lowering_the_limit_trims_now(widget: LogWidget) -> None:
    """A limit lowered in a settings dialog reaches an open view, not the next restart.

    **Test steps:**

    * Fill the widget and lower its limit below what it holds.
    * Assert it holds only that many.
    """
    fill(widget)
    widget.limit = 2
    assert widget.model.rowCount() == 2


# endregion


# region attaching


def test_attaching_replays_what_was_logged_first(widget: LogWidget, bridge: LogBridge, log: logging.Logger) -> None:
    """Records logged before this surface existed are handed to it on attach.

    Which is the whole reason the bridge caches: startup, the settings read and an early failure all
    happen before there is anything to show them.

    **Test steps:**

    * Log two records, then attach.
    * Assert both are in the widget's history, in order.
    """
    log.info("logged first")
    log.warning("logged second")
    widget.attach_to(bridge)
    assert visible_messages(widget) == ["logged first", "logged second"]


def test_a_scoped_attach_sees_only_that_scopes_records(
    widget: LogWidget, bridge: LogBridge, log: logging.Logger, deliver: Any
) -> None:
    """A surface attached for one scope is the log of that thing, and of nothing else.

    **Test steps:**

    * Attach for one scope.
    * Log a record under it, one under another, and one unscoped.
    * Assert only the first arrived.
    """
    widget.attach_to(bridge, scope="a-resource")
    log.info("about this one", extra={"log_scope": "a-resource"})
    log.info("about another", extra={"log_scope": "another-resource"})
    log.info("about nothing in particular")
    deliver()
    assert visible_messages(widget) == ["about this one"]


def test_detaching_keeps_the_rows_already_shown(
    widget: LogWidget, bridge: LogBridge, log: logging.Logger, deliver: Any
) -> None:
    """A re-scope is a detach and a re-attach; the history stays, because the thing was renamed.

    **Test steps:**

    * Attach, log, then detach.
    * Log again.
    * Assert the first record is still shown and the second never arrived.
    """
    widget.attach_to(bridge)
    log.info("before the detach")
    deliver()
    widget.detach_from(bridge)
    log.info("after the detach")
    deliver()
    assert visible_messages(widget) == ["before the detach"]


def test_a_destroyed_surface_detaches_itself(
    widget: LogWidget, bridge: LogBridge, log: logging.Logger, deliver: Any, qtbot: QtBot
) -> None:
    """A closed document's surface cannot leave the bridge dispatching into a deleted object.

    A per-resource surface lives as long as its document while the bridge lives for the whole run, so
    the detach has to happen without anyone remembering to ask for it.

    **Test steps:**

    * Attach two surfaces to one bridge, then destroy one.
    * Log a record and let the dispatch run.
    * Assert the surviving surface got it, and nothing raised delivering to the dead one.
    """
    widget.attach_to(bridge)
    doomed = LogWidget()
    doomed.attach_to(bridge)
    with qtbot.waitSignal(doomed.model.destroyed):
        doomed.deleteLater()

    log.info("logged after one surface went away")
    deliver()

    assert visible_messages(widget) == ["logged after one surface went away"]


# endregion


# region saving and restoring the reader's choices


def test_saves_every_choice(widget: LogWidget) -> None:
    """The blob holds the four bands, the follow toggle and the search text -- and no entries.

    What is saved is the reader's *view* of the log, not the log: a restored surface starts from the
    bridge's replay under the filters it was left with.

    **Test steps:**

    * Set every control to a non-default.
    * Assert the decoded blob carries each of them.
    """
    ui(widget).show_debugs_action.setChecked(False)
    ui(widget).show_infos_action.setChecked(False)
    ui(widget).show_warnings_action.setChecked(False)
    ui(widget).show_errors_action.setChecked(False)
    ui(widget).follow_tail_action.setChecked(False)
    ui(widget).search_edit.setText("a search")
    values = cbor2.loads(widget.save_state())
    assert values == {
        STATE_SHOW_DEBUGS_KEY: False,
        STATE_SHOW_INFOS_KEY: False,
        STATE_SHOW_WARNINGS_KEY: False,
        STATE_SHOW_ERRORS_KEY: False,
        STATE_FOLLOW_TAIL_KEY: False,
        STATE_SEARCH_KEY: "a search",
    }


def test_restores_every_choice(widget: LogWidget, qtbot: QtBot) -> None:
    """A restored surface comes back under the filters it was left with.

    **Test steps:**

    * Save a widget with non-default choices.
    * Restore them into a fresh one.
    * Assert each came back, and that the filter is really applied.
    """
    ui(widget).show_debugs_action.setChecked(False)
    ui(widget).search_edit.setText("warning")
    state = widget.save_state()

    restored = LogWidget()
    qtbot.addWidget(restored)
    restored.restore_state(state)
    fill(restored)

    assert not ui(restored).show_debugs_action.isChecked()
    assert ui(restored).search_edit.text() == "warning"
    assert visible_messages(restored) == ["a warning"]


def test_a_truncated_blob_changes_nothing(widget: LogWidget) -> None:
    """A blob that cannot be decoded at all leaves every control as it was.

    **Test steps:**

    * Restore from a cbor map header with nothing after it.
    * Assert the defaults are intact.
    """
    widget.restore_state(b"\xa1")
    assert ui(widget).show_debugs_action.isChecked()
    assert ui(widget).search_edit.text() == ""


def test_a_blob_that_is_not_cbor_changes_nothing(widget: LogWidget) -> None:
    """Junk that happens to decode to something is still not a state to apply.

    **Test steps:**

    * Restore from arbitrary bytes.
    * Assert the defaults are intact.
    """
    widget.restore_state(b"not cbor at all")
    assert ui(widget).show_debugs_action.isChecked()
    assert ui(widget).search_edit.text() == ""


def test_a_blob_of_the_wrong_shape_changes_nothing(widget: LogWidget) -> None:
    """A blob decoding to something that is not a mapping is ignored rather than indexed into.

    **Test steps:**

    * Restore from a cbor list.
    * Assert the defaults are intact.
    """
    widget.restore_state(cbor2.dumps(["not", "a", "mapping"]))
    assert ui(widget).show_debugs_action.isChecked()


def test_a_missing_key_keeps_its_current_value(widget: LogWidget) -> None:
    """Each key is independent, so a blob written before one existed still answers about the others.

    **Test steps:**

    * Restore a blob naming the debugs toggle alone.
    * Assert it was applied and nothing else moved.
    """
    widget.restore_state(cbor2.dumps({STATE_SHOW_DEBUGS_KEY: False}))
    assert not ui(widget).show_debugs_action.isChecked()
    assert ui(widget).show_errors_action.isChecked()
    assert ui(widget).follow_tail_action.isChecked()


def test_a_key_of_the_wrong_type_is_ignored(widget: LogWidget) -> None:
    """A stored value of the wrong type is not coerced into a choice the reader never made.

    **Test steps:**

    * Restore a blob whose toggle value is a string.
    * Assert the toggle is untouched.
    """
    widget.restore_state(cbor2.dumps({STATE_SHOW_DEBUGS_KEY: "no", STATE_SEARCH_KEY: 7}))
    assert ui(widget).show_debugs_action.isChecked()
    assert ui(widget).search_edit.text() == ""


# endregion
