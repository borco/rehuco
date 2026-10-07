"""Tests for :class:`~rehuco_core.RootFolderLister` (#378)."""

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

from pytest import fixture
from rehuco_core import (
    TRUST_NOT_TRACKED,
    ChecksumTrust,
    FileType,
    RehucoRoot,
    RehuDocument,
    RenameCoordinator,
    RootFolderLister,
    RootStorage,
)

ROOT_ID: Final = UUID("a41b9c3d-0000-4000-8000-000000000001")


@fixture(name="library")
def library_fixture(tmp_path: Path) -> Path:
    """A root folder holding a directory-scoped resource, a video and a record.

    :param tmp_path: pytest's temporary directory.
    :returns: the root folder.
    """
    root = tmp_path / "library"
    (root / "python" / "week1").mkdir(parents=True)
    (root / "python" / "info.rehu").write_text("{}", encoding="utf-8")
    (root / "intro.mp4").write_bytes(b"x")
    (root / "info.rehu").write_text("{}", encoding="utf-8")
    return root


def lister_for(
    root: Path, coordinator: RenameCoordinator | None = None, trust: ChecksumTrust | None = None
) -> RootFolderLister:
    """A lister over one root.

    :param root: the root's folder.
    :param coordinator: what each read is held under.
    :param trust: what says when a record began to be trusted here.
    :returns: the lister.
    """
    return RootFolderLister(
        [RehucoRoot(ROOT_ID, root, "library", RootStorage.LOCAL)], coordinator=coordinator, trust=trust
    )


def test_a_root_lists_its_entries_with_their_kinds(library: Path) -> None:
    """The root's own folder lists every entry, folders marked and files typed.

    **Test steps:**

    * list the root with no relative path
    * verify it is reachable and the entries are the subfolder, the video and the record, by type
    """
    listing = lister_for(library).list(ROOT_ID)
    assert listing.reachable
    assert {(entry.name, entry.file_type, entry.is_directory) for entry in listing.entries} == {
        ("python", FileType.DIRECTORY, True),
        ("intro.mp4", FileType.VIDEO, False),
        ("info.rehu", FileType.RECORD, False),
    }


def test_a_relative_path_lists_a_folder_under_the_root(library: Path) -> None:
    """A relative path, one name per step, lists that folder.

    **Test steps:**

    * list ``python`` and then ``python/week1``
    * verify the first holds ``week1`` and its record, and the second is reachable and empty
    """
    lister = lister_for(library)
    assert {entry.name for entry in lister.list(ROOT_ID, ("python",)).entries} == {"week1", "info.rehu"}
    deepest = lister.list(ROOT_ID, ("python", "week1"))
    assert deepest.reachable
    assert not deepest.entries


def test_a_missing_folder_and_an_unknown_root_are_not_reachable(library: Path) -> None:
    """Gone is not empty: both answers say so, and neither raises.

    **Test steps:**

    * list a folder that does not exist, and a root id the lister was not given
    * verify both come back empty and not reachable
    """
    lister = lister_for(library)
    for listing in (lister.list(ROOT_ID, ("nope",)), lister.list(uuid4())):
        assert not listing.reachable
        assert not listing.entries


def test_a_listing_leaves_the_folder_renamable(library: Path) -> None:
    """No handle is held after a listing, so the folder can be renamed at once.

    **Test steps:**

    * list ``python`` under a coordinator, then rename the resource whose folder it is
    * verify the rename lands
    """
    coordinator = RenameCoordinator()
    lister_for(library, coordinator).list(ROOT_ID, ("python",))
    coordinator.rename(library / "python" / "info.rehu", "py")
    assert (library / "py" / "week1").is_dir()


