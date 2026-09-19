"""Tests for AskingDeleter: the interactive `~rehuco_core.Deleter` wrapper that offers a permanent
delete for a file the Recycle Bin cannot take (#301).

The question itself is `~rehuco_agent.delete_confirmation.ask_permanent_delete`'s (#313), tested in
``test_delete_confirmation.py``; here it is patched where this class looks it up, so what these tests
read is what the deleter asked for -- the kind, the title, the text -- and when. `QMessageBox.critical`
is mocked the same way for the failure notice.
"""

from pathlib import Path
from typing import Final

import pytest
from pytest_mock import MockerFixture
from rehuco_agent.asking_deleter import TITLE, AskingDeleter
from rehuco_agent.settings.deletion_settings import DeletionKind, shared_deletion_settings
from rehuco_core import NoTrashBinError

PATH: Final = Path("/fake/tutorial/info00.jpg")
OTHER_PATH: Final = Path("/fake/tutorial/info01.jpg")

QUESTION: Final = "rehuco_agent.asking_deleter.ask_permanent_delete"
CRITICAL: Final = "rehuco_agent.asking_deleter.QMessageBox.critical"

KIND: Final = DeletionKind.IMAGES
"""The kind every deleter here is built with; the tests about the box flip that kind's flag."""


class RefusingDeleter:  # pylint: disable=too-few-public-methods
    """A :class:`~rehuco_core.Deleter` that always refuses with `~rehuco_core.NoTrashBinError`."""

    def delete(self, path: Path) -> None:
        """Refuse to delete ``path``."""
        raise NoTrashBinError(f"no bin for {path.parent}")


class RecordingDeleter:  # pylint: disable=too-few-public-methods
    """A :class:`~rehuco_core.Deleter` that records what it was asked to delete."""

    def __init__(self) -> None:
        self.deleted: list[Path] = []

    def delete(self, path: Path) -> None:
        """Record ``path`` rather than raising or touching disk."""
        self.deleted.append(path)


class LockedDeleter:  # pylint: disable=too-few-public-methods
    """A :class:`~rehuco_core.Deleter` that always fails with a plain ``OSError`` -- a genuine failure,
    not a missing bin."""

    def delete(self, path: Path) -> None:
        """Refuse to delete ``path``."""
        raise OSError(f"locked: {path}")


def test_success_passes_through_untouched() -> None:
    """A delete that does not refuse never involves the question at all.

    **Test steps:**

    * delete through an `AskingDeleter` wrapping a recording deleter
    * verify the inner deleter, and only it, was asked
    """
    inner = RecordingDeleter()

    AskingDeleter(inner, KIND).delete(PATH)

    assert inner.deleted == [PATH]


def test_yes_deletes_the_current_file_permanently(mocker: MockerFixture) -> None:
    """Answering Yes deletes the one file asked about, and the call succeeds.

    **Test steps:**

    * answer Yes to a refusal
    * delete through an `AskingDeleter` wrapping a refusing deleter
    * verify the permanent deleter was used and nothing was raised
    """
    mocker.patch(QUESTION, return_value=True)
    unlink = mocker.patch.object(Path, "unlink", autospec=True)

    AskingDeleter(RefusingDeleter(), KIND).delete(PATH)

    unlink.assert_called_once_with(PATH)


def test_no_re_raises_for_the_current_file(mocker: MockerFixture) -> None:
    """Answering No leaves the refusal exactly as it came, for the caller's own handling.

    **Test steps:**

    * answer No to a refusal
    * delete through an `AskingDeleter` wrapping a refusing deleter
    * verify `NoTrashBinError` propagates
    """
    mocker.patch(QUESTION, return_value=False)

    with pytest.raises(NoTrashBinError):
        AskingDeleter(RefusingDeleter(), KIND).delete(PATH)


