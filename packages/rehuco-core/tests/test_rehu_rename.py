"""Tests for renaming a `.rehu` resource on disk ([[plugins#toolkit-surfaces]]'s execute step)."""

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from pytest import mark, param, raises
from pytest_mock import MockerFixture
from rehuco_core import PartialRenameError, rename_rehu_resource

DIRECTORY: Final = Path("/fake/library")
FOLDER: Final = DIRECTORY / "old_folder"
INFO_PATH: Final = FOLDER / "info.rehu"
FILE_PATH: Final = DIRECTORY / "old_file.rehu"
NEW_NAME: Final = "new_name"

SIBLINGS: Final = (FILE_PATH, DIRECTORY / "old_file00.jpg", DIRECTORY / "old_file01.png")
"""The file-scoped fixture's default directory listing: the `.rehu` and two screenshots."""

SCREENSHOTS: Final = SIBLINGS[1:]


def mock_environment(
    mocker: MockerFixture,
    *,
    existing: frozenset[Path] = frozenset(),
    siblings: Sequence[Path] = SIBLINGS,
    directories: frozenset[Path] = frozenset(),
    absent: frozenset[Path] = frozenset(),
    listing_error: OSError | None = None,
    rename_side_effect: Any = None,
) -> Any:
    """Mock every filesystem touchpoint the renamer uses.

    :param mocker: pytest-mock fixture.
    :param existing: paths that should report as already occupying a rename destination.
    :param siblings: the whole directory listing to hand back for a file-scoped resource.
    :param directories: which of those entries are directories rather than files.
    :param absent: paths that should report as **not** on disk (the source-exists check).
    :param listing_error: raised instead of handing back ``siblings``, for a directory that cannot be
        listed -- or to prove a code path never lists one at all.
    :param rename_side_effect: optional ``side_effect`` for the rename mock (e.g. to fail part-way).
    :returns: the ``Path.rename`` mock, whose calls are the whole record of what moved.
    """
    mocker.patch.object(Path, "exists", autospec=True, side_effect=lambda self: self in existing)
    mocker.patch.object(Path, "is_dir", autospec=True, side_effect=lambda self: self in directories)
    mocker.patch.object(
        Path, "is_file", autospec=True, side_effect=lambda self: self not in directories and self not in absent
    )
    mocker.patch.object(
        Path,
        "iterdir",
        autospec=True,
        side_effect=listing_error or (lambda self: list(siblings)),
    )
    return mocker.patch.object(Path, "rename", autospec=True, side_effect=rename_side_effect)


def renames(mock_rename: Any) -> list[tuple[Path, Path]]:
    """The ``(source, destination)`` pairs a ``Path.rename`` mock actually recorded.

    :param mock_rename: the autospec'd ``Path.rename`` mock (``self`` is its first argument).
    :returns: one pair per call, in call order.
    """
    return [(call.args[0], call.args[1]) for call in mock_rename.call_args_list]


# region directory-scoped renames
def test_directory_scoped_renames_the_parent_directory(mocker: MockerFixture) -> None:
    """An ``info.rehu`` renames its **parent directory** -- one rename, carrying everything inside it.

    **Test steps:**

    * rename a directory-scoped resource
    * verify the single rename moved the folder, not the `.rehu`, and the new `info.rehu` path came back
    """
    mock_rename = mock_environment(mocker)

    result = rename_rehu_resource(INFO_PATH, NEW_NAME)

    assert renames(mock_rename) == [(FOLDER, DIRECTORY / NEW_NAME)]
    assert result == DIRECTORY / NEW_NAME / "info.rehu"


def test_directory_scoped_never_lists_the_directory(mocker: MockerFixture) -> None:
    """A directory rename carries everything inside it, so its contents are never enumerated.

    **Test steps:**

    * make any attempt to list a directory raise
    * rename a directory-scoped resource
    * verify it succeeded, so no listing was ever attempted
    """
    mock_rename = mock_environment(mocker, listing_error=OSError("the directory must not be listed"))

    rename_rehu_resource(INFO_PATH, NEW_NAME)

    assert renames(mock_rename) == [(FOLDER, DIRECTORY / NEW_NAME)]


