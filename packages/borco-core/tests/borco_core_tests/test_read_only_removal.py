"""Tests for removing a file or a folder that is read-only, or sits in a read-only folder."""

import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Final
from unittest.mock import Mock

import pytest
from borco_core import remove_clearing_read_only, remove_file, remove_folder
from pytest_mock import MockerFixture

READ_ONLY: Final = stat.S_IFREG | stat.S_IREAD
"""A read-only file's mode: no write bit."""

WRITABLE: Final = READ_ONLY | stat.S_IWRITE
"""The same file's mode once writable."""

READ_ONLY_FOLDER: Final = stat.S_IFDIR | 0o555
"""A read-only folder's mode, as an archive extracts it on POSIX."""


def path_with_mode(mocker: MockerFixture, mode: int) -> Mock:
    """A path whose ``stat`` reports ``mode`` and whose ``chmod`` is recorded, touching no disk.

    :param mocker: pytest-mock's fixture.
    :param mode: what ``stat`` reports.
    :returns: the path, a ``Mock`` spec'd on `Path`.
    """
    path = mocker.Mock(spec=Path)
    path.stat.return_value = SimpleNamespace(st_mode=mode)
    return path


def test_a_removal_that_goes_at_once_touches_no_attribute(mocker: MockerFixture) -> None:
    """A removal that is not refused runs once, and the path is neither read nor made writable.

    **Test steps:**

    * hand a removal that succeeds
    * verify it ran once, with no ``stat`` and no ``chmod``
    """
    path = path_with_mode(mocker, READ_ONLY)
    removal = mocker.Mock()

    remove_clearing_read_only(path, removal)

    removal.assert_called_once()
    path.stat.assert_not_called()
    path.chmod.assert_not_called()


def test_a_read_only_path_refused_is_made_writable_and_removed(mocker: MockerFixture) -> None:
    """A removal refused on a read-only path makes it writable and runs again, which removes it.

    **Test steps:**

    * hand a read-only path and a removal refused once, then allowed
    * verify it ran twice, and the path was made writable once, keeping the rest of its mode
    """
    path = path_with_mode(mocker, READ_ONLY)
    removal = mocker.Mock(side_effect=[PermissionError("read-only"), None])

    remove_clearing_read_only(path, removal)

    assert removal.call_count == 2
    path.chmod.assert_called_once_with(WRITABLE)


def test_a_writable_path_refused_raises_the_refusal_untouched(mocker: MockerFixture) -> None:
    """A writable path that is refused -- held open elsewhere -- is not made anything, and its refusal is raised.

    **Test steps:**

    * hand a writable path and a removal always refused
    * verify the refusal is raised after one try, with no ``chmod``
    """
    path = path_with_mode(mocker, WRITABLE)
    removal = mocker.Mock(side_effect=PermissionError("held"))

    with pytest.raises(PermissionError, match="held"):
        remove_clearing_read_only(path, removal)

    removal.assert_called_once()
    path.chmod.assert_not_called()


def test_a_read_only_path_still_refused_gets_its_attribute_back(mocker: MockerFixture) -> None:
    """A read-only path refused again once writable -- a held file, a folder not empty -- is made read-only again,
    and the second refusal is raised.

    **Test steps:**

    * hand a read-only path and a removal refused, then failing as not empty
    * verify the second failure is raised, and the path was made writable, then given its old mode back
    """
    path = path_with_mode(mocker, READ_ONLY)
    removal = mocker.Mock(side_effect=[PermissionError("read-only"), OSError("not empty")])

    with pytest.raises(OSError, match="not empty"):
        remove_clearing_read_only(path, removal)

    assert path.chmod.call_args_list == [mocker.call(WRITABLE), mocker.call(READ_ONLY)]


def test_an_attribute_that_will_not_come_back_leaves_the_second_refusal_raised(mocker: MockerFixture) -> None:
    """Putting the mode back is a best effort: a failure there does not hide why the removal failed.

    **Test steps:**

    * hand a read-only path refused twice, whose second ``chmod`` fails
    * verify the second refusal is what is raised
    """
    path = path_with_mode(mocker, READ_ONLY)
    path.chmod.side_effect = [None, OSError("gone")]
    removal = mocker.Mock(side_effect=[PermissionError("read-only"), PermissionError("held")])

    with pytest.raises(PermissionError, match="held"):
        remove_clearing_read_only(path, removal)


