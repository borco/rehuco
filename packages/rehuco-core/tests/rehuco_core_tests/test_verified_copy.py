"""Tests for the verified copy (#339): the source's record must cover its content, the copy resumes per file, follows
a rename of its record and is checked against the record, the original goes only once the copy proved out and is level
with it, and a cancelled copy takes back what it wrote."""

import filecmp
import json
import logging
from pathlib import Path
from typing import Any, Final

from pytest import LogCaptureFixture, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    CopyJournal,
    LinkInRecordError,
    Relocation,
    RenameCoordinator,
    SourceChangedError,
    VerifiedCopy,
    VerifiedCopyError,
    check_move_source,
    generate_checksums,
    lock_path_for,
    recorded_digests,
    remove_leftovers,
)
from rehuco_core.verified_copy import name_list

from rehuco_core_tests.real_links import directory_link

RECORD_TEXT: Final = "{}"
CONTENT: Final = b"content bytes"
PART: Final = b"a nested part"
SCREENSHOT: Final = b"a screenshot"
NEW_NAME: Final = "Intro [2024]"
DENIED: Final = 13
"""``EACCES``: a refusal no retry waits out."""


def make_folder_record(root: Path, *, checksums: bool = True) -> Path:
    """A directory-scoped record at ``root/Old/Intro``: a content file, a nested one, a screenshot, an empty folder.

    :param root: the source root's folder.
    :param checksums: whether to generate its checksum record.
    :returns: its ``info.rehu``.
    """
    folder = root / "Old" / "Intro"
    (folder / "sub").mkdir(parents=True)
    (folder / "empty").mkdir()
    (folder / "content.zip").write_bytes(CONTENT)
    (folder / "sub" / "part.bin").write_bytes(PART)
    (folder / "info00.jpg").write_bytes(SCREENSHOT)
    record = folder / "info.rehu"
    record.write_text(RECORD_TEXT)
    if checksums:
        generate_checksums(record)
    return record


