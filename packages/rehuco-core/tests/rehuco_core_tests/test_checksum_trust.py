"""Tests for the per-machine register of where each ``.checksum`` record was verified (#357).

The trust file, the ``.rehu`` the id is read from, and path resolution are all faked: what is under test
is which location a record is trusted at and since when, and a fake is what lets a test count the writes
a sweep's batching exists to save -- and remap a drive, which no real directory can do on demand.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final

from pytest import fixture, mark
from pytest_mock import MockerFixture
from rehuco_core import TRUST_NOT_TRACKED, ChecksumTrust, RehuFormatError

LIBRARY: Final = Path("/fake/library")
INFO_PATH: Final = LIBRARY / "sculpting" / "info.rehu"
RENAMED_PATH: Final = LIBRARY / "sculpting v2" / "info.rehu"
TC_PATH: Final = LIBRARY / "painting" / "info.tc"

MAPPED_LIBRARY: Final = Path("/mapped/library")
"""The same library reached through a second mount point -- a share mapped under another drive letter --
which resolves to :data:`LIBRARY`."""

TRUST_FILE: Final = Path("/fake/config/checksum-trust.json")

RESOURCE_ID: Final = "0b6f3c1e-2d6a-4a8e-9a53-5d1f0c1b7e42"
OTHER_ID: Final = "7d2e9f40-8c1b-4f5a-b3e6-1a9c2d4e6f80"

VERIFIED_AT: Final = datetime(2026, 8, 5, 12, 0, 30, 250_000, tzinfo=UTC)
"""A run's start instant, with the microseconds a clock reports and a stamp drops."""

LATER: Final = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)


# region Fakes


class FakeFiles:
    """The trust file and the ``.rehu`` ids, and a record of every write.

    :param ids: each ``.rehu``'s id, by path; a path missing here does not load.
    """

    def __init__(self, ids: dict[Path, str]) -> None:
        self.ids: Final = ids
        self.texts: Final[dict[Path, str]] = {}
        self.writes: list[Path] = []
        self.read_error: OSError | None = None
        """What reading the trust file raises instead of serving it."""
        self.write_error: OSError | None = None
        """What writing the trust file raises instead of storing it."""

    def read_text(self, path: Path) -> str:
        """Serve a file's text.

        :param path: the file.
        :returns: its text.
        :raises OSError: :attr:`read_error`, or ``FileNotFoundError`` when nothing is there.
        """
        if self.read_error is not None:
            raise self.read_error
        if path not in self.texts:
            raise FileNotFoundError(str(path))
        return self.texts[path]

    def write_text(self, path: Path, text: str) -> None:
        """Store a file's text, counting the write.

        :param path: the file.
        :param text: what to store.
        :raises OSError: :attr:`write_error`.
        """
        if self.write_error is not None:
            raise self.write_error
        self.writes.append(path)
        self.texts[path] = text

    def load(self, path: Path) -> SimpleNamespace:
        """Stand in for :meth:`~rehuco_core.RehuDocument.load`, answering only the id.

        :param path: the ``.rehu``.
        :returns: an object carrying ``id``.
        :raises RehuFormatError: no id is known for ``path``.
        """
        if path not in self.ids:
            raise RehuFormatError(f"Not a document: {path}")
        return SimpleNamespace(id=self.ids[path])

    @staticmethod
    def resolve(path: Path) -> Path:
        """Resolve a path as the operating system would, with :data:`MAPPED_LIBRARY` mapped to :data:`LIBRARY`.

        :param path: the path to resolve.
        :returns: the canonical path.
        """
        if path == MAPPED_LIBRARY or MAPPED_LIBRARY in path.parents:
            return LIBRARY / path.relative_to(MAPPED_LIBRARY)
        return path

    @property
    def saved(self) -> dict[str, Any]:
        """The trust file as last written.

        :returns: the parsed file.
        """
        return json.loads(self.texts[TRUST_FILE])


@fixture(name="files")
def fixture_files(mocker: MockerFixture) -> FakeFiles:
    """The filesystem under the store's feet: one resource with an id, and an empty trust file.

    :param mocker: pytest-mock fixture.
    :returns: the fake.
    """
    files = FakeFiles({INFO_PATH: RESOURCE_ID, RENAMED_PATH: RESOURCE_ID})
    mocker.patch.object(Path, "read_text", autospec=True, side_effect=lambda self, **_kwargs: files.read_text(self))
    mocker.patch.object(Path, "mkdir", autospec=True)
    mocker.patch.object(Path, "resolve", autospec=True, side_effect=lambda self, **_kwargs: files.resolve(self))
    mocker.patch("rehuco_core.checksum_trust.atomic_write_text", side_effect=files.write_text)
    mocker.patch("rehuco_core.checksum_trust.RehuDocument.load", side_effect=files.load)
    return files