def test_a_listing_waits_for_a_rename_in_flight(library: Path) -> None:
    """A read started while a rename is waiting to run holds off until the rename is done, and then sees its result.

    **Test steps:**

    * occupy the coordinator with a reader on one thread, and start a rename on another, which raises
      ``yield_wanted`` and waits for that reader
    * start a listing on a third thread: it waits, since a rename is pending
    * release the reader
    * verify the rename landed and the listing returned afterwards, naming the folder as renamed
    """
    coordinator = RenameCoordinator()
    lister = lister_for(library, coordinator)
    reader_in = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with coordinator.holding():
            reader_in.set()
            release.wait(5)

    holder = threading.Thread(target=hold)
    holder.start()
    assert reader_in.wait(5)
    renamer = threading.Thread(target=lambda: coordinator.rename(library / "python" / "info.rehu", "py"))
    renamer.start()
    while not coordinator.yield_wanted:
        threading.Event().wait(0.01)
    listed: list[set[str]] = []
    reader = threading.Thread(target=lambda: listed.append({entry.name for entry in lister.list(ROOT_ID).entries}))
    reader.start()
    release.set()
    for thread in (holder, renamer, reader):
        thread.join(5)
    assert listed == [{"py", "intro.mp4", "info.rehu"}]


# region What the records that cover a folder's files say (#457)

STAMP: Final = "2026-10-05T08:15:00Z"
DIGEST: Final = "aabbccdd"


def write_record(path: Path, *entries: dict[str, str]) -> None:
    """Write a ``.checksum`` record.

    :param path: the record's path.
    :param entries: the entries, as the record keeps them.
    """
    path.write_text(json.dumps({"version": 1, "files": list(entries)}), encoding="utf-8")


def entry(name: str, status: str = "matched", digest: str = DIGEST) -> dict[str, str]:
    """One entry of a record, hashed and dated.

    :param name: the file's name relative to the record.
    :param status: what the last check answered.
    :param digest: the recorded CRC32.
    :returns: the entry.
    """
    return {"name": name, "crc32": digest, "verified": STAMP, "status": status}


@fixture(name="resources")
def resources_fixture(tmp_path: Path) -> Path:
    """A root with a file-scoped resource, a directory-scoped one with a subfolder, and a record that is not one.

    ``loose`` holds ``foo.rehu`` with its ``foo.checksum`` (listing ``foo.mp4``, not ``foo.srt``), a screenshot, a
    stranger's video and ``bar.rehu`` with no checksum file. ``pack`` holds ``info.rehu`` and ``info.checksum``, a
    video, a subfolder with another video and, in its own resource, a nested folder. ``broken`` holds an unreadable
    record.

    :param tmp_path: pytest's temporary directory.
    :returns: the root folder.
    """
    root = tmp_path / "library"
    loose = root / "loose"
    pack = root / "pack"
    (pack / "sub").mkdir(parents=True)
    (pack / "nested").mkdir()
    loose.mkdir()
    (root / "broken").mkdir()
    for name in ("foo.rehu", "foo.mp4", "foo.srt", "foo00.jpg", "stranger.mp4", "bar.rehu", "bar.mp4"):
        (loose / name).write_bytes(b"x")
    write_record(loose / "foo.checksum", entry("foo.mp4"))
    for name in ("info.rehu", "01.mp4", "02.mp4", "sub/03.mp4", "sub/04.mp4", "nested/info.rehu", "nested/05.mp4"):
        (pack / name).write_bytes(b"x")
    write_record(
        pack / "info.checksum",
        entry("01.mp4"),
        entry("sub/03.mp4", "mismatched"),
        entry("nested/05.mp4"),
        {"name": "sub/04.mp4", "crc32": "not hex"},
        {"name": 3},  # type: ignore[dict-item]
    )
    (root / "broken" / "info.rehu").write_bytes(b"x")
    (root / "broken" / "info.checksum").write_text("not json", encoding="utf-8")
    (root / "broken" / "a.mp4").write_bytes(b"x")
    return root


