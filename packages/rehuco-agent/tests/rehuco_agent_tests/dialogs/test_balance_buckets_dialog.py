"""Tests for BalanceBucketsDialog: which roots to balance and with which limits (#681)."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from uuid import UUID

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtWidgets import QLabel, QListWidget, QSpinBox
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.dialogs.balance_buckets_dialog import NO_RULE_NOTE, START_TEXT, BalanceBucketsDialog
from rehuco_agent.settings.balance_buckets_dialog_settings import BalanceBucketsDialogSettings
from rehuco_agent.settings.move_settings import MoveSettings
from rehuco_core import Layouts, MappedRoot

MODULE = "rehuco_agent.dialogs.balance_buckets_dialog"
BUCKETED: Layouts = {"asset": ("{site}/{buckets}/{site_id}",)}


def root_of(number: int, label: str, layouts: Layouts) -> MappedRoot:
    """A root this machine maps.

    :param number: its id.
    :param label: its label.
    :param layouts: its layouts.
    :returns: the root.
    """
    return MappedRoot(UUID(int=number), label, f"//nas/{number}", Path("/roots", str(number)), layouts=layouts)


ASSETS = root_of(1, "Assets", BUCKETED)
UNLABELED = root_of(2, "", BUCKETED)
PLAIN = root_of(3, "Plain", {"*": ("*",)})
ROOTS = (ASSETS, UNLABELED, PLAIN)


@fixture(name="store", autouse=True)
def fixture_store(mocker: MockerFixture) -> dict[str, Any]:
    """Stand in for the persistent settings with a plain dictionary.

    :param mocker: pytest-mock fixture.
    :returns: what is stored, by key.
    """
    values: dict[str, Any] = {}
    store = Mock()
    store.value.side_effect = lambda key, default, **_: values.get(key, default)
    store.setValue.side_effect = values.__setitem__
    mocker.patch(f"{MODULE}.persistent_settings", return_value=store)
    return values


@fixture(name="moves")
def fixture_moves() -> MoveSettings:
    """Limits other than the shipped ones.

    :returns: the settings.
    """
    moves = MoveSettings()
    moves.split_limit, moves.join_limit = 300, 120
    return moves


def build(
    qtbot: QtBot, moves: MoveSettings, roots: Sequence[MappedRoot] = ROOTS, only: UUID | None = None
) -> BalanceBucketsDialog:
    """The dialog.

    :param qtbot: pytest-qt fixture.
    :param moves: the limits.
    :param roots: the roots it lists.
    :param only: the root it is opened for.
    :returns: the dialog, shown.
    """
    dialog = BalanceBucketsDialog(roots, moves, only)
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog


def rows_of(dialog: BalanceBucketsDialog) -> QListWidget:
    """The dialog's list of roots.

    :param dialog: the dialog.
    :returns: the list.
    """
    found = dialog.findChild(QListWidget, "roots_list")
    assert isinstance(found, QListWidget)
    return found


def check(dialog: BalanceBucketsDialog, row: int, checked: bool) -> None:
    """Check a root, or uncheck it.

    :param dialog: the dialog.
    :param row: the root's row.
    :param checked: which.
    """
    rows_of(dialog).item(row).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)


def ids(*roots: MappedRoot) -> tuple[UUID, ...]:
    """The ids of roots.

    :param roots: the roots.
    :returns: their ids.
    """
    return tuple(root.root_id for root in roots)


def test_it_lists_every_root_and_checks_those_with_a_rule(qtbot: QtBot, moves: MoveSettings) -> None:
    """The first time, every root whose layouts have buckets is checked; one with none is listed, noted and unchecked.

    **Test steps:**

    * open the dialog from the menu with nothing remembered
    * verify the rows' texts and tooltips, what is checked, the limits and the Start button
    """
    dialog = build(qtbot, moves)

    rows = rows_of(dialog)
    assert [rows.item(row).text() for row in range(rows.count())] == ["Assets", "//nas/2", f"Plain ({NO_RULE_NOTE})"]
    assert rows.item(0).toolTip() == str(ASSETS.path)
    assert dialog.root_ids == ids(ASSETS, UNLABELED)
    assert dialog.limits == (300, 120)
    assert dialog.start_button.text() == START_TEXT
    assert dialog.start_button.isEnabled()


def test_start_saves_the_limits_and_the_roots(qtbot: QtBot, moves: MoveSettings) -> None:
    """Start stores the limits as the Files page would, and the next time the menu checks the same roots.

    **Test steps:**

    * change both limits and which roots are checked, and press Start
    * verify the settings were changed and announced; open the dialog again and verify what it shows
    """
    dialog = build(qtbot, moves)
    for name, value in (("split_limit_spin_box", 500), ("join_limit_spin_box", 400)):
        spin_box = dialog.findChild(QSpinBox, name)
        assert isinstance(spin_box, QSpinBox)
        spin_box.setValue(value)
    check(dialog, 0, False)
    check(dialog, 2, True)

    with qtbot.waitSignal(moves.changed, timeout=1000):
        dialog.start_button.click()

    assert dialog.result() == BalanceBucketsDialog.DialogCode.Accepted
    assert (moves.split_limit, moves.join_limit) == (500, 400)
    again = build(qtbot, moves)
    assert again.root_ids == ids(UNLABELED, PLAIN)
    assert again.limits == (500, 400)


def test_cancel_saves_neither(qtbot: QtBot, moves: MoveSettings) -> None:
    """Cancel leaves the limits and what the menu checks as they were.

    **Test steps:**

    * change a limit and a root, and cancel
    * verify the settings, and what the dialog shows when opened again
    """
    dialog = build(qtbot, moves)
    spin_box = dialog.findChild(QSpinBox, "split_limit_spin_box")
    assert isinstance(spin_box, QSpinBox)
    spin_box.setValue(500)
    check(dialog, 0, False)

    with qtbot.assertNotEmitted(moves.changed):
        dialog.reject()

    assert (moves.split_limit, moves.join_limit) == (300, 120)
    assert build(qtbot, moves).root_ids == ids(ASSETS, UNLABELED)


def test_opened_for_a_root_it_checks_that_root_and_remembers_nothing(qtbot: QtBot, moves: MoveSettings) -> None:
    """From a root's own entry that root alone is checked, rule or not; a run from there saves the limits, and leaves
    what the menu checks.

    **Test steps:**

    * run the dialog from the menu with one root checked
    * open it for another root, and press Start
    * verify what was checked, that the limits were saved, and that the menu's is still the first
    """
    dialog = build(qtbot, moves)
    check(dialog, 1, False)
    dialog.accept()

    single = build(qtbot, moves, only=PLAIN.root_id)
    assert single.root_ids == ids(PLAIN)
    with qtbot.waitSignal(moves.changed, timeout=1000):
        single.accept()

    assert build(qtbot, moves).root_ids == ids(ASSETS)


def test_another_catalogs_choice_is_kept(qtbot: QtBot, moves: MoveSettings) -> None:
    """A catalog none of whose roots were balanced starts as on the first run, and leaves the other's choice.

    **Test steps:**

    * run the dialog over one catalog with its first root checked, then over another catalog
    * verify what each checks when opened again
    """
    dialog = build(qtbot, moves, (ASSETS, PLAIN))
    dialog.accept()

    other = build(qtbot, moves, (UNLABELED,))
    assert other.root_ids == ids(UNLABELED)
    other.accept()

    assert build(qtbot, moves, (ASSETS, PLAIN)).root_ids == ids(ASSETS)


def test_start_needs_a_root(qtbot: QtBot, moves: MoveSettings) -> None:
    """With none checked there is nothing to balance.

    **Test steps:**

    * uncheck every root, then check one
    * verify Start is off, then on
    """
    dialog = build(qtbot, moves)
    check(dialog, 0, False)
    check(dialog, 1, False)
    assert not dialog.start_button.isEnabled()

    check(dialog, 2, True)
    assert dialog.start_button.isEnabled()


@mark.parametrize("roots", [(), ROOTS], ids=["none", "some"])
def test_a_catalog_with_no_root_here_says_so(qtbot: QtBot, moves: MoveSettings, roots: tuple[MappedRoot, ...]) -> None:
    """With no root mapped there is no list, but a sentence.

    **Test steps:**

    * open the dialog over no root, and over some
    * verify which of the list and the sentence shows, and Start
    """
    dialog = build(qtbot, moves, roots)

    label = dialog.findChild(QLabel, "no_roots_label")
    assert isinstance(label, QLabel)
    assert label.isVisible() is not bool(roots)
    assert rows_of(dialog).isVisible() is bool(roots)
    assert dialog.start_button.isEnabled() is bool(roots)


@mark.parametrize("accepts", [True, False])
def test_every_exit_saves_the_geometry(qtbot: QtBot, moves: MoveSettings, mocker: MockerFixture, accepts: bool) -> None:
    """Where the dialog was is kept on Start and on Cancel, and restored when it is opened again.

    **Test steps:**

    * close the dialog, its geometry known, by each exit
    * open it again, and verify the geometry was restored
    """
    dialog = build(qtbot, moves)
    mocker.patch.object(dialog, "saveGeometry", return_value=QByteArray(b"geometry"))
    restore = mocker.patch.object(BalanceBucketsDialog, "restoreGeometry")

    (dialog.accept if accepts else dialog.reject)()
    build(qtbot, moves)

    restore.assert_called_once_with(QByteArray(b"geometry"))


def test_nothing_saved_restores_no_geometry(qtbot: QtBot, moves: MoveSettings, mocker: MockerFixture) -> None:
    """The first time, the dialog opens where Qt puts it.

    **Test steps:**

    * open the dialog with nothing saved
    * verify no geometry was restored
    """
    restore = mocker.patch.object(BalanceBucketsDialog, "restoreGeometry")
    assert not BalanceBucketsDialogSettings().geometry

    build(qtbot, moves)

    restore.assert_not_called()
