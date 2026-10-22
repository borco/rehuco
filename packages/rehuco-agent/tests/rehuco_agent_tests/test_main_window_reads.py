"""Tests for MainWindow's ``Open recents`` while a record opened is read off the GUI thread (#564): whether the open
read a file at all is known only once the record arrives, so the record joins the recents then.

Every read is held back (``held_reads``) and answered when the test says so; how a model takes a read is its own tests'
subject.
"""

from pathlib import Path

from borco_pyside.qtads import tab_label
from pytest import mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.main_window import MainWindow
from rehuco_core.access import ResourceKey

from rehuco_agent_tests.record_reads import HeldReads
from rehuco_agent_tests.test_main_window import (  # noqa: F401  # pylint: disable=unused-import
    mock_persistent_settings,
    preview_dock_of,
    serve_tutorials,
)

pytestmark = mark.usefixtures("stub_settings_pages", "stub_sub_docks")
"""Every window here is built over stub settings pages, and every document it opens over stub sub-docks (#545)."""


def recents_of(window: MainWindow) -> list[Path]:
    """The window's ``Open recents``, newest first.

    :param window: the main window.
    :returns: the entries.
    """
    return window._MainWindow__recent_files.newest_first()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def test_an_open_joins_recents_once_its_record_arrives(
    mocker: MockerFixture, qtbot: QtBot, held_reads: HeldReads
) -> None:
    """A record opened is in ``Open recents`` once its file has been read, not while the read is out.

    **Test steps:**

    * open a record, its read held
    * verify ``Open recents`` is empty
    * let the record arrive
    * verify it is the newest recent entry
    """
    window = MainWindow()
    qtbot.addWidget(window)
    serve_tutorials(mocker)
    path = Path("a", "info.rehu").resolve()

    window.open_file(path)

    assert recents_of(window) == []

    held_reads.answer(0)

    assert recents_of(window) == [path]


def test_a_preview_promoted_while_its_record_is_out_joins_recents_once_it_arrives(
    mocker: MockerFixture, qtbot: QtBot, held_reads: HeldReads
) -> None:
    """A preview kept before its record arrived is in ``Open recents`` once the record has arrived.

    **Test steps:**

    * show a record in the preview, its read held, and double-click the preview's title
    * verify ``Open recents`` is empty
    * let the record arrive
    * verify it is the newest recent entry
    """
    window = MainWindow()
    qtbot.addWidget(window)
    serve_tutorials(mocker)
    path = Path("a", "info.rehu").resolve()
    window.show_in_preview(path)

    tab_label(preview_dock_of(window)).doubleClicked.emit()

    assert recents_of(window) == []

    held_reads.answer(0)

    assert recents_of(window) == [path]


def test_a_promotion_of_a_record_nobody_holds_records_nothing(qtbot: QtBot) -> None:
    """A promotion naming a record no document holds any more has nothing to judge, and records nothing.

    **Test steps:**

    * emit ``preview_promoted`` with the key of a record nobody holds
    * verify ``Open recents`` stays empty
    """
    window = MainWindow()
    qtbot.addWidget(window)
    docs_dock = window._MainWindow__documents_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    docs_dock.preview_promoted.emit(ResourceKey(Path("a", "info.rehu").resolve()))

    assert recents_of(window) == []