def make_file_record(root: Path) -> Path:
    """A file-scoped record ``root/foo.rehu`` with its archive, a screenshot, its checksums, and someone else's file.

    :param root: the source root's folder.
    :returns: its ``foo.rehu``.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "foo.zip").write_bytes(CONTENT)
    (root / "foo00.jpg").write_bytes(SCREENSHOT)
    (root / "foobar.zip").write_bytes(CONTENT)
    record = root / "foo.rehu"
    record.write_text(RECORD_TEXT)
    generate_checksums(record)
    return record


def copier(record: Path, into: Path, name: str = NEW_NAME) -> VerifiedCopy:
    """A copy of ``record`` into ``into``, read through a coordinator of its own.

    :param record: the source ``.rehu``.
    :param into: the destination folder.
    :param name: the name there.
    :returns: the copy.
    """
    return VerifiedCopy(record, into, name, coordinator=RenameCoordinator())


def tree(folder: Path) -> list[str]:
    """Every file and folder under ``folder``, relative and POSIX-spelled.

    :param folder: the folder.
    :returns: the sorted list.
    """
    return sorted(path.relative_to(folder).as_posix() for path in folder.rglob("*"))


def failing_for(name: str, real: Any) -> Any:
    """A ``Path`` method stand-in failing for the file named ``name`` and running ``real`` for every other.

    :param name: the file name that fails.
    :param real: the method it stands in for.
    :returns: the side effect.
    """

    def side_effect(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self.name == name:
            raise PermissionError(DENIED, "Access is denied", str(self))
        return real(self, *args, **kwargs)

    return side_effect


# region the source's record
def test_a_record_with_no_checksums_is_refused(tmp_path: Path) -> None:
    """A copy can only be checked against a record, so a source without one is refused before anything is read.

    **Test steps:**

    * make a folder record with no checksum record
    * check the source check raises, naming the remedy
    """
    record = make_folder_record(tmp_path, checksums=False)

    with raises(VerifiedCopyError, match="has no checksum record"):
        check_move_source(record)


def test_a_missing_record_is_made_by_the_source_verify_when_allowed(tmp_path: Path) -> None:
    """With *Create missing checksum on verify* on, a missing record is the source verify's to make.

    **Test steps:**

    * make a folder record with no checksum record
    * check the source check passes and says the verify has entries to add
    """
    record = make_folder_record(tmp_path, checksums=False)

    assert check_move_source(record, create_if_missing=True) is True


def test_a_record_missing_a_file_is_refused_naming_it(tmp_path: Path) -> None:
    """A content file the record does not cover could not be checked at the target.

    **Test steps:**

    * make a folder record with its checksums, then add a content file
    * check the source check raises, naming the file
    """
    record = make_folder_record(tmp_path)
    (record.parent / "late.zip").write_bytes(CONTENT)

    with raises(VerifiedCopyError, match=r"does not cover late\.zip"):
        check_move_source(record)


def test_a_record_missing_a_file_is_completed_when_allowed(tmp_path: Path) -> None:
    """With creating allowed, the uncovered file is the source verify's to add.

    **Test steps:**

    * make a folder record with its checksums, then add a content file
    * check the source check passes, saying the verify has entries to add
    """
    record = make_folder_record(tmp_path)
    (record.parent / "late.zip").write_bytes(CONTENT)

    assert check_move_source(record, create_if_missing=True) is True


def test_a_record_covering_everything_needs_no_verify_to_complete_it(tmp_path: Path) -> None:
    """A complete record passes, with nothing for a verify to add.

    **Test steps:**

    * make a folder record with its checksums
    * check the source check answers ``False``
    """
    assert check_move_source(make_folder_record(tmp_path)) is False


def test_a_long_list_of_names_is_cut_short() -> None:
    """A sentence names three files and counts the rest.

    **Test steps:**

    * list five names, then two
    * check the first reads three names and "(and 2 more)", the second both names
    """
    assert name_list(["a", "b", "c", "d", "e"]) == "a, b, c (and 2 more)"
    assert name_list(["a", "b"]) == "a, b"


# endregion


# region copying
def test_a_folder_record_is_copied_whole_with_its_record_last(tmp_path: Path) -> None:
    """Every file and folder of a folder record lands under the new name, the ``.rehu`` written last, and the copy
    counts its bytes.

    **Test steps:**

    * copy a folder record into a destination folder that does not exist yet
    * check the tree matches the source's, the ``.rehu`` is the journal's last file, the folders made are journalled
      topmost first -- each spelled from the folder the record lands in -- the last progress report is the whole, and
      the checkpoint was called
    """
    record = make_folder_record(tmp_path / "a")
    into = tmp_path / "b" / "Smith"
    copy = copier(record, into)
    journal = CopyJournal()
    reports: list[tuple[int, int | None]] = []
    checkpoints: list[None] = []

    copy.copy(
        journal, progress=lambda done, total: reports.append((done, total)), checkpoint=lambda: checkpoints.append(None)
    )

    target = into / NEW_NAME
    assert tree(target) == tree(record.parent)
    assert copy.target == target / "info.rehu"
    assert journal.written[-1] == f"{NEW_NAME}/info.rehu"
    assert journal.made[:3] == ["..", ".", NEW_NAME]
    assert reports[-1][0] == reports[-1][1]
    assert checkpoints
    assert (target / "content.zip").stat().st_mtime_ns == (record.parent / "content.zip").stat().st_mtime_ns


def test_a_file_record_copies_its_set_and_leaves_others(tmp_path: Path) -> None:
    """A file record carries every file named after it, renamed; a file merely starting alike stays behind.

    **Test steps:**

    * copy ``foo.rehu`` into another folder as ``bar``
    * check the destination holds exactly ``bar.checksum``, ``bar.rehu``, ``bar.zip``, ``bar00.jpg``, and the copy's
      record is ``bar.rehu``
    """
    record = make_file_record(tmp_path / "a")
    into = tmp_path / "b"
    copy = copier(record, into, "bar")

    copy.copy(CopyJournal())

    assert tree(into) == ["bar.checksum", "bar.rehu", "bar.zip", "bar00.jpg"]
    assert copy.target == into / "bar.rehu"


def test_an_entry_this_build_cannot_read_is_no_hash_to_skip_by(tmp_path: Path) -> None:
    """A malformed entry in the record gives no hash to compare a copy with, so nothing is skipped by it.

    **Test steps:**

    * make a folder record whose checksum record holds one entry with no usable hash
    * check the record's hashes leave that entry out
    """
    record = make_folder_record(tmp_path / "a", checksums=False)
    (record.parent / "info.checksum").write_text(json.dumps({"version": 1, "files": [{"name": "content.zip"}]}))

    assert not recorded_digests(record)


def test_a_resumed_copy_skips_what_matches_and_recopies_a_partial_file(tmp_path: Path, mocker: MockerFixture) -> None:
    """A copy run again writes only what is not already there whole: a content file matching the record is skipped,
    a truncated one copied again, and every file no checksum covers copied again -- the record's own ``.checksum``
    written afresh rather than copied.

    **Test steps:**

    * copy a folder record, then truncate the copy's ``content.zip``
    * copy again with ``copy_file`` spied on
    * check ``content.zip`` was recopied whole and ``part.bin`` was not copied at all
    """
    record = make_folder_record(tmp_path / "a")
    copy = copier(record, tmp_path / "b")
    journal = CopyJournal()
    copy.copy(journal)
    (copy.target.parent / "content.zip").write_bytes(CONTENT[:3])
    spy = mocker.spy(VerifiedCopy, "copy_file")

    copy.copy(journal)

    copied = {call.args[1].source.name for call in spy.call_args_list}
    assert copied == {"content.zip", "info00.jpg", "info.rehu"}
    assert (copy.target.parent / "content.zip").read_bytes() == CONTENT


def test_a_record_with_no_checksums_yet_is_copied_whole(tmp_path: Path) -> None:
    """With no record to compare against, nothing is taken as already there.

    **Test steps:**

    * copy a folder record that has no checksum record, twice
    * check the second copy left the content in place, whole
    """
    record = make_folder_record(tmp_path / "a", checksums=False)
    copy = copier(record, tmp_path / "b")
    journal = CopyJournal()
    copy.copy(journal)

    copy.copy(journal)

    assert (copy.target.parent / "content.zip").read_bytes() == CONTENT


def test_a_place_holding_something_else_is_refused(tmp_path: Path) -> None:
    """A copy never writes into a place something it did not write already occupies.

    **Test steps:**

    * make the destination folder of a folder record's copy, holding a file
    * check the copy raises ``FileExistsError`` and leaves that file alone
    """
    record = make_folder_record(tmp_path / "a")
    occupied = tmp_path / "b" / NEW_NAME
    occupied.mkdir(parents=True)
    (occupied / "theirs.txt").write_text("theirs")

    with raises(FileExistsError):
        copier(record, tmp_path / "b").copy(CopyJournal())

    assert tree(occupied) == ["theirs.txt"]


def test_a_folder_that_will_not_list_fails_the_copy(tmp_path: Path, mocker: MockerFixture) -> None:
    """A copy missing a branch is no copy: a folder of the record that will not list fails it.

    **Test steps:**

    * make every directory listing refuse
    * check listing what the record carries raises the refusal
    """
    record = make_folder_record(tmp_path / "a")
    mocker.patch("os.scandir", side_effect=PermissionError(DENIED, "Access is denied"))

    with raises(PermissionError):
        copier(record, tmp_path / "b").carried()


# endregion


# region checking the copy
def test_a_whole_copy_verifies_and_is_trusted_where_it_is(tmp_path: Path, mocker: MockerFixture) -> None:
    """The copy's check passes when every entry matched, and registers the copy as verified on this machine.

    **Test steps:**

    * copy a folder record, then check the copy with a trust stand-in
    * check every entry matched and the copy's ``.rehu`` was registered
    """
    record = make_folder_record(tmp_path / "a")
    copy = copier(record, tmp_path / "b")
    copy.copy(CopyJournal())
    trust = mocker.MagicMock()
    trust.trusted_since.return_value = None

    report = copy.verify_target(trust=trust, algorithm="xxh3")

    assert set(report.statuses.values()) == {"matched"}
    trust.register.assert_called_once()
    assert trust.register.call_args.args[0] == copy.target


def test_a_corrupted_copy_fails_its_check(tmp_path: Path) -> None:
    """A byte flipped in the copy is caught by the check, which names the file; the original is untouched.

    **Test steps:**

    * copy a folder record, then change a byte of the copy's ``content.zip``
    * check the copy's check raises, naming ``content.zip``, and the original is as it was
    """
    record = make_folder_record(tmp_path / "a")
    copy = copier(record, tmp_path / "b")
    copy.copy(CopyJournal())
    (copy.target.parent / "content.zip").write_bytes(b"X" + CONTENT[1:])

    with raises(VerifiedCopyError, match=r"content\.zip"):
        copy.verify_target(trust=None, algorithm="xxh3")

    assert (record.parent / "content.zip").read_bytes() == CONTENT


def test_a_copy_holding_a_file_the_record_does_not_list_fails_its_check(tmp_path: Path) -> None:
    """A check of a copy adopts nothing: a file the record does not list is a failure there.

    **Test steps:**

    * copy a folder record, then add a content file to the copy
    * check the copy's check raises, naming it
    """
    record = make_folder_record(tmp_path / "a")
    copy = copier(record, tmp_path / "b")
    copy.copy(CopyJournal())
    (copy.target.parent / "extra.zip").write_bytes(CONTENT)

    with raises(VerifiedCopyError, match=r"extra\.zip"):
        copy.verify_target(trust=None, algorithm="xxh3")


# endregion


def test_a_record_renamed_while_it_is_copied_is_followed(tmp_path: Path, mocker: MockerFixture) -> None:
    """A rename of the record that lands between two of its files moves the copy's reads with it: the copy finishes,
    under the name it was asked for.

    **Test steps:**

    * copy a folder record through a coordinator, renaming the record through it before the second file is copied
    * check every file of the renamed record is in the copy, and the copy follows the record to its new name
    """
    record = make_folder_record(tmp_path / "a")
    coordinator = RenameCoordinator()
    copy = VerifiedCopy(record, tmp_path / "b", NEW_NAME, coordinator=coordinator)
    real = VerifiedCopy.copy_file
    calls: list[str] = []

    def renaming(self: VerifiedCopy, *args: Any, **kwargs: Any) -> None:
        calls.append(args[0].target.name)
        if len(calls) == 2:
            coordinator.rename(record, "Renamed")
        real(self, *args, **kwargs)

    mocker.patch.object(VerifiedCopy, "copy_file", autospec=True, side_effect=renaming)

    copy.copy(CopyJournal())

    renamed = record.parent.with_name("Renamed")
    assert copy.source == renamed / "info.rehu"
    assert tree(tmp_path / "b" / NEW_NAME) == tree(renamed)


def test_a_record_holding_a_linked_folder_is_not_copied(tmp_path: Path) -> None:
    """A folder linked into a record -- a junction, a symlink -- refuses the copy before anything is written: a copy
    neither follows a link nor carries one.

    **Test steps:**

    * link a folder outside the record into it, holding a file, then copy the record
    * check the copy raises naming the link, nothing was written, and the file outside is still there
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "theirs.bin").write_bytes(CONTENT)
    record = make_folder_record(tmp_path / "a")
    link = directory_link(record.parent / "linked", outside)
    journal = CopyJournal()

    with raises(LinkInRecordError, match="linked"):
        copier(record, tmp_path / "b").copy(journal)

    assert str(link) in str(LinkInRecordError(str(link)))
    assert not (tmp_path / "b").exists() and not journal.written
    assert (outside / "theirs.bin").read_bytes() == CONTENT


