"""Tests for prefix buckets: where an entry lands, and how a crowded folder splits from the disk alone (#680).

The splitter moves through a real :class:`~rehuco_core.RecordBucketMover`, over a fresh
:class:`~rehuco_core.RenameCoordinator` and the host stand-in that runs a step where it is asked, so what lands on
``tmp_path`` is what a move does: a record's sidecars travel with it and a folder moves whole.
"""

from pathlib import Path, PurePosixPath
from typing import Final

from pytest import fixture, mark, param, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    BUCKETS_MARKER,
    MAX_SPLIT_LIMIT,
    MIN_SPLIT_LIMIT,
    TEMPORARY_BUCKET_PREFIX,
    BucketChain,
    BucketedPlace,
    BucketEntry,
    BucketListing,
    BucketSplitter,
    RecordBucketMover,
    RecordMoveHosting,
    RenameCoordinator,
    bucket_key,
    bucket_of,
    bucket_prefix,
    clamped_limits,
    is_bucket_chain,
    is_never_split,
    is_split,
    max_join_limit,
    place_chains,
    place_holds,
    records_beneath,
    resolve_buckets,
    temporary_bucket_of,
    temporary_prefix,
    unresolve_buckets,
)
from rehuco_core import prefix_buckets as prefix_buckets_module

LIMIT: Final = MIN_SPLIT_LIMIT
"""The smallest limit a split takes, so a test crowds a folder with the fewest files."""

TOKEN: Final = "0a1b2c3d"
"""A temporary bucket's random part, as a stopped split left it."""


def file_record(folder: Path, name: str) -> Path:
    """Write a file record and one screenshot beside it.

    :param folder: where it goes, made when missing.
    :param name: its stem.
    :returns: its ``.rehu``.
    """
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}00.jpg").write_bytes(b"jpg")
    record = folder / f"{name}.rehu"
    record.write_text("{}", encoding="utf-8")
    return record


def folder_record(folder: Path, name: str) -> Path:
    """Write a folder record.

    :param folder: where its folder goes.
    :param name: its folder's name.
    :returns: its ``info.rehu``.
    """
    record = folder / name / "info.rehu"
    record.parent.mkdir(parents=True)
    record.write_text("{}", encoding="utf-8")
    return record


def mark_split(folder: Path) -> None:
    """Make a folder a split one.

    :param folder: the folder, made when missing.
    """
    folder.mkdir(parents=True, exist_ok=True)
    (folder / BUCKETS_MARKER).touch()


def names_under(folder: Path) -> set[str]:
    """Every file beneath a folder, relative to it.

    :param folder: the folder.
    :returns: the files' POSIX paths.
    """
    return {path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()}


@fixture(name="splitter")
def fixture_splitter() -> BucketSplitter:
    """A splitter at the smallest limit, moving through the barrier where it runs.

    :returns: the splitter.
    """
    return BucketSplitter(LIMIT, RecordBucketMover(RenameCoordinator(), RecordMoveHosting(), lambda: None))


# region The rules of a name


