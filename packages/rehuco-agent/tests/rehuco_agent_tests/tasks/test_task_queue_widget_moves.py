"""Tests for the Tasks dock's entries on a move (#712): Show Rehu, Show Move Source and Show Move Destination at the
head of its menu, and Retry on a done row that is not clean.

A sibling of ``test_task_queue_widget.py``, which is past the size cap: its rig, fixtures and helpers are imported by
name. The jobs are ``create_autospec(MoveRecordJob)`` (the job's own tests are in rehuco-core), and the file browser is
patched where the widget looks it up.
"""

from pathlib import Path
from typing import Any, Final
from unittest.mock import MagicMock, create_autospec

from borco_pyside.file_browser import FILE_BROWSER_NAME
from PySide6.QtCore import QPoint
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.tasks import task_queue_widget as widget_module
from rehuco_agent.tasks.task_queue_widget import TaskQueueWidget
from rehuco_core import JobState, MoveRecordJob

from rehuco_agent_tests.tasks.test_task_queue_widget import (  # noqa: F401  # pylint: disable=unused-import
    SEPARATOR,
    SIGNAL_TIMEOUT_MS,
    Rig,
    fixture_queue,
    fixture_rig,
    fixture_widget,
    select_rows,
    ui_of,
)

ORIGIN: Final = Path("T:/Courses/Old/Intro/info.rehu")
LANDING: Final = Path("E:/Courses/Smith/Intro")
RECORD: Final = LANDING / "info.rehu"


def add_move(rig: Rig, dock: TaskQueueWidget, state: JobState = JobState.RUNNING, **places: Path | None) -> MagicMock:
    """Put a move's row in the queue, its job naming its places, and select it.

    :param rig: the rig.
    :param dock: the widget over the rig.
    :param state: the row's state.
    :param places: ``source``, ``origin`` or ``landing`` to name otherwise than the defaults.
    :returns: its job.
    """
    job = create_autospec(MoveRecordJob, instance=True)
    job.configure_mock(**({"source": RECORD, "origin": ORIGIN, "landing": LANDING} | places))
    serial = rig.add("move", state)
    rig.queue.job.side_effect = {serial: job}.get
    rig.settle()
    select_rows(dock, 0)
    return job


def menu_entries(dock: TaskQueueWidget, mocker: MockerFixture) -> list[Any]:
    """Open the context menu with ``QMenu`` patched, and read what it was given, in order.

    :param dock: the widget.
    :param mocker: pytest-mock fixture.
    :returns: each action, and :data:`SEPARATOR` for each separator.
    """
    menu = mocker.patch.object(widget_module, "QMenu").return_value
    dock._TaskQueueWidget__show_context_menu(QPoint(0, 0))  # type: ignore[attr-defined]  # pylint: disable=protected-access
    entries: list[Any] = []
    for made in menu.method_calls:
        if made[0] == "addActions":
            entries.extend(made.args[0])
        elif made[0] == "addAction":
            entries.append(made.args[0])
        elif made[0] == "addSeparator":
            entries.append(SEPARATOR)
    return entries


# region the menu


def test_a_move_s_menu_leads_with_its_three_places(widget: TaskQueueWidget, rig: Rig, mocker: MockerFixture) -> None:
    """Show Rehu, Show Move Source and Show Move Destination head a move's menu, behind their own separator.

    **Test steps:**

    * script a move and select it, and open the menu
    * verify the three entries come first, then a separator, then Pause, each entry enabled
    """
    add_move(rig, widget)
    ui: Any = ui_of(widget)

    entries = menu_entries(widget, mocker)

    assert entries[:5] == [
        ui.show_rehu_action,
        ui.show_source_action,
        ui.show_destination_action,
        SEPARATOR,
        ui.pause_action,
    ]
    assert all(action.isEnabled() for action in entries[:3])


def test_the_reveal_entries_name_the_file_browser(widget: TaskQueueWidget) -> None:
    """The two reveal entries say which program shows the place.

    **Test steps:**

    * read the two entries' text
    * verify each names this platform's file browser
    """
    ui: Any = ui_of(widget)

    assert ui.show_source_action.text() == f"Show Move Source in {FILE_BROWSER_NAME}"
    assert ui.show_destination_action.text() == f"Show Move Destination in {FILE_BROWSER_NAME}"


def test_a_place_a_move_cannot_name_is_offered_disabled(
    widget: TaskQueueWidget, rig: Rig, mocker: MockerFixture
) -> None:
    """A move that does not know a place says so by a disabled entry, not a missing one.

    **Test steps:**

    * script a move naming none of its places, select it, and open the menu
    * verify the three entries are there and disabled
    """
    add_move(rig, widget, source=None, origin=None, landing=None)
    ui: Any = ui_of(widget)

    entries = menu_entries(widget, mocker)

    assert entries[:3] == [ui.show_rehu_action, ui.show_source_action, ui.show_destination_action]
    assert not any(action.isEnabled() for action in entries[:3])


