"""Tests for the scan's half of "a record has one row" (#498): it never enters another root, and it keeps one name of
a file it finds under several.

Unlike `test_rehudb_scan`, these run on real folders under ``tmp_path``: a root met by identity, a junction and a
hardlink are what the operating system answers for them, which a declared tree cannot prove. Where the claim is about
rows, the scans are applied to a cache over `test_rehudb`'s in-memory database.
"""

import json
import logging
import os
from collections.abc import Callable, Generator, Mapping, Sequence
from pathlib import Path
from uuid import UUID

from pytest import LogCaptureFixture, fixture
from pytest_mock import MockerFixture
from rehuco_core import (
    CURRENT_FORMAT_VERSION,
    CatalogCache,
    CatalogRoot,
    CatalogRootScan,
    HardlinkedRecord,
    RecordSignature,
    RehucoFile,
    RenameCoordinator,
    RootScanEffects,
    RootScanResult,
    enumerate_content_files,
)

from rehuco_core_tests.real_links import directory_link, hardlink
from rehuco_core_tests.test_rehudb import (  # noqa: F401  # pylint: disable=unused-import
    MemoryDatabase,
    fixture_memory,
    nesting,
)
from rehuco_core_tests.test_rehudb_scan import signatures_of


def write_record(path: Path, title: str = "") -> Path:
    """Write a current ``.rehu`` at ``path``, its folders included.

    :param path: the record.
    :param title: its primary source's title.
    :returns: ``path``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    content = {"format_version": CURRENT_FORMAT_VERSION, "core": {"sources": [{"title": title}]}}
    path.write_text(json.dumps(content), encoding="utf-8")
    return path


def file_id(path: Path) -> str:
    """A file's identity as the scan spells it.

    :param path: the file.
    :returns: ``"<st_dev>:<st_ino>"``.
    """
    status = os.stat(path)
    return f"{status.st_dev}:{status.st_ino}"


def scan(
    root: Path, others: Sequence[CatalogRoot] = (), known: Mapping[str, RecordSignature] | None = None
) -> RootScanResult:
    """Scan a real root over a fresh coordinator.

    :param root: the root's folder.
    :param others: the catalog's other roots.
    :param known: the cached rows to skip unchanged records by.
    :returns: what the scan found.
    """
    return CatalogRootScan(root, coordinator=RenameCoordinator(), others=others, known=known).scan()


def paths(result: RootScanResult) -> list[str]:
    """The root-relative paths a scan read, in its order.

    :param result: what the scan found.
    :returns: each read record's root-relative path.
    """
    return [record.path for record in result.records]


@fixture(name="cache")
def fixture_cache(
    mocker: MockerFixture, memory: Callable[[], MemoryDatabase], tmp_path: Path
) -> Generator[CatalogCache]:
    """A cache over an in-memory database, its folder a real one, closed when the test ends.

    :param mocker: pytest-mock fixture.
    :param memory: where the database comes from.
    :param tmp_path: the folder the cache file would be in.
    :yields: the open cache.
    """
    mocker.patch("rehuco_core.rehudb.sqlite3.connect", side_effect=memory().connect)
    with CatalogCache.open(tmp_path / "catalog.rehudb") as cache:
        yield cache


def scan_into(cache: CatalogCache, root_id: UUID) -> tuple[RootScanResult, RootScanEffects]:
    """Scan one of the cache's roots against the others, as the scan job does, and apply what it found.

    :param cache: the cache.
    :param root_id: the root to scan.
    :returns: what the scan found, and what applying it did.
    """
    roots = cache.roots()
    (root,) = [each for each in roots if each.root_id == root_id]
    result = scan(root.path, [each for each in roots if each.root_id != root_id])
    effects = RootScanEffects()
    cache.apply_root_scan(
        root_id, result.records, unchanged=result.unchanged, identities=result.identities, effects=effects
    )
    return result, effects


def rows_by_root(cache: CatalogCache) -> dict[str, list[str]]:
    """Every row's root-relative path, by its root's label.

    :param cache: the cache.
    :returns: the root-relative paths of each root's rows, keyed by the root's label.
    """
    found: dict[str, list[str]] = {}
    for row in cache.rows():
        found.setdefault(row.root_label, []).append(row.record.path)
    return found


# region Another root inside


def test_a_root_moved_inside_another_is_left_to_its_own_scan(tmp_path: Path, cache: CatalogCache) -> None:
    """Nesting that arose after the add -- a folder moved in outside the app -- still gives each record one row: the
    outer scan does not enter the inner root, and names it as met.

    **Test steps:**

    * hold an outer root and a root inside it, each with a record
    * scan the outer root, then the inner one, into the cache
    * verify the outer scan read only its own record and met the inner root, and each record has one row
    """
    write_record(tmp_path / "outer" / "a.rehu")
    write_record(tmp_path / "outer" / "inner" / "b.rehu")
    rehuco = nesting(tmp_path / "outer", tmp_path / "outer" / "inner")
    outer, inner = rehuco.roots
    cache.reconcile_roots(rehuco.roots)

    result, _ = scan_into(cache, outer.root_id)
    scan_into(cache, inner.root_id)

    assert paths(result) == ["a.rehu"]
    assert result.met_roots == frozenset({inner.root_id})
    assert rows_by_root(cache) == {"outer": ["a.rehu"], "inner": ["b.rehu"]}


def test_a_root_inside_another_reached_through_a_link_is_met_by_identity(tmp_path: Path, cache: CatalogCache) -> None:
    """An outer root spelled through a link walks the inner root under a path no spelling of it matches: only the
    folder's identity says it is the inner root.

    **Test steps:**

    * make a folder ``real`` with a record, and a subfolder ``real/sub`` with another; link ``alias`` to ``real``
    * hold the outer root spelled ``alias`` and the inner root spelled ``real/sub``
    * scan the outer root, then the inner one, into the cache
    * verify the outer scan read only its own record and met the inner root, and each record has one row
    """
    write_record(tmp_path / "real" / "a.rehu")
    write_record(tmp_path / "real" / "sub" / "b.rehu")
    alias = directory_link(tmp_path / "alias", tmp_path / "real")
    rehuco = nesting(alias, tmp_path / "real" / "sub")
    outer, inner = rehuco.roots
    cache.reconcile_roots(rehuco.roots)

    result, _ = scan_into(cache, outer.root_id)
    scan_into(cache, inner.root_id)

    assert paths(result) == ["a.rehu"]
    assert result.met_roots == frozenset({inner.root_id})
    assert rows_by_root(cache) == {"alias": ["a.rehu"], "sub": ["b.rehu"]}


def test_a_root_that_is_another_under_a_second_spelling_is_flagged_and_scanned(
    tmp_path: Path, caplog: LogCaptureFixture
) -> None:
    """A root spelled through a link to another root is that root: neither spelling is more right, so it is still
    scanned, and the other root is named as met.

    **Test steps:**

    * hold a root ``lib`` with a record, and a root ``alias`` linking to it
    * scan ``alias`` with ``lib`` as the other root
    * verify the record was read, ``lib`` met, and the warning logged
    """
    write_record(tmp_path / "lib" / "a.rehu")
    alias = directory_link(tmp_path / "alias", tmp_path / "lib")
    lib = CatalogRoot(UUID(int=1), "lib", tmp_path / "lib", 0, False, True, None)

    with caplog.at_level(logging.WARNING, logger="rehuco_core.rehudb_scan"):
        result = scan(alias, [lib])

    assert paths(result) == ["a.rehu"]
    assert result.met_roots == frozenset({lib.root_id})
    assert "under a second spelling" in caplog.text


# endregion

# region Hardlinks


def test_a_file_with_several_names_in_one_root_keeps_the_smallest(tmp_path: Path, caplog: LogCaptureFixture) -> None:
    """Three names of one record keep one row, the smallest path as the cache folds it, whichever was found first; a
    record with one name has no identity.

    **Test steps:**

    * write a plain record, and a record under three names: ``z.rehu``, ``a/y.rehu``, ``b/x.rehu``
    * scan the root
    * verify only the plain record and ``a/y.rehu`` are read, the two others reported dropped and logged, and only the
      hardlinked one carries its identity
    """
    write_record(tmp_path / "m.rehu")
    first = write_record(tmp_path / "z.rehu")
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    hardlink(tmp_path / "a" / "y.rehu", first)
    hardlink(tmp_path / "b" / "x.rehu", first)

    with caplog.at_level(logging.WARNING, logger="rehuco_core.rehudb_scan"):
        result = scan(tmp_path)

    assert paths(result) == ["m.rehu", "a/y.rehu"]
    assert result.hardlinked == (("a/y.rehu", "z.rehu"), ("a/y.rehu", "b/x.rehu"))
    assert result.identities == {"a/y.rehu": file_id(first)}
    assert caplog.text.count("are one file") == 2


def test_an_unchanged_hardlinked_record_keeps_its_identity_until_it_has_one_name(tmp_path: Path) -> None:
    """A rescan that skips a record still says which file it is; once its second name is gone it is a lone file.

    **Test steps:**

    * scan a record with two names, and rescan against what the first scan read
    * verify the rescan found it unchanged, with its identity
    * delete the second name and rescan; verify no identity and nothing dropped
    """
    first = write_record(tmp_path / "a.rehu")
    hardlink(tmp_path / "b.rehu", first)
    known = signatures_of(scan(tmp_path))

    rescan = scan(tmp_path, known=known)

    assert rescan.unchanged == ("a.rehu",)
    assert rescan.identities == {"a.rehu": file_id(first)}
    (tmp_path / "b.rehu").unlink()
    alone = scan(tmp_path, known=known)
    assert (alone.unchanged, alone.identities, alone.hardlinked) == (("a.rehu",), {}, ())


def test_one_file_under_two_roots_keeps_one_row_under_the_earlier_root_either_order(
    tmp_path: Path, cache: CatalogCache
) -> None:
    """Which root keeps a file named under both is a rule -- the earlier root in the ``.rehuco`` -- so the answer is
    the same whichever root is scanned first.

    **Test steps:**

    * hold two roots, one record named in each through a hardlink
    * scan the second root, then the first: verify the second's row is deleted, its id touched, the pair reported
    * scan the second again: verify its name is dropped again, and one row stays, under the first root
    """
    first_name = write_record(tmp_path / "one" / "a.rehu")
    (tmp_path / "two").mkdir()
    hardlink(tmp_path / "two" / "b.rehu", first_name)
    rehuco = RehucoFile.new()
    rehuco.add_root(tmp_path / "one")
    rehuco.add_root(tmp_path / "two")
    first, second = rehuco.roots
    cache.reconcile_roots(rehuco.roots)

    scan_into(cache, second.root_id)
    (lost,) = cache.rows()
    _, effects = scan_into(cache, first.root_id)

    assert lost.resource_id in effects.touched
    assert effects.hardlinked == [HardlinkedRecord(first.root_id, "a.rehu", second.root_id, "b.rehu")]
    _, again = scan_into(cache, second.root_id)
    assert again.hardlinked == [HardlinkedRecord(first.root_id, "a.rehu", second.root_id, "b.rehu")]
    assert rows_by_root(cache) == {"one": ["a.rehu"]}


def test_a_hardlinked_content_file_is_read_like_any_other(tmp_path: Path) -> None:
    """The content walk is not the catalog's: two names of one content file are two files of the resource.

    **Test steps:**

    * write a resource with a content file and a hardlink to it
    * verify the content walk lists both names
    """
    info = write_record(tmp_path / "course" / "info.rehu")
    video = tmp_path / "course" / "lesson.mp4"
    video.write_bytes(b"video")
    hardlink(tmp_path / "course" / "copy.mp4", video)

    assert sorted(path.name for path in enumerate_content_files(info).files) == ["copy.mp4", "lesson.mp4"]


# endregion