def test_the_limits_are_clamped_to_their_floor_and_half() -> None:
    """The split limit is never under 50, and the join limit never above half of it, nor under 0.

    **Test steps:**

    * clamp a split limit under the floor and one over the top, and join limits above half, below 0 and in range
    * verify each
    """
    assert clamped_limits(10, 100) == (MIN_SPLIT_LIMIT, MIN_SPLIT_LIMIT // 2)
    assert clamped_limits(200, 150) == (200, 100)
    assert clamped_limits(200, -5) == (200, 0)
    assert clamped_limits(300, 60) == (300, 60)
    assert clamped_limits(MAX_SPLIT_LIMIT + 1, MAX_SPLIT_LIMIT) == (MAX_SPLIT_LIMIT, max_join_limit(MAX_SPLIT_LIMIT))
    assert max_join_limit(201) == 100


@mark.parametrize(
    "name, depth, expected",
    [
        param("01ABC", 0, "0", id="the-first-character"),
        param("01ABC", 2, "01a", id="folded-at-depth"),
        param("01", 2, None, id="too-short-to-descend"),
        param("ab.cd", 2, None, id="a-prefix-ending-in-a-dot"),
        param("ab cd", 2, None, id="a-prefix-ending-in-a-space"),
        param("a?b", 1, None, id="a-prefix-a-sanitize-changes"),
        param(".abc", 0, None, id="a-prefix-starting-with-a-dot"),
    ],
)
def test_a_name_belongs_to_the_bucket_of_one_more_character(name: str, depth: int, expected: str | None) -> None:
    """A split folder at depth *n* puts a name in the bucket of its first *n+1* characters, folded, when a folder may
    be named so.

    **Test steps:**

    * ask for the bucket of each name at its depth
    * verify the prefix, or none
    """
    assert bucket_prefix(name, depth) == expected


def test_a_chain_is_the_names_prefixes_from_the_top() -> None:
    """Folders between a layout's folder and an entry are its buckets when each is one more of its characters.

    **Test steps:**

    * ask whether no folders, its prefixes in any case, a wrong prefix and a skipped level are a chain for a name
    * verify yes, yes, no, no
    """
    assert is_bucket_chain((), "01abc")
    assert is_bucket_chain(("0", "01", "01A"), "01abc")
    assert not is_bucket_chain(("1",), "01abc")
    assert not is_bucket_chain(("01",), "01abc")


@mark.parametrize(
    "levels, holds",
    [
        param(("fab", "01abc"), True, id="no-bucket-yet"),
        param(("FAB", "0", "01", "01ABC"), True, id="a-chain-in-another-case"),
        param(("fab", "1", "01abc"), False, id="a-wrong-bucket"),
        param(("fab", "0", "01abc", "x"), False, id="a-level-too-many"),
        param(("fab",), False, id="a-level-short"),
        param(("other", "01abc"), False, id="another-folder"),
    ],
)
def test_a_place_holds_a_path_under_any_chain_of_its_buckets(levels: tuple[str, ...], holds: bool) -> None:
    """A path is a bucketed place's when its levels match, each bucketed level after a valid chain, read off no disk.

    **Test steps:**

    * ask whether each path is ``fab/{buckets}/01abc``
    * verify the answer
    """
    assert place_holds(levels, PurePosixPath("fab", "01abc"), (1,)) is holds


def test_a_place_with_two_bucketed_levels_holds_each_under_its_own_chain() -> None:
    """Each bucketed level is matched under its own chain, the levels between them exactly.

    **Test steps:**

    * ask whether ``fab/j/Jane/i/Intro`` and ``fab/Jane/Intro`` are ``fab/{buckets}/Jane/{buckets}/Intro``, and
      whether ``fab/j/Jane/j/Intro`` is
    * verify yes, yes, no
    """
    relative = PurePosixPath("fab", "Jane", "Intro")

    assert place_holds(("fab", "j", "Jane", "i", "Intro"), relative, (1, 2))
    assert place_holds(("fab", "Jane", "Intro"), relative, (1, 2))
    assert not place_holds(("fab", "j", "Jane", "j", "Intro"), relative, (1, 2))


@mark.parametrize(
    "name, expected",
    [
        param(f"{TEMPORARY_BUCKET_PREFIX}ab-{TOKEN}", "ab", id="a-temporary-bucket"),
        param(f"{TEMPORARY_BUCKET_PREFIX}a-b-{TOKEN}", "a-b", id="a-prefix-with-a-dash"),
        param(f"{TEMPORARY_BUCKET_PREFIX}{TOKEN}", None, id="no-prefix"),
        param(f"{TEMPORARY_BUCKET_PREFIX}-{TOKEN}", None, id="an-empty-prefix"),
        param("ab", None, id="a-bucket"),
    ],
)
def test_a_temporary_buckets_name_says_its_prefix(name: str, expected: str | None) -> None:
    """A temporary bucket is named by the prefix it is built for, then a dash and a token.

    **Test steps:**

    * read the prefix of each name
    * verify it, or none
    """
    assert temporary_prefix(name) == expected


def test_a_folder_is_split_by_a_marker_file_and_never_by_a_marker_folder(tmp_path: Path) -> None:
    """The marker file splits its folder; a folder of that name keeps its folder plain.

    **Test steps:**

    * ask about a plain folder, one with the marker file, and one with a folder named like it
    * verify which is split and which is never split
    """
    plain, split, kept = tmp_path / "plain", tmp_path / "split", tmp_path / "kept"
    plain.mkdir()
    mark_split(split)
    (kept / BUCKETS_MARKER).mkdir(parents=True)

    assert (is_split(plain), is_never_split(plain)) == (False, False)
    assert (is_split(split), is_never_split(split)) == (True, False)
    assert (is_split(kept), is_never_split(kept)) == (False, True)


def test_a_chain_round_trips_through_its_state() -> None:
    """A chain is kept as JSON primitives and read back as it was; anything else is refused.

    **Test steps:**

    * write a chain down and read it back
    * read back a state that is no object, and one whose buckets are not names
    * verify the same chain, then two refusals
    """
    chain = BucketChain(PurePosixPath("fab", "x"), ("0", "01"))

    assert BucketChain.from_state(chain.to_state()) == chain
    with raises(ValueError, match="not a folder"):
        BucketChain.from_state(["fab"])
    with raises(ValueError, match="not a folder"):
        BucketChain.from_state({"folder": "fab", "buckets": [1]})


# endregion

# region What a folder holds, and where an entry lands


def test_a_listing_tells_entries_from_buckets_and_leaves_out_the_rest(tmp_path: Path) -> None:
    """A split folder's buckets are its folders of one more character; a temporary bucket is one by its name; hidden
    names, sidecars and a folder record's own file are no entries.

    **Test steps:**

    * fill a split folder at depth 1 with a bucket, a temporary bucket, an entry folder, a file record and its
      screenshot, a hidden folder, a hidden record, an ``info.rehu`` and a stray file
    * verify the entries, the bucket and the temporary bucket
    """
    folder = tmp_path / "a"
    mark_split(folder)
    (folder / "ab").mkdir()
    (folder / f"{TEMPORARY_BUCKET_PREFIX}ac-{TOKEN}").mkdir()
    (folder / "abc").mkdir()
    file_record(folder, "abd")
    (folder / ".git").mkdir()
    (folder / ".old.rehu").write_text("{}", encoding="utf-8")
    (folder / "info.rehu").write_text("{}", encoding="utf-8")
    (folder / "notes.txt").write_text("x", encoding="utf-8")

    listing = BucketListing.of(folder, 1)

    assert listing.entries == [
        BucketEntry("abc", folder / "abc", is_folder=True),
        BucketEntry("abd", folder / "abd.rehu", is_folder=False),
    ]
    assert listing.buckets == {"ab": folder / "ab"}
    assert listing.temporaries == {"ac": folder / f"{TEMPORARY_BUCKET_PREFIX}ac-{TOKEN}"}


def test_an_unsplit_folders_folders_are_all_entries(tmp_path: Path) -> None:
    """A folder named like a bucket is an entry until its folder is split.

    **Test steps:**

    * list a plain folder holding a one-character folder
    * verify it is an entry, and there is no bucket
    """
    (tmp_path / "a").mkdir()

    listing = BucketListing.of(tmp_path, 0)

    assert listing.entries == [BucketEntry("a", tmp_path / "a", is_folder=True)]
    assert not listing.buckets


def test_an_entry_lands_in_the_deepest_bucket_of_its_name(tmp_path: Path) -> None:
    """Down every split folder, to the bucket of one more character -- the last one possibly still to be made.

    **Test steps:**

    * split the layout folder and its bucket ``0``; make bucket ``01`` but not ``010``
    * ask where ``01abc`` and ``0abc`` land, and where anything lands under a plain folder
    * verify ``0/01`` (``01`` is plain), ``0/0a`` (still to be made), and nowhere
    """
    mark_split(tmp_path / "fab")
    mark_split(tmp_path / "fab" / "0")
    (tmp_path / "fab" / "0" / "01").mkdir()
    (tmp_path / "plain").mkdir()

    assert bucket_of(tmp_path / "fab", "01abc") == PurePosixPath("0", "01")
    assert bucket_of(tmp_path / "fab", "0abc") == PurePosixPath("0", "0a")
    assert bucket_of(tmp_path / "plain", "01abc") == PurePosixPath()


def test_an_entry_too_short_or_unbucketable_stays_up(tmp_path: Path) -> None:
    """A name too short for the next level, or whose next prefix makes no folder, stays where it is.

    **Test steps:**

    * split the layout folder and its bucket ``a``
    * ask where ``a`` and ``a.b`` land
    * verify ``a/`` for both
    """
    mark_split(tmp_path)
    mark_split(tmp_path / "a")

    assert bucket_of(tmp_path, "A") == PurePosixPath("a")
    assert bucket_of(tmp_path, "a.b") == PurePosixPath("a")


def test_an_entry_lands_in_a_bucket_being_built(tmp_path: Path) -> None:
    """A bucket a split is building is landed in under its temporary name, for the split to rename into place.

    **Test steps:**

    * split a folder that holds a temporary bucket for ``a`` and a file named like one
    * ask where ``abc`` lands, and which temporary bucket is building ``a`` and ``b``
    * verify the temporary bucket, and none for ``b``
    """
    mark_split(tmp_path)
    temporary = tmp_path / f"{TEMPORARY_BUCKET_PREFIX}a-{TOKEN}"
    temporary.mkdir()
    (tmp_path / f"{TEMPORARY_BUCKET_PREFIX}b-{TOKEN}").write_text("x", encoding="utf-8")

    assert bucket_of(tmp_path, "abc") == PurePosixPath(temporary.name)
    assert temporary_bucket_of(tmp_path, "a") == temporary
    assert temporary_bucket_of(tmp_path, "b") is None


def test_a_place_resolves_each_bucketed_level_the_innermost_chain_first(tmp_path: Path) -> None:
    """Two bucketed levels resolve top-down, each under the folders resolved above it; their chains come innermost
    first, the order they are settled in.

    **Test steps:**

    * split ``fab``, then ``fab/j/Jane``
    * resolve ``fab/{buckets}/Jane/{buckets}/Intro``, and a place with no buckets
    * verify the place with both buckets, the chains innermost first, and the plain place unchanged, told to lead
      into a folder its layout does not bucket (#681)
    """
    mark_split(tmp_path / "fab")
    mark_split(tmp_path / "fab" / "j" / "Jane")

    place = resolve_buckets(tmp_path, PurePosixPath("fab", "Jane", "Intro"), (1, 2))

    assert place == BucketedPlace(
        PurePosixPath("fab", "j", "Jane", "i", "Intro"),
        (BucketChain(PurePosixPath("fab", "j", "Jane"), ("i",)), BucketChain(PurePosixPath("fab"), ("j",))),
    )
    assert resolve_buckets(tmp_path, PurePosixPath("fab", "Intro"), ()) == BucketedPlace(
        PurePosixPath("fab", "Intro"), (), tmp_path / "fab"
    )


def test_records_beneath_a_folder_are_found_at_any_depth(tmp_path: Path) -> None:
    """A folder move tells every record beneath it; a folder that cannot be listed fails the walk.

    **Test steps:**

    * write a folder record nested in a folder of records, and a file record beside it
    * list the records beneath, then beneath a folder that is not there
    * verify both records, then the error
    """
    nested = folder_record(tmp_path / "Jane" / "Course", "Part 1")
    single = file_record(tmp_path / "Jane", "Intro")

    assert set(records_beneath(tmp_path / "Jane")) == {nested, single}
    with raises(FileNotFoundError):
        records_beneath(tmp_path / "gone")


# endregion

# region Splitting


def test_a_folder_at_the_limit_is_left_alone(splitter: BucketSplitter, tmp_path: Path) -> None:
    """A folder holding no more than the limit stays flat and unmarked.

    **Test steps:**

    * write as many file records as the limit
    * settle the folder
    * verify no marker and every record in place
    """
    for index in range(LIMIT):
        file_record(tmp_path, f"{index:04x}")

    splitter.settle(tmp_path, ())

    assert splitter.limit == LIMIT
    assert not is_split(tmp_path)
    assert len(list(tmp_path.glob("*.rehu"))) == LIMIT


def test_a_crowded_folder_splits_and_so_does_every_crowded_bucket(splitter: BucketSplitter, tmp_path: Path) -> None:
    """One record past the limit splits the folder, and each bucket past it splits again, one character deeper, each
    record moving with its screenshot.

    **Test steps:**

    * write one more file record than the limit, ids ``0000`` to ``0032``, all sharing their first two characters
    * settle the folder
    * verify the markers down to ``0/00``, and each record and screenshot in the bucket of its first three characters
    """
    names = [f"{index:04x}" for index in range(LIMIT + 1)]
    for name in names:
        file_record(tmp_path, name)

    splitter.settle(tmp_path, ())

    expected = {f"0/00/{name[:3]}/{name}{suffix}" for name in names for suffix in (".rehu", "00.jpg")}
    markers = {f"{BUCKETS_MARKER}", f"0/{BUCKETS_MARKER}", f"0/00/{BUCKETS_MARKER}"}
    assert names_under(tmp_path) == expected | markers


def test_a_folder_named_like_its_bucket_goes_into_it(splitter: BucketSplitter, tmp_path: Path) -> None:
    """A folder whose name is its bucket's is moved aside first, then lands inside the bucket of its own name.

    **Test steps:**

    * crowd a folder with folder records, one of them named ``A``, the rest starting with ``a``
    * settle it
    * verify ``A`` is in bucket ``a``, as ``a/A``, staying there beside the buckets when ``a`` splits in turn, and no
      temporary bucket is left
    """
    folder_record(tmp_path, "A")
    for index in range(LIMIT):
        folder_record(tmp_path, f"a{index:02}")

    splitter.settle(tmp_path, ())

    assert (tmp_path / "a" / "A" / "info.rehu").is_file()
    assert is_split(tmp_path / "a")
    assert (tmp_path / "a" / "a0" / "a00" / "info.rehu").is_file()
    assert not list(tmp_path.glob(f"{TEMPORARY_BUCKET_PREFIX}*"))


def test_folders_of_records_move_whole(splitter: BucketSplitter, tmp_path: Path) -> None:
    """At a folder level the entries are folders of records, each moved with everything beneath it.

    **Test steps:**

    * crowd a layout folder with author folders, one holding two course folders
    * settle it
    * verify the author's courses moved with it into its bucket
    """
    folder_record(tmp_path / "Jane", "Course 1")
    folder_record(tmp_path / "Jane", "Course 2")
    for index in range(LIMIT):
        (tmp_path / f"k{index:02}").mkdir()

    splitter.settle(tmp_path, ())

    assert names_under(tmp_path / "j") == {"Jane/Course 1/info.rehu", "Jane/Course 2/info.rehu"}


def test_a_split_marked_but_not_moved_is_finished(splitter: BucketSplitter, tmp_path: Path) -> None:
    """A split stopped right after its marker is finished however few entries are left.

    **Test steps:**

    * mark a folder holding two file records and a name too short to descend
    * settle it
    * verify the two in their buckets, the short one where it was
    """
    mark_split(tmp_path / "fab")
    file_record(tmp_path / "fab", "01abc")
    file_record(tmp_path / "fab", "1abc")

    splitter.settle(tmp_path / "fab", ())

    assert (tmp_path / "fab" / "0" / "01abc.rehu").is_file()
    assert (tmp_path / "fab" / "1" / "1abc00.jpg").is_file()


def test_a_split_stopped_before_its_marker_is_finished(splitter: BucketSplitter, tmp_path: Path) -> None:
    """A folder holding a temporary bucket is a split under way: it is marked, the bucket renamed into place, and the
    rest swept in.

    **Test steps:**

    * leave a temporary bucket for ``a`` holding folder ``a``, beside file record ``ab``, in an unmarked folder
    * settle it
    * verify the marker, ``a/a`` and ``a/ab``, and no temporary bucket
    """
    temporary = tmp_path / f"{TEMPORARY_BUCKET_PREFIX}a-{TOKEN}"
    folder_record(temporary, "a")
    file_record(tmp_path, "ab")

    splitter.settle(tmp_path, ())

    assert is_split(tmp_path)
    assert names_under(tmp_path) == {BUCKETS_MARKER, "a/a/info.rehu", "a/ab.rehu", "a/ab00.jpg"}


def test_a_split_stopped_while_setting_aside_reuses_its_temporary_bucket(
    splitter: BucketSplitter, tmp_path: Path
) -> None:
    """A folder named like its bucket, still outside the temporary bucket built for it, joins that one.

    **Test steps:**

    * leave an unmarked folder holding a temporary bucket for ``a`` and a folder ``A`` beside it
    * settle it
    * verify ``a/A``, and only one bucket for ``a``
    """
    temporary = tmp_path / f"{TEMPORARY_BUCKET_PREFIX}a-{TOKEN}"
    file_record(temporary, "ab")
    folder_record(tmp_path, "A")

    splitter.settle(tmp_path, ())

    assert names_under(tmp_path) == {BUCKETS_MARKER, "a/A/info.rehu", "a/ab.rehu", "a/ab00.jpg"}


def test_a_temporary_bucket_whose_bucket_exists_is_emptied_into_it(splitter: BucketSplitter, tmp_path: Path) -> None:
    """A bucket built aside while its bucket exists hands what it holds to the bucket and goes.

    **Test steps:**

    * split a folder holding bucket ``a`` and a temporary bucket for ``a`` holding file record ``ab``
    * settle it
    * verify ``a/ab``, and the temporary bucket gone
    """
    mark_split(tmp_path)
    (tmp_path / "a").mkdir()
    temporary = tmp_path / f"{TEMPORARY_BUCKET_PREFIX}a-{TOKEN}"
    file_record(temporary, "ab")

    splitter.settle(tmp_path, ("a",))

    assert (tmp_path / "a" / "ab.rehu").is_file()
    assert not temporary.exists()


def test_a_temporary_bucket_holding_other_files_is_left(
    splitter: BucketSplitter, tmp_path: Path, mocker: MockerFixture
) -> None:
    """A temporary bucket that still holds files no record owns is left, and the log says so.

    **Test steps:**

    * split a folder holding bucket ``a`` and a temporary bucket holding a stray file
    * settle it
    * verify the temporary bucket is left and a warning logged
    """
    warning = mocker.spy(prefix_buckets_module.LOG, "warning")
    mark_split(tmp_path)
    (tmp_path / "a").mkdir()
    temporary = tmp_path / f"{TEMPORARY_BUCKET_PREFIX}a-{TOKEN}"
    temporary.mkdir()
    (temporary / "notes.txt").write_text("x", encoding="utf-8")

    splitter.settle(tmp_path, ())

    assert (temporary / "notes.txt").is_file()
    warning.assert_called_once()


def test_a_settle_follows_a_chain_through_a_temporary_bucket(splitter: BucketSplitter, tmp_path: Path) -> None:
    """A place that went into a temporary bucket is settled on in the bucket it was renamed to.

    **Test steps:**

    * split a folder whose temporary bucket for ``a`` holds more than the limit
    * settle the folder along a chain naming the temporary bucket
    * verify bucket ``a`` is in place and split in turn
    """
    mark_split(tmp_path)
    temporary = tmp_path / f"{TEMPORARY_BUCKET_PREFIX}a-{TOKEN}"
    for index in range(LIMIT + 1):
        file_record(temporary, f"a{index:02}")

    splitter.settle(tmp_path, (temporary.name,))

    assert is_split(tmp_path / "a")
    assert (tmp_path / "a" / "a0" / "a00.rehu").is_file()


def test_a_settle_stops_at_a_bucket_that_is_gone(splitter: BucketSplitter, tmp_path: Path) -> None:
    """A chain naming a bucket no longer there settles what is there and stops.

    **Test steps:**

    * settle a plain folder along a chain naming a bucket it does not hold
    * verify nothing was made
    """
    splitter.settle(tmp_path, ("a", "ab"))

    assert not list(tmp_path.iterdir())


def test_a_folder_marked_never_split_is_left_crowded(splitter: BucketSplitter, tmp_path: Path) -> None:
    """A folder holding a folder named like the marker stays flat, however crowded.

    **Test steps:**

    * crowd a folder that holds a ``.rehubuckets`` folder
    * settle it
    * verify every record is where it was
    """
    (tmp_path / BUCKETS_MARKER).mkdir()
    for index in range(LIMIT + 1):
        file_record(tmp_path, f"{index:04x}")

    splitter.settle(tmp_path, ())

    assert len(list(tmp_path.glob("*.rehu"))) == LIMIT + 1


def test_a_folder_no_bucket_may_be_named_after_blocks_the_split(
    splitter: BucketSplitter, tmp_path: Path, mocker: MockerFixture
) -> None:
    """A folder named like its bucket, whose bucket could not be named, keeps its folder from splitting, logged, and
    nothing is set aside first: a folder listed before it, whose bucket could be named, stays where it was too.

    **Test steps:**

    * crowd a folder with folders, one named ``0`` and one named ``a``, with the sanitize step refusing ``a``
    * settle it
    * verify no marker, no temporary bucket, every folder where it was, and a warning
    """
    mocker.patch.object(prefix_buckets_module, "sanitize_name", side_effect=lambda name: None if name == "a" else name)
    warning = mocker.spy(prefix_buckets_module.LOG, "warning")
    (tmp_path / "0").mkdir()
    (tmp_path / "a").mkdir()
    for index in range(LIMIT):
        (tmp_path / f"b{index:02}").mkdir()

    splitter.settle(tmp_path, ())

    assert not is_split(tmp_path)
    assert (tmp_path / "0").is_dir()
    assert (tmp_path / "a").is_dir()
    assert not BucketListing.of(tmp_path, 0).temporaries
    warning.assert_called_once()


def test_a_swept_folder_goes_to_the_deepest_bucket_of_its_name(splitter: BucketSplitter, tmp_path: Path) -> None:
    """A folder left beside the buckets is moved past a bucket already split: named as long as that bucket's own
    buckets, it would be taken for one there (#681).

    **Test steps:**

    * split a folder whose bucket ``a`` is split in turn, and leave folder records ``ab`` and ``ac`` beside it, ``ab``'s
      bucket made and ``ac``'s not
    * settle it
    * verify ``a/ab/ab`` and ``a/ac/ac``
    """
    mark_split(tmp_path)
    mark_split(tmp_path / "a")
    file_record(tmp_path / "a" / "ab", "abc")
    folder_record(tmp_path, "ab")
    folder_record(tmp_path, "ac")

    splitter.settle(tmp_path, ())

    assert (tmp_path / "a" / "ab" / "ab" / "info.rehu").is_file()
    assert (tmp_path / "a" / "ac" / "ac" / "info.rehu").is_file()


def test_a_bucket_swept_into_past_another_splits_in_turn(splitter: BucketSplitter, tmp_path: Path) -> None:
    """Every bucket on the way to where an entry went is settled, not only the first.

    **Test steps:**

    * split a folder and its bucket ``a``, crowd ``a/ab`` to the limit, and leave a record of it beside ``a``
    * settle the folder
    * verify ``a/ab`` is split
    """
    mark_split(tmp_path)
    mark_split(tmp_path / "a")
    for index in range(LIMIT):
        file_record(tmp_path / "a" / "ab", f"ab{index:02}")
    file_record(tmp_path, "abz")

    splitter.settle(tmp_path, ())

    assert is_split(tmp_path / "a" / "ab")
    assert (tmp_path / "a" / "ab" / "abz" / "abz.rehu").is_file()


def test_a_folder_swept_into_a_bucket_being_built_is_settled_there(splitter: BucketSplitter, tmp_path: Path) -> None:
    """An entry swept past a bucket whose own split was stopped lands in the temporary bucket, which is then placed.

    **Test steps:**

    * split a folder and its bucket ``a``, which holds a temporary bucket for ``ab``, and leave record ``abc`` beside it
    * settle the folder
    * verify ``a/ab/abc``, and no temporary bucket
    """
    mark_split(tmp_path)
    mark_split(tmp_path / "a")
    folder_record(tmp_path / "a" / f"{TEMPORARY_BUCKET_PREFIX}ab-{TOKEN}", "ab")
    file_record(tmp_path, "abc")

    splitter.settle(tmp_path, ())

    assert names_under(tmp_path / "a" / "ab") == {"ab/info.rehu", "abc.rehu", "abc00.jpg"}
    assert not list(tmp_path.rglob(f"{TEMPORARY_BUCKET_PREFIX}*"))


def test_a_place_gives_its_chain_at_each_bucketed_level() -> None:
    """A path at a place says the buckets it is in, the folder each chain is under as the path spells it; a temporary
    bucket is the bucket it is built for, and a path elsewhere has none.

    **Test steps:**

    * ask for the chains of a path under two bucketed levels, one of them in a temporary bucket
    * ask for those of a path that is another place's
    * verify both chains, the outermost first, and none
    """
    relative = PurePosixPath("fab", "Jane", "Intro")
    temporary = f"{TEMPORARY_BUCKET_PREFIX}i-{TOKEN}"

    assert place_chains(("Fab", "j", "Jane", temporary, "Intro"), relative, (1, 2)) == (
        BucketChain(PurePosixPath("Fab"), ("j",)),
        BucketChain(PurePosixPath("Fab", "j", "Jane"), (temporary,)),
    )
    assert place_chains(("Fab", "k", "Jane", "Intro"), relative, (1, 2)) is None
    assert place_chains(("fab", "Jane", "Intro"), relative, ()) == ()


def test_a_folder_record_is_never_a_bucket(splitter: BucketSplitter, tmp_path: Path) -> None:
    """A folder record put by hand where a bucket of its name would be is an entry: it goes into the bucket of its name,
    and its own folders stay its own (#681).

    **Test steps:**

    * split a folder holding folder record ``a`` with more folders in it than the limit, and file record ``ab`` beside
      it; ask where a new entry lands
    * settle the folder
    * verify ``a`` whole in bucket ``a``, ``ab`` beside it, and that nothing was to land inside it
    """
    mark_split(tmp_path)
    folder_record(tmp_path, "a")
    for index in range(LIMIT + 1):
        (tmp_path / "a" / f"chapter {index:02}").mkdir()
    file_record(tmp_path, "ab")

    assert bucket_of(tmp_path, "abc") == PurePosixPath()
    splitter.settle(tmp_path, ())

    assert len(list((tmp_path / "a" / "a").iterdir())) == LIMIT + 2
    assert (tmp_path / "a" / "ab.rehu").is_file()
    assert BucketListing.of(tmp_path, 0).buckets == {"a": tmp_path / "a"}


def test_an_entry_whose_name_is_taken_is_left_and_the_rest_moves(
    splitter: BucketSplitter, tmp_path: Path, mocker: MockerFixture
) -> None:
    """One duplicate put there by hand stops nothing else (#681).

    **Test steps:**

    * split a folder holding ``a/abc`` and, beside its buckets, ``abc`` and ``bcd``
    * settle it
    * verify ``abc`` is where it was, ``bcd`` moved, and the reason told and logged
    """
    warning = mocker.spy(prefix_buckets_module.LOG, "warning")
    mark_split(tmp_path)
    folder_record(tmp_path / "a", "abc")
    folder_record(tmp_path, "abc")
    folder_record(tmp_path, "bcd")

    splitter.settle(tmp_path, ())

    assert (tmp_path / "abc" / "info.rehu").is_file()
    assert (tmp_path / "b" / "bcd" / "info.rehu").is_file()
    assert splitter.left == (f"{tmp_path / 'abc'}: its name is taken in {tmp_path / 'a'}",)
    warning.assert_called_once()


def test_a_split_stops_before_its_marker_when_a_name_is_taken_aside(splitter: BucketSplitter, tmp_path: Path) -> None:
    """A folder named like its bucket that cannot be set aside keeps its folder unmarked, or it would read as a bucket.

    **Test steps:**

    * leave an unmarked folder holding a temporary bucket for ``a`` with ``a`` in it, and another folder ``a`` beside it
    * settle it
    * verify no marker, and the reason
    """
    temporary = tmp_path / f"{TEMPORARY_BUCKET_PREFIX}a-{TOKEN}"
    folder_record(temporary, "a")
    folder_record(tmp_path, "a")

    splitter.settle(tmp_path, ())

    assert not is_split(tmp_path)
    assert splitter.left == (f"{tmp_path / 'a'}: its name is taken in {temporary}",)


@mark.parametrize("name", ["$RECYCLE.BIN", "$Recycle.Bin", "System Volume Information", "@Recycle"])
def test_a_systems_folder_is_no_entry(tmp_path: Path, name: str) -> None:
    """A layout that buckets a drive's own top folder leaves its Recycle Bin alone (#681).

    **Test steps:**

    * list a folder holding one such folder
    * verify it holds no entry
    """
    (tmp_path / name).mkdir()

    assert not BucketListing.of(tmp_path, 0).entries


def test_a_legacy_record_beside_its_rehu_is_one_entry(tmp_path: Path) -> None:
    """The ``.tc`` of a converted record moves with its ``.rehu``; one alone is an entry of its own (#681).

    **Test steps:**

    * list a folder holding ``a.rehu`` with ``A.tc``, and ``b.tc``
    * verify two entries
    """
    for name in ("a.rehu", "A.tc", "b.tc"):
        (tmp_path / name).write_text("{}", encoding="utf-8")

    assert [entry.path.name for entry in BucketListing.of(tmp_path, 0).entries] == ["a.rehu", "b.tc"]


def test_a_resolved_place_goes_back_to_what_it_was(tmp_path: Path) -> None:
    """A place's buckets are taken out of it again, for a move that reads them anew (#681).

    **Test steps:**

    * split ``fab`` and ``fab/j/Jane``, resolve a place with two bucketed levels, and undo it
    * undo a place with no buckets
    * verify each as it was before
    """
    mark_split(tmp_path / "fab")
    mark_split(tmp_path / "fab" / "j" / "Jane")
    relative = PurePosixPath("fab", "Jane", "Intro")
    place = resolve_buckets(tmp_path, relative, (1, 2))

    assert unresolve_buckets(place.relative, place.chains) == (relative, (1, 2))
    assert unresolve_buckets(relative, ()) == (relative, ())


def test_a_stop_between_moves_leaves_every_record_whole(tmp_path: Path) -> None:
    """A checkpoint raising mid-split stops it with every record in one piece; settling again finishes it.

    **Test steps:**

    * crowd a folder, and settle it with a checkpoint that raises on its third call
    * verify the stop, each record with its screenshot in exactly one place
    * settle again and verify every record in its bucket
    """
    names = [f"{index:04x}" for index in range(LIMIT + 1)]
    for name in names:
        file_record(tmp_path, name)
    calls = iter(range(1000))

    def checkpoint() -> None:
        """Stop on the third call."""
        if next(calls) == 2:
            raise InterruptedError

    mover = RecordBucketMover(RenameCoordinator(), RecordMoveHosting(), lambda: None)
    with raises(InterruptedError):
        BucketSplitter(LIMIT, mover, checkpoint).settle(tmp_path, ())

    records = list(tmp_path.rglob("*.rehu"))
    assert sorted(path.stem for path in records) == names
    assert all(path.with_name(f"{path.stem}00.jpg").is_file() for path in records)
    BucketSplitter(LIMIT, mover).settle(tmp_path, ())
    assert {bucket_key(path.parent.name) for path in tmp_path.rglob("*.rehu")} == {name[:3] for name in names}


# endregion
