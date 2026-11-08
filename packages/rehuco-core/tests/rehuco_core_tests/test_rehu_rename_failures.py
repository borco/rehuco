"""Tests for renaming a `.rehu` resource on disk when a step fails: rollback, and retries over transient locks.

Split from ``test_rehu_rename.py``, whose fake filesystem it uses.
"""

from pytest import raises
from pytest_mock import MockerFixture
from rehuco_core import PartialRenameError, rename_rehu_resource
from rehuco_core.rehu_rename import RETRY_DELAYS

from rehuco_core_tests.test_rehu_rename import (
    DIRECTORY,
    FILE_PATH,
    FOLDER,
    INFO_PATH,
    NEW_NAME,
    SCREENSHOTS,
    mock_environment,
    renames,
)


# region failure and rollback
def test_a_failure_part_way_rolls_the_completed_renames_back(mocker: MockerFixture) -> None:
    """A sibling set whose second rename fails puts the first back under its original name and
    re-raises, so the resource is left exactly as it was.

    **Test steps:**

    * fail the second of three renames with ``PermissionError``
    * rename, expecting that error back
    * verify the `.rehu` was renamed, then renamed back, and the third was never attempted
    """
    failure = PermissionError("denied")
    mock_rename = mock_environment(mocker, rename_side_effect=[None, failure, None])

    with raises(PermissionError):
        rename_rehu_resource(FILE_PATH, NEW_NAME)

    assert renames(mock_rename) == [
        (FILE_PATH, DIRECTORY / f"{NEW_NAME}.rehu"),
        (SCREENSHOTS[0], DIRECTORY / f"{NEW_NAME}00.jpg"),
        (DIRECTORY / f"{NEW_NAME}.rehu", FILE_PATH),
    ]


def test_the_rollback_undoes_the_completed_renames_most_recent_first(mocker: MockerFixture) -> None:
    """The rollback walks the completed steps in reverse -- the mirror image of how they ran.

    **Test steps:**

    * fail the **third** of three renames
    * rename, expecting the error back
    * verify the two restores ran newest-first
    """
    mock_rename = mock_environment(mocker, rename_side_effect=[None, None, OSError("boom"), None, None])

    with raises(OSError):
        rename_rehu_resource(FILE_PATH, NEW_NAME)

    assert renames(mock_rename)[3:] == [
        (DIRECTORY / f"{NEW_NAME}00.jpg", SCREENSHOTS[0]),
        (DIRECTORY / f"{NEW_NAME}.rehu", FILE_PATH),
    ]


def test_a_rollback_that_itself_fails_raises_partial_rename_error(mocker: MockerFixture) -> None:
    """When a restore is refused too, the resource really is split between both names -- reported as
    :class:`~rehuco_core.PartialRenameError`, naming the stranded file and carrying the original
    failure as its cause.

    **Test steps:**

    * fail the second rename, then fail the restore of the first
    * rename, expecting ``PartialRenameError``
    * verify the message names the stranded file and both names, and the cause is the original failure
    """
    failure = PermissionError("denied")
    mock_environment(mocker, rename_side_effect=[None, failure, OSError("still locked")])

    with raises(PartialRenameError) as error:
        rename_rehu_resource(FILE_PATH, NEW_NAME)

    assert f"{NEW_NAME}.rehu" in str(error.value)
    assert "old_file" in str(error.value)
    assert error.value.__cause__ is failure


def test_a_rollback_restores_every_file_it_still_can(mocker: MockerFixture) -> None:
    """One refused restore does not abandon the rest: every completed step is still attempted, so the
    rollback recovers as much as the filesystem allows before reporting what it could not.

    **Test steps:**

    * fail the third rename, then fail only the *first* restore attempted
    * rename, expecting ``PartialRenameError``
    * verify the second restore was attempted anyway
    """
    mock_rename = mock_environment(mocker, rename_side_effect=[None, None, OSError("boom"), OSError("locked"), None])

    with raises(PartialRenameError):
        rename_rehu_resource(FILE_PATH, NEW_NAME)

    assert renames(mock_rename)[-1] == (DIRECTORY / f"{NEW_NAME}.rehu", FILE_PATH)


