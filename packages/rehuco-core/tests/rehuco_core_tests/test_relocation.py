"""Tests for the executed plan of a rename, read back the other way (#376).

Pure path arithmetic: nothing here touches a filesystem, so nothing is mocked either.
"""

from pathlib import Path
from typing import Final

from pytest import mark
from rehuco_core import Relocation

LIBRARY: Final = Path("/fake/library")
FOLDER: Final = LIBRARY / "pack"
RENAMED: Final = LIBRARY / "kit"
FOLDER_RENAME: Final = Relocation(((FOLDER, RENAMED),))
FILE_RENAME: Final = Relocation(
    (
        (LIBRARY / "foo.rehu", LIBRARY / "bar.rehu"),
        (LIBRARY / "foo.zip", LIBRARY / "bar.zip"),
        (LIBRARY / "foo01.jpg", LIBRARY / "bar01.jpg"),
    )
)


# region relocate
def test_a_renamed_source_lands_on_its_destination() -> None:
    """The renamed entry itself answers its destination.

    **Test steps:**

    * relocate the folder and one of the file-scoped siblings
    """
    assert FOLDER_RENAME.relocate(FOLDER) == RENAMED
    assert FILE_RENAME.relocate(LIBRARY / "foo.zip") == LIBRARY / "bar.zip"


def test_a_path_beneath_a_renamed_folder_keeps_its_offset() -> None:
    """A record nested anywhere under a renamed folder rebases with it.

    **Test steps:**

    * relocate a nested record under the renamed folder
    """
    assert FOLDER_RENAME.relocate(FOLDER / "member" / "info.rehu") == RENAMED / "member" / "info.rehu"


def test_a_sibling_whose_name_merely_starts_alike_stays() -> None:
    """``pack2`` starts with ``pack`` as text and is not beneath it as a path.

    **Test steps:**

    * relocate a path in a folder whose name extends the renamed one's
    """
    candidate = LIBRARY / "pack2" / "info.rehu"

    assert FOLDER_RENAME.relocate(candidate) == candidate


def test_an_empty_relocation_moves_nothing() -> None:
    """What a rename that did not happen answers with.

    **Test steps:**

    * relocate through an empty relocation
    """
    assert Relocation().relocate(FOLDER) == FOLDER


@mark.windows
def test_case_folds_on_windows_and_the_tail_keeps_its_own_spelling() -> None:
    """A differently-cased ancestor still relocates, without respelling the rest of the name.

    **Test steps:**

    * relocate a path under the folder spelled in another case
    """
    assert FOLDER_RENAME.relocate(LIBRARY / "PACK" / "Member.rehu") == RENAMED / "Member.rehu"


# endregion


# region touches
@mark.parametrize(
    ("directory", "touched"),
    [
        (LIBRARY, True),
        (FOLDER, True),
        (FOLDER / "member", True),
        (RENAMED, True),
        (RENAMED / "member", True),
        (LIBRARY / "other", False),
        (LIBRARY / "pack2", False),
    ],
)
def test_a_folder_rename_touches_its_parent_itself_its_subtree_and_its_destination(
    directory: Path, touched: bool
) -> None:
    """A listing of any of these would show something different after the rename -- a folder beneath the
    destination included, which is where a holder that already followed the rename asks from.

    **Test steps:**

    * ask each directory whether the folder rename touches it
    """
    assert FOLDER_RENAME.touches(directory) is touched


def test_a_file_rename_touches_the_folder_holding_the_files_only() -> None:
    """The sibling set moves within one folder; a subfolder beside it is not touched.

    **Test steps:**

    * ask the folder and a subfolder of it
    """
    assert FILE_RENAME.touches(LIBRARY)
    assert not FILE_RENAME.touches(LIBRARY / "pack")


def test_an_empty_relocation_touches_nothing() -> None:
    """Nothing moved, so no listing needs reading again.

    **Test steps:**

    * ask an empty relocation about a folder
    """
    assert not Relocation().touches(LIBRARY)


# endregion