def test_a_file_record_with_a_linked_file_is_not_copied(tmp_path: Path, mocker: MockerFixture) -> None:
    """One of a file record's files being a symbolic link refuses the copy the same way.

    **Test steps:**

    * make ``foo.zip`` read as a symbolic link, and copy ``foo.rehu``
    * check the copy raises naming it, with nothing written
    """
    record = make_file_record(tmp_path / "a")
    mocker.patch.object(Path, "is_symlink", autospec=True, side_effect=lambda path: path.name == "foo.zip")

    with raises(LinkInRecordError, match=r"foo\.zip"):
        copier(record, tmp_path / "b", "bar").copy(CopyJournal())

    assert not (tmp_path / "b").exists()


# endregion


# region removing the original
def copied_and_checked(tmp_path: Path) -> tuple[Path, VerifiedCopy, CopyJournal, list[str]]:
    """A folder record copied to ``tmp_path/b`` and its copy checked.

    :param tmp_path: pytest's folder.
    :returns: the source record, the copy, its journal and the names the check matched.
    """
    record = make_folder_record(tmp_path / "a")
    copy = copier(record, tmp_path / "b")
    journal = CopyJournal()
    copy.copy(journal)
    report = copy.verify_target(trust=None, algorithm="xxh3")
    return record, copy, journal, list(report.statuses)