# endregion


# region transient locks (#355)
def locked(winerror: int) -> PermissionError:
    """A refusal carrying a Windows error code, whatever platform the suite runs on.

    Set as an attribute rather than passed to the constructor: ``OSError``'s fourth argument only
    becomes ``winerror`` on Windows, and the suite also runs on Linux.

    :param winerror: the Windows error code.
    :returns: the error.
    """
    error = PermissionError(13, "The process cannot access the file because it is being used by another process")
    setattr(error, "winerror", winerror)
    return error


def test_a_step_refused_over_a_transient_lock_is_retried(mocker: MockerFixture) -> None:
    """A scanner briefly holding a freshly written file costs a short wait, not a failed rename.

    **Test steps:**

    * refuse the folder rename twice with a sharing violation, then let it through
    * rename a directory-scoped resource
    * verify it succeeded on the third try, after two short waits
    """
    sleep = mocker.patch("rehuco_core.rehu_rename.time.sleep")
    mock_rename = mock_environment(mocker, rename_side_effect=[locked(32), locked(5), None])

    result = rename_rehu_resource(INFO_PATH, NEW_NAME)

    assert result == DIRECTORY / NEW_NAME / "info.rehu"
    assert renames(mock_rename) == [(FOLDER, DIRECTORY / NEW_NAME)] * 3
    assert sleep.call_count == 2


def test_a_lock_that_outlasts_the_retries_fails_the_rename(mocker: MockerFixture) -> None:
    """A lock that is not transient -- an Explorer window open on the folder -- is reported once the
    retries run out, with nothing moved.

    **Test steps:**

    * refuse every folder rename with a sharing violation
    * rename, expecting that error
    * verify the retries were bounded and each waited
    """
    sleep = mocker.patch("rehuco_core.rehu_rename.time.sleep")
    refusal = locked(32)
    mock_rename = mock_environment(mocker, rename_side_effect=refusal)

    with raises(PermissionError) as raised:
        rename_rehu_resource(INFO_PATH, NEW_NAME)

    assert raised.value is refusal
    assert len(renames(mock_rename)) == len(RETRY_DELAYS) + 1
    assert [call.args[0] for call in sleep.call_args_list] == list(RETRY_DELAYS)


def test_a_rollback_step_refused_over_a_transient_lock_is_retried_too(mocker: MockerFixture) -> None:
    """A scanner opening a file right after its forward rename must not turn a clean rollback into a
    split resource.

    **Test steps:**

    * fail the third forward rename for good, then refuse the first restore once with a sharing violation
    * rename, expecting the original failure and no ``PartialRenameError``
    * verify both completed steps were put back, the refused one on its second try, after one wait
    """
    sleep = mocker.patch("rehuco_core.rehu_rename.time.sleep")
    mock_rename = mock_environment(mocker, rename_side_effect=[None, None, OSError("boom"), locked(32), None, None])

    with raises(OSError, match="boom"):
        rename_rehu_resource(FILE_PATH, NEW_NAME)

    restores = renames(mock_rename)[3:]
    assert restores[0] == restores[1] == (DIRECTORY / f"{NEW_NAME}00.jpg", SCREENSHOTS[0])
    assert restores[2] == (DIRECTORY / f"{NEW_NAME}.rehu", FILE_PATH)
    assert sleep.call_count == 1


def test_an_error_no_wait_changes_is_not_retried(mocker: MockerFixture) -> None:
    """Only a lock is worth waiting out; any other refusal is a fact about the rename.

    **Test steps:**

    * refuse the folder rename with an error carrying no transient Windows code
    * rename, expecting that error
    * verify it was tried once and never waited
    """
    sleep = mocker.patch("rehuco_core.rehu_rename.time.sleep")
    mock_rename = mock_environment(mocker, rename_side_effect=PermissionError(13, "Permission denied"))

    with raises(PermissionError):
        rename_rehu_resource(INFO_PATH, NEW_NAME)

    assert len(renames(mock_rename)) == 1
    sleep.assert_not_called()


# endregion
