"""Tests for joining a split folder's buckets back into it, from the disk alone (#681).

The joiner moves through a real :class:`~rehuco_core.RecordBucketMover`, as :mod:`test_prefix_buckets`' splitter does,
whose helpers are imported by name.
"""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Final
from unittest.mock import Mock

from pytest import fixture, mark, param, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    BUCKETS_MARKER,
    DEFAULT_DELETER,
    EXCLUDED_FILE_PATTERNS,
    TEMPORARY_BUCKET_PREFIX,
    BucketJoiner,
    BucketJunk,
    BucketSplitter,
    Deleter,
    JoinResult,
    NoTrashBinError,
    RecordBucketMover,
    RecordLockedError,
    RecordMoveHosting,
    RenameCoordinator,
    bucket_of,
    is_split,
)
from rehuco_core import bucket_joiner as bucket_joiner_module

from rehuco_core_tests.test_prefix_buckets import LIMIT, TOKEN, file_record, folder_record, mark_split, names_under

JOIN_LIMIT: Final = 10
"""A join limit the trees below are within."""

JOINED: Final = {
    "a/info.rehu",
    "ab/info.rehu",
    "abc.rehu",
    "abc00.jpg",
    "abd/info.rehu",
    "b/info.rehu",
    "bcd.rehu",
    "bcd00.jpg",
}
"""What :func:`split_tree` holds once joined: every entry in the layout's folder, its sidecars with it."""

ENTRIES: Final = ("a", "ab", "abc", "abd", "b", "bcd")
"""The names of the entries of :func:`split_tree`."""


def make_mover() -> RecordBucketMover:
    """A mover through the barrier, its steps running where they are asked.

    :returns: the mover.
    """
    return RecordBucketMover(RenameCoordinator(), RecordMoveHosting(), lambda: None)


def make_joiner(
    limit: int = JOIN_LIMIT, deleter: Deleter | None = None, checkpoint: Callable[[], None] = lambda: None
) -> BucketJoiner:
    """A joiner with the shipped junk patterns.

    :param limit: the join limit.
    :param deleter: how junk is deleted; the plain unlink when ``None``.
    :param checkpoint: its checkpoint.
    :returns: the joiner.
    """
    junk = BucketJunk(EXCLUDED_FILE_PATTERNS, deleter if deleter is not None else DEFAULT_DELETER)
    return BucketJoiner(limit, make_mover(), junk=junk, checkpoint=checkpoint)


def split_tree(folder: Path) -> Path:
    """A layout folder split two levels deep, holding every shape an entry has: file and folder records, at depths 1
    and 2, and folders named as long as the bucket they are in (``a/a``, ``b/b``, ``a/ab/ab``).

    :param folder: the layout's folder.
    :returns: it.
    """
    mark_split(folder)
    mark_split(folder / "a")
    folder_record(folder / "a", "a")
    file_record(folder / "a" / "ab", "abc")
    folder_record(folder / "a" / "ab", "abd")
    folder_record(folder / "a" / "ab", "ab")
    folder_record(folder / "b", "b")
    file_record(folder / "b", "bcd")
    return folder


def entry_places(folder: Path) -> dict[str, Path]:
    """Where each entry of a tree is, checked to be in one place and whole.

    :param folder: the layout's folder.
    :returns: the folder each entry is in, by its name.
    """
    places: dict[str, Path] = {}
    for record in folder.rglob("*.rehu"):
        is_folder = record.name == "info.rehu"
        name, place = (record.parent.name, record.parent.parent) if is_folder else (record.stem, record.parent)
        assert name not in places
        assert is_folder or (place / f"{name}00.jpg").is_file()
        places[name] = place
    return places


def stopping_at(call: int) -> Callable[[], None]:
    """A checkpoint that stops at one of its calls.

    :param call: which one, the first being 0.
    :returns: the checkpoint.
    """
    calls = iter(range(10_000))

    def checkpoint() -> None:
        """Stop at the chosen call."""
        if next(calls) == call:
            raise InterruptedError

    return checkpoint


