"""Tests for what a Roots listing accounts for: which cached records beneath a listed folder it no longer shows a way
to (#645)."""

import os
from pathlib import Path
from typing import Final

from pytest import mark
from rehuco_agent.rehuco.roots_listing import ListedFolder

FOLDER: Final = Path("C:/root/folder").absolute()
LISTED: Final = ListedFolder(FOLDER, (), folders=("Kept",), files=("here.rehu",))


@mark.parametrize(
    ("record", "unlisted"),
    [
        (FOLDER / "Kept" / "deep" / "info.rehu", False),
        (FOLDER / "here.rehu", False),
        (FOLDER / "gone" / "info.rehu", True),
        (FOLDER / "missing.rehu", True),
        (FOLDER / "here.rehu" / "info.rehu", True),
        (FOLDER / "Kept.rehu", True),
        (FOLDER.parent / "beside" / "info.rehu", False),
        (FOLDER, False),
    ],
    ids=[
        "beneath-a-listed-folder",
        "a-listed-file",
        "beneath-a-folder-gone",
        "a-file-gone",
        "beneath-what-is-now-a-file",
        "a-file-named-like-a-listed-folder",
        "not-beneath-the-folder",
        "the-folder-itself",
    ],
)
def test_a_record_is_unlisted_when_the_listing_shows_no_way_to_it(record: Path, unlisted: bool) -> None:
    """A record directly in the folder needs its file listed, one deeper its first folder down; one outside the folder
    is not the listing's to judge (#645).

    **Test steps:**

    * a listing of one folder and one file
    * verify the record is unlisted exactly when the listing shows no way to it
    """
    assert LISTED.unlisted([record]) == ([record] if unlisted else [])


def test_names_match_as_the_file_system_compares_them() -> None:
    """The cache may spell a name in another case than the listing: where the file system folds case -- Windows --
    that is the same name, and elsewhere another one (#645).

    **Test steps:**

    * cached records beneath the listed folder and file, spelled in another case
    * verify they are unlisted only where case is not folded
    """
    records = [FOLDER / "KEPT" / "info.rehu", FOLDER / "HERE.REHU"]

    assert LISTED.unlisted(records) == ([] if os.path.normcase("A") == "a" else records)
