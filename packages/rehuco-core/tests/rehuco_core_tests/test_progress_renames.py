"""Tests for a renamed video taking its watch progress along ([[field-schema#watch-progress]], #411): the evidence
ladder on its own, then end to end on disk.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from pytest import raises
from rehuco_core import (
    ChecksumEntry,
    MissingFile,
    ProgressEntry,
    RenameCandidate,
    VideoFacts,
    generate_checksums,
    plan_progress_renames,
    reattach_renamed_progress,
    record_progress,
)
from rehuco_core.plugins import DEFAULT_PLUGIN_REGISTRY
from rehuco_core.progress_renames import file_digest, move_progress_entries

from rehuco_core_tests.test_watch_progress import UPDATED, make_tutorial, users_of

DIGEST: Final = "0123456789abcdef"


def hashed(name: str, digest: str = DIGEST) -> ChecksumEntry:
    """A ``.checksum`` entry recording an xxh3 hash.

    :param name: the file's name.
    :param digest: the recorded hash.
    :returns: the parsed entry.
    """
    return ChecksumEntry(name, "xxh3", digest, None, "matched")


@dataclass
class FakeDigests:
    """Answers each candidate's hash from a table, counting the reads."""

    table: dict[str, str | None]
    """The digest by candidate key; ``None`` for a file that cannot be read."""

    reads: list[tuple[str, str]] = field(default_factory=list)
    """Each read asked for, in order."""

    def __call__(self, key: str, algorithm: str) -> str | None:
        """Hash a candidate.

        :param key: the candidate's key.
        :param algorithm: the algorithm name.
        :returns: its digest from the table.
        """
        self.reads.append((key, algorithm))
        return self.table[key]


# region the ladder -- the hash rung
def test_an_equal_hash_moves_the_entry() -> None:
    """A recorded hash decides: the one candidate hashing equal takes the entry, the setting off or not.

    **Test steps:**

    * plan a missing file with a recorded hash against an equal-hashing candidate, the size rung off
    * verify the move
    """
    missing = {"a.mp4": MissingFile(ProgressEntry(1.0, size=10), checksum=hashed("a.mp4"))}

    plan = plan_progress_renames(
        missing, {"b.mp4": RenameCandidate(10)}, match_by_size=False, digest=FakeDigests({"b.mp4": DIGEST})
    )

    assert plan == {"a.mp4": "b.mp4"}


def test_a_different_hash_moves_nothing_even_with_the_size_rung_on() -> None:
    """With a usable hash the size rung never decides: a candidate of the same size hashing differently stays
    unmatched.

    **Test steps:**

    * plan a missing file with a recorded hash against one same-size candidate hashing differently
    * verify no move
    """
    missing = {"a.mp4": MissingFile(ProgressEntry(1.0, size=10), checksum=hashed("a.mp4"))}

    plan = plan_progress_renames(
        missing, {"b.mp4": RenameCandidate(10)}, match_by_size=True, digest=FakeDigests({"b.mp4": "f" * 16})
    )

    assert not plan


def test_the_hash_tells_equal_sizes_apart() -> None:
    """Two candidates of the same size are told apart by the hash, and only same-size candidates are read.

    **Test steps:**

    * plan against two same-size candidates and one of another size
    * verify the equal-hashing one takes the entry and the other size was never read
    """
    missing = {"a.mp4": MissingFile(ProgressEntry(1.0, size=10), checksum=hashed("a.mp4"))}
    digests = FakeDigests({"b.mp4": "f" * 16, "c.mp4": DIGEST, "d.mp4": DIGEST})
    candidates = {"b.mp4": RenameCandidate(10), "c.mp4": RenameCandidate(10), "d.mp4": RenameCandidate(11)}

    plan = plan_progress_renames(missing, candidates, match_by_size=True, digest=digests)

    assert plan == {"a.mp4": "c.mp4"}
    assert sorted(digests.reads) == [("b.mp4", "xxh3"), ("c.mp4", "xxh3")]