def steps_of_a_join(folder: Path) -> int:
    """How many places a join of :func:`split_tree` can be stopped at.

    :param folder: a folder to join a tree in.
    :returns: the count of its checkpoints.
    """
    counted = Mock()
    make_joiner(checkpoint=counted).join(split_tree(folder), 0)
    return counted.call_count


STOPS: Final = 32
"""More places than a join of :func:`split_tree` can be stopped at, so every one is tried."""


@fixture(name="layout")
def fixture_layout(tmp_path: Path) -> Path:
    """A split layout folder (:func:`split_tree`).

    :param tmp_path: pytest fixture.
    :returns: the folder.
    """
    return split_tree(tmp_path / "fab")


# region Joining


def test_a_folder_within_the_limit_is_joined_whole(layout: Path) -> None:
    """Every entry beneath moves up into the folder with its sidecars; its buckets, their markers and its own go.

    **Test steps:**

    * join a folder split two levels deep, its subtree within the limit
    * verify every entry is in the folder, and nothing else is
    """
    joiner = make_joiner()

    assert joiner.join(layout, 0) is JoinResult.JOINED

    assert names_under(layout) == JOINED
    assert not list(layout.rglob(f"{BUCKETS_MARKER}*"))
    assert not joiner.left


def test_a_bucket_within_the_limit_is_joined_at_its_own_depth(layout: Path) -> None:
    """A bucket is joined as a layout's folder is, a folder named as long as *its* buckets set aside.

    **Test steps:**

    * join the bucket ``a`` alone, at depth 1
    * verify its entries are in it, ``ab`` among them, and the folder above still split
    """
    assert make_joiner().join(layout / "a", 1) is JoinResult.JOINED

    assert names_under(layout / "a") == {"a/info.rehu", "ab/info.rehu", "abc.rehu", "abc00.jpg", "abd/info.rehu"}
    assert is_split(layout)


def test_a_folder_over_the_limit_is_left_as_it_is(layout: Path) -> None:
    """One entry over the limit keeps the folder split, the folder's own entries counted with its buckets'.

    **Test steps:**

    * join a folder holding six entries with a limit of five, then with a limit of six
    * verify nothing moved, then joined
    """
    before = names_under(layout)

    assert make_joiner(len(ENTRIES) - 1).join(layout, 0) is JoinResult.NONE
    assert names_under(layout) == before

    assert make_joiner(len(ENTRIES)).join(layout, 0) is JoinResult.JOINED


def test_the_folders_own_entries_count(tmp_path: Path) -> None:
    """An entry too short to descend, beside the buckets, is one of the subtree's.

    **Test steps:**

    * split a bucket holding its own ``a`` beside bucket ``ab`` with one record
    * join it with a limit of one
    * verify it is left
    """
    mark_split(tmp_path)
    folder_record(tmp_path, "a")
    file_record(tmp_path / "ab", "abc")

    assert make_joiner(1).join(tmp_path, 1) is JoinResult.NONE


def test_a_folder_never_split_has_nothing_to_join(tmp_path: Path) -> None:
    """A plain folder has no buckets: its one-character folders are entries.

    **Test steps:**

    * join a plain folder holding a folder ``a`` with a record in it
    * verify nothing moved
    """
    file_record(tmp_path / "a", "abc")

    assert make_joiner().join(tmp_path, 0) is JoinResult.NONE

    assert names_under(tmp_path) == {"a/abc.rehu", "a/abc00.jpg"}


def test_an_empty_split_folder_becomes_plain(tmp_path: Path) -> None:
    """A folder whose records all left loses its empty buckets and its marker.

    **Test steps:**

    * split a folder into an empty bucket holding an empty split bucket
    * join it with a limit of nothing
    * verify it is empty
    """
    mark_split(tmp_path)
    mark_split(tmp_path / "a")
    (tmp_path / "a" / "ab").mkdir()

    assert make_joiner(0).join(tmp_path, 0) is JoinResult.JOINED

    assert not list(tmp_path.iterdir())