@fixture(name="clock")
def fixture_clock(mocker: MockerFixture) -> list[float]:
    """The monotonic clock the store batches writes by, as a one-element list a test moves forward.

    :param mocker: pytest-mock fixture.
    :returns: the clock's current reading, in seconds.
    """
    clock = [1000.0]
    mocker.patch("rehuco_core.checksum_trust.time.monotonic", side_effect=lambda: clock[0])
    return clock


# endregion


# region ChecksumTrust tests


def test_a_store_with_no_file_tracks_nothing(files: FakeFiles) -> None:
    """Until the agent attaches a file, freshness is the window's alone and nothing is written -- what
    the node, a script and every test that never asks keep.

    **Test steps:**

    * build a store with no file
    * ask about a location, register it, and move it
    * check every answer is *not tracked* and nothing was written
    """
    trust = ChecksumTrust()

    trust.register(INFO_PATH, VERIFIED_AT)
    trust.moved(INFO_PATH, RENAMED_PATH)

    assert not trust.tracking
    assert trust.trusted_since(INFO_PATH) == TRUST_NOT_TRACKED
    assert files.writes == []


def test_a_location_never_verified_here_is_not_trusted(files: FakeFiles) -> None:
    """Unverified until verified here: a fresh machine trusts nothing.

    **Test steps:**

    * attach an empty store and ask about a location
    """
    del files
    trust = ChecksumTrust(TRUST_FILE)

    assert trust.tracking
    assert trust.trusted_since(INFO_PATH) is None


def test_a_registered_location_is_trusted_from_the_run_s_start(files: FakeFiles) -> None:
    """Registering trusts the location from the instant given, in whole seconds as a stamp spells it --
    so a stamp the same run wrote is at, not before, the trust.

    **Test steps:**

    * register a location
    * check it is trusted from that instant, and that the file was written once with the resource's id
    """
    trust = ChecksumTrust(TRUST_FILE)

    trust.register(INFO_PATH, VERIFIED_AT)

    assert trust.trusted_since(INFO_PATH) == VERIFIED_AT.replace(microsecond=0)
    assert files.writes == [TRUST_FILE]
    assert files.saved == {
        "version": 1,
        "locations": {
            ChecksumTrust.location_key(INFO_PATH): {"id": RESOURCE_ID, "trusted_since": "2026-08-05T12:00:30Z"}
        },
    }


def test_a_trusted_location_keeps_its_instant(files: FakeFiles) -> None:
    """A later run at a trusted location must not move the trust forward, which would distrust every stamp
    written there before it.

    **Test steps:**

    * register a location, then register it again a day later
    * check the first instant stands and the second registration wrote nothing
    """
    trust = ChecksumTrust(TRUST_FILE)
    trust.register(INFO_PATH, VERIFIED_AT)

    trust.register(INFO_PATH, LATER)

    assert trust.trusted_since(INFO_PATH) == VERIFIED_AT.replace(microsecond=0)
    assert files.writes == [TRUST_FILE]


def test_a_different_resource_at_a_trusted_location_is_not_trusted(files: FakeFiles) -> None:
    """A resource moved into a path this machine trusts does not inherit that path's trust, and verifying
    it there replaces the old entry with its own.

    **Test steps:**

    * register a location, then put a different resource there
    * check it is not trusted, and that registering it trusts it from its own instant
    """
    trust = ChecksumTrust(TRUST_FILE)
    trust.register(INFO_PATH, VERIFIED_AT)
    files.ids[INFO_PATH] = OTHER_ID

    assert trust.trusted_since(INFO_PATH) is None

    trust.register(INFO_PATH, LATER)

    assert trust.trusted_since(INFO_PATH) == LATER


@mark.parametrize("path", [TC_PATH, LIBRARY / "drawing" / "info.rehu"], ids=["a .tc", "a .rehu that will not load"])
def test_a_record_with_no_readable_id_is_trusted_by_location_alone(files: FakeFiles, path: Path) -> None:
    """A ``.tc`` carries no id and a broken ``.rehu`` yields none; either is still trusted where it was
    verified, guarded by nothing more than its location.

    **Test steps:**

    * register a record whose resource has no readable id
    * check it is trusted
    """
    del files
    trust = ChecksumTrust(TRUST_FILE)

    trust.register(path, LATER)

    assert trust.trusted_since(path) == LATER


