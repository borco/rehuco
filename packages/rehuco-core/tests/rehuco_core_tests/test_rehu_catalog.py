"""Tests for the catalog walk -- where the resources are, for the checksum sweep (#242)."""

from pathlib import Path
from typing import Final

from pytest import raises
from pytest_mock import MockerFixture
from rehuco_core import (
    INFO_REHU_FILENAME,
    ContentUnreachableError,
    enumerate_catalog_resources,
)
from rehuco_core.rehu_content_files import MAX_NAMED_UNREADABLE

from rehuco_core_tests.fake_directories import FakeDirEntry, FakeScandir

ROOT: Final = Path("/fake/library")


def mock_catalog(  # pylint: disable=too-many-arguments
    mocker: MockerFixture,
    filenames: list[str],
    *,
    directories: list[str] | None = None,
    unreadable: list[str] | None = None,
    irregular: list[str] | None = None,
    directory_links: list[str] | None = None,
) -> None:
    """Mock a directory tree under :data:`ROOT`, read one directory at a time via ``os.scandir``.

    The catalog walk's counterpart of `test_rehu_content_files.mock_tree`, and deliberately a second
    helper rather than a parameter on the first: the two walks patch different modules, and a shared
    helper that took the module to patch would read as though one walk could be tested through the
    other's seam.

    :param mocker: pytest-mock fixture.
    :param filenames: fake paths relative to :data:`ROOT`, ``/``-separated, that are regular files.
    :param directories: fake paths relative to :data:`ROOT` that are directories.
    :param unreadable: fake directory paths whose listing should raise ``OSError`` -- an offline branch
        of a mount. They must also appear in ``directories`` to be reached at all.
    :param irregular: fake paths that are neither a directory nor a regular file.
    :param directory_links: fake paths that are *symlinks to* directories; their target's listing is
        deliberately not modeled, so a test proves the walk never descends by what does not appear.
    """
    offline = {ROOT / name for name in unreadable or []}
    listing: dict[Path, list[FakeDirEntry]] = {ROOT: []}
    for name in directories or []:
        path = ROOT / name
        listing.setdefault(path.parent, []).append(FakeDirEntry(path.name, directory=True))
        listing.setdefault(path, [])
    for name in filenames:
        path = ROOT / name
        listing.setdefault(path.parent, []).append(FakeDirEntry(path.name))
    for name in irregular or []:
        path = ROOT / name
        listing.setdefault(path.parent, []).append(FakeDirEntry(path.name, regular=False))
    for name in directory_links or []:
        path = ROOT / name
        listing.setdefault(path.parent, []).append(FakeDirEntry(path.name, directory=True, regular=False, link=True))

    def scandir(directory: Path) -> FakeScandir:
        if Path(directory) in offline:
            raise PermissionError(directory)
        if Path(directory) not in listing:
            raise FileNotFoundError(directory)
        return FakeScandir(listing[Path(directory)])

    mocker.patch("rehuco_core.rehu_catalog.os.scandir", side_effect=scandir)


# region What the walk finds


def test_a_directory_scoped_and_a_file_scoped_record_are_both_resources(mocker: MockerFixture) -> None:
    """Every ``.rehu`` counts, whichever scoping rule it follows ([[data-model#resource-scoping]])."""
    mock_catalog(
        mocker,
        [f"tutorial/{INFO_REHU_FILENAME}", "packs/foo.rehu", "packs/foo.zip"],
        directories=["tutorial", "packs"],
    )

    found = enumerate_catalog_resources(ROOT)

    assert found.resources == [ROOT / "packs/foo.rehu", ROOT / f"tutorial/{INFO_REHU_FILENAME}"]


def test_several_records_in_one_directory_are_all_found(mocker: MockerFixture) -> None:
    """A folder of file-scoped resources is a folder of resources, not one."""
    mock_catalog(mocker, ["packs/foo.rehu", "packs/bar.rehu", "packs/baz.rehu"], directories=["packs"])

    found = enumerate_catalog_resources(ROOT)

    assert found.resources == [ROOT / "packs/bar.rehu", ROOT / "packs/baz.rehu", ROOT / "packs/foo.rehu"]


def test_a_record_in_the_root_itself_is_found(mocker: MockerFixture) -> None:
    """The root is walked like any other directory -- pointing at one resource is a legal sweep."""
    mock_catalog(mocker, [INFO_REHU_FILENAME, "video.mp4"])

    assert enumerate_catalog_resources(ROOT).resources == [ROOT / INFO_REHU_FILENAME]


def test_a_nested_resource_is_found_and_its_bookkeeping_is_not_mistaken_for_one(mocker: MockerFixture) -> None:
    """A nested record is not a scan boundary, and only a ``.rehu`` is a resource.

    The screenshots, the checksum record and the legacy manifests beside a record are that record's
    bookkeeping (#226) and no walk should offer them as resources -- here by the plainest possible rule:
    a resource is a file whose suffix is ``.rehu``.
    """
    mock_catalog(
        mocker,
        [
            INFO_REHU_FILENAME,
            "info00.jpg",
            "info.checksum",
            "info.sfv",
            f"sub/{INFO_REHU_FILENAME}",
            "sub/info00.jpg",
            "sub/info.checksum",
            "sub/video.mp4",
        ],
        directories=["sub"],
    )

    found = enumerate_catalog_resources(ROOT)

    assert found.resources == [ROOT / INFO_REHU_FILENAME, ROOT / f"sub/{INFO_REHU_FILENAME}"]