def test_a_split_stopped_before_its_marker_is_joined_within_the_limit(tmp_path: Path) -> None:
    """An unmarked folder holding a temporary bucket takes back what is in it.

    **Test steps:**

    * leave an unmarked folder holding a temporary bucket with folder ``a`` in it, beside file record ``ab``
    * join it
    * verify both entries in the folder and no temporary bucket
    """
    folder_record(tmp_path / f"{TEMPORARY_BUCKET_PREFIX}a-{TOKEN}", "a")
    file_record(tmp_path, "ab")

    assert make_joiner().join(tmp_path, 0) is JoinResult.JOINED

    assert names_under(tmp_path) == {"a/info.rehu", "ab.rehu", "ab00.jpg"}


def test_a_temporary_bucket_beneath_is_emptied_too(tmp_path: Path) -> None:
    """A bucket whose own split was stopped hands over what its temporary buckets hold.

    **Test steps:**

    * split a folder whose bucket ``a`` holds a temporary bucket with folder ``ab`` in it
    * join it
    * verify ``ab`` in the folder and nothing else
    """
    mark_split(tmp_path)
    folder_record(tmp_path / "a" / f"{TEMPORARY_BUCKET_PREFIX}ab-{TOKEN}", "ab")

    assert make_joiner().join(tmp_path, 0) is JoinResult.JOINED

    assert names_under(tmp_path) == {"ab/info.rehu"}


def test_a_folder_set_aside_reuses_the_temporary_bucket_there_is(tmp_path: Path) -> None:
    """A folder named like its bucket goes into the temporary bucket already there for that name, so a stop leaves one.

    **Test steps:**

    * split a folder holding a temporary bucket for ``a`` with ``abc`` in it, and bucket ``a`` with folder ``a`` in it
    * join it, stopped once the folder was set aside
    * verify one temporary bucket holds both
    """
    mark_split(tmp_path)
    temporary = tmp_path / f"{TEMPORARY_BUCKET_PREFIX}a-{TOKEN}"
    folder_record(temporary, "abc")
    folder_record(tmp_path / "a", "a")

    # two folders surveyed, then the move aside, then the removal it stops before
    with raises(InterruptedError):
        make_joiner(checkpoint=stopping_at(3)).join(tmp_path, 0)

    assert names_under(temporary) == {"a/info.rehu", "abc/info.rehu"}
    assert [path.name for path in tmp_path.glob(f"{TEMPORARY_BUCKET_PREFIX}*")] == [temporary.name]


# endregion

# region Stopping


def test_every_stop_is_tried(tmp_path: Path) -> None:
    """The stops below cover the whole join.

    **Test steps:**

    * count the checkpoints of a join of the tree
    * verify there are no more than are tried
    """
    assert steps_of_a_join(tmp_path / "fab") <= STOPS


@mark.parametrize("call", range(STOPS))
def test_a_join_stopped_anywhere_is_finished_by_the_next(layout: Path, call: int) -> None:
    """Wherever a join is stopped, every record is whole and in one place, and joining again finishes it.

    **Test steps:**

    * join a tree with a checkpoint that stops it at one of its calls
    * verify each entry is in exactly one place, with its sidecars
    * join again and verify the folder joined whole
    """
    try:
        make_joiner(checkpoint=stopping_at(call)).join(layout, 0)
    except InterruptedError:
        pass

    assert sorted(entry_places(layout)) == sorted(ENTRIES)
    make_joiner().join(layout, 0)
    assert names_under(layout) == JOINED
    assert {path.name for path in layout.iterdir() if path.is_dir()} == {"a", "ab", "abd", "b"}


@mark.parametrize("call", range(STOPS))
def test_a_join_stopped_anywhere_is_settled_by_a_split(layout: Path, call: int) -> None:
    """A record arriving after a stopped join settles the folder: every record then sits where its name lands, and
    nothing is lost or left in a temporary bucket.

    **Test steps:**

    * join a tree with a checkpoint that stops it at one of its calls
    * settle the folder as an arriving record does
    * verify each entry is in exactly one place, the one its name lands in
    """
    try:
        make_joiner(checkpoint=stopping_at(call)).join(layout, 0)
    except InterruptedError:
        pass

    BucketSplitter(LIMIT, make_mover()).settle(layout, ("a",))

    places = entry_places(layout)
    assert places == {name: layout.joinpath(*bucket_of(layout, name).parts) for name in ENTRIES}
    assert not list(layout.rglob(f"{TEMPORARY_BUCKET_PREFIX}*"))


