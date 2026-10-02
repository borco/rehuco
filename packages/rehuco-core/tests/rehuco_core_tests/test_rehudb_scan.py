"""Tests for a full scan of one ``.rehuco`` root (#372).

The filesystem is declared, never touched: listings come from :class:`FakeScandir`, a record's stat and bytes
from the same declaration, and its parse from the payload the test gave it.
"""

from collections.abc import Callable
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any, Final

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_core import (
    CURRENT_FORMAT_VERSION,
    CatalogRootScan,
    RecordKind,
    RehuDocument,
    RehuFormatError,
    RenameCoordinator,
    RootScanOutcome,
)
from rehuco_core.rehu_parse_limits import MAX_FILE_BYTES

from rehuco_core_tests.concurrency import SETTLE, running, wait_until
from rehuco_core_tests.fake_directories import FakeDirEntry, FakeScandir

ROOT: Final = Path("/fake/library")


def payload(title: str = "", **core: Any) -> dict[str, Any]:
    """A current-version ``.rehu`` payload whose primary source has ``title``, and ``core`` besides."""
    return {"format_version": CURRENT_FORMAT_VERSION, "core": {"sources": [{"title": title}], **core}}


class FakeTree:  # pylint: disable=too-many-instance-attributes  # one knob per seam the scan reads through
    """A declared directory tree under :data:`ROOT`, mocked at every seam a root scan reads through.

    :param mocker: pytest-mock fixture.
    """

    def __init__(self, mocker: MockerFixture) -> None:
        self.listing: dict[Path, list[FakeDirEntry]] = {ROOT: []}
        self.payloads: dict[Path, dict[str, Any] | Exception] = {}
        self.sizes: dict[Path, int] = {}
        self.unreadable: set[Path] = set()
        self.gone_at_end = False
        self.on_list: Callable[[Path], None] = lambda directory: None
        mocker.patch("rehuco_core.rehu_catalog.os.scandir", side_effect=self.__scandir)
        mocker.patch.object(Path, "stat", autospec=True, side_effect=self.__stat)
        self.read_bytes = mocker.patch.object(Path, "read_bytes", autospec=True, side_effect=self.__read_bytes)
        self.is_dir = mocker.patch.object(Path, "is_dir", autospec=True, side_effect=lambda path: not self.gone_at_end)
        mocker.patch.object(RehuDocument, "load", side_effect=self.__load)
        mocker.patch("rehuco_core.rehudb_scan.load_tc", side_effect=self.__load)

    def directory(self, name: str) -> None:
        """Declare a directory, relative to :data:`ROOT`."""
        path = ROOT / name
        self.listing.setdefault(path.parent, []).append(FakeDirEntry(path.name, directory=True))
        self.listing.setdefault(path, [])

    def file(self, name: str, content: dict[str, Any] | Exception | None = None, *, size: int = 10) -> None:
        """Declare a file, relative to :data:`ROOT`, holding ``content`` when it is a record."""
        path = ROOT / name
        self.listing.setdefault(path.parent, []).append(FakeDirEntry(path.name))
        self.payloads[path] = payload() if content is None else content
        self.sizes[path] = size

    def __scandir(self, directory: Path) -> FakeScandir:
        self.on_list(Path(directory))
        if Path(directory) in self.unreadable:
            raise PermissionError(directory)
        if Path(directory) not in self.listing:
            raise FileNotFoundError(directory)
        return FakeScandir(self.listing[Path(directory)])

    def __stat(self, path: Path, **_kwargs: object) -> SimpleNamespace:
        if path not in self.sizes:
            raise FileNotFoundError(path)
        return SimpleNamespace(st_size=self.sizes[path], st_mtime_ns=1_000)

    def __read_bytes(self, path: Path) -> bytes:
        return str(path).encode()

    def __load(self, path: Path | str, **_kwargs: object) -> RehuDocument:
        content = self.payloads[Path(path)]
        if isinstance(content, Exception):
            raise content
        return RehuDocument(content, Path(path))


@fixture(name="tree")
def fixture_tree(mocker: MockerFixture) -> FakeTree:
    """An empty declared tree; a test adds what it needs.

    :param mocker: pytest-mock fixture.
    :returns: the tree.
    """
    return FakeTree(mocker)


def scan(**kwargs: Any) -> Any:
    """Scan :data:`ROOT` over a fresh coordinator."""
    return CatalogRootScan(ROOT, coordinator=kwargs.pop("coordinator", RenameCoordinator()), **kwargs).scan()