def test_a_path_that_cannot_be_read_raises_the_first_refusal(mocker: MockerFixture) -> None:
    """A refused path whose mode cannot be read is not made writable: the refusal is raised as it came.

    **Test steps:**

    * hand a path whose ``stat`` fails, and a removal refused
    * verify that refusal is raised after one try, with no ``chmod``
    """
    path = path_with_mode(mocker, READ_ONLY)
    path.stat.side_effect = OSError("unreadable")
    removal = mocker.Mock(side_effect=PermissionError("refused"))

    with pytest.raises(PermissionError, match="refused") as caught:
        remove_clearing_read_only(path, removal)

    assert caught.value.__suppress_context__
    removal.assert_called_once()
    path.chmod.assert_not_called()


def test_a_path_that_cannot_be_made_writable_raises_the_refusal(mocker: MockerFixture) -> None:
    """A refused read-only path whose attribute cannot be cleared -- a share denying it -- raises the refusal itself,
    chained to why it could not be cleared, and is not tried again.

    **Test steps:**

    * hand a read-only path whose ``chmod`` fails, and a removal refused
    * verify that refusal is raised after one try, its cause the ``chmod``'s failure
    """
    path = path_with_mode(mocker, READ_ONLY)
    path.chmod.side_effect = OSError("attributes denied")
    removal = mocker.Mock(side_effect=PermissionError("refused"))

    with pytest.raises(PermissionError, match="refused") as caught:
        remove_clearing_read_only(path, removal)

    assert str(caught.value.__cause__) == "attributes denied"
    removal.assert_called_once()


def test_another_failure_passes_straight_through(mocker: MockerFixture) -> None:
    """Only a refusal is answered: any other failure is the removal's own, raised at once.

    **Test steps:**

    * hand a removal that raises ``FileNotFoundError``
    * verify it raises after one try, with no ``stat``
    """
    path = path_with_mode(mocker, READ_ONLY)
    removal = mocker.Mock(side_effect=FileNotFoundError)

    with pytest.raises(FileNotFoundError):
        remove_clearing_read_only(path, removal)

    removal.assert_called_once()
    path.stat.assert_not_called()


def test_a_path_found_gone_once_refused_is_gone_not_refused(mocker: MockerFixture) -> None:
    """A refused path that is gone when it is read -- removed meanwhile, or delete-pending -- raises
    ``FileNotFoundError``, not the refusal.

    **Test steps:**

    * hand a path whose ``stat`` finds nothing, and a removal refused
    * verify ``FileNotFoundError`` is raised after one try, with no ``chmod``
    """
    path = path_with_mode(mocker, READ_ONLY)
    path.stat.side_effect = FileNotFoundError("gone")
    removal = mocker.Mock(side_effect=PermissionError("refused"))

    with pytest.raises(FileNotFoundError, match="gone"):
        remove_clearing_read_only(path, removal)

    removal.assert_called_once()
    path.chmod.assert_not_called()


def test_a_path_gone_before_it_is_made_writable_is_gone_not_refused(mocker: MockerFixture) -> None:
    """A read-only path that is gone by the time it is made writable raises ``FileNotFoundError``, not the refusal.

    **Test steps:**

    * hand a read-only path whose ``chmod`` finds nothing, and a removal refused
    * verify ``FileNotFoundError`` is raised after one try
    """
    path = path_with_mode(mocker, READ_ONLY)
    path.chmod.side_effect = FileNotFoundError("gone")
    removal = mocker.Mock(side_effect=PermissionError("refused"))

    with pytest.raises(FileNotFoundError, match="gone"):
        remove_clearing_read_only(path, removal)

    removal.assert_called_once()


@pytest.mark.parametrize("missing_ok", [False, True])
def test_a_file_is_unlinked(mocker: MockerFixture, missing_ok: bool) -> None:
    """``remove_file`` unlinks a file that is there, whatever ``missing_ok`` says.

    **Test steps:**

    * remove a file, with ``missing_ok`` off and on
    * verify ``unlink`` was called once
    """
    path = path_with_mode(mocker, WRITABLE)

    remove_file(path, missing_ok=missing_ok)

    path.unlink.assert_called_once_with()