def test_a_recorded_hash_in_upper_case_still_matches() -> None:
    """A hash seeded from a legacy ``.sfv`` may be upper case; digests compare as hex, not as text.

    **Test steps:**

    * plan with an upper-case recorded hash against a candidate hashing to its lower case
    * verify the move
    """
    missing = {"a.mp4": MissingFile(ProgressEntry(1.0, size=10), checksum=hashed("a.mp4", DIGEST.upper()))}

    plan = plan_progress_renames(
        missing, {"b.mp4": RenameCandidate(10)}, match_by_size=False, digest=FakeDigests({"b.mp4": DIGEST})
    )

    assert plan == {"a.mp4": "b.mp4"}


def test_a_candidate_that_cannot_be_read_leaves_the_hash_rung_undecided() -> None:
    """A candidate whose read failed might be the renamed file, so a match elsewhere is not *exactly one*: nothing
    moves.

    **Test steps:**

    * plan against an equal-hashing candidate and an unreadable one of the same size
    * verify no move
    """
    missing = {"a.mp4": MissingFile(ProgressEntry(1.0, size=10), checksum=hashed("a.mp4"))}
    candidates = {"b.mp4": RenameCandidate(10), "c.mp4": RenameCandidate(10)}

    plan = plan_progress_renames(
        missing, candidates, match_by_size=True, digest=FakeDigests({"b.mp4": DIGEST, "c.mp4": None})
    )

    assert not plan


def test_each_candidate_is_hashed_once_for_two_missing_files() -> None:
    """Two missing files of one size share their candidates' reads.

    **Test steps:**

    * plan two missing same-size files with different hashes against two candidates
    * verify both move and each candidate was read once
    """
    missing = {
        "a.mp4": MissingFile(ProgressEntry(1.0, size=10), checksum=hashed("a.mp4", "1" * 16)),
        "b.mp4": MissingFile(ProgressEntry(1.0, size=10), checksum=hashed("b.mp4", "2" * 16)),
    }
    digests = FakeDigests({"x.mp4": "2" * 16, "y.mp4": "1" * 16})

    plan = plan_progress_renames(
        missing, {"x.mp4": RenameCandidate(10), "y.mp4": RenameCandidate(10)}, match_by_size=False, digest=digests
    )

    assert plan == {"a.mp4": "y.mp4", "b.mp4": "x.mp4"}
    assert len(digests.reads) == 2


# endregion


# region the ladder -- the size rung
def test_a_unique_size_moves_the_entry_with_the_setting_on() -> None:
    """With no recorded hash, exactly one candidate of the same size takes the entry -- when the setting allows.

    **Test steps:**

    * plan a missing file with no hash against one same-size candidate, with the setting on and off
    * verify the move only with it on, and that nothing was hashed
    """
    missing = {"a.mp4": MissingFile(ProgressEntry(1.0, size=10))}
    candidates = {"b.mp4": RenameCandidate(10), "c.mp4": RenameCandidate(11)}
    digests = FakeDigests({})

    assert plan_progress_renames(missing, candidates, match_by_size=True, digest=digests) == {"a.mp4": "b.mp4"}
    assert not plan_progress_renames(missing, candidates, match_by_size=False, digest=digests)
    assert not digests.reads


def test_two_candidates_of_the_same_size_move_nothing() -> None:
    """Size alone cannot tell two candidates apart.

    **Test steps:**

    * plan a missing file with no hash against two same-size candidates
    * verify no move
    """
    missing = {"a.mp4": MissingFile(ProgressEntry(1.0, size=10))}
    candidates = {"b.mp4": RenameCandidate(10), "c.mp4": RenameCandidate(10)}

    assert not plan_progress_renames(missing, candidates, match_by_size=True, digest=FakeDigests({}))


def test_no_candidate_moves_nothing() -> None:
    """A missing file with nothing new on disk stays missing.

    **Test steps:**

    * plan a missing file against no candidate, and against one of another size
    * verify no move
    """
    missing = {"a.mp4": MissingFile(ProgressEntry(1.0, size=10))}

    assert not plan_progress_renames(missing, {}, match_by_size=True, digest=FakeDigests({}))
    assert not plan_progress_renames(missing, {"b.mp4": RenameCandidate(9)}, match_by_size=True, digest=FakeDigests({}))


