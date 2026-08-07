"""Tests for finding which resources under a folder still hold retained conversion backups (#193,
[[acquisition-tooling#convert-mechanics]])."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from fake_directories import FakeDirEntry, FakeScandir
from pytest import raises
from pytest_mock import MockerFixture
from rehuco_core import RehuDocument, scan_conversion_backups

ROOT: Final = Path("/fake/library")

SEEDED_STAMP: Final = "2023-11-14T22:13:20Z"
"""What a conversion wrote into both ``created`` and ``updated``."""

EDITED_STAMP: Final = "2026-08-06T09:00:00Z"
"""An ``updated`` that has drifted from the seeded ``created`` -- the resource was saved again."""

BACKUP_SIZE: Final = 1000
"""What every mocked file reports, so a total is a multiple of it."""

# a keep-backups conversion whose three recognized screenshots landed on two slots -- one tie-break loser
TIE_BROKEN: Final = ("info.rehu", "info00.jpg", "info.tc.orig", "cover.jpg.orig", "sample-00.jpg.orig")

# a keep-backups conversion where every recognized screenshot was installed
CLEAN_CONVERSION: Final = ("info.rehu", "info00.jpg", "info.tc.orig", "cover.jpg.orig")

# a resource whose backups were discarded (or that was never converted) -- not this scan's business
NO_BACKUPS: Final = ("info.rehu", "info00.jpg")


def mock_catalog(
    mocker: MockerFixture,
    tree: Mapping[str, Sequence[str]],
    *,
    unreadable: Sequence[str] = (),
    edited: Sequence[str] = (),
) -> None:
    """Mock a catalog of resource directories, listed both by the walk and by each inventory.

    Two seams, because the scan genuinely crosses two: the catalog walk reads through ``os.scandir``
    (`test_rehu_catalog.mock_catalog`'s own seam) while each resource's inventory reads through
    ``Path.iterdir`` (`test_tc_conversion_backups.mock_environment`'s). Mocking both is what makes this
    an integration of the pair rather than a test of the composition alone.

    :param mocker: pytest-mock fixture.
    :param tree: ``{directory name under ROOT: the filenames it holds}``.
    :param unreadable: directory names whose listing raises -- an offline branch of a mount.
    :param edited: directory names whose ``.rehu`` reports an ``updated`` that has drifted from its
        ``created``, i.e. it was saved again since the conversion.
    """
    offline = {ROOT / name for name in unreadable}
    contents = {ROOT / name: [ROOT / name / filename for filename in filenames] for name, filenames in tree.items()}
    every_path = {path for paths in contents.values() for path in paths}
    listing: dict[Path, list[FakeDirEntry]] = {ROOT: [FakeDirEntry(name, directory=True) for name in tree]}
    listing |= {ROOT / name: [FakeDirEntry(path.name) for path in contents[ROOT / name]] for name in tree}
    for name in unreadable:
        listing[ROOT] = [*listing[ROOT], FakeDirEntry(name, directory=True)]

    def scandir(directory: Path) -> FakeScandir:
        if Path(directory) in offline:
            raise PermissionError(directory)
        if Path(directory) not in listing:
            raise FileNotFoundError(directory)
        return FakeScandir(listing[Path(directory)])

    def iterdir(self: Path) -> list[Path]:
        if self in offline:
            raise PermissionError(self)
        return contents.get(self, [])

    def load(path: Path, **_kwargs: Any) -> Any:
        updated = EDITED_STAMP if Path(path).parent.name in edited else SEEDED_STAMP
        return mocker.MagicMock(created=SEEDED_STAMP, updated=updated)

    mocker.patch("rehuco_core.rehu_catalog.os.scandir", side_effect=scandir)
    mocker.patch.object(Path, "iterdir", autospec=True, side_effect=iterdir)
    mocker.patch.object(Path, "exists", autospec=True, side_effect=lambda self: self in every_path)
    mocker.patch.object(Path, "stat", return_value=mocker.MagicMock(st_size=BACKUP_SIZE))
    mocker.patch.object(RehuDocument, "load", side_effect=load)


def names(scan: Any) -> list[str]:
    """The resource directory names a scan reported, for a readable assertion."""
    return [backups.rehu_path.parent.name for backups in scan.resources]


# region What the scan finds


def test_only_resources_that_still_hold_backups_are_reported(mocker: MockerFixture) -> None:
    """The answer is the work a caller could actually do, not an inventory of the catalog -- so a
    resource whose backups were already discarded is examined and dropped.

    **Test steps:**

    * mock a catalog holding two converted resources with backups and one without
    * scan the root
    * verify only the two are reported, and that all three were examined
    """
    mock_catalog(mocker, {"Sculpting": TIE_BROKEN, "ZBrush": CLEAN_CONVERSION, "Painting": NO_BACKUPS})

    scan = scan_conversion_backups(ROOT)

    assert names(scan) == ["Sculpting", "ZBrush"]
    assert scan.examined == 3
    assert scan.root == ROOT


def test_the_totals_add_up_what_a_discard_would_reclaim(mocker: MockerFixture) -> None:
    """The header line a backups manager leads with is the number that makes the decision easy, so it
    counts files and bytes across every reported resource rather than per row.

    **Test steps:**

    * mock a catalog of two converted resources holding four and three backups
    * scan the root
    * verify the file count and the byte total span both
    """
    mock_catalog(mocker, {"Sculpting": TIE_BROKEN, "ZBrush": CLEAN_CONVERSION})

    scan = scan_conversion_backups(ROOT)

    assert scan.total_files == 5
    assert scan.total_bytes == BACKUP_SIZE * 5


def test_the_scan_counts_the_rows_worth_reviewing(mocker: MockerFixture) -> None:
    """Reverting is offered on what can be reverted, warned about on what has been edited since, and the
    tie-break count is the ~1--2 % #193 exists to review -- so each is a count the header can name.

    **Test steps:**

    * mock a catalog whose two converted resources differ in tie-break and in edited-since
    * scan the root
    * verify each count names exactly the resource it is about
    """
    mock_catalog(mocker, {"Sculpting": TIE_BROKEN, "ZBrush": CLEAN_CONVERSION}, edited=["ZBrush"])

    scan = scan_conversion_backups(ROOT)

    assert scan.revertible == 2
    assert scan.tie_break == 1
    assert scan.edited_since == 1


def test_an_unreadable_branch_is_named_rather_than_silently_dropped(mocker: MockerFixture) -> None:
    """An offline branch of a mount costs its own subtree and *says so* -- because a catalog with no
    retained backups and a catalog that would not list are the same sentence otherwise (#245).

    **Test steps:**

    * mock a catalog with one readable converted resource and one branch that will not list
    * scan the root
    * verify the readable resource is reported and the branch is named
    """
    mock_catalog(mocker, {"Sculpting": TIE_BROKEN}, unreadable=["Away"])

    scan = scan_conversion_backups(ROOT)

    assert names(scan) == ["Sculpting"]
    assert scan.unreadable == (ROOT / "Away",)


def test_a_catalog_with_nothing_retained_reports_an_empty_scan(mocker: MockerFixture) -> None:
    """*Nothing left to clean up* is a real answer, and it has to be distinguishable from *nothing was
    looked at* -- which is what the examined count is for.

    **Test steps:**

    * mock a catalog whose only resource has no backups
    * scan the root
    * verify nothing is reported, the totals are zero, and the resource was still examined
    """
    mock_catalog(mocker, {"Painting": NO_BACKUPS})

    scan = scan_conversion_backups(ROOT)

    assert not scan.resources
    assert scan.total_bytes == 0
    assert scan.examined == 1


# endregion

# region Progress and cancellation


def test_progress_counts_every_resource_examined_not_only_the_ones_found(mocker: MockerFixture) -> None:
    """A catalog where almost nothing has backups left would otherwise report a motionless zero for the
    whole length of the walk, which reads as a hung scan.

    **Test steps:**

    * mock a catalog of three resources, only one of which has backups
    * scan the root with a progress callback
    * verify it was called once per resource, counting up
    """
    mock_catalog(mocker, {"Painting": NO_BACKUPS, "Sculpting": TIE_BROKEN, "Sketching": NO_BACKUPS})
    seen: list[int] = []

    scan_conversion_backups(ROOT, progress=seen.append)

    assert seen == [1, 2, 3]


def test_whatever_progress_raises_unwinds_the_scan(mocker: MockerFixture) -> None:
    """How a surface cancels a long scan: the callback raises and nothing here catches it, the same
    contract the dry-run plan's own progress documents (#191).

    **Test steps:**

    * mock a catalog of three converted resources
    * scan with a progress callback that raises on the second
    * verify the exception escapes
    """
    mock_catalog(mocker, {"A": TIE_BROKEN, "B": TIE_BROKEN, "C": TIE_BROKEN})

    def stop_after_one(count: int) -> None:
        if count > 1:
            raise KeyboardInterrupt

    with raises(KeyboardInterrupt):
        scan_conversion_backups(ROOT, progress=stop_after_one)


def test_the_checkpoint_can_stop_the_walk_before_any_resource_is_read(mocker: MockerFixture) -> None:
    """The walk itself is the slow part over a mount, and it runs before a single record has been
    examined -- so cancelling has to reach it, not only the per-resource loop.

    **Test steps:**

    * mock a catalog of converted resources
    * scan with a checkpoint that raises immediately
    * verify the exception escapes and no progress was ever reported
    """
    mock_catalog(mocker, {"Sculpting": TIE_BROKEN})
    seen: list[int] = []

    def stop_at_once() -> None:
        raise KeyboardInterrupt

    with raises(KeyboardInterrupt):
        scan_conversion_backups(ROOT, progress=seen.append, checkpoint=stop_at_once)

    assert not seen


# endregion