def test_directory_scoped_collision_is_refused_before_anything_moves(mocker: MockerFixture) -> None:
    """A directory already sitting at the destination refuses the rename with nothing touched.

    **Test steps:**

    * mock the destination folder as already existing
    * rename, expecting ``FileExistsError``
    * verify nothing was renamed
    """
    mock_rename = mock_environment(mocker, existing=frozenset({DIRECTORY / NEW_NAME}))

    with raises(FileExistsError):
        rename_rehu_resource(INFO_PATH, NEW_NAME)

    mock_rename.assert_not_called()


# endregion


# region file-scoped renames
def test_file_scoped_renames_every_file_named_after_the_resource(mocker: MockerFixture) -> None:
    """A standalone ``foo.rehu`` renames everything named after it -- the record, its screenshots, its
    checksum manifest, and the content itself, whether one archive or a multi-part set -- since being
    named after it is the only thing tying them together ([[data-model#resource-scoping]]).

    **Test steps:**

    * list a `.rehu` beside two screenshots, an `.sfv`, a `.zip`, a two-part `.001`/`.002` set, an
      indexed non-image, and a file carrying the bare stem
    * rename
    * verify all eight moved, the `.rehu` first and the rest sorted, each keeping its own tail
    * verify the new `.rehu` path came back
    """
    mock_rename = mock_environment(
        mocker,
        siblings=[
            FILE_PATH,
            *SCREENSHOTS,
            DIRECTORY / "old_file.sfv",
            DIRECTORY / "old_file.zip",
            DIRECTORY / "old_file.001",
            DIRECTORY / "old_file.002",
            DIRECTORY / "old_file02.txt",
            DIRECTORY / "old_file",
            DIRECTORY / "unrelated.zip",
        ],
    )

    result = rename_rehu_resource(FILE_PATH, NEW_NAME)

    assert renames(mock_rename) == [
        (FILE_PATH, DIRECTORY / f"{NEW_NAME}.rehu"),
        (DIRECTORY / "old_file", DIRECTORY / NEW_NAME),
        (DIRECTORY / "old_file.001", DIRECTORY / f"{NEW_NAME}.001"),
        (DIRECTORY / "old_file.002", DIRECTORY / f"{NEW_NAME}.002"),
        (DIRECTORY / "old_file.sfv", DIRECTORY / f"{NEW_NAME}.sfv"),
        (DIRECTORY / "old_file.zip", DIRECTORY / f"{NEW_NAME}.zip"),
        (SCREENSHOTS[0], DIRECTORY / f"{NEW_NAME}00.jpg"),
        (SCREENSHOTS[1], DIRECTORY / f"{NEW_NAME}01.png"),
        (DIRECTORY / "old_file02.txt", DIRECTORY / f"{NEW_NAME}02.txt"),
    ]
    assert result == DIRECTORY / f"{NEW_NAME}.rehu"


def test_file_scoped_leaves_a_coincidental_prefix_alone(mocker: MockerFixture) -> None:
    """A name that merely *starts* like the resource is a different name, not one of its files: what
    follows the stem must be an extension separator or a digit, never more letters.

    **Test steps:**

    * list ``old_filebar.zip``, ``old_file_extras.txt`` and ``old_file notes.md`` beside the resource
    * rename
    * verify only the `.rehu` moved -- no `.rehu` sits beside those three to mark them as anyone's, and
      the naming rule alone is what leaves them be
    """
    mock_rename = mock_environment(
        mocker,
        siblings=[
            FILE_PATH,
            DIRECTORY / "old_filebar.zip",
            DIRECTORY / "old_file_extras.txt",
            DIRECTORY / "old_file notes.md",
        ],
    )

    rename_rehu_resource(FILE_PATH, NEW_NAME)

    assert renames(mock_rename) == [(FILE_PATH, DIRECTORY / f"{NEW_NAME}.rehu")]