def remove_original(copy: VerifiedCopy, journal: CopyJournal, verified: list[str]) -> tuple[Relocation, list[str]]:
    """Run the move's last step whole: bring the copy level, detach the original, remove what is left of it.

    :param copy: the copy.
    :param journal: its journal.
    :param verified: the names its check matched.
    :returns: what moved, and what could not be removed.
    """
    listing = copy.reconcile(journal, verified)
    relocation = copy.detach_source(listing)
    return relocation, remove_leftovers(listing.files, listing.folders)


def test_the_original_goes_once_its_copy_verified(tmp_path: Path) -> None:
    """Removing the source takes every file and folder, and answers the folder's move for everyone holding a path;
    removing what is already gone is no failure.

    **Test steps:**

    * copy and check a folder record, then remove the source, keeping its listing
    * check the source folder is gone, nothing was left, and the relocation moves the folder to the copy
    * remove the same listing again, and check nothing is reported
    """
    record, copy, journal, verified = copied_and_checked(tmp_path)
    listing = copy.reconcile(journal, verified)

    relocation = copy.detach_source(listing)

    assert not record.exists() and (record.parent / "content.zip").exists()
    assert not remove_leftovers(listing.files, listing.folders)
    assert not record.parent.exists()
    assert relocation.relocate(record) == copy.target
    assert not remove_leftovers(listing.files, listing.folders)