def test_a_file_scoped_record_covers_its_own_files_and_says_what_it_lists(resources: Path) -> None:
    """``foo.checksum`` speaks for ``foo``'s files only: a listed one carries its entry, an unlisted one none.

    **Test steps:**

    * list the folder holding ``foo.rehu``, ``foo.checksum``, ``bar.rehu`` and a stranger's video
    * verify ``foo.mp4`` has its entry, ``foo.srt`` is covered without one, and nothing else is covered -- not the
      screenshot, not the stranger, not ``bar``'s file whose record has no checksum file
    """
    covered = lister_for(resources).list(ROOT_ID, ("loose",)).covered

    assert set(covered) == {"foo.mp4", "foo.srt"}
    assert covered["foo.mp4"].entry is not None
    assert covered["foo.mp4"].entry.digest == DIGEST
    assert covered["foo.srt"].entry is None


def test_a_directory_scoped_record_covers_its_folder_and_the_folders_below_it(resources: Path) -> None:
    """``info.checksum`` names a subfolder's files by their path under it, and the caller says where it is.

    **Test steps:**

    * list ``pack`` itself, then ``pack/sub`` told the record above it
    * verify each file reads its own entry, a file the record does not list is covered with none, and an entry
      this build cannot read is flagged
    """
    lister = lister_for(resources)

    top = lister.list(ROOT_ID, ("pack",)).covered
    below = lister.list(ROOT_ID, ("pack", "sub"), covering=("pack", "info.rehu")).covered

    assert set(top) == {"01.mp4", "02.mp4"}
    assert top["01.mp4"].entry is not None
    assert top["02.mp4"].entry is None
    assert set(below) == {"03.mp4", "04.mp4"}
    assert below["03.mp4"].entry is not None
    assert below["03.mp4"].entry.status == "mismatched"
    assert below["04.mp4"].malformed


def test_a_folder_below_a_resource_is_covered_only_when_the_caller_names_the_record(resources: Path) -> None:
    """The lister reads one folder: which record is above it is the caller's to say, from listings it already holds.

    **Test steps:**

    * list ``pack/sub`` with no record named
    * verify nothing is covered
    """
    assert not lister_for(resources).list(ROOT_ID, ("pack", "sub")).covered


def test_a_nested_resource_is_not_covered_by_the_record_above_it(resources: Path) -> None:
    """A folder with an ``info.rehu`` of its own is another resource, whatever the record above lists.

    **Test steps:**

    * list ``pack/nested`` told the record above it
    * verify nothing is covered, though ``info.checksum`` lists ``nested/05.mp4``
    """
    listing = lister_for(resources).list(ROOT_ID, ("pack", "nested"), covering=("pack", "info.rehu"))

    assert not listing.covered


def test_a_record_that_cannot_be_read_covers_nothing(resources: Path) -> None:
    """An unparseable record is not a reason to fail the listing, or to call its files unchecked.

    **Test steps:**

    * list the folder whose ``info.checksum`` is not JSON
    * verify the listing is reachable, holds the video, and covers nothing
    """
    listing = lister_for(resources).list(ROOT_ID, ("broken",))

    assert listing.reachable
    assert "a.mp4" in {entry.name for entry in listing.entries}
    assert not listing.covered


def test_a_covered_file_says_since_when_the_machine_has_trusted_its_record(resources: Path) -> None:
    """The stamp of an old check is only as good as the place it was made: the trust store says since when.

    **Test steps:**

    * list ``pack`` with no trust store, with one that does not know the record, and with one that has registered it
    * verify the answers: every stamp counts, the location is unknown, and the registered instant
    """
    pack = resources / "pack"
    RehuDocument.new(pack / "info.rehu").save()
    store = ChecksumTrust()
    store.attach(resources.parent / "trust.json")

    plain = lister_for(resources).list(ROOT_ID, ("pack",)).covered["01.mp4"]
    unknown = lister_for(resources, trust=store).list(ROOT_ID, ("pack",)).covered["01.mp4"]
    store.register(pack / "info.rehu", datetime(2026, 9, 1, tzinfo=UTC))
    known = lister_for(resources, trust=store).list(ROOT_ID, ("pack",)).covered["01.mp4"]

    assert plain.trusted_since == TRUST_NOT_TRACKED
    assert unknown.trusted_since is None
    assert known.trusted_since == datetime(2026, 9, 1, tzinfo=UTC)


# endregion
