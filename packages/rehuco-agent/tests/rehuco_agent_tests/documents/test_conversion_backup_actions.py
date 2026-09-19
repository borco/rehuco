"""Tests for one document's Discard Backups action (#193, #290).

The core operation itself is `test_tc_conversion_backups`'s subject and is mocked here: what this module
is about is whether the action is offered, what the inline strip says, what the confirmation warns about,
and that a refusal changes nothing. It runs **inline**, not on the queue, so there is no engine in these
tests -- which is itself the thing being asserted.
"""

from pathlib import Path
from typing import Any, Final

from PySide6.QtWidgets import QMessageBox
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.asking_deleter import AskingDeleter
from rehuco_agent.documents.conversion_backup_actions import ConversionBackupActions
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.settings.deletion_settings import DeletionKind, shared_deletion_settings
from rehuco_core import ConversionBackups, Deleter, NoTrashBinError, RehuDocument

DIRECTORY: Final = Path("/fake/library/sculpting")
INFO_PATH: Final = DIRECTORY / "info.rehu"
LEGACY_PATH: Final = DIRECTORY / "info.tc"

CONVERTED_STAMP: Final = "2023-11-14T22:13:20Z"

ACTIONS_MODULE: Final = "rehuco_agent.documents.conversion_backup_actions"


def make_backups(*, files: int = 3, total_bytes: int = 14_000_000) -> ConversionBackups:
    """One resource's inventory, as :func:`~rehuco_core.conversion_backups` would report it.

    :param files: how many backups it retains; ``0`` means none at all.
    :param total_bytes: what they occupy.
    :returns: the inventory.
    """
    backups = tuple(DIRECTORY / f"sample-{index:02}.jpg.orig" for index in range(files))
    if files:
        backups = (*backups, DIRECTORY / "info.tc.orig")
    return ConversionBackups(
        rehu_path=INFO_PATH,
        backups=backups,
        total_bytes=total_bytes if files else 0,
        dropped_screenshots=0,
        converted=CONVERTED_STAMP,
    )


# region fixtures


@fixture(autouse=True)
def permanent_deletes() -> None:
    """Turn the Recycle Bin off, so a discard is permanent from the start and therefore confirmed --
    the shape most of this module asserts on (#312). ``conftest.py`` already hands every test a fresh,
    isolated `DeletionSettings`; a test about a bin-bound discard turns the bin back on itself."""
    shared_deletion_settings().use_recycle_bin = False


@fixture(name="model")
def fixture_model(qapp: Any) -> RehuDocumentModel:
    """A view-model over a directory-scoped resource that is on disk.

    :param qapp: pytest-qt's application fixture -- these tests build ``QAction``s, which need one to
        exist before they are constructed.
    :returns: the model the actions are about.
    """
    del qapp
    document = RehuDocument(
        {"type": "Tutorial", "sources": [{"title": "Sculpting Series", "primary": True}]},
        INFO_PATH,
    )
    return RehuDocumentModel(document)


@fixture(name="inventory")
def fixture_inventory(mocker: MockerFixture) -> Any:
    """The inventory this resource reports, patched at the seam the actions read it through.

    :param mocker: pytest-mock fixture.
    :returns: the patched :func:`~rehuco_core.conversion_backups`, so a test can change its answer and
        call :meth:`~ConversionBackupActions.refresh`.
    """
    return mocker.patch(f"{ACTIONS_MODULE}.conversion_backups", return_value=make_backups())


@fixture(name="actions")
def fixture_actions(qtbot: QtBot, model: RehuDocumentModel, inventory: Any) -> ConversionBackupActions:
    """The action under test, over a converted resource that still has its backups.

    :param qtbot: pytest-qt fixture, for waiting on signals.
    :param model: the document the actions are about.
    :param inventory: the patched inventory seam.
    :returns: the actions.
    """
    del qtbot, inventory
    return ConversionBackupActions(model)