def test_a_known_length_rules_out_a_same_size_candidate() -> None:
    """When both lengths are known they must agree within a second; the measured length wins over the entry's, and
    an unknown one rules nothing out.

    **Test steps:**

    * plan against a same-size candidate measured 5 s longer than the missing file's ``videos`` length
    * plan the same with the candidate's length within the tolerance, and with it unmeasured
    * verify only the first moves nothing
    """
    missing = {"a.mp4": MissingFile(ProgressEntry(1.0, 100.0, size=10), facts=VideoFacts(60.0))}

    def plan(facts: VideoFacts | None) -> dict[str, str]:
        """Plan against one same-size candidate.

        :param facts: the candidate's measured facts.
        :returns: the plan.
        """
        return plan_progress_renames(
            missing, {"b.mp4": RenameCandidate(10, facts)}, match_by_size=True, digest=FakeDigests({})
        )

    assert not plan(VideoFacts(65.0))
    assert plan(VideoFacts(60.5)) == {"a.mp4": "b.mp4"}
    assert plan(None) == {"a.mp4": "b.mp4"}


def test_the_entrys_length_decides_when_the_missing_file_was_never_measured() -> None:
    """With no ``videos`` entry left for the missing file, the length its player saw is compared.

    **Test steps:**

    * plan a missing file known only by its entry's length against a candidate measured differently
    * verify no move
    """
    missing = {"a.mp4": MissingFile(ProgressEntry(1.0, 100.0, size=10))}

    plan = plan_progress_renames(
        missing, {"b.mp4": RenameCandidate(10, VideoFacts(60.0))}, match_by_size=True, digest=FakeDigests({})
    )

    assert not plan


# endregion


# region the ladder -- what never moves
def test_an_entry_with_no_recorded_size_never_moves() -> None:
    """Without the size it was played at, no candidate can be narrowed to -- not even by hash.

    **Test steps:**

    * plan a missing file with no size and a recorded hash against an equal-hashing candidate
    * verify no move and no read
    """
    missing = {"a.mp4": MissingFile(ProgressEntry(1.0), checksum=hashed("a.mp4"))}
    digests = FakeDigests({"b.mp4": DIGEST})

    assert not plan_progress_renames(missing, {"b.mp4": RenameCandidate(10)}, match_by_size=True, digest=digests)
    assert not digests.reads


def test_one_candidate_claimed_by_two_missing_files_moves_neither() -> None:
    """Two missing files matching one candidate cannot both be it, and neither is more likely.

    **Test steps:**

    * plan two missing same-size files with no hash against one candidate
    * verify no move
    """
    missing = {"a.mp4": MissingFile(ProgressEntry(1.0, size=10)), "b.mp4": MissingFile(ProgressEntry(2.0, size=10))}

    assert not plan_progress_renames(
        missing, {"c.mp4": RenameCandidate(10)}, match_by_size=True, digest=FakeDigests({})
    )


# endregion


# region reattach_renamed_progress -- on disk
def test_a_renamed_file_takes_its_entry_by_size(tmp_path: Path) -> None:
    """End to end: the size recorded while playing finds the file under its new name; another user's entry, the
    ``videos`` map and ``updated`` are left alone.

    **Test steps:**

    * record progress on a file, rename it, and keep an unrelated file of another size beside it
    * reattach
    * verify the entry moved as stored, and nothing else changed
    """
    folder = tmp_path / "t"
    path = make_tutorial(folder, [], block={"videos": {"01/a.mp4": {"duration": 10.0}}})
    (folder / "01").mkdir()
    (folder / "01" / "a.mp4").write_bytes(b"12345")
    (folder / "01" / "other.mp4").write_bytes(b"123")
    record_progress(path, "admin", "01/a.mp4", 4.0, 10.0)
    record_progress(path, "bob", "01/other.mp4", 1.0, 5.0)
    (folder / "01" / "a.mp4").rename(folder / "01" / "a renamed.mp4")

    assert reattach_renamed_progress(path, "admin") == {"01/a.mp4": "01/a renamed.mp4"}

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["core"]["updated"] == UPDATED
    assert saved["tutorial"]["videos"] == {"01/a.mp4": {"duration": 10.0}}
    assert saved["tutorial"]["users"]["admin"]["progress"] == {
        "01/a renamed.mp4": {"position": 4.0, "duration": 10.0, "size": 5, "viewed": False}
    }
    assert list(saved["tutorial"]["users"]["bob"]["progress"]) == ["01/other.mp4"]