def test_a_rename_carries_the_trust_to_the_new_name(files: FakeFiles) -> None:
    """A rename rewrites no bytes, so what was verified under the old name holds under the new one -- and
    the old name, which no longer exists, is trusted no more.

    **Test steps:**

    * register a location, then move it to a new name
    * check the new name is trusted from the same instant and the old one is not
    """
    trust = ChecksumTrust(TRUST_FILE)
    trust.register(INFO_PATH, VERIFIED_AT)

    trust.moved(INFO_PATH, RENAMED_PATH)

    assert trust.trusted_since(RENAMED_PATH) == VERIFIED_AT.replace(microsecond=0)
    assert trust.trusted_since(INFO_PATH) is None
    assert files.writes == [TRUST_FILE, TRUST_FILE]


def test_renaming_an_untrusted_resource_changes_nothing(files: FakeFiles) -> None:
    """There is no trust to carry, so nothing is written.

    **Test steps:**

    * move a location the store never registered
    * check nothing was written and the new name is not trusted
    """
    trust = ChecksumTrust(TRUST_FILE)

    trust.moved(INFO_PATH, RENAMED_PATH)

    assert files.writes == []
    assert trust.trusted_since(RENAMED_PATH) is None


def test_a_share_mapped_under_another_mount_point_keeps_its_trust(files: FakeFiles) -> None:
    """The container is resolved before keying, so the same record reached through a second mount point
    is the same location.

    **Test steps:**

    * register a location through the library's own path
    * ask about it through the mapped one
    """
    trust = ChecksumTrust(TRUST_FILE)
    trust.register(INFO_PATH, LATER)
    mapped = MAPPED_LIBRARY / "sculpting" / "info.rehu"
    files.ids[mapped] = RESOURCE_ID

    assert trust.trusted_since(mapped) == LATER


def test_a_file_scoped_record_is_keyed_by_its_own_name(files: FakeFiles) -> None:
    """Two file-scoped resources in one folder keep separate records, and so separate trust.

    **Test steps:**

    * register one file-scoped resource
    * check its sibling in the same folder is not trusted
    """
    del files
    trust = ChecksumTrust(TRUST_FILE)

    trust.register(LIBRARY / "foo.tc", LATER)

    assert trust.trusted_since(LIBRARY / "foo.tc") == LATER
    assert trust.trusted_since(LIBRARY / "bar.tc") is None


def test_what_was_saved_is_what_the_next_session_reads(files: FakeFiles) -> None:
    """Trust outlives the process that earned it.

    **Test steps:**

    * register a location, then attach a second store to the same file
    * check the second store trusts it
    """
    del files
    ChecksumTrust(TRUST_FILE).register(INFO_PATH, LATER)

    assert ChecksumTrust(TRUST_FILE).trusted_since(INFO_PATH) == LATER


@mark.parametrize(
    "text",
    [
        "not json",
        json.dumps(["a", "list"]),
        json.dumps({"version": 2, "locations": {}}),
        json.dumps({"version": 1, "locations": ["a", "list"]}),
    ],
    ids=["not json", "not an object", "a newer version", "locations not an object"],
)
def test_a_trust_file_this_build_cannot_read_trusts_nothing(files: FakeFiles, text: str, caplog: Any) -> None:
    """Losing the trust costs a re-verification and never a false *current*, so a file that does not read
    is logged and read as empty rather than guessed at.

    **Test steps:**

    * write something unreadable where the trust file lives, then attach
    * check nothing is trusted and the reason was logged
    """
    files.texts[TRUST_FILE] = text

    with caplog.at_level("WARNING", logger="rehuco_core.checksum_trust"):
        trust = ChecksumTrust(TRUST_FILE)

    assert trust.trusted_since(INFO_PATH) is None
    assert "every location reads unverified" in caplog.text


def test_an_entry_that_is_not_an_object_is_dropped(files: FakeFiles) -> None:
    """One broken entry costs itself; its neighbours still read.

    **Test steps:**

    * save a trusted location, add a broken entry beside it, and attach again
    * check the good entry is still trusted
    """
    ChecksumTrust(TRUST_FILE).register(INFO_PATH, LATER)
    saved = files.saved
    saved["locations"]["elsewhere"] = "not an object"
    files.texts[TRUST_FILE] = json.dumps(saved)

    assert ChecksumTrust(TRUST_FILE).trusted_since(INFO_PATH) == LATER