def test_file_scoped_skips_directories(mocker: MockerFixture) -> None:
    """A directory named after the resource is still left alone: a file-scoped `.rehu` describes
    **files**, and a folder beside it is either a resource of its own or nothing to do with this one.

    **Test steps:**

    * list an ``old_file.parts`` **directory** -- named after the resource by every other rule, so only
      being a directory can keep it out -- beside the resource's own files
    * rename
    * verify the directory was not renamed and the files were
    """
    extras = DIRECTORY / "old_file.parts"
    mock_rename = mock_environment(
        mocker, siblings=[FILE_PATH, extras, DIRECTORY / "old_file.zip"], directories=frozenset({extras})
    )

    rename_rehu_resource(FILE_PATH, NEW_NAME)

    assert renames(mock_rename) == [
        (FILE_PATH, DIRECTORY / f"{NEW_NAME}.rehu"),
        (DIRECTORY / "old_file.zip", DIRECTORY / f"{NEW_NAME}.zip"),
    ]


def test_file_scoped_leaves_another_records_files_alone(mocker: MockerFixture) -> None:
    """With ``old_file.rehu`` and ``old_file2.rehu`` side by side, renaming the first must not drag the
    second's whole set along -- a sibling `.rehu` whose stem extends this one's owns everything under
    that longer stem.

    **Test steps:**

    * list ``old_file2.rehu`` and its own screenshot and archive among the stem's siblings
    * rename ``old_file``
    * verify only this resource's own files moved
    """
    mock_rename = mock_environment(
        mocker,
        siblings=[
            FILE_PATH,
            DIRECTORY / "old_file.zip",
            DIRECTORY / "old_file2.rehu",
            DIRECTORY / "old_file200.jpg",
            DIRECTORY / "old_file2.zip",
        ],
    )

    rename_rehu_resource(FILE_PATH, NEW_NAME)

    assert renames(mock_rename) == [
        (FILE_PATH, DIRECTORY / f"{NEW_NAME}.rehu"),
        (DIRECTORY / "old_file.zip", DIRECTORY / f"{NEW_NAME}.zip"),
    ]


def test_file_scoped_keeps_a_siblings_own_case_spelling(mocker: MockerFixture) -> None:
    """A sibling whose stem is spelled in another case keeps its own tail verbatim -- only the stem is
    replaced. (Matching folds case exactly where the filesystem does, via ``normcase``.)

    **Test steps:**

    * force Windows-style case folding and list an ``OLD_FILE02.JPG`` sibling
    * rename
    * verify its destination is the new stem plus that same ``02.JPG`` tail
    """
    mocker.patch.object(os.path, "normcase", side_effect=lambda path: str(path).lower())
    odd = DIRECTORY / "OLD_FILE02.JPG"
    mock_rename = mock_environment(mocker, siblings=[FILE_PATH, odd])

    rename_rehu_resource(FILE_PATH, NEW_NAME)

    assert (odd, DIRECTORY / f"{NEW_NAME}02.JPG") in renames(mock_rename)


def test_file_scoped_collision_on_a_screenshot_refuses_the_whole_plan(mocker: MockerFixture) -> None:
    """A collision on the *last* screenshot still refuses before the **first** rename runs -- the plan
    is checked whole, so a sibling set is never half-moved by a foreseeable clash.

    **Test steps:**

    * mock only the second screenshot's destination as already existing
    * rename, expecting ``FileExistsError``
    * verify nothing was renamed at all
    """
    mock_rename = mock_environment(mocker, existing=frozenset({DIRECTORY / f"{NEW_NAME}01.png"}))

    with raises(FileExistsError) as error:
        rename_rehu_resource(FILE_PATH, NEW_NAME)

    assert f"{NEW_NAME}01.png" in str(error.value)
    mock_rename.assert_not_called()


# endregion