def test_a_row_that_is_no_move_has_no_place_entries(widget: TaskQueueWidget, rig: Rig, mocker: MockerFixture) -> None:
    """A job that is not a move has no places to show, so its menu starts with Pause as before.

    **Test steps:**

    * script a row with no move behind it, select it, and open the menu
    * verify the menu starts with Pause
    """
    rig.add("scan", JobState.RUNNING)
    rig.settle()
    select_rows(widget, 0)
    ui: Any = ui_of(widget)

    assert menu_entries(widget, mocker)[0] is ui.pause_action


# endregion


# region what each entry does


def test_show_rehu_asks_for_the_record_where_it_is_now(widget: TaskQueueWidget, rig: Rig, qtbot: QtBot) -> None:
    """Show Rehu hands the window the record the move is moving, as the job follows it.

    **Test steps:**

    * script a move and select it, and trigger Show Rehu
    * verify the request carries the job's source
    """
    add_move(rig, widget)
    ui: Any = ui_of(widget)

    with qtbot.waitSignal(widget.open_record_requested, timeout=SIGNAL_TIMEOUT_MS) as asked:
        ui.show_rehu_action.trigger()

    assert asked.args == [RECORD]


def test_show_source_reveals_the_origin(widget: TaskQueueWidget, rig: Rig, mocker: MockerFixture) -> None:
    """Show Move Source reveals where the record was.

    **Test steps:**

    * script a move and select it, and trigger Show Move Source
    * verify the file browser was asked for the origin, once
    """
    reveal = mocker.patch.object(widget_module, "reveal_in_file_browser", return_value=True)
    add_move(rig, widget)

    ui_of(widget).show_source_action.trigger()  # type: ignore[attr-defined]

    reveal.assert_called_once_with(ORIGIN)


def test_show_source_falls_back_to_the_folder_that_held_the_record(
    widget: TaskQueueWidget, rig: Rig, mocker: MockerFixture
) -> None:
    """Once the original is removed, its own folder is gone too: the folder that held it is shown instead.

    **Test steps:**

    * script a move, make the first reveal find nothing, and trigger Show Move Source
    * verify the folder holding the record's folder was revealed next
    """
    reveal = mocker.patch.object(widget_module, "reveal_in_file_browser", side_effect=[False, True])
    add_move(rig, widget, JobState.DONE)

    ui_of(widget).show_source_action.trigger()  # type: ignore[attr-defined]

    assert [made.args[0] for made in reveal.call_args_list] == [ORIGIN, ORIGIN.parent.parent]


def test_show_destination_reveals_the_landing(widget: TaskQueueWidget, rig: Rig, mocker: MockerFixture) -> None:
    """Show Move Destination reveals where the record goes, a finished move's included.

    **Test steps:**

    * script a finished move and select it, and trigger Show Move Destination
    * verify the file browser was asked for its landing
    """
    reveal = mocker.patch.object(widget_module, "reveal_in_file_browser", return_value=True)
    add_move(rig, widget, JobState.DONE)

    ui_of(widget).show_destination_action.trigger()  # type: ignore[attr-defined]

    reveal.assert_called_once_with(LANDING)


def test_an_entry_run_with_no_move_selected_does_nothing(
    widget: TaskQueueWidget, rig: Rig, mocker: MockerFixture
) -> None:
    """The selection may change between the menu and the click: with no move selected then, nothing is shown.

    **Test steps:**

    * script a row with no move behind it and select it
    * run each entry's handler
    * verify nothing was revealed or asked for
    """
    reveal = mocker.patch.object(widget_module, "reveal_in_file_browser")
    asked = mocker.Mock()
    widget.open_record_requested.connect(asked)
    rig.add("scan", JobState.RUNNING)
    rig.settle()
    select_rows(widget, 0)

    widget._TaskQueueWidget__show_rehu()  # type: ignore[attr-defined]  # pylint: disable=protected-access
    widget._TaskQueueWidget__show_source()  # type: ignore[attr-defined]  # pylint: disable=protected-access
    widget._TaskQueueWidget__show_destination()  # type: ignore[attr-defined]  # pylint: disable=protected-access

    reveal.assert_not_called()
    asked.assert_not_called()


# endregion


# region Retry


def test_retry_is_offered_on_a_done_row_that_is_not_clean_only(widget: TaskQueueWidget, rig: Rig) -> None:
    """A done row that left something to act on can be run again; one that finished well cannot (#712).

    **Test steps:**

    * script a done row and a done row that is not clean
    * select each and read Retry
    """
    rig.add("clean", JobState.DONE)
    rig.add("unclean", JobState.DONE, clean=False)
    rig.settle()
    ui: Any = ui_of(widget)

    select_rows(widget, 0)
    assert not ui.retry_action.isEnabled()
    select_rows(widget, 1)
    assert ui.retry_action.isEnabled()
    select_rows(widget, 0, 1)
    assert not ui.retry_action.isEnabled()


# endregion