def test_a_screenshot_changed_meanwhile_is_copied_again_before_the_original_goes(tmp_path: Path) -> None:
    """A file no checksum covers may change while the copy waits; it is copied again and compared before the source
    is removed.

    **Test steps:**

    * copy and check a folder record, then change its screenshot and add another
    * remove the source
    * check the copy holds both screenshots as the source last had them
    """
    record, copy, journal, verified = copied_and_checked(tmp_path)
    (record.parent / "info00.jpg").write_bytes(b"retaken")
    (record.parent / "info01.jpg").write_bytes(b"added")

    remove_original(copy, journal, verified)

    assert (copy.target.parent / "info00.jpg").read_bytes() == b"retaken"
    assert (copy.target.parent / "info01.jpg").read_bytes() == b"added"


def test_a_folder_added_meanwhile_is_made_at_the_copy(tmp_path: Path) -> None:
    """A folder that appeared in the source while the copy waited is made at the copy too.

    **Test steps:**

    * copy and check a folder record, then add an empty folder to the source
    * remove the source
    * check the folder is at the copy
    """
    record, copy, journal, verified = copied_and_checked(tmp_path)
    (record.parent / "late").mkdir()

    remove_original(copy, journal, verified)

    assert (copy.target.parent / "late").is_dir()


def test_content_added_meanwhile_keeps_the_original(tmp_path: Path) -> None:
    """A content file the check never saw stops the move with nothing removed.

    **Test steps:**

    * copy and check a folder record, then add a content file to the source
    * check bringing the copy level raises, naming the file, and the source is whole
    """
    record, copy, journal, verified = copied_and_checked(tmp_path)
    (record.parent / "late.zip").write_bytes(CONTENT)
    before = tree(record.parent)

    with raises(VerifiedCopyError, match=r"late\.zip appeared"):
        copy.reconcile(journal, verified)

    assert tree(record.parent) == before