# region a resource that is not there
@mark.parametrize(
    ("path", "scope"),
    [
        param(INFO_PATH, "directory-scoped", id="directory-scoped"),
        param(FILE_PATH, "file-scoped", id="file-scoped"),
    ],
)
def test_a_missing_rehu_is_refused_before_anything_is_attempted(mocker: MockerFixture, path: Path, scope: str) -> None:
    """A resource whose `.rehu` is gone is not renamed at all, in either scope: a missing record's
    remedy is a re-read, never a rename of whatever else still carries its name.

    **Test steps:**

    * mock the `.rehu` as absent
    * rename, expecting ``FileNotFoundError``
    * verify nothing was renamed
    """
    assert scope
    mock_rename = mock_environment(mocker, absent=frozenset({path}))

    with raises(FileNotFoundError):
        rename_rehu_resource(path, NEW_NAME)

    mock_rename.assert_not_called()


def test_a_missing_rehu_is_refused_even_for_a_no_op_rename(mocker: MockerFixture) -> None:
    """The existence check runs **before** the same-name shortcut, so a missing resource is reported as
    missing rather than quietly reported as "nothing to do".

    **Test steps:**

    * mock the `.rehu` as absent and rename it to the name it already has
    * verify ``FileNotFoundError`` came back rather than a no-op success
    """
    mock_environment(mocker, absent=frozenset({FILE_PATH}))

    with raises(FileNotFoundError):
        rename_rehu_resource(FILE_PATH, FILE_PATH.stem)


def test_an_unlistable_directory_moves_nothing(mocker: MockerFixture) -> None:
    """A directory that cannot be listed (an offline mount) fails the plan, so nothing is renamed --
    a partial listing must never become a partial rename.

    **Test steps:**

    * make ``iterdir`` raise ``OSError``
    * rename a file-scoped resource, expecting that error
    * verify nothing was renamed
    """
    mock_rename = mock_environment(mocker, listing_error=OSError("offline mount"))

    with raises(OSError):
        rename_rehu_resource(FILE_PATH, NEW_NAME)

    mock_rename.assert_not_called()


# endregion


# region name handling
@mark.parametrize(
    "new_name",
    [
        param("", id="empty"),
        param(".", id="dot"),
        param("..", id="parent"),
        param("sub/name", id="separator"),
    ],
)
def test_a_name_that_is_not_a_plain_filename_is_refused(mocker: MockerFixture, new_name: str) -> None:
    """Only a plain file/folder name is accepted; anything reaching outside the resource's own
    directory is refused before the plan is even built.

    **Test steps:**

    * rename to each rejected name, expecting ``ValueError``
    * verify nothing was renamed
    """
    mock_rename = mock_environment(mocker)

    with raises(ValueError):
        rename_rehu_resource(FILE_PATH, new_name)

    mock_rename.assert_not_called()


def test_renaming_to_the_current_name_touches_nothing(mocker: MockerFixture) -> None:
    """Renaming a resource to the name it already has is a no-op success, not an error.

    **Test steps:**

    * rename a directory-scoped resource to its own folder name
    * verify the original path came back and nothing was renamed
    """
    mock_rename = mock_environment(mocker)

    assert rename_rehu_resource(INFO_PATH, FOLDER.name) == INFO_PATH

    mock_rename.assert_not_called()


def test_a_case_only_rename_is_performed_not_read_as_a_collision(mocker: MockerFixture) -> None:
    """Recasing a name (``old_folder`` -> ``OLD_FOLDER``) is a real rename: on a case-insensitive
    filesystem the destination "exists" because it *is* the source, which is not a collision.

    **Test steps:**

    * mock the destination folder as existing (what Windows reports for a case-only rename)
    * rename to the same name in another case
    * verify the rename ran rather than being refused
    """
    recased = FOLDER.name.upper()
    mock_rename = mock_environment(mocker, existing=frozenset({DIRECTORY / recased}))
    mocker.patch.object(os.path, "normcase", side_effect=lambda path: str(path).lower())

    result = rename_rehu_resource(INFO_PATH, recased)

    assert renames(mock_rename) == [(FOLDER, DIRECTORY / recased)]
    assert result == DIRECTORY / recased / "info.rehu"


# endregion


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