def test_a_renamed_folder_is_matched_by_its_recorded_hashes(tmp_path: Path) -> None:
    """A folder rename moves every file in it; the ``.checksum`` hashes tell each file from a same-size stranger
    elsewhere in the resource, with the size rung off.

    **Test steps:**

    * record progress on two files of one size in a folder, and hash the resource
    * rename the folder and add a same-size file elsewhere
    * reattach with the size rung off
    * verify both entries moved to the right files
    """
    folder = tmp_path / "t"
    path = make_tutorial(folder, [])
    (folder / "01").mkdir()
    (folder / "01" / "a.mp4").write_bytes(b"aaaa")
    (folder / "01" / "b.mp4").write_bytes(b"bbbb")
    generate_checksums(path)
    record_progress(path, "admin", "01/a.mp4", 1.0, None)
    record_progress(path, "admin", "01/b.mp4", 2.0, None)
    (folder / "01").rename(folder / "01 Basics")
    (folder / "stranger.mp4").write_bytes(b"cccc")

    moves = reattach_renamed_progress(path, "admin", match_by_size=False)

    assert moves == {"01/a.mp4": "01 Basics/a.mp4", "01/b.mp4": "01 Basics/b.mp4"}
    progress = users_of(path)["admin"]["progress"]
    assert progress["01 Basics/a.mp4"]["position"] == 1.0
    assert progress["01 Basics/b.mp4"]["position"] == 2.0


def test_a_standalone_records_file_is_matched_under_its_checksum_name(tmp_path: Path) -> None:
    """A standalone record keys its file without the stem, while its ``.checksum`` names it whole; the hash is
    found by that name.

    **Test steps:**

    * hash a standalone record's file and record progress on it
    * change the file's extension, keeping its bytes
    * reattach with the size rung off
    * verify the entry moved to the new extension's key
    """
    path = make_tutorial(tmp_path / "t", [], record="lesson.rehu")
    (tmp_path / "t" / "lesson.mp4").write_bytes(b"video")
    generate_checksums(path)
    record_progress(path, "admin", ".mp4", 3.0, None)
    (tmp_path / "t" / "lesson.mp4").rename(tmp_path / "t" / "lesson.mkv")

    assert reattach_renamed_progress(path, "admin", match_by_size=False) == {".mp4": ".mkv"}
    assert list(users_of(path)["admin"]["progress"]) == [".mkv"]


def test_a_move_carries_the_entry_as_stored(tmp_path: Path) -> None:
    """The entry moves byte for byte, keys this build does not know included.

    **Test steps:**

    * hold an entry with an unknown key for a file now under another name
    * reattach
    * verify the moved entry is unchanged
    """
    entry = {"position": 1.0, "size": 3, "viewed": True, "note": "kept"}
    path = make_tutorial(tmp_path / "t", [], block={"users": {"admin": {"progress": {"old.mp4": entry}}}})
    (tmp_path / "t" / "new.mp4").write_bytes(b"123")

    reattach_renamed_progress(path, "admin")

    assert users_of(path)["admin"]["progress"] == {"new.mp4": entry}


def test_nothing_is_written_when_no_entry_is_missing(tmp_path: Path) -> None:
    """A listing with every keyed file on disk reads no ``.checksum``, hashes nothing and leaves the record alone.

    **Test steps:**

    * record progress on the only file, and add an unkeyed one
    * reattach
    * verify no move and the record's bytes unchanged
    """
    path = make_tutorial(tmp_path / "t", ["a.mp4", "b.mp4"])
    record_progress(path, "admin", "a.mp4", 1.0, None)
    before = path.read_bytes()

    assert not reattach_renamed_progress(path, "admin")
    assert path.read_bytes() == before


def test_a_user_with_no_progress_has_nothing_to_reattach(tmp_path: Path) -> None:
    """A user who never played anything has no entry to move, whatever another user has.

    **Test steps:**

    * reattach for a user with no entries, beside another user's missing one
    * verify no move and the record's bytes unchanged
    """
    block = {"users": {"bob": {"progress": {"old.mp4": {"position": 1.0, "size": 3}}}}}
    path = make_tutorial(tmp_path / "t", [], block=block)
    (tmp_path / "t" / "new.mp4").write_bytes(b"123")
    before = path.read_bytes()

    assert not reattach_renamed_progress(path, "admin")
    assert path.read_bytes() == before