def test_a_file_that_will_not_copy_the_same_keeps_the_original(tmp_path: Path, mocker: MockerFixture) -> None:
    """A file that still differs from its copy after being copied again stops the move with nothing removed.

    **Test steps:**

    * copy and check a folder record, then make every comparison say the files differ
    * check bringing the copy level raises and the source's record is still there
    """
    record, copy, journal, verified = copied_and_checked(tmp_path)
    mocker.patch.object(filecmp, "cmp", return_value=False)

    with raises(VerifiedCopyError, match="changed while being moved"):
        copy.reconcile(journal, verified)

    assert record.exists()


def test_an_original_changed_since_it_was_compared_is_not_detached(tmp_path: Path) -> None:
    """Between the comparing and the detaching a file may change, come or go: the original is then left whole, to
    be compared again.

    **Test steps:**

    * copy and check a folder record and bring the copy level, then change a screenshot's size
    * check detaching raises and the record is still there
    * bring the copy level again, add a file, and check detaching raises again
    """
    record, copy, journal, verified = copied_and_checked(tmp_path)
    listing = copy.reconcile(journal, verified)
    (record.parent / "info00.jpg").write_bytes(b"retaken, and longer")

    with raises(SourceChangedError):
        copy.detach_source(listing)
    assert record.exists()

    listing = copy.reconcile(journal, verified)
    (record.parent / "info01.jpg").write_bytes(b"added")
    with raises(SourceChangedError):
        copy.detach_source(listing)
    assert record.exists()