@pytest.mark.parametrize(
    "unlinks",
    [
        pytest.param([FileNotFoundError("gone")], id="already gone"),
        pytest.param([PermissionError("read-only"), FileNotFoundError("gone")], id="gone once writable"),
    ],
)
def test_a_file_gone_is_no_failure_only_when_missing_ok(mocker: MockerFixture, unlinks: list[OSError]) -> None:
    """A file already gone, or gone by the second try, is no failure with ``missing_ok`` on, and raises with it off.

    **Test steps:**

    * remove a read-only file whose unlinks answer ``unlinks``, with ``missing_ok`` on
    * verify nothing is raised
    * remove it again, with ``missing_ok`` off, and verify ``FileNotFoundError`` is raised
    """
    path = path_with_mode(mocker, READ_ONLY)
    path.unlink.side_effect = unlinks

    remove_file(path, missing_ok=True)

    path.unlink.side_effect = unlinks
    with pytest.raises(FileNotFoundError, match="gone"):
        remove_file(path)


def test_a_read_only_folder_refused_is_made_writable_and_removed(mocker: MockerFixture) -> None:
    """``remove_folder`` removes the folder, a read-only one refused at first made writable.

    **Test steps:**

    * remove a read-only folder whose ``rmdir`` is refused once
    * verify ``rmdir`` ran twice, and the folder was made writable
    """
    path = path_with_mode(mocker, stat.S_IFDIR | stat.S_IREAD)
    path.rmdir.side_effect = [PermissionError("read-only"), None]

    remove_folder(path)

    assert path.rmdir.call_count == 2
    path.chmod.assert_called_once_with(stat.S_IFDIR | stat.S_IREAD | stat.S_IWRITE)


def in_folder(mocker: MockerFixture, path: Mock, mode: int) -> Mock:
    """Give ``path`` a folder holding it, whose ``stat`` reports ``mode``.

    :param mocker: pytest-mock's fixture.
    :param path: the path, from :func:`path_with_mode`.
    :param mode: what the folder's ``stat`` reports.
    :returns: the folder.
    """
    folder = path_with_mode(mocker, mode)
    path.parent = folder
    return folder


def test_a_path_in_a_read_only_folder_of_ours_is_removed_and_the_folder_given_back(mocker: MockerFixture) -> None:
    """POSIX asks the folder holding a path: a writable file in a read-only folder the caller owns is removed with
    that folder made writable for the moment, which then gets its mode back.

    **Test steps:**

    * hand a writable file in a read-only folder that is the caller's, refused once, then allowed
    * verify it ran twice, the file was never changed, and the folder was made writable, then given back
    """
    path = path_with_mode(mocker, WRITABLE)
    folder = in_folder(mocker, path, READ_ONLY_FOLDER)
    removal = mocker.Mock(side_effect=[PermissionError("folder read-only"), None])

    remove_clearing_read_only(path, removal, parent_is_ours=True)

    assert removal.call_count == 2
    path.chmod.assert_not_called()
    assert folder.chmod.call_args_list == [mocker.call(READ_ONLY_FOLDER | stat.S_IWRITE), mocker.call(READ_ONLY_FOLDER)]


def test_a_folder_that_is_not_ours_is_never_read(mocker: MockerFixture) -> None:
    """The folder holding a path is changed only when the caller says it is its own: otherwise it is not even read,
    and a writable path refused raises its refusal.

    **Test steps:**

    * hand a writable file in a read-only folder that is not the caller's, and a removal refused
    * verify the refusal is raised after one try, the folder neither read nor changed
    """
    path = path_with_mode(mocker, WRITABLE)
    folder = in_folder(mocker, path, READ_ONLY_FOLDER)
    removal = mocker.Mock(side_effect=PermissionError("folder read-only"))

    with pytest.raises(PermissionError, match="folder read-only"):
        remove_clearing_read_only(path, removal)

    removal.assert_called_once()
    folder.stat.assert_not_called()
    folder.chmod.assert_not_called()