@fixture(name="answer_yes")
def fixture_answer_yes(mocker: MockerFixture) -> Any:
    """The up-front permanent-delete gate answered Yes.

    `~rehuco_agent.delete_confirmation.confirm_delete` is the whole of the policy and
    ``test_delete_confirmation.py`` its subject; patched where the action looks it up (#313), so a
    test here reads what the action asked for.

    :param mocker: pytest-mock fixture.
    :returns: the patched gate, so a test can read what was asked.
    """
    return mocker.patch(f"{ACTIONS_MODULE}.confirm_delete", return_value=True)


@fixture(name="answer_no")
def fixture_answer_no(mocker: MockerFixture) -> Any:
    """The up-front permanent-delete gate answered No.

    :param mocker: pytest-mock fixture.
    :returns: the patched gate.
    """
    return mocker.patch(f"{ACTIONS_MODULE}.confirm_delete", return_value=False)


def question_of(confirm: Any) -> str:
    """What the last confirmation actually asked."""
    return str(confirm.call_args.args[3])


# endregion


# region What the document shows


def test_the_action_is_offered_while_backups_are_retained(actions: ConversionBackupActions) -> None:
    """The same visible-while-the-condition-holds shape the two convert actions have for ``legacy_tc``.

    **Test steps:**

    * build the actions over a resource with retained backups
    * verify it is visible and the resource reads as retained
    """
    assert actions.retained is True
    assert actions.discard_action.isVisible()