def test_a_checksum_record_that_will_not_go_yet_is_left_for_the_cleanup(
    tmp_path: Path, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """Once the ``.rehu`` is gone the original is no record; its ``.checksum`` refusing to go is logged, and is the
    cleanup's to report.

    **Test steps:**

    * copy and check a folder record, make removing ``info.checksum`` refuse, and detach the original
    * check the ``.rehu`` is gone, the refusal was logged, and the cleanup reports the ``.checksum``
    """
    record, copy, journal, verified = copied_and_checked(tmp_path)
    listing = copy.reconcile(journal, verified)
    mocker.patch.object(Path, "unlink", autospec=True, side_effect=failing_for("info.checksum", Path.unlink))

    with caplog.at_level(logging.WARNING):
        copy.detach_source(listing)
    left = remove_leftovers(listing.files, listing.folders)

    assert not record.exists()
    assert "Could not remove the checksum record" in caplog.text
    assert [line.split(" (")[0] for line in left] == [str(record.with_suffix(".checksum")), str(record.parent)]


def test_what_will_not_go_is_reported_and_the_rest_removed(tmp_path: Path, mocker: MockerFixture) -> None:
    """A source file that will not be removed is named, and the rest still go.

    **Test steps:**

    * copy and check a folder record, then make removing ``part.bin`` refuse
    * remove the source
    * check ``part.bin`` and the folders above it are reported, the ``.rehu`` is gone, ``part.bin`` is still there
    """
    record, copy, journal, verified = copied_and_checked(tmp_path)
    mocker.patch.object(Path, "unlink", autospec=True, side_effect=failing_for("part.bin", Path.unlink))

    _, left = remove_original(copy, journal, verified)

    assert [line.split(" (")[0] for line in left] == [
        str(record.parent / "sub" / "part.bin"),
        str(record.parent / "sub"),
        str(record.parent),
    ]
    assert not record.exists()
    assert (record.parent / "sub" / "part.bin").exists()


def test_a_lock_left_beside_the_record_keeps_its_folder(tmp_path: Path) -> None:
    """A stale lock is nobody's file to carry, so it stays, and its folder with it -- reported.

    **Test steps:**

    * copy and check a folder record, then leave a lock file beside its ``.rehu``
    * remove the source
    * check the folder is the one thing reported, holding only the lock
    """
    record, copy, journal, verified = copied_and_checked(tmp_path)
    lock_path_for(record).write_text("")

    _, left = remove_original(copy, journal, verified)

    assert [line.split(" (")[0] for line in left] == [str(record.parent)]
    assert tree(record.parent) == [lock_path_for(record).name]


def test_a_file_record_is_removed_file_by_file(tmp_path: Path) -> None:
    """A file record's original is its set of files, each removed; its folder and its neighbours stay.

    **Test steps:**

    * copy and check ``foo.rehu`` as ``bar``, then remove the source
    * check only ``foobar.zip`` is left in the source folder
    """
    record = make_file_record(tmp_path / "a")
    copy = copier(record, tmp_path / "b", "bar")
    journal = CopyJournal()
    copy.copy(journal)
    report = copy.verify_target(trust=None, algorithm="xxh3")

    _, left = remove_original(copy, journal, list(report.statuses))

    assert not left
    assert tree(tmp_path / "a") == ["foobar.zip"]


# endregion


# region undoing a copy
def test_a_cancelled_copy_takes_back_what_it_wrote(tmp_path: Path) -> None:
    """Cancelling removes the files the copy wrote and the folders it made, and nothing that was there before.

    **Test steps:**

    * make the destination's parent with a file of its own, then copy a folder record under it
    * take the copy back
    * check only the parent and its own file remain, and the source is whole
    """
    record = make_folder_record(tmp_path / "a")
    parent = tmp_path / "b"
    parent.mkdir()
    (parent / "theirs.txt").write_text("theirs")
    copy = copier(record, parent / "Smith")
    journal = CopyJournal()
    copy.copy(journal)

    assert not copy.remove_copy(journal)

    assert tree(parent) == ["theirs.txt"]
    assert (record.parent / "content.zip").read_bytes() == CONTENT


def test_a_copy_is_taken_back_where_its_folder_is_mapped_now(tmp_path: Path) -> None:
    """The journal spells what was written from the folder the record lands in, so a copy made under one mapping of
    that folder is taken back under another.

    **Test steps:**

    * copy a folder record into ``b/Smith``, then move ``b`` to ``c``, as a root mapped elsewhere reads
    * take the copy back through a copy built over ``c/Smith``
    * check ``c`` holds nothing of it
    """
    record = make_folder_record(tmp_path / "a")
    (tmp_path / "b").mkdir()
    journal = CopyJournal()
    copier(record, tmp_path / "b" / "Smith").copy(journal)
    (tmp_path / "b").rename(tmp_path / "c")

    assert not copier(record, tmp_path / "c" / "Smith").remove_copy(journal)

    assert tree(tmp_path / "c") == []


def test_an_undo_reports_what_will_not_go(tmp_path: Path, mocker: MockerFixture) -> None:
    """A file that will not be removed, and the folders it keeps, are reported; a folder already gone is no failure.

    **Test steps:**

    * copy a folder record, journal a made folder that is already gone, make removing ``part.bin`` refuse
    * take the copy back
    * check ``part.bin`` and the two folders above it are what is reported
    """
    record = make_folder_record(tmp_path / "a")
    copy = copier(record, tmp_path / "b")
    journal = CopyJournal()
    copy.copy(journal)
    journal.made.append("../gone")
    mocker.patch.object(Path, "unlink", autospec=True, side_effect=failing_for("part.bin", Path.unlink))

    left = copy.remove_copy(journal)

    target = copy.target.parent
    assert [line.split(" (")[0] for line in left] == [
        str(target / "sub" / "part.bin"),
        str(target / "sub"),
        str(target),
        str(tmp_path / "b"),
    ]


# endregion


# region the journal
def test_a_journal_round_trips_through_its_state() -> None:
    """What a journal writes is what it reads back; a file noted twice is kept once.

    **Test steps:**

    * note one file twice and a made folder, write the journal down, read it back
    * check the copy equals the original and lists the file once
    """
    journal = CopyJournal()
    journal.wrote("t/a")
    journal.wrote("t/a")
    journal.made.append("t")

    restored = CopyJournal.from_state(journal.to_state())

    assert restored == journal
    assert restored.written == ["t/a"]


def test_a_journal_reads_anything_but_its_shape_as_empty_or_refuses_it() -> None:
    """A missing journal is an empty one; a malformed one is refused.

    **Test steps:**

    * read ``None``, then two lists of the wrong shape
    * check the first is empty and the others raise ``ValueError``
    """
    assert CopyJournal.from_state(None) == CopyJournal()
    with raises(ValueError, match="not two lists"):
        CopyJournal.from_state({"written": "x", "made": []})
    with raises(ValueError, match="not a path"):
        CopyJournal.from_state({"written": [1], "made": []})


# endregion