def test_a_missing_file_with_no_match_leaves_the_record_alone(tmp_path: Path) -> None:
    """A missing entry no evidence places is left missing, and a keyed file on disk is never a candidate.

    **Test steps:**

    * hold a missing entry and a keyed file of its size, the size rung off and no ``.checksum``
    * reattach
    * verify no move and the record's bytes unchanged
    """
    block = {
        "users": {"admin": {"progress": {"gone.mp4": {"position": 1.0, "size": 3}, "kept.mp4": {"position": 2.0}}}}
    }
    path = make_tutorial(tmp_path / "t", [], block=block)
    (tmp_path / "t" / "kept.mp4").write_bytes(b"123")
    (tmp_path / "t" / "new.mp4").write_bytes(b"123")
    before = path.read_bytes()

    assert not reattach_renamed_progress(path, "admin", match_by_size=False)
    assert path.read_bytes() == before


def test_a_stored_key_that_is_not_a_content_key_stays_missing(tmp_path: Path) -> None:
    """A key a hand edit wrote wrong names no file inside the resource, so nothing could have been renamed from it:
    it is left missing, and the listing it is read in does not fail on it.

    **Test steps:**

    * hold an entry under ``../x.mp4`` with a size matching an unkeyed file
    * reattach
    * verify no move and the entry still there
    """
    block = {"users": {"admin": {"progress": {"../x.mp4": {"position": 1.0, "size": 3}}}}}
    path = make_tutorial(tmp_path / "t", [], block=block)
    (tmp_path / "t" / "new.mp4").write_bytes(b"123")

    assert not reattach_renamed_progress(path, "admin")
    assert list(users_of(path)["admin"]["progress"]) == ["../x.mp4"]


def test_a_checksum_record_naming_a_file_twice_holds_no_usable_hash(tmp_path: Path) -> None:
    """A record listing one name under two hashes does not say which is the file's, so the size rung decides.

    **Test steps:**

    * write a ``.checksum`` naming the missing file twice, neither hash the candidate's
    * reattach with the size rung on
    * verify the entry moved by size
    """
    block = {"users": {"admin": {"progress": {"old.mp4": {"position": 1.0, "size": 3}}}}}
    path = make_tutorial(tmp_path / "t", [], block=block)
    (tmp_path / "t" / "new.mp4").write_bytes(b"123")
    entries = [{"name": "old.mp4", "xxh3": "1" * 16}, {"name": "old.mp4", "xxh3": "2" * 16}]
    (tmp_path / "t" / "info.checksum").write_text(json.dumps({"version": 1, "files": entries}), encoding="utf-8")

    assert reattach_renamed_progress(path, "admin") == {"old.mp4": "new.mp4"}


def test_a_move_the_fresh_record_overtook_is_skipped(tmp_path: Path) -> None:
    """The moves are re-checked against the record as read for the write: an entry already gone, or a new key
    already taken, is left as the fresh record holds it.

    **Test steps:**

    * write a plan whose old key has no entry and one whose new key already has one
    * verify neither applied and the entries unchanged
    """
    progress = {"a.mp4": {"position": 1.0}, "b.mp4": {"position": 2.0}}
    path = make_tutorial(tmp_path / "t", [], block={"users": {"admin": {"progress": progress}}})

    applied = move_progress_entries(
        path,
        "admin",
        {"gone.mp4": "c.mp4", "a.mp4": "b.mp4"},
        current_username="admin",
        plugins=DEFAULT_PLUGIN_REGISTRY,
    )

    assert not applied
    assert users_of(path)["admin"]["progress"] == progress


def test_a_file_that_cannot_be_read_hashes_to_nothing(tmp_path: Path) -> None:
    """An unreadable candidate answers no digest rather than raising.

    **Test steps:**

    * hash a path that does not exist
    * verify ``None``
    """
    assert file_digest(tmp_path / "absent.mp4", "xxh3") is None


def test_reattaching_refuses_a_record_that_is_not_a_tutorial(tmp_path: Path) -> None:
    """Watch progress lives on tutorials only.

    **Test steps:**

    * reattach on a course record
    * verify the refusal
    """
    path = make_tutorial(tmp_path / "t", [], resource_type="course")

    with raises(ValueError, match="tutorials only"):
        reattach_renamed_progress(path, "admin")


# endregion