def paths(result: Any) -> list[str]:
    """The root-relative paths a scan found, in its order."""
    return [record.path for record in result.records]


# region What a scan reads


def test_a_record_is_read_into_its_common_core(tree: FakeTree) -> None:
    """The fields a browser shows, the value lists, and the record's own signature."""
    tree.directory("course")
    tree.file(
        "course/info.rehu",
        payload(
            "Donut",
            id="u1",
            type="tutorial",
            authors=["Ann", {"name": "Bob"}],
            advertised_tags=["3d"],
            extra_tags=["blender"],
            released="2024-03",
            current_size=55,
            updated="2026-01-01",
        ),
    )

    result = scan()

    assert result.outcome is RootScanOutcome.SCANNED
    (record,) = result.records
    assert (record.path, record.kind, record.uuid, record.type, record.title) == (
        "course/info.rehu",
        RecordKind.REHU,
        "u1",
        "tutorial",
        "Donut",
    )
    assert (record.released, record.current_size, record.updated) == ("2024-03", 55, "2026-01-01")
    assert record.authors == ("Ann", "Bob")
    assert record.tags == ("3d", "blender")
    assert (record.mtime_ns, record.size) == (1_000, 10)
    assert record.content_hash
    assert record.error is None


def test_every_sources_publisher_is_kept_the_primarys_first(tree: FakeTree) -> None:
    """``publishers`` is every source's, named once; ``publisher`` is the primary's."""
    content = payload()
    content["core"]["sources"] = [
        {"title": "T", "publisher": "Second"},
        {"publisher": "First", "primary": True},
        {"publisher": "Second"},
        "not a source",
    ]
    tree.file("foo.rehu", content)

    (record,) = scan().records

    assert record.publisher == "First"
    assert record.publishers == ("First", "Second")


def test_a_legacy_record_is_read_only_where_no_rehu_covers_it(tree: FakeTree) -> None:
    """A converted ``foo.tc`` beside its ``foo.rehu`` is not a second resource; a lone one, or a nested
    ``info.tc``, is."""
    tree.file("info.rehu")
    tree.file("info.tc")
    tree.file("Foo.TC")
    tree.directory("sub")
    tree.file("sub/info.tc")

    result = scan()

    assert paths(result) == ["Foo.TC", "info.rehu", "sub/info.tc"]
    assert [record.kind for record in result.records] == [RecordKind.TC, RecordKind.REHU, RecordKind.TC]
    assert result.legacy_records == 2


def test_an_unparsable_record_keeps_a_row_with_the_reason(tree: FakeTree) -> None:
    """Reported, not fatal: the scan goes on to the next record."""
    tree.file("bad.rehu", RehuFormatError("Not JSON"))
    tree.file("good.rehu", payload("Good"))

    result = scan()

    bad, good = result.records
    assert bad.error == "Not JSON"
    assert bad.content_hash
    assert good.title == "Good"
    assert result.unreadable_records == 1


def test_a_record_that_vanished_after_its_listing_keeps_a_row_with_the_reason(tree: FakeTree) -> None:
    """A stat that fails is a reason like any other."""
    tree.file("gone.rehu")
    del tree.sizes[ROOT / "gone.rehu"]

    (record,) = scan().records

    assert record.error is not None
    assert record.content_hash == ""


def test_an_oversized_record_is_refused_without_being_read(tree: FakeTree) -> None:
    """The parse limit is applied before the bytes are hashed, so a stray huge file costs a stat."""
    tree.file("huge.rehu", size=MAX_FILE_BYTES + 1)

    (record,) = scan().records

    assert record.error is not None
    assert record.size == MAX_FILE_BYTES + 1
    tree.read_bytes.assert_not_called()


def test_progress_counts_records_as_they_are_read(tree: FakeTree, mocker: MockerFixture) -> None:
    """A running count, since a first scan has no total to show a percentage of."""
    tree.file("a.rehu")
    tree.file("b.rehu")
    progress = mocker.Mock()

    scan(progress=progress)

    assert [call.args for call in progress.call_args_list] == [(1,), (2,)]


def test_the_checkpoint_runs_for_every_directory_and_every_record(tree: FakeTree, mocker: MockerFixture) -> None:
    """A cancel bites within one listing or one read."""
    tree.directory("sub")
    tree.file("sub/a.rehu")
    tree.file("b.rehu")
    checkpoint = mocker.Mock()

    scan(checkpoint=checkpoint)

    assert checkpoint.call_count == 4


# endregion

# region Online and offline


