"""Tests for ``save_or_prompt_retry``: the one seam every save call site funnels an I/O failure through (#146), and a
conflict (#416)."""

from pathlib import Path
from typing import Any, Final

from PySide6.QtWidgets import QButtonGroup, QMessageBox, QPushButton, QWidget
from pytest import fixture, mark, raises
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.dialogs.record_conflict_dialog import ConflictResolution, RecordConflictDialog
from rehuco_agent.documents import save_or_prompt_retry as module
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.documents.save_or_prompt_retry import ask_about_conflict, save_or_prompt_retry
from rehuco_core import DEFAULT_CURRENT_USERNAME, RecordConflict, RecordVersion, RehuDocument

from .test_rehu_document_model_conflict import RATING_PATH, edit_on_disk, in_conflict, opened, write_record

TITLE_PATH: Final = ("core", "sources", 0, "title")

KEEP_THEIRS: Final = {TITLE_PATH: "Theirs"}
"""What a person keeping the file's title answers."""

KEEP_ORIGINAL: Final = {TITLE_PATH: "Old"}
"""What a person keeping the title as opened answers."""

ORIGINAL_RADIO: Final = "original radio"
"""Not a button's name: :func:`press_in_dialog` clicks the first row's Original radio for it."""


@fixture
def parent(qtbot: QtBot) -> QWidget:
    """A real widget to parent the (mocked) error dialog to, registered for teardown."""
    widget = QWidget()
    qtbot.addWidget(widget)
    return widget


def test_returns_true_and_saves_once_on_a_clean_save(mocker: MockerFixture, parent: QWidget) -> None:
    """A save that succeeds returns ``True`` and shows no dialog.

    **Test steps:**

    * stand in a model whose ``save`` succeeds and mock the critical dialog to detect any call
    * call ``save_or_prompt_retry``
    * verify it returned ``True``, saved once, and never showed the dialog
    """
    model = mocker.MagicMock(label="doc.rehu")
    critical = mocker.patch.object(QMessageBox, "critical")

    assert save_or_prompt_retry(parent, model) is True
    model.save.assert_called_once_with()
    critical.assert_not_called()


def test_shows_a_critical_dialog_and_returns_false_on_cancel(mocker: MockerFixture, parent: QWidget) -> None:
    """An ``OSError`` (an offline mount) shows a critical dialog; Cancel returns ``False``.

    **Test steps:**

    * stand in a model whose ``save`` raises ``OSError`` and mock the critical dialog to answer Cancel
    * call ``save_or_prompt_retry``
    * verify the dialog was shown once and it returned ``False``
    """
    model = mocker.MagicMock(label="doc.rehu")
    model.save.side_effect = OSError("offline mount")
    critical = mocker.patch.object(QMessageBox, "critical", return_value=QMessageBox.StandardButton.Cancel)

    assert save_or_prompt_retry(parent, model) is False
    critical.assert_called_once()


def test_retries_until_the_save_succeeds(mocker: MockerFixture, parent: QWidget) -> None:
    """Answering Retry re-attempts the save; a save that then succeeds returns ``True``.

    **Test steps:**

    * stand in a model whose ``save`` raises ``OSError`` twice then succeeds, and mock the critical
      dialog to answer Retry
    * call ``save_or_prompt_retry``
    * verify it saved three times and returned ``True``
    """
    model = mocker.MagicMock(label="doc.rehu")
    model.save.side_effect = [OSError("offline mount"), OSError("offline mount"), None]
    mocker.patch.object(QMessageBox, "critical", return_value=QMessageBox.StandardButton.Retry)

    assert save_or_prompt_retry(parent, model) is True
    assert model.save.call_count == 3


def test_falls_back_to_untitled_when_the_model_has_no_label(mocker: MockerFixture, parent: QWidget) -> None:
    """A path-less model (empty label) is named "Untitled" in the failure dialog rather than blank.

    **Test steps:**

    * stand in a model with an empty label whose ``save`` raises ``OSError``, and mock the critical
      dialog to answer Cancel
    * call ``save_or_prompt_retry``
    * verify the dialog's message names the document "Untitled"
    """
    model = mocker.MagicMock(label="")
    model.save.side_effect = OSError("offline mount")
    critical = mocker.patch.object(QMessageBox, "critical", return_value=QMessageBox.StandardButton.Cancel)

    save_or_prompt_retry(parent, model)

    assert "Untitled" in critical.call_args.args[2]