def test_a_record_is_recognized_whatever_the_suffix_casing(mocker: MockerFixture) -> None:
    """SMB and macOS hand back casings Windows never wrote, so the suffix test folds case."""
    mock_catalog(mocker, ["packs/foo.REHU"], directories=["packs"])

    assert enumerate_catalog_resources(ROOT).resources == [ROOT / "packs/foo.REHU"]


def test_a_directory_named_like_a_record_is_descended_rather_than_reported(mocker: MockerFixture) -> None:
    """A resource is a *file*; a folder called ``foo.rehu`` is a folder, and may hold resources."""
    mock_catalog(mocker, ["foo.rehu/bar.rehu"], directories=["foo.rehu"])

    assert enumerate_catalog_resources(ROOT).resources == [ROOT / "foo.rehu/bar.rehu"]


def test_an_entry_that_is_neither_a_file_nor_a_directory_is_not_a_resource(mocker: MockerFixture) -> None:
    """A real listing hands back sockets and broken symlinks; none of them is a record to verify."""
    mock_catalog(mocker, [], irregular=["foo.rehu"])

    assert not enumerate_catalog_resources(ROOT).resources


def test_the_walk_never_descends_a_directory_symlink(mocker: MockerFixture) -> None:
    """One pointing at an ancestor would loop forever, one pointing sideways would sweep twice."""
    mock_catalog(mocker, ["packs/foo.rehu"], directories=["packs"], directory_links=["elsewhere"])

    assert enumerate_catalog_resources(ROOT).resources == [ROOT / "packs/foo.rehu"]


def test_the_resources_come_back_sorted_by_path(mocker: MockerFixture) -> None:
    """A stable order is what makes an interrupted sweep resume over the same sequence it left."""
    mock_catalog(
        mocker,
        ["c/foo.rehu", "a/foo.rehu", "b/foo.rehu"],
        directories=["c", "a", "b"],
    )

    found = enumerate_catalog_resources(ROOT)

    assert found.resources == sorted(found.resources, key=str)


# endregion

# region What the walk could not see


def test_an_empty_root_is_reachable_with_no_resources(mocker: MockerFixture) -> None:
    """*Nothing here* and *away* are different answers, which is the whole point of #245's shape."""
    mock_catalog(mocker, [])

    found = enumerate_catalog_resources(ROOT)

    assert not found.resources
    assert found.reachable
    assert found.complete


def test_a_root_that_will_not_list_is_unreachable_rather_than_empty(mocker: MockerFixture) -> None:
    """An unmapped drive answers ``FileNotFoundError``; the walk still reports rather than raises."""
    mocker.patch("rehuco_core.rehu_catalog.os.scandir", side_effect=FileNotFoundError(ROOT))

    found = enumerate_catalog_resources(ROOT)

    assert not found.reachable
    assert found.unreadable == (ROOT,)


def test_an_unreachable_root_is_refused_when_the_caller_asks(mocker: MockerFixture) -> None:
    """The sweep's one refusal: a root it cannot list means the run has nothing to say."""
    mocker.patch("rehuco_core.rehu_catalog.os.scandir", side_effect=PermissionError(ROOT))

    with raises(ContentUnreachableError, match="The folder could not be read"):
        enumerate_catalog_resources(ROOT).require_reachable()


def test_an_offline_branch_costs_its_own_subtree_and_is_named(mocker: MockerFixture) -> None:
    """An offline branch of a mount ([[mounts-and-storage#offline-mounts]]) is reported, not fatal."""
    mock_catalog(
        mocker,
        ["packs/foo.rehu", "away/bar.rehu"],
        directories=["packs", "away"],
        unreadable=["away"],
    )

    found = enumerate_catalog_resources(ROOT)

    assert found.resources == [ROOT / "packs/foo.rehu"]
    assert found.reachable
    assert not found.complete
    assert found.unreadable == (ROOT / "away",)
    found.require_reachable()


def test_the_unreadable_text_names_a_few_and_counts_the_rest(mocker: MockerFixture) -> None:
    """A tree that went away wholesale would otherwise produce a sentence nobody reads."""
    branches = [f"away{index}" for index in range(MAX_NAMED_UNREADABLE + 2)]
    mock_catalog(mocker, [], directories=branches, unreadable=branches)

    text = enumerate_catalog_resources(ROOT).unreadable_text()

    assert text.endswith("(and 2 more)")
    assert text.count(str(ROOT)) == MAX_NAMED_UNREADABLE


def test_the_unreadable_text_names_them_all_when_there_are_few(mocker: MockerFixture) -> None:
    """Nothing is counted away when everything fits."""
    mock_catalog(mocker, [], directories=["away"], unreadable=["away"])

    assert enumerate_catalog_resources(ROOT).unreadable_text() == str(ROOT / "away")


# endregion

# region Stopping


def test_the_checkpoint_runs_once_for_every_directory(mocker: MockerFixture) -> None:
    """A listing is the walk's unit of work, so that is where it asks whether it should still run."""
    mock_catalog(mocker, ["a/foo.rehu", "a/b/bar.rehu"], directories=["a", "a/b"])
    checkpoint = mocker.Mock()

    enumerate_catalog_resources(ROOT, checkpoint=checkpoint)

    assert checkpoint.call_count == 3


def test_whatever_the_checkpoint_raises_leaves_the_walk(mocker: MockerFixture) -> None:
    """A cancel a walk swallowed is a walk that cannot be stopped."""

    class Stop(Exception):
        """Whatever a caller's checkpoint raises -- the walk knows nothing about it."""

    mock_catalog(mocker, ["a/foo.rehu"], directories=["a"])

    with raises(Stop):
        enumerate_catalog_resources(ROOT, checkpoint=mocker.Mock(side_effect=Stop))


# endregion