def test_a_root_that_does_not_list_is_offline_and_nothing_is_read(tree: FakeTree) -> None:
    """Offline is not empty: the result says so, and carries nothing to apply."""
    tree.file("a.rehu")
    tree.unreadable.add(ROOT)

    result = scan()

    assert result.outcome is RootScanOutcome.OFFLINE
    assert not result.applicable
    assert not result.records


def test_a_root_that_goes_away_before_the_end_is_not_applied(tree: FakeTree) -> None:
    """A mount dropping mid-walk looks like folders vanishing; the probe at the end tells them apart."""
    tree.file("a.rehu")
    tree.gone_at_end = True

    result = scan()

    assert result.outcome is RootScanOutcome.WENT_OFFLINE
    assert not result.applicable
    assert not result.records


def test_an_unreadable_branch_under_an_online_root_is_named_and_contributes_nothing(tree: FakeTree) -> None:
    """A root is wholly online: what a branch would not show is not kept."""
    tree.directory("away")
    tree.file("away/lost.rehu")
    tree.file("kept.rehu")
    tree.unreadable.add(ROOT / "away")

    result = scan()

    assert result.applicable
    assert paths(result) == ["kept.rehu"]
    assert result.unreadable_branches == (ROOT / "away",)


# endregion

# region Renames


def test_a_directory_scoped_rename_succeeds_while_the_scan_is_inside_that_directory(
    tree: FakeTree, mocker: MockerFixture
) -> None:
    """The scan is parked inside ``old/``'s listing when the rename arrives: the rename waits out that one
    listing rather than the scan, and the record the scan then reads is found under its new name.

    **Test steps:**

    * park the scan inside ``old/``'s listing
    * rename ``old/info.rehu``'s folder on another thread; check it waits
    * let the listing finish; check the rename lands and the record is read from ``new/``
    """
    mocker.patch.object(Path, "is_file", autospec=True, return_value=True)
    mocker.patch.object(Path, "exists", autospec=True, return_value=False)
    renamed = mocker.patch.object(Path, "rename", autospec=True)
    tree.directory("old")
    tree.file("old/info.rehu", payload("Moved"))
    tree.payloads[ROOT / "new/info.rehu"] = tree.payloads[ROOT / "old/info.rehu"]
    tree.sizes[ROOT / "new/info.rehu"] = 10
    inside, proceed = Event(), Event()

    def park(directory: Path) -> None:
        if directory == ROOT / "old":
            inside.set()
            proceed.wait(SETTLE)

    tree.on_list = park
    coordinator = RenameCoordinator()
    results: list[Any] = []

    with running(lambda: results.append(scan(coordinator=coordinator))):
        assert inside.wait(SETTLE)
        with running(lambda: coordinator.rename(ROOT / "old/info.rehu", "new")):
            assert wait_until(lambda: coordinator.yield_wanted)
            renamed.assert_not_called()
            proceed.set()
            assert wait_until(lambda: renamed.called)
        assert wait_until(lambda: bool(results))

    assert len(results) == 1
    result = results[0]
    assert paths(result) == ["new/info.rehu"]
    assert result.records[0].title == "Moved"


def test_the_root_itself_renamed_at_the_very_end_still_yields_root_relative_paths(
    tree: FakeTree, mocker: MockerFixture
) -> None:
    """The root and its records are read under one hold, so a rename asked for while the scan probes its
    root waits for the probe and the result is wholly pre-rename -- never an old root paired with records
    already moved, which is a ``ValueError`` out of ``relative_to``."""
    mocker.patch.object(Path, "is_file", autospec=True, return_value=True)
    mocker.patch.object(Path, "exists", autospec=True, return_value=False)
    mocker.patch.object(Path, "rename", autospec=True)
    tree.file("info.rehu", payload("Root resource"))
    coordinator = RenameCoordinator()
    probed, proceed = Event(), Event()

    def probing(path: Path) -> bool:
        del path
        probed.set()
        proceed.wait(SETTLE)
        return True

    tree.is_dir.side_effect = probing
    results: list[Any] = []

    with running(lambda: results.append(CatalogRootScan(ROOT, coordinator=coordinator).scan())):
        assert probed.wait(SETTLE)
        with running(lambda: coordinator.rename(ROOT / "info.rehu", "moved")):
            assert wait_until(lambda: coordinator.yield_wanted)
            proceed.set()
        assert wait_until(lambda: bool(results))

    assert len(results) == 1
    assert results[0].outcome is RootScanOutcome.SCANNED
    assert results[0].root == ROOT
    assert paths(results[0]) == ["info.rehu"]


# endregion