def test_the_question_lists_every_file_the_operation_will_delete(mocker: MockerFixture) -> None:
    """The answer is given knowing its whole reach: the question names every file, not just the one
    that happened to be refused first -- and it is put through the shared permanent-delete question,
    for this operation's kind, under the no-bin title (#313).

    **Test steps:**

    * delete through an `AskingDeleter` built with a two-file operation
    * verify the question was put for the kind and title, and names the count and both files
    """
    question = mocker.patch(QUESTION, return_value=False)

    with pytest.raises(NoTrashBinError):
        AskingDeleter(RefusingDeleter(), KIND, files=(PATH, OTHER_PATH)).delete(PATH)

    _parent, kind, title, text = question.call_args.args
    assert kind is KIND
    assert title == TITLE
    assert "2 files" in text
    assert PATH.name in text
    assert OTHER_PATH.name in text


def test_a_single_file_operation_names_the_file(mocker: MockerFixture) -> None:
    """One file is named outright rather than counted.

    **Test steps:**

    * delete through an `AskingDeleter` built with no file list
    * verify the question names the refused file and no count
    """
    question = mocker.patch(QUESTION, return_value=False)

    with pytest.raises(NoTrashBinError):
        AskingDeleter(RefusingDeleter(), KIND).delete(PATH)

    text = question.call_args.args[3]
    assert PATH.name in text
    assert "files" not in text


def test_a_yes_answers_every_later_refusal_without_asking_again(mocker: MockerFixture) -> None:
    """A bin's reach is the location's, and an operation's files share one: Yes once is Yes for all.

    **Test steps:**

    * answer Yes once, then delete a second refused file through the same instance
    * verify the question was asked only once, and both files were deleted permanently
    """
    question = mocker.patch(QUESTION, return_value=True)
    unlink = mocker.patch.object(Path, "unlink", autospec=True)
    deleter = AskingDeleter(RefusingDeleter(), KIND, files=(PATH, OTHER_PATH))

    deleter.delete(PATH)
    deleter.delete(OTHER_PATH)

    assert question.call_count == 1
    assert unlink.call_args_list == [mocker.call(PATH), mocker.call(OTHER_PATH)]


def test_a_no_answers_every_later_refusal_without_asking_again(mocker: MockerFixture) -> None:
    """Declining once is not asked again on the next file either -- the same answer, for the same
    reason, would only be a second dialog.

    **Test steps:**

    * answer No once, then delete a second refused file through the same instance
    * verify both refusals propagated and the question was asked only once
    """
    question = mocker.patch(QUESTION, return_value=False)
    deleter = AskingDeleter(RefusingDeleter(), KIND, files=(PATH, OTHER_PATH))

    with pytest.raises(NoTrashBinError):
        deleter.delete(PATH)
    with pytest.raises(NoTrashBinError):
        deleter.delete(OTHER_PATH)

    assert question.call_count == 1


def test_the_kinds_without_asking_box_skips_the_question_entirely(mocker: MockerFixture) -> None:
    """With the kind's *without asking* box ticked, a refusal never reaches the question, on any file
    (#312, #313).

    **Test steps:**

    * tick the kind's box on the shared settings
    * delete two different refused files through one `AskingDeleter` of that kind
    * verify the question was never asked, and both files were deleted permanently
    """
    question = mocker.patch(QUESTION)
    unlink = mocker.patch.object(Path, "unlink", autospec=True)
    shared_deletion_settings().set_without_asking(KIND, True)
    deleter = AskingDeleter(RefusingDeleter(), KIND)

    deleter.delete(PATH)
    deleter.delete(OTHER_PATH)

    question.assert_not_called()
    assert unlink.call_args_list == [mocker.call(PATH), mocker.call(OTHER_PATH)]


def test_the_other_kinds_box_does_not_silence_this_one(mocker: MockerFixture) -> None:
    """Each box silences its own kind of file only: the backups box says nothing about an images
    delete (#313).

    **Test steps:**

    * tick the *other* kind's box on the shared settings
    * delete through an `AskingDeleter` of this kind
    * verify the question was asked
    """
    question = mocker.patch(QUESTION, return_value=False)
    shared_deletion_settings().set_without_asking(DeletionKind.BACKUPS, True)

    with pytest.raises(NoTrashBinError):
        AskingDeleter(RefusingDeleter(), KIND).delete(PATH)

    question.assert_called_once()