# region conflicts
def refusal(tmp_path: Path) -> RecordConflict:
    """A conflict naming a file's title as ``Theirs``, for a stand-in model to raise.

    :param tmp_path: where the conflicting document is bound.
    :returns: the conflict.
    """
    theirs = RehuDocument.new(tmp_path / "info.rehu")
    theirs.title = "Theirs"
    return RecordConflict(theirs, RecordVersion("metadata", "file", ()))


def answer_conflicts(mocker: MockerFixture, *answers: tuple[ConflictResolution, dict[Any, Any]]) -> Any:
    """Replace the conflict dialog with these answers, one per conflict.

    :param mocker: pytest-mock fixture.
    :param answers: what each dialog shown answers, in turn.
    :returns: the stand-in, to check how it was asked.
    """
    return mocker.patch.object(module, "ask_about_conflict", side_effect=list(answers))


def test_a_conflict_resolved_with_save_saves_the_picks(mocker: MockerFixture, parent: QWidget, tmp_path: Path) -> None:
    """Save in the conflict dialog puts the picks and saves; the gated action goes on.

    **Test steps:**

    * stand in a model whose save is refused as a conflict, and answer the dialog with Save and a pick
    * call ``save_or_prompt_retry``
    * verify the dialog was asked about that conflict, the picks were resolved, and it returned ``True``
    """
    conflict = refusal(tmp_path)
    model = mocker.MagicMock(label="doc.rehu")
    model.save.side_effect = conflict
    ask = answer_conflicts(mocker, (ConflictResolution.SAVE, KEEP_THEIRS))

    assert save_or_prompt_retry(parent, model) is True

    ask.assert_called_once_with(parent, model, conflict)
    model.resolve_conflict.assert_called_once_with(KEEP_THEIRS)
    model.revert.assert_not_called()


def test_a_conflict_resolved_by_discarding_reverts(mocker: MockerFixture, parent: QWidget, tmp_path: Path) -> None:
    """Discard My Edits loads the file as it is: nothing is left unsaved, so the gated action goes on.

    **Test steps:**

    * stand in a model whose save is refused as a conflict, and answer the dialog with Discard
    * call ``save_or_prompt_retry``
    * verify the model was reverted, nothing resolved, and it returned ``True``
    """
    model = mocker.MagicMock(label="doc.rehu")
    model.save.side_effect = refusal(tmp_path)
    answer_conflicts(mocker, (ConflictResolution.DISCARD, {}))

    assert save_or_prompt_retry(parent, model) is True

    model.revert.assert_called_once_with()
    model.resolve_conflict.assert_not_called()


def test_a_cancelled_conflict_aborts(mocker: MockerFixture, parent: QWidget, tmp_path: Path) -> None:
    """Cancel leaves the edits unsaved, so whatever the save was gating must not go on.

    **Test steps:**

    * stand in a model whose save is refused as a conflict, and answer the dialog with Cancel
    * call ``save_or_prompt_retry``
    * verify it returned ``False``, with nothing resolved or reverted
    """
    model = mocker.MagicMock(label="doc.rehu")
    model.save.side_effect = refusal(tmp_path)
    answer_conflicts(mocker, (ConflictResolution.CANCEL, {}))

    assert save_or_prompt_retry(parent, model) is False

    model.resolve_conflict.assert_not_called()
    model.revert.assert_not_called()


def test_a_resolution_refused_again_asks_again(mocker: MockerFixture, parent: QWidget, tmp_path: Path) -> None:
    """The file can change once more while the dialog is open: the newer conflict is shown, and its picks saved.

    **Test steps:**

    * stand in a model whose save is refused, and whose first resolution is refused too
    * answer both dialogs with Save, each with its own picks
    * verify the dialog was asked twice, each set of picks resolved in turn, and it returned ``True``
    """
    first, second = refusal(tmp_path), refusal(tmp_path)
    model = mocker.MagicMock(label="doc.rehu")
    model.save.side_effect = first
    model.resolve_conflict.side_effect = [second, None]
    again: dict[Any, Any] = {TITLE_PATH: "Theirs again"}
    ask = answer_conflicts(mocker, (ConflictResolution.SAVE, KEEP_THEIRS), (ConflictResolution.SAVE, again))

    assert save_or_prompt_retry(parent, model) is True

    assert [call.args[2] for call in ask.call_args_list] == [first, second]
    assert [call.args for call in model.resolve_conflict.call_args_list] == [(KEEP_THEIRS,), (again,)]
    model.save.assert_called_once_with()