# endregion

# region What keeps a folder split


def test_a_file_of_no_record_keeps_its_folder_split(layout: Path, mocker: MockerFixture) -> None:
    """A stray file in a bucket beneath is found before anything moves; the folder is left whole, the file named.

    **Test steps:**

    * put a note in a bucket two levels down
    * join the folder
    * verify nothing moved, the reason names the note, and it is logged
    """
    warning = mocker.spy(bucket_joiner_module.LOG, "warning")
    stray = layout / "a" / "ab" / "notes.txt"
    stray.write_text("x", encoding="utf-8")
    before = names_under(layout)
    joiner = make_joiner()

    assert joiner.join(layout, 0) is JoinResult.NONE

    assert names_under(layout) == before
    assert joiner.left == (f"{layout}: {stray} belongs to no record",)
    warning.assert_called_once()


@mark.parametrize(
    "stray",
    [
        param("b/.hidden/info.rehu", id="a-hidden-folder"),
        param("b/.old.rehu", id="a-hidden-record"),
        param("b/._cache/x", id="a-hidden-folder-named-like-junk"),
        param("b/gone.rehu.lock", id="a-lock-of-no-record"),
        param("b/bcdx.zip", id="a-file-that-only-starts-alike"),
    ],
)
def test_anything_no_entry_takes_along_is_a_stray(layout: Path, stray: str) -> None:
    """What a bucket listing leaves out, or no record's name covers, would stay behind in its bucket.

    **Test steps:**

    * put one such file or folder in a bucket
    * join the folder
    * verify it is left split, the stray named
    """
    path = layout / stray
    path.parent.mkdir(exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    joiner = make_joiner()

    assert joiner.join(layout, 0) is JoinResult.NONE

    assert joiner.left == (f"{layout}: {layout.joinpath(*Path(stray).parts[:2])} belongs to no record",)


def test_junk_is_deleted_and_the_folder_joined(layout: Path) -> None:
    """What an operating system leaves behind goes, in any case, and the folder is joined; beside the folder's own
    entries it is in nobody's way, and stays.

    **Test steps:**

    * put a ``.DS_Store``, a ``thumbs.DB`` in buckets beneath, and a ``.DS_Store`` in the folder itself
    * join it
    * verify it is joined, only its own ``.DS_Store`` left
    """
    for junk in (layout / "a" / ".DS_Store", layout / "a" / "ab" / "thumbs.DB", layout / ".DS_Store"):
        junk.write_bytes(b"x")

    assert make_joiner().join(layout, 0) is JoinResult.JOINED

    assert names_under(layout) == JOINED | {".DS_Store"}


def test_junk_goes_through_the_deleter_and_one_refused_keeps_the_folder_split(layout: Path) -> None:
    """A deletion refused -- no Recycle Bin for the share -- leaves the folder split before anything moved.

    **Test steps:**

    * put a ``.DS_Store`` in a bucket, with a deleter that refuses it
    * join the folder
    * verify nothing moved, and the reason names the file and why
    """
    junk = layout / "b" / ".DS_Store"
    junk.write_bytes(b"x")
    before = names_under(layout)
    deleter = Mock(spec=Deleter)
    deleter.delete.side_effect = NoTrashBinError("no bin here")
    joiner = make_joiner(deleter=deleter)

    assert joiner.join(layout, 0) is JoinResult.NONE

    deleter.delete.assert_called_once_with(junk)
    assert names_under(layout) == before
    assert joiner.left == (f"{layout}: {junk} could not be deleted (no bin here)",)


def test_junk_already_gone_is_no_refusal(layout: Path) -> None:
    """A junk file somebody else deleted meanwhile keeps nothing split.

    **Test steps:**

    * put a ``.DS_Store`` in a bucket, with a deleter that deletes it and says it was not there
    * join the folder
    * verify it is joined
    """
    (layout / "b" / ".DS_Store").write_bytes(b"x")

    def delete(path: Path) -> None:
        """Delete the file, then say it was gone."""
        path.unlink()
        raise FileNotFoundError(path)

    deleter = Mock(spec=Deleter)
    deleter.delete.side_effect = delete

    assert make_joiner(deleter=deleter).join(layout, 0) is JoinResult.JOINED


def test_a_bucket_its_owner_pinned_keeps_the_folders_above_it_split(layout: Path) -> None:
    """A bucket marked *never split* is its owner's choice: it is not emptied, and nothing is said about it.

    **Test steps:**

    * mark a bucket two levels down as never split, by a folder named like the marker
    * join the folder
    * verify nothing moved and no reason is given
    """
    (layout / "a" / "ab" / BUCKETS_MARKER).mkdir()
    before = names_under(layout)
    joiner = make_joiner()

    assert joiner.join(layout, 0) is JoinResult.NONE

    assert names_under(layout) == before
    assert not joiner.left


def test_a_file_arriving_while_it_is_joined_keeps_the_folder_split(layout: Path) -> None:
    """A bucket found holding something at its removal stays, and its folder stays marked.

    **Test steps:**

    * join a tree with a checkpoint that writes a file into a bucket once the first entry moved
    * verify the folder is left split, the file named, every entry whole
    """
    stray = layout / "a" / "ab" / "late.txt"

    def checkpoint() -> None:
        """Write the file once ``abc`` is up."""
        if (layout / "abc.rehu").is_file():
            stray.write_text("x", encoding="utf-8")

    joiner = make_joiner(checkpoint=checkpoint)

    assert joiner.join(layout, 0) is JoinResult.HALTED

    assert joiner.left == (f"{layout}: {stray} arrived while it was joined",)
    assert is_split(layout)
    assert sorted(entry_places(layout)) == sorted(ENTRIES)


def test_a_bucket_back_before_the_marker_goes_keeps_the_folder_split(layout: Path) -> None:
    """The marker is removed only with no bucket there, looked at again with nothing able to land in one meanwhile.

    **Test steps:**

    * join a tree, a record landing in a bucket just before the marker's removal
    * verify the folder is left split, the bucket named, and the removal entered exclusively
    """

    @contextmanager
    def landing() -> Generator[None]:
        """Let a record land, as a move that went first does."""
        file_record(layout / "z", "zed")
        yield

    exclusively = Mock(side_effect=landing)
    joiner = BucketJoiner(JOIN_LIMIT, make_mover(), exclusively=exclusively)

    assert joiner.join(layout, 0) is JoinResult.HALTED

    exclusively.assert_called_once_with()
    assert joiner.left == (f"{layout}: {layout / 'z'} arrived while it was joined",)
    assert is_split(layout)


def test_a_file_arriving_in_a_temporary_bucket_halts_the_join(layout: Path) -> None:
    """A temporary bucket found holding something at its removal stays, and the join is not told as done.

    **Test steps:**

    * join a tree with a checkpoint that writes a file into the temporary buckets once the marker is gone
    * verify the join halted, every entry whole
    """

    def checkpoint() -> None:
        """Write a file into each temporary bucket once the folder is unmarked."""
        if not is_split(layout):
            for temporary in layout.glob(f"{TEMPORARY_BUCKET_PREFIX}*"):
                (temporary / "late.txt").write_text("x", encoding="utf-8")

    assert make_joiner(checkpoint=checkpoint).join(layout, 0) is JoinResult.HALTED

    assert sorted(entry_places(layout)) == sorted(ENTRIES)


def test_junk_written_back_while_it_is_joined_is_deleted_again(layout: Path) -> None:
    """A file manager showing a bucket writes its junk back as files move; it keeps nothing split.

    **Test steps:**

    * join a tree with a checkpoint that writes a ``Thumbs.db`` into a bucket still there
    * verify it is joined whole
    """

    def checkpoint() -> None:
        """Write the junk back."""
        if (layout / "b").is_dir() and not (layout / "b" / "info.rehu").exists() and is_split(layout):
            (layout / "b" / "Thumbs.db").write_bytes(b"x")

    assert make_joiner(checkpoint=checkpoint).join(layout, 0) is JoinResult.JOINED

    assert names_under(layout) == JOINED


def test_junk_written_back_and_refused_halts_the_join(layout: Path) -> None:
    """Junk that came back and cannot be deleted leaves its bucket, and the folder split.

    **Test steps:**

    * join a tree with a checkpoint that writes junk back, and a deleter that refuses it
    * verify the join halted, the file named
    """
    junk = layout / "a" / "ab" / "Thumbs.db"
    deleter = Mock(spec=Deleter)
    deleter.delete.side_effect = NoTrashBinError("no bin here")

    def checkpoint() -> None:
        """Write the junk once ``abc`` is up."""
        if (layout / "abc.rehu").is_file():
            junk.write_bytes(b"x")

    joiner = make_joiner(deleter=deleter, checkpoint=checkpoint)

    assert joiner.join(layout, 0) is JoinResult.HALTED

    assert joiner.left == (f"{layout}: {junk} could not be deleted (no bin here)",)


def test_two_entries_of_one_name_keep_their_folder_split(layout: Path) -> None:
    """An entry beside the buckets with the name of one in them is found before anything moves.

    **Test steps:**

    * put a folder record ``ABD`` beside the buckets of a tree that holds ``abd`` in one
    * join the folder
    * verify nothing moved, and the reason names one of them
    """
    folder_record(layout, "ABD")
    before = names_under(layout)
    joiner = make_joiner()

    assert joiner.join(layout, 0) is JoinResult.NONE

    assert names_under(layout) == before
    assert joiner.left == (f"{layout}: {layout / 'a' / 'ab' / 'abd'} has the name of another entry",)


def test_a_stray_is_told_once_for_the_folders_it_keeps_split(layout: Path) -> None:
    """A folder and the bucket beneath it, both split for one file, name it once.

    **Test steps:**

    * put a note two levels down, and join the folder, then its bucket
    * verify one reason
    """
    (layout / "a" / "ab" / "notes.txt").write_text("x", encoding="utf-8")
    joiner = make_joiner()

    joiner.join(layout, 0)
    joiner.join(layout / "a", 1)

    assert len(joiner.left) == 1


def test_a_file_another_record_claims_is_a_stray(layout: Path) -> None:
    """What no record's move takes along is a stray, by the rename's own rule: a file another record's longer stem
    claims and its name does not cover travels with neither.

    **Test steps:**

    * put records ``bd`` and ``bd1`` in a bucket, and a ``bd1_extra.zip``
    * join the folder
    * verify it is left split, the file named, nothing moved
    """
    file_record(layout / "b", "bd")
    file_record(layout / "b", "bd1")
    stray = layout / "b" / "bd1_extra.zip"
    stray.write_bytes(b"x")
    before = names_under(layout)
    joiner = make_joiner()

    assert joiner.join(layout, 0) is JoinResult.NONE

    assert names_under(layout) == before
    assert joiner.left == (f"{layout}: {stray} belongs to no record",)


def test_legacy_records_move_with_their_own(layout: Path) -> None:
    """A ``.tc`` whose stem extends another's is an entry of its own, and one beside its ``.rehu`` is part of it.

    **Test steps:**

    * put ``bx.tc``, ``bx1.tc`` and ``by.rehu`` with ``by.tc`` in a bucket, and join the folder
    * verify each is up, once
    """
    for name in ("bx.tc", "bx1.tc", "by.rehu", "by.tc"):
        (layout / "b" / name).write_text("{}", encoding="utf-8")

    assert make_joiner().join(layout, 0) is JoinResult.JOINED

    assert names_under(layout) == JOINED | {"bx.tc", "bx1.tc", "by.rehu", "by.tc"}


def test_a_lock_beside_its_record_is_no_stray(layout: Path) -> None:
    """A write under way is waited for by the move of its record, not told as a stray file.

    **Test steps:**

    * put a lock nobody here holds beside a record in a bucket, and join the folder
    * verify the move's refusal leaves through the join
    """
    (layout / "b" / "bcd.rehu.lock").write_text("{}", encoding="utf-8")

    with raises(RecordLockedError):
        make_joiner().join(layout, 0)


# endregion