def test_the_box_is_read_at_the_refusal_not_at_construction(mocker: MockerFixture) -> None:
    """A tick made after the deleter was built -- on the operation's own up-front confirm, which
    runs before the deleter is handed over -- still silences the refusal question (#313).

    **Test steps:**

    * build the deleter, then tick the kind's box
    * delete a refused file
    * verify the question was never asked, and the file was deleted permanently
    """
    question = mocker.patch(QUESTION)
    unlink = mocker.patch.object(Path, "unlink", autospec=True)
    deleter = AskingDeleter(RefusingDeleter(), KIND)
    shared_deletion_settings().set_without_asking(KIND, True)

    deleter.delete(PATH)

    question.assert_not_called()
    unlink.assert_called_once_with(PATH)


def test_a_genuine_os_error_is_not_reported_by_default(mocker: MockerFixture) -> None:
    """`report_delete_failures` off (the default) leaves a real failure to the caller's own handling.

    **Test steps:**

    * delete through an `AskingDeleter` wrapping a deleter that raises a plain ``OSError``
    * verify it propagates, and no message box was shown
    """
    critical = mocker.patch(CRITICAL)

    with pytest.raises(OSError, match="locked"):
        AskingDeleter(LockedDeleter(), KIND).delete(PATH)

    critical.assert_not_called()


def test_a_genuine_os_error_is_reported_when_asked_to(mocker: MockerFixture) -> None:
    """`report_delete_failures` on (the images dock) shows the failure by name, then still re-raises.

    **Test steps:**

    * delete through an `AskingDeleter` wrapping a deleter that raises a plain ``OSError``, reporting on
    * verify a message box named the file, and the error still propagated
    """
    critical = mocker.patch(CRITICAL)

    with pytest.raises(OSError, match="locked"):
        AskingDeleter(LockedDeleter(), KIND, report_delete_failures=True).delete(PATH)

    critical.assert_called_once()
    assert PATH.name in critical.call_args[0][2]


def test_a_failed_permanent_fallback_is_reported_too(mocker: MockerFixture) -> None:
    """Answering Yes and then having the permanent delete itself fail is a real failure, and reported
    like any other -- the fallback runs outside the refusal's handler for exactly this reason.

    **Test steps:**

    * answer Yes to a refusal, with the permanent delete refusing in its own right
    * delete through an `AskingDeleter` with reporting on
    * verify a message box named the file, and the error still propagated
    """
    mocker.patch(QUESTION, return_value=True)
    mocker.patch.object(Path, "unlink", autospec=True, side_effect=PermissionError("read-only"))
    critical = mocker.patch(CRITICAL)

    with pytest.raises(PermissionError):
        AskingDeleter(RefusingDeleter(), KIND, report_delete_failures=True).delete(PATH)

    critical.assert_called_once()
    assert PATH.name in critical.call_args[0][2]


def test_a_file_already_gone_is_re_raised_but_never_reported(mocker: MockerFixture) -> None:
    """A file that vanished between the scan and the click is a rescan, not a failure: re-raised for
    the caller's rebuild, with no box even when reporting is on.

    **Test steps:**

    * delete through an `AskingDeleter` wrapping a deleter that raises ``FileNotFoundError``, reporting on
    * verify it propagates and no message box was shown
    """
    critical = mocker.patch(CRITICAL)

    class VanishedDeleter:  # pylint: disable=too-few-public-methods
        """A `~rehuco_core.Deleter` whose file is already gone."""

        def delete(self, path: Path) -> None:
            """Report ``path`` as already gone."""
            raise FileNotFoundError(path)

    with pytest.raises(FileNotFoundError):
        AskingDeleter(VanishedDeleter(), KIND, report_delete_failures=True).delete(PATH)

    critical.assert_not_called()