def test_a_resolution_that_fails_to_write_is_retried_as_a_resolution(
    mocker: MockerFixture, parent: QWidget, tmp_path: Path
) -> None:
    """Retry after an I/O failure repeats what failed -- the resolution with its picks, not a plain save that would
    only be refused again.

    **Test steps:**

    * stand in a model whose save is refused, and whose first resolution fails with ``OSError``
    * answer the dialog with Save, and the failure with Retry
    * verify the picks were resolved twice, the plain save attempted once, and it returned ``True``
    """
    model = mocker.MagicMock(label="doc.rehu")
    model.save.side_effect = refusal(tmp_path)
    model.resolve_conflict.side_effect = [OSError("offline mount"), None]
    answer_conflicts(mocker, (ConflictResolution.SAVE, KEEP_THEIRS))
    mocker.patch.object(QMessageBox, "critical", return_value=QMessageBox.StandardButton.Retry)

    assert save_or_prompt_retry(parent, model) is True

    assert model.resolve_conflict.call_count == 2
    model.save.assert_called_once_with()


def refused_title(tmp_path: Path) -> tuple[RehuDocumentModel, RecordConflict]:
    """A real model whose save was refused: its title edited to ``Mine`` while the file's became ``Theirs``.

    :param tmp_path: where the record is written.
    :returns: the model, and its refusal.
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    return in_conflict(path, "Mine", "Theirs")


def press_in_dialog(mocker: MockerFixture, *names: str) -> list[RecordConflictDialog]:
    """Make the conflict dialog's ``exec`` press these buttons, by ``.ui`` name, instead of waiting for a person.

    :param mocker: pytest-mock fixture.
    :param names: the buttons to press, in turn -- :data:`ORIGINAL_RADIO` for the first row's Original radio.
    :returns: every dialog shown, filled in as each is executed.
    """
    shown: list[RecordConflictDialog] = []

    def execute(dialog: RecordConflictDialog) -> int:
        """Press the buttons on ``dialog``.

        :param dialog: the dialog shown.
        :returns: its result.
        """
        shown.append(dialog)
        for name in names:
            if name == ORIGINAL_RADIO:
                dialog.findChildren(QButtonGroup)[0].buttons()[0].click()
                continue
            found = dialog.findChild(QPushButton, name)
            assert isinstance(found, QPushButton)
            found.click()
        return dialog.result()

    mocker.patch.object(RecordConflictDialog, "exec", new=execute)
    return shown


@mark.usefixtures("real_path_stat")
def test_asking_about_a_conflict_shows_the_two_sides_and_disposes_of_the_dialog(
    mocker: MockerFixture, parent: QWidget, qtbot: QtBot, tmp_path: Path
) -> None:
    """The dialog compares the record as opened, as edited and as on disk; its picks are returned, and the dialog is
    deleted once answered rather than kept parented to the window.

    **Test steps:**

    * bring a real model into conflict over its title
    * ask about it, with the dialog answered All On Disk, then the title's Original radio, then Save
    * verify the answer is Save with the title as opened, the dialog was parented to the window, and it is destroyed
    """
    model, conflict = refused_title(tmp_path)
    shown = press_in_dialog(mocker, "all_on_disk_button", ORIGINAL_RADIO, "save_button")
    destroyed: list[bool] = []

    answer = ask_about_conflict(parent, model, conflict)

    assert answer == (ConflictResolution.SAVE, KEEP_ORIGINAL)
    assert len(shown) == 1
    dialog = shown[0]
    assert dialog.parent() is parent
    dialog.destroyed.connect(lambda: destroyed.append(True))
    qtbot.waitUntil(lambda: bool(destroyed))


@mark.usefixtures("real_path_stat")
def test_asking_about_a_conflict_lists_the_own_per_user_fields_and_not_another_users(
    mocker: MockerFixture, parent: QWidget, tmp_path: Path
) -> None:
    """The dialog is built from the whole record: this user's rating, changed on both sides, is a row to choose; the
    rating another user gave meanwhile is always the file's, so it is not.

    **Test steps:**

    * open a record rated 1, retitle it and rate it 5
    * meanwhile retitle the file, rate it 3 for this user and 4 for ``bob``
    * save, and ask about the refusal with the dialog answered Save
    * verify the picks are this document's title and rating, and name no field of ``bob``'s
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old", rating=1)

    def theirs(document: RehuDocument) -> None:
        document.title = "Theirs"
        document.set_user_field(DEFAULT_CURRENT_USERNAME, "rating", 3)
        document.set_user_field("bob", "rating", 4)

    model = opened(path)
    model.title = "Mine"
    model.rating = 5
    edit_on_disk(path, theirs)
    with raises(RecordConflict) as refused:
        model.save()
    press_in_dialog(mocker, "save_button")

    resolution, picks = ask_about_conflict(parent, model, refused.value)

    assert resolution is ConflictResolution.SAVE
    assert picks == {TITLE_PATH: "Mine", RATING_PATH: 5}
    assert not [key for key in picks if "bob" in key]


