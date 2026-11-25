"""Tests for what the main window does about a root's buckets (#681): ``Tools`` > ``Balance Buckets...`` and the Roots
view's entry ask the same dialog and queue what it answers, and the app's host knows the queue its moves are on."""

from pathlib import Path
from typing import override
from unittest.mock import Mock
from uuid import UUID, uuid4

from PySide6.QtCore import QSettings
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.dialogs.balance_buckets_dialog import BalanceBucketsDialog
from rehuco_agent.documents.main_thread_move_host import MainThreadMoveHost
from rehuco_agent.main_window import MainWindow
from rehuco_agent.rehuco import RootCatalog
from rehuco_agent.settings.move_settings import shared_move_settings
from rehuco_core import MappedRoot

from .test_main_window import mock_persistent_settings  # noqa: F401  # pylint: disable=unused-import

pytestmark = mark.usefixtures("stub_settings_pages", "stub_sub_docks")
"""Every window here is built over stub settings pages, and every document it opens over stub sub-docks (#545)."""


class AnsweringDialog(BalanceBucketsDialog):
    """The dialog with the user's answer built in, in place of showing it."""

    accepts = True
    """Whether the user presses Start rather than Cancel."""

    @override
    def exec(self) -> int:
        """Answer at once, with what it opened with."""
        return self.DialogCode.Accepted if self.accepts else self.DialogCode.Rejected


class CancelingDialog(AnsweringDialog):
    """The dialog the user cancels."""

    accepts = False


@fixture(name="roots")
def fixture_roots(mocker: MockerFixture, tmp_path: Path) -> tuple[MappedRoot, ...]:
    """The open catalog's roots: two whose layouts have buckets.

    :param mocker: pytest-mock fixture.
    :param tmp_path: pytest fixture.
    :returns: the roots.
    """
    layouts = {"asset": ("{site}/{buckets}/{site_id}",)}
    roots = tuple(MappedRoot(uuid4(), name, f"//nas/{name}", tmp_path / name, layouts=layouts) for name in ("a", "b"))
    mocker.patch.object(RootCatalog, "mapped_roots", return_value=roots)
    return roots


@fixture(name="rebalance")
def fixture_rebalance(mocker: MockerFixture) -> Mock:
    """Replace what queues the jobs, before the window is built.

    :param mocker: pytest-mock fixture.
    :returns: the stand-in.
    """
    return mocker.patch.object(RootCatalog, "rebalance")


@fixture(name="window")
def fixture_window(qtbot: QtBot, rebalance: Mock) -> MainWindow:
    """A window with no catalog open.

    :param qtbot: pytest-qt fixture.
    :param rebalance: what queues the jobs.
    :returns: the window.
    """
    del rebalance
    window = MainWindow()
    qtbot.addWidget(window)
    return window


def test_balance_buckets_is_on_only_while_a_catalog_is_open(window: MainWindow, tmp_path: Path) -> None:
    """The action's roots are the catalog's, so it is there to use only while one is open.

    **Test steps:**

    * verify the action is off in a window with no catalog, on once one is opened, and off again once it is closed
    """
    action = window._MainWindow__ui.balance_buckets_action  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    catalog = window._MainWindow__root_catalog  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert not action.isEnabled()

    catalog.rehuco_path_changed.emit(tmp_path / "home.rehuco")
    assert action.isEnabled()

    catalog.rehuco_path_changed.emit(None)
    assert not action.isEnabled()


@mark.parametrize("from_a_root", [False, True], ids=["from-the-menu", "from-a-root"])
def test_each_entry_queues_what_the_dialog_answers(
    window: MainWindow, roots: tuple[MappedRoot, ...], rebalance: Mock, mocker: MockerFixture, from_a_root: bool
) -> None:
    """The menu's entry asks about every root, a root's own about that root; Start queues the roots checked with the
    limits shown.

    **Test steps:**

    * let the user press Start, from each entry
    * verify the roots and limits queued
    """
    mocker.patch("rehuco_agent.main_window.BalanceBucketsDialog", AnsweringDialog)
    moves = shared_move_settings()
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    panel = window._MainWindow__roots_panel  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    if from_a_root:
        panel.rebalance_requested.emit(roots[1].root_id)
    else:
        ui.balance_buckets_action.setEnabled(True)
        ui.balance_buckets_action.trigger()

    asked: tuple[UUID, ...] = (roots[1].root_id,) if from_a_root else tuple(root.root_id for root in roots)
    rebalance.assert_called_once_with(asked, moves.split_limit, moves.join_limit)


def test_a_canceled_dialog_queues_nothing(
    window: MainWindow, roots: tuple[MappedRoot, ...], rebalance: Mock, mocker: MockerFixture
) -> None:
    """Cancel balances nothing.

    **Test steps:**

    * let the user cancel
    * verify nothing was queued
    """
    mocker.patch("rehuco_agent.main_window.BalanceBucketsDialog", CancelingDialog)

    window._MainWindow__on_balance_root(roots[0].root_id)  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    rebalance.assert_not_called()


@mark.usefixtures("window")
def test_a_changed_limit_moves_nothing_by_itself(rebalance: Mock) -> None:
    """Saving other limits counts for the next record that arrives, and for the next balance asked for.

    **Test steps:**

    * save the move settings with a changed split limit
    * verify nothing was queued
    """
    moves = shared_move_settings()
    moves.split_limit = moves.split_limit + 1

    moves.save(Mock(spec=QSettings))

    rebalance.assert_not_called()


def test_the_move_host_follows_the_windows_queue(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A restored rebalance asks the host which moves are under way, so the host knows the queue as the queue is
    restored.

    **Test steps:**

    * build a window, recording what its host is told to follow
    * verify the window's own queue
    """
    follow = mocker.spy(MainThreadMoveHost, "follow_queue")

    window = MainWindow()
    qtbot.addWidget(window)

    queue = window._MainWindow__task_queue  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert [call.args[1] for call in follow.call_args_list] == [queue]