def test_a_path_and_its_folder_still_refused_both_get_their_modes_back(mocker: MockerFixture) -> None:
    """A read-only file in a read-only folder of ours refused again once both are writable gets both modes back.

    **Test steps:**

    * hand a read-only file in a read-only folder of the caller's, refused twice
    * verify the second refusal is raised, and each was made writable, then given back
    """
    path = path_with_mode(mocker, READ_ONLY)
    folder = in_folder(mocker, path, READ_ONLY_FOLDER)
    removal = mocker.Mock(side_effect=[PermissionError("read-only"), PermissionError("held")])

    with pytest.raises(PermissionError, match="held"):
        remove_clearing_read_only(path, removal, parent_is_ours=True)

    assert path.chmod.call_args_list == [mocker.call(WRITABLE), mocker.call(READ_ONLY)]
    assert folder.chmod.call_args_list == [mocker.call(READ_ONLY_FOLDER | stat.S_IWRITE), mocker.call(READ_ONLY_FOLDER)]


def test_a_folder_that_cannot_be_made_writable_gives_the_path_its_mode_back(mocker: MockerFixture) -> None:
    """When the folder will not be made writable after the path was, the path gets its mode back, and the refusal is
    raised, chained to why.

    **Test steps:**

    * hand a read-only file in a read-only folder of the caller's, the folder's ``chmod`` failing
    * verify the refusal is raised after one try, and the file was made writable, then given back
    """
    path = path_with_mode(mocker, READ_ONLY)
    folder = in_folder(mocker, path, READ_ONLY_FOLDER)
    folder.chmod.side_effect = OSError("attributes denied")
    removal = mocker.Mock(side_effect=PermissionError("refused"))

    with pytest.raises(PermissionError, match="refused") as caught:
        remove_clearing_read_only(path, removal, parent_is_ours=True)

    assert str(caught.value.__cause__) == "attributes denied"
    removal.assert_called_once()
    assert path.chmod.call_args_list == [mocker.call(WRITABLE), mocker.call(READ_ONLY)]


def test_a_folder_gone_once_refused_is_gone_not_refused(mocker: MockerFixture) -> None:
    """A folder holding the path that is gone once the path was refused means the path is gone too.

    **Test steps:**

    * hand a file in a folder of the caller's whose ``stat`` finds nothing, and a removal refused
    * verify ``FileNotFoundError`` is raised after one try, nothing changed
    """
    path = path_with_mode(mocker, READ_ONLY)
    folder = in_folder(mocker, path, READ_ONLY_FOLDER)
    folder.stat.side_effect = FileNotFoundError("gone")
    removal = mocker.Mock(side_effect=PermissionError("refused"))

    with pytest.raises(FileNotFoundError, match="gone"):
        remove_clearing_read_only(path, removal, parent_is_ours=True)

    removal.assert_called_once()
    path.chmod.assert_not_called()


def test_remove_file_hands_on_whose_the_folder_is(mocker: MockerFixture) -> None:
    """``remove_file`` makes a read-only folder of the caller's writable for the unlink.

    **Test steps:**

    * remove a writable file in a read-only folder of the caller's, its unlink refused once
    * verify the folder was made writable, then given back
    """
    path = path_with_mode(mocker, WRITABLE)
    folder = in_folder(mocker, path, READ_ONLY_FOLDER)
    path.unlink.side_effect = [PermissionError("folder read-only"), None]

    remove_file(path, parent_is_ours=True)

    assert folder.chmod.call_args_list == [mocker.call(READ_ONLY_FOLDER | stat.S_IWRITE), mocker.call(READ_ONLY_FOLDER)]


def test_remove_folder_hands_on_whose_the_folder_is(mocker: MockerFixture) -> None:
    """``remove_folder`` makes a read-only folder of the caller's writable for the ``rmdir``.

    **Test steps:**

    * remove a writable folder in a read-only folder of the caller's, its ``rmdir`` refused once
    * verify the folder holding it was made writable, then given back
    """
    path = path_with_mode(mocker, stat.S_IFDIR | 0o755)
    folder = in_folder(mocker, path, READ_ONLY_FOLDER)
    path.rmdir.side_effect = [PermissionError("folder read-only"), None]

    remove_folder(path, parent_is_ours=True)

    assert folder.chmod.call_args_list == [mocker.call(READ_ONLY_FOLDER | stat.S_IWRITE), mocker.call(READ_ONLY_FOLDER)]