@mark.usefixtures("real_path_stat")
def test_asking_about_a_conflict_leaves_out_a_block_the_save_drops(
    mocker: MockerFixture, parent: QWidget, tmp_path: Path
) -> None:
    """A block this document claimed and abandoned is dropped by the save whatever is picked, so its values are no rows:
    the file's change to it goes with it, as it would on a save with no conflict.

    **Test steps:**

    * open a tutorial holding a foreign ``reference_images`` block, retitle it, switch to that type and back
    * meanwhile retitle the file and change the block's image count
    * save, and ask about the refusal with the dialog answered Save
    * verify the only pick is the title
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    edit_on_disk(path, lambda document: document.data.update(reference_images={"format_version": 1, "image_count": 1}))

    def theirs(document: RehuDocument) -> None:
        document.title = "Theirs"
        document.data.update(reference_images={"format_version": 1, "image_count": 2})

    model = opened(path)
    model.title = "Mine"
    model.document.set_active_type("reference_images")
    model.document.set_active_type("tutorial")
    edit_on_disk(path, theirs)
    with raises(RecordConflict) as refused:
        model.save()
    press_in_dialog(mocker, "save_button")

    _, picks = ask_about_conflict(parent, model, refused.value)

    assert picks == {TITLE_PATH: "Mine"}


@mark.usefixtures("real_path_stat")
@mark.parametrize(
    ("name", "resolution"),
    [("discard_button", ConflictResolution.DISCARD), ("cancel_button", ConflictResolution.CANCEL)],
)
def test_asking_about_a_conflict_answers_no_picks_unless_saving(
    mocker: MockerFixture, parent: QWidget, tmp_path: Path, name: str, resolution: ConflictResolution
) -> None:
    """Only a Save carries picks: a discard or a cancel has nothing to put, whatever the rows say.

    **Test steps:**

    * bring a real model into conflict over its title
    * ask about it, with the dialog answered All On Disk then Discard, or Cancel
    * verify the answer is that resolution, with no picks
    """
    model, conflict = refused_title(tmp_path)
    press_in_dialog(mocker, "all_on_disk_button", name)

    assert ask_about_conflict(parent, model, conflict) == (resolution, {})


@mark.usefixtures("real_path_stat")
def test_a_conflict_kept_all_on_disk_cannot_be_saved_and_discarding_takes_the_files_title(
    mocker: MockerFixture, parent: QWidget, tmp_path: Path
) -> None:
    """End to end through a real model and file: keeping the file's side everywhere leaves nothing to save -- Save is
    disabled, and a press does nothing -- so Discard My Edits is how the file's title is taken.

    **Test steps:**

    * bring a real model into conflict over its title, and clear the conflict so a save is asked afresh
    * save through ``save_or_prompt_retry``, with the dialog answered All On Disk, then Save, then Discard My Edits
    * verify Save was disabled, it returned ``True``, the file and the model hold the file's title, and the model is
      clean
    """
    model, _ = refused_title(tmp_path)
    model.conflict = None
    shown = press_in_dialog(mocker, "all_on_disk_button", "save_button", "discard_button")

    assert save_or_prompt_retry(parent, model) is True

    save = shown[0].findChild(QPushButton, "save_button")
    assert isinstance(save, QPushButton)
    assert not save.isEnabled()
    assert shown[0].resolution is ConflictResolution.DISCARD
    assert RehuDocument.load(tmp_path / "info.rehu").title == "Theirs"
    assert (model.title, model.dirty, model.conflict) == ("Theirs", False, None)


@mark.usefixtures("real_path_stat")
def test_a_conflict_kept_as_original_saves_the_title_as_opened(
    mocker: MockerFixture, parent: QWidget, tmp_path: Path
) -> None:
    """End to end through a real model and file: the person keeps neither edit, and the title as opened is saved.

    **Test steps:**

    * bring a real model into conflict over its title, and clear the conflict so a save is asked afresh
    * save through ``save_or_prompt_retry``, with the dialog answered with the title's Original radio, then Save
    * verify it returned ``True``, the file and the model hold the original title, and the model is clean
    """
    model, _ = refused_title(tmp_path)
    model.conflict = None
    press_in_dialog(mocker, ORIGINAL_RADIO, "save_button")

    assert save_or_prompt_retry(parent, model) is True

    assert RehuDocument.load(tmp_path / "info.rehu").title == "Old"
    assert (model.title, model.dirty, model.conflict) == ("Old", False, None)


# endregion
