"""Tests for the split folders of a root no layout buckets any more (#681): a place that leads into one, and finding
them on the disk. :mod:`test_prefix_buckets`, whose helpers are imported by name, tests a folder a layout does bucket.
"""

import os
from pathlib import Path, PurePosixPath
from unittest.mock import Mock

from pytest import LogCaptureFixture, mark, param, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    BUCKETS_MARKER,
    TEMPORARY_BUCKET_PREFIX,
    resolve_buckets,
    split_folders,
    ungoverned_reason,
)

from rehuco_core_tests.test_prefix_buckets import file_record, mark_split


@mark.parametrize(
    "marked, relative, bucketed, expected",
    [
        param("Fab", ("Fab", "0abc"), (), "Fab", id="a-plain-place-in-a-split-folder"),
        param("", ("0abc",), (), "", id="a-split-root"),
        param("Fab", ("Fab", "Jane", "Intro"), (), "Fab", id="beneath-a-split-folder"),
        param("Fab", ("Fab", "0", "Jane", "Intro"), (3,), "Fab", id="above-a-bucketed-level"),
        param("Fab/0", ("Fab", "0", "0abc"), (), "Fab/0", id="inside-a-bucket-itself-split"),
        param("Fab", ("Fab", "0abc"), (1,), None, id="a-place-the-layout-buckets"),
        param("Fab", ("Fab", "Jane", "Intro"), (1,), None, id="a-level-beneath-a-bucketed-one"),
        param("Other", ("Fab", "0abc"), (), None, id="a-split-folder-off-the-path"),
        param("Fab/0abc", ("Fab", "0abc"), (), None, id="the-records-own-folder"),
    ],
)
def test_a_place_into_a_folder_its_layout_does_not_bucket_is_told(
    tmp_path: Path, marked: str, relative: tuple[str, ...], bucketed: tuple[int, ...], expected: str | None
) -> None:
    """The first folder on a place's way that is split where its layout has no ``{buckets}`` comes with the place.

    **Test steps:**

    * mark one folder as split
    * resolve a place whose path leads into it, or past it
    * verify the folder, or none, and that a reason names it
    """
    mark_split(tmp_path / marked)

    place = resolve_buckets(tmp_path, PurePosixPath(*relative), bucketed)

    assert place.ungoverned == (None if expected is None else tmp_path / expected)
    if place.ungoverned is not None:
        assert ungoverned_reason(place.ungoverned).startswith(f"{place.ungoverned.name} is split into buckets")


def test_a_folder_pinned_by_a_folder_marker_governs_nothing(tmp_path: Path) -> None:
    """A folder marked never split was never split, so it keeps nothing out.

    **Test steps:**

    * put a folder named like the marker on a plain place's way
    * resolve the place
    * verify no folder is told
    """
    (tmp_path / "Fab" / BUCKETS_MARKER).mkdir(parents=True)

    assert resolve_buckets(tmp_path, PurePosixPath("Fab", "0abc"), ()).ungoverned is None


def test_the_split_folders_of_a_root_are_found_the_deepest_first(tmp_path: Path) -> None:
    """Each folder with buckets of its own is found once, a bucket never as one, at any depth: below another folder's
    buckets, in a plain folder, and one whose split was stopped before its marker.

    **Test steps:**

    * split a folder two levels deep, with a split author folder in a bucket and a split folder in a plain one
    * leave a temporary bucket in a folder not marked
    * verify what is found, the deepest first
    """
    mark_split(tmp_path / "Fab")
    mark_split(tmp_path / "Fab" / "j")
    mark_split(tmp_path / "Fab" / "j" / "ja" / "Jane")
    file_record(tmp_path / "Fab" / "j" / "ja" / "Jane" / "i", "Intro")
    mark_split(tmp_path / "Plain" / "Deep")
    (tmp_path / "Half" / f"{TEMPORARY_BUCKET_PREFIX}ab-1234" / "ab").mkdir(parents=True)

    assert split_folders(tmp_path) == (
        tmp_path / "Fab" / "j" / "ja" / "Jane",
        tmp_path / "Plain" / "Deep",
        tmp_path / "Fab",
        tmp_path / "Half",
    )


def test_a_split_root_is_one_of_its_folders(tmp_path: Path) -> None:
    """A layout may bucket the root's own folder, a record describing it or not.

    **Test steps:**

    * split a root's folder that holds a record of its own
    * verify it is found
    """
    mark_split(tmp_path)
    (tmp_path / "info.rehu").write_text("{}", encoding="utf-8")

    assert split_folders(tmp_path) == (tmp_path,)


def test_no_buckets_are_looked_for_in_a_record_or_a_systems_folder(tmp_path: Path) -> None:
    """A marker in a folder record, a hidden folder or a Recycle Bin is nobody's; neither is one in a folder record
    named like a bucket.

    **Test steps:**

    * put a marker in each
    * verify only the folder holding them all, itself split, is found
    """
    mark_split(tmp_path / "Fab")
    for name in ("Intro", "a", ".hidden", "$RECYCLE.BIN"):
        mark_split(tmp_path / "Fab" / name / "inner")
    for name in ("Intro", "a"):
        (tmp_path / "Fab" / name / "info.rehu").write_text("{}", encoding="utf-8")

    assert split_folders(tmp_path) == (tmp_path / "Fab",)


def test_a_split_folder_record_is_found_and_not_looked_into(tmp_path: Path) -> None:
    """A record put into a split folder itself keeps it as locked as any, so a balance has to find it.

    **Test steps:**

    * put a folder's record beside its marker, with a split folder beneath
    * verify the folder is found, the one beneath not
    """
    mark_split(tmp_path / "Fab")
    mark_split(tmp_path / "Fab" / "Inner")
    (tmp_path / "Fab" / "info.rehu").write_text("{}", encoding="utf-8")

    assert split_folders(tmp_path) == (tmp_path / "Fab",)


def test_the_search_stops_when_asked_and_passes_over_what_it_may_not_list(
    tmp_path: Path, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """A checkpoint stops it; a folder it has no permission for is logged and left out; any other failure is raised.

    **Test steps:**

    * search with a checkpoint that raises
    * search with the listing of one folder refused, then failing
    * verify each end, and the log
    """
    mark_split(tmp_path / "Fab")
    mark_split(tmp_path / "Other")
    with raises(InterruptedError):
        split_folders(tmp_path, Mock(side_effect=InterruptedError))
    scandir = os.scandir

    def refusing(folder: Path) -> object:
        """List a folder, but for one."""
        if folder == tmp_path / "Fab":
            raise error
        return scandir(folder)

    mocker.patch("rehuco_core.prefix_buckets.os.scandir", side_effect=refusing)
    error: OSError = PermissionError("denied")
    assert split_folders(tmp_path) == (tmp_path / "Other",)
    assert "could not be looked at for buckets" in caplog.text
    error = OSError("network name no longer available")
    with raises(OSError, match="no longer available"):
        split_folders(tmp_path)