def test_the_action_is_not_offered_without_backups(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """A resource that was never converted, or whose backups have been discarded, offers nothing and
    says nothing -- rather than a control that would refuse.

    **Test steps:**

    * build the actions over a resource with no retained backups
    * verify it is hidden and there is no notice
    """
    del qtbot
    mocker.patch(f"{ACTIONS_MODULE}.conversion_backups", return_value=make_backups(files=0))

    actions = ConversionBackupActions(model)

    assert actions.retained is False
    assert not actions.discard_action.isVisible()
    assert actions.notice == ""


def test_a_pending_placeholder_takes_no_inventory_until_loaded(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A session-restore placeholder's inventory is not taken (#66) -- it would read the whole
    ``.rehu`` for the timestamps, the very read the deferral exists to avoid -- and the deferred
    load's ``reloaded`` is what takes it, through the wiring the actions already have.

    **Test steps:**

    * build the actions over a pending placeholder and verify no inventory ran and nothing is offered
    * complete the deferred load (its ``reloaded`` fires) and verify the inventory ran once
    """
    del qtbot
    inventory = mocker.patch(f"{ACTIONS_MODULE}.conversion_backups", return_value=make_backups())
    model = RehuDocumentModel.create_pending(INFO_PATH)
    actions = ConversionBackupActions(model)

    assert inventory.call_count == 0
    assert actions.retained is False
    assert not actions.discard_action.isVisible()

    mocker.patch.object(
        Path, "read_text", return_value='{"type": "Tutorial", "sources": [{"title": "Foo", "primary": true}]}'
    )
    model.load_pending()

    assert inventory.call_count == 1
    assert actions.retained is True


def test_a_document_with_no_path_reads_nothing(qtbot: QtBot, mocker: MockerFixture, qapp: Any) -> None:
    """A never-saved document has no directory to look in, so the inventory is never asked for at all.

    **Test steps:**

    * build the actions over a path-less document
    * verify nothing was read and the action is not offered
    """
    del qtbot, qapp
    inventory = mocker.patch(f"{ACTIONS_MODULE}.conversion_backups")
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}))

    actions = ConversionBackupActions(model)

    inventory.assert_not_called()
    assert actions.retained is False


def test_the_notice_names_what_the_backups_amount_to(actions: ConversionBackupActions) -> None:
    """The reason to act on retained backups is usually that they occupy space, so the sentence says how
    much.

    **Test steps:**

    * read the notice over a resource holding four backups
    * verify it counts the files and names the size
    """
    assert "4 files, 14.0 MB" in actions.notice


def test_a_save_never_discards_the_backups(
    qtbot: QtBot, actions: ConversionBackupActions, inventory: Any, model: RehuDocumentModel
) -> None:
    """Discarding is the one irreversible step in the whole import flow, so it is never a side effect.

    **Test steps:**

    * save the document (dirty clearing is the seam)
    * verify the inventory was re-read and nothing discarded it
    """
    del qtbot
    discard = actions.discard_action

    model.dirty = True
    model.dirty = False

    assert actions.retained is True
    assert discard.isVisible()
    assert inventory.call_count > 1


def test_the_strip_is_told_to_rebuild_when_the_inventory_moves(
    qtbot: QtBot, actions: ConversionBackupActions, inventory: Any, model: RehuDocumentModel
) -> None:
    """The document's banner rebuilds off this signal, so a condition that stops being true has to say so.

    **Test steps:**

    * make the inventory report no backups, then cross a file-touching seam
    * verify the signal fired
    """
    inventory.return_value = make_backups(files=0)

    with qtbot.waitSignal(actions.changed):
        model.dirty = True

    assert actions.retained is False


# endregion


# region Discarding


def test_discarding_asks_first_and_names_what_it_frees(
    actions: ConversionBackupActions, answer_yes: Any, mocker: MockerFixture
) -> None:
    """The only irreversible act in the whole import flow, so a permanent discard's confirmation names
    the size rather than asking a reflexive yes/no.

    **Test steps:**

    * discard, with the Recycle Bin off, with the confirmation answered Yes
    * verify the question was put for the backups kind, names the bytes and says it cannot be undone,
      and that the operation ran through the shared asking deleter
    """
    discard = mocker.patch(f"{ACTIONS_MODULE}.discard_conversion_backups", return_value=())
    deleter = mocker.Mock()
    mocker.patch(f"{ACTIONS_MODULE}.configured_deleter", return_value=deleter)

    actions.discard()

    assert answer_yes.call_args.args[1] is DeletionKind.BACKUPS
    assert "14.0 MB" in question_of(answer_yes)
    assert "cannot be undone" in question_of(answer_yes)
    args, kwargs = discard.call_args
    assert args == (INFO_PATH,)
    assert isinstance(kwargs["deleter"], AskingDeleter)


def test_a_discard_bound_for_the_recycle_bin_asks_nothing(
    actions: ConversionBackupActions, mocker: MockerFixture
) -> None:
    """One deletion policy (#312): a question accompanies a permanent delete only, so with the bin on
    the discard simply runs -- through the real gate, which shows no box.

    **Test steps:**

    * turn the Recycle Bin on and discard
    * verify no box was shown and the operation ran
    """
    shared_deletion_settings().use_recycle_bin = True
    shown = mocker.patch.object(QMessageBox, "exec")
    discard = mocker.patch(f"{ACTIONS_MODULE}.discard_conversion_backups", return_value=())

    actions.discard()

    shown.assert_not_called()
    discard.assert_called_once()


def test_clear_backups_without_asking_skips_the_permanent_confirm(
    actions: ConversionBackupActions, mocker: MockerFixture
) -> None:
    """With **Clear backups without asking** on, even a permanent discard is not confirmed, and the
    asking deleter -- built for the backups kind -- reads the same box and does not ask either
    (#312, #313).

    **Test steps:**

    * turn the box on, keep the bin off, and discard, through the real gate
    * verify no box was shown, the operation ran, and a refusal inside it deletes permanently with no
      question
    """
    shared_deletion_settings().clear_backups_without_asking = True
    mocker.patch(
        f"{ACTIONS_MODULE}.configured_deleter",
        return_value=mocker.Mock(delete=mocker.Mock(side_effect=NoTrashBinError("no bin"))),
    )
    shown = mocker.patch.object(QMessageBox, "exec")
    unlink = mocker.patch.object(Path, "unlink", autospec=True)

    def discard(rehu_path: Path, *, deleter: Deleter) -> tuple[Path, ...]:
        deleter.delete(rehu_path.parent / "info.tc.orig")
        return ()

    operation = mocker.patch(f"{ACTIONS_MODULE}.discard_conversion_backups", side_effect=discard)

    actions.discard()

    shown.assert_not_called()
    operation.assert_called_once()
    unlink.assert_called_once_with(DIRECTORY / "info.tc.orig")


def test_a_declined_discard_changes_nothing(
    actions: ConversionBackupActions, answer_no: Any, mocker: MockerFixture
) -> None:
    """Nothing is deleted until the question is answered Yes.

    **Test steps:**

    * discard with the confirmation answered No
    * verify the operation never ran
    """
    del answer_no
    discard = mocker.patch(f"{ACTIONS_MODULE}.discard_conversion_backups")

    actions.discard()

    discard.assert_not_called()


def test_a_discard_re_reads_the_inventory_so_the_strip_stops_saying_it(
    actions: ConversionBackupActions, inventory: Any, answer_yes: Any, mocker: MockerFixture
) -> None:
    """The row is state, not a notification, so it has to clear the moment its condition does.

    **Test steps:**

    * discard, then make the inventory report an emptied directory
    * verify the action no longer offers anything
    """
    del answer_yes
    mocker.patch(f"{ACTIONS_MODULE}.discard_conversion_backups", return_value=())
    inventory.return_value = make_backups(files=0)

    actions.discard()

    assert actions.retained is False
    assert actions.notice == ""


def test_a_discard_that_fails_reports_the_reason(
    actions: ConversionBackupActions, answer_yes: Any, mocker: MockerFixture
) -> None:
    """A read-only mount refuses the unlink, and that has to reach the user rather than escape.

    **Test steps:**

    * make the operation raise
    * verify the failure was reported
    """
    del answer_yes
    reported = mocker.patch.object(QMessageBox, "warning")
    mocker.patch(f"{ACTIONS_MODULE}.discard_conversion_backups", side_effect=PermissionError("read-only"))

    actions.discard()

    assert "read-only" in str(reported.call_args.args[2])


def test_discarding_a_resource_with_no_backups_does_nothing(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture, answer_yes: Any
) -> None:
    """The hidden action must not be reachable past its condition.

    **Test steps:**

    * discard a resource with no retained backups
    * verify nothing was asked and nothing ran
    """
    del qtbot
    mocker.patch(f"{ACTIONS_MODULE}.conversion_backups", return_value=make_backups(files=0))
    discard = mocker.patch(f"{ACTIONS_MODULE}.discard_conversion_backups")

    ConversionBackupActions(model).discard()

    discard.assert_not_called()
    answer_yes.assert_not_called()


def test_a_declined_bin_refusal_logs_instead_of_reporting_a_failure(
    actions: ConversionBackupActions, mocker: MockerFixture, caplog: Any
) -> None:
    """A `NoTrashBinError` reaching here can only mean the asking deleter already asked and the answer
    was No (#301, exercised in ``test_asking_deleter.py``) -- the outcome reads like convert's: a logged
    warning, no ``Discard Failed`` box on top of the question already answered.

    **Test steps:**

    * discard, with the bin on so nothing is confirmed up front, where the underlying operation is
      refused with `NoTrashBinError`
    * verify no failure box was shown, and a warning naming the resource was logged
    """
    shared_deletion_settings().use_recycle_bin = True
    reported = mocker.patch.object(QMessageBox, "warning")
    mocker.patch(
        f"{ACTIONS_MODULE}.discard_conversion_backups",
        side_effect=NoTrashBinError(f"No Recycle Bin is available for {DIRECTORY}"),
    )

    with caplog.at_level("WARNING", logger=ACTIONS_MODULE):
        actions.discard()

    reported.assert_not_called()
    assert any("left in place" in record.message for record in caplog.records)


# endregion