def test_a_trust_file_that_cannot_be_opened_trusts_nothing(files: FakeFiles, caplog: Any) -> None:
    """A refused read is logged and read as empty, the same as a file that will not parse.

    **Test steps:**

    * make the trust file refuse to open, then attach
    """
    files.read_error = PermissionError(str(TRUST_FILE))

    with caplog.at_level("ERROR", logger="rehuco_core.checksum_trust"):
        trust = ChecksumTrust(TRUST_FILE)

    assert trust.trusted_since(INFO_PATH) is None
    assert "could not be read" in caplog.text


def test_a_trust_file_that_cannot_be_written_does_not_fail_the_caller(files: FakeFiles, caplog: Any) -> None:
    """Registration happens after a run has written its record, and must not fail that run -- the trust is
    still held for this session.

    **Test steps:**

    * make the trust file refuse writes, and register a location
    * check nothing was raised, the failure was logged, and the location is trusted in memory
    """
    files.write_error = PermissionError(str(TRUST_FILE))
    trust = ChecksumTrust(TRUST_FILE)

    with caplog.at_level("ERROR", logger="rehuco_core.checksum_trust"):
        trust.register(INFO_PATH, LATER)

    assert "could not be saved" in caplog.text
    assert trust.trusted_since(INFO_PATH) == LATER


def test_detaching_stops_the_tracking(files: FakeFiles) -> None:
    """Attaching ``None`` is how tracking stops: freshness goes back to the window alone.

    **Test steps:**

    * register a location, then detach
    * check nothing is tracked, and that saving now writes nothing
    """
    trust = ChecksumTrust(TRUST_FILE)
    trust.register(INFO_PATH, LATER)

    trust.attach(None)
    trust.save()

    assert not trust.tracking
    assert trust.trusted_since(INFO_PATH) == TRUST_NOT_TRACKED
    assert files.writes == [TRUST_FILE]


def test_deferred_saves_write_once_at_the_end(files: FakeFiles, clock: list[float]) -> None:
    """A sweep registers resource after resource, and one write per registration would rewrite a growing
    file thousands of times; deferred, they are written once, on the way out.

    **Test steps:**

    * register three locations inside a deferred block, a second apart
    * check nothing was written until the block ended, and then once
    """
    trust = ChecksumTrust(TRUST_FILE)

    with trust.deferred_saves():
        for name in ("one", "two", "three"):
            trust.register(LIBRARY / name / "info.tc", LATER)
            clock[0] += 1.0
        assert files.writes == []

    assert files.writes == [TRUST_FILE]
    assert len(files.saved["locations"]) == 3


def test_a_long_deferred_block_still_writes_every_minute(files: FakeFiles, clock: list[float]) -> None:
    """A sweep that runs for hours still writes its trust down as it goes, so a crash loses at most a
    minute of it.

    **Test steps:**

    * register a location inside a deferred block, then another after more than a minute
    * check the second one was written straight away, and the block's end had nothing left to write
    """
    trust = ChecksumTrust(TRUST_FILE)

    with trust.deferred_saves():
        trust.register(LIBRARY / "one" / "info.tc", LATER)
        clock[0] += 61.0
        trust.register(LIBRARY / "two" / "info.tc", LATER)
        assert files.writes == [TRUST_FILE]

    assert files.writes == [TRUST_FILE]


def test_nested_deferred_blocks_write_when_the_outermost_ends(files: FakeFiles, clock: list[float]) -> None:
    """A sweep's verify may itself defer; only the outermost block's end writes what was held back.

    **Test steps:**

    * register a location inside a block nested in another
    * check nothing was written when the inner block ended, and once when the outer one did
    """
    del clock
    trust = ChecksumTrust(TRUST_FILE)

    with trust.deferred_saves():
        with trust.deferred_saves():
            trust.register(INFO_PATH, LATER)
        assert files.writes == []

    assert files.writes == [TRUST_FILE]


def test_a_deferred_block_that_changed_nothing_writes_nothing(files: FakeFiles, clock: list[float]) -> None:
    """A sweep over an already-trusted catalog registers nothing, and the end of its block has nothing to
    write.

    **Test steps:**

    * open and close a deferred block without registering anything
    """
    del clock
    trust = ChecksumTrust(TRUST_FILE)

    with trust.deferred_saves():
        pass

    assert files.writes == []


# endregion
