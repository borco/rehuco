"""Tests for what NameSuggestionModel reads of the buckets on the disk (#681): a place with them, whether anything may
be put there, and whether the record may be renamed. :mod:`test_name_suggestion_model`, whose fixtures and helpers are
imported by name, tests the places it offers without reading them.
"""

from pathlib import Path, PurePosixPath
from typing import Final

from pytest import mark, param
from pytest_mock import MockerFixture
from rehuco_agent.documents.name_suggestion_model import NameSuggestionModel, RootDestination
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_core import BUCKETS_MARKER, TEMPORARY_BUCKET_PREFIX, Layouts, ungoverned_reason

from .test_name_suggestion_model import (  # noqa: F401  # pylint: disable=unused-import
    BUCKETED_TITLES,
    BY_AUTHOR,
    RootsSignals,
    catalog_of,
    document,
    fixture_authored,
    fixture_signals,
    model,
    place,
    root_at,
)

BLOCKED: Final = ungoverned_reason(Path("Jane"))
"""Why nothing may be put into ``Jane``, split, by a layout with no buckets there."""


def mark_split(folder: Path) -> None:
    """Make a folder one that has been split.

    :param folder: the folder.
    """
    folder.mkdir(parents=True, exist_ok=True)
    (folder / BUCKETS_MARKER).touch()


@mark.parametrize(
    "layouts, where",
    [
        param(BUCKETED_TITLES, (("Jane", "f", "foo.rehu"), True), id="its-name-bucketed-and-there"),
        param(BUCKETED_TITLES, (("Jane", "x", "foo.rehu"), False), id="not-there"),
        param(
            {"*": ("{buckets}/{authors}/{title}",)}, (("j", "Jane", "foo.rehu"), False), id="an-outer-level-bucketed"
        ),
        param(BY_AUTHOR, (("Jane", "foo.rehu"), False), id="no-buckets"),
    ],
)
def test_a_rename_lands_in_a_bucket_where_the_records_own_name_is_bucketed(
    tmp_path: Path,
    authored: RehuDocumentModel,
    signals: RootsSignals,
    layouts: Layouts,
    where: tuple[tuple[str, ...], bool],
) -> None:
    """A rename moves the record to its new name's bucket only where the place it sits at buckets its own name.

    **Test steps:**

    * open a record under each layout, at a place or not, and ask where a rename lands it
    * check the place under the new name, its buckets unread and not there, or none
    """
    record, bucketed = where
    root = root_at(tmp_path, layouts)
    place(authored, tmp_path.joinpath(*record))

    found = NameSuggestionModel(authored, catalog_of(signals, root)).bucket_place("Bar")

    assert (found is not None) is bucketed
    if found is not None:
        assert (found.relative, found.bucketed) == (PurePosixPath("Jane/Bar"), (1,))
        assert found.same_root and not found.here


# region A place with its buckets


def offered(suggestions: NameSuggestionModel) -> RootDestination:
    """The place offered that the record is not at.

    :param suggestions: the suggestions.
    :returns: the place.
    """
    (found,) = (found for found in suggestions.root_destinations() if not found.here)
    return found


@mark.parametrize(
    "split, expected",
    [
        param((), "Jane/Foo", id="not-split"),
        param(("Jane",), "Jane/f/Foo", id="split"),
        param(("Jane", "Jane/f"), "Jane/f/fo/Foo", id="split-two-levels-deep"),
    ],
)
def test_a_bucketed_place_is_read_off_the_disk(
    tmp_path: Path, authored: RehuDocumentModel, signals: RootsSignals, split: tuple[str, ...], expected: str
) -> None:
    """The row is drawn by the folder the record would land in now; the place a click moves by keeps its buckets unread.

    **Test steps:**

    * offer a bucketed place whose folder is plain, split, or split two levels deep
    * read it, and check its path, nothing unread or blocked, and the place offered unchanged
    """
    root = root_at(tmp_path, BUCKETED_TITLES)
    place(authored, tmp_path / "Old" / "foo.rehu")
    for folder in split:
        mark_split(tmp_path / folder)
    suggestions = NameSuggestionModel(authored, catalog_of(signals, root))

    found = suggestions.resolved(offered(suggestions))

    assert (found.relative, found.bucketed, found.blocked) == (PurePosixPath(expected), (), "")
    assert found.shown == PurePosixPath(expected)
    assert (offered(suggestions).relative, offered(suggestions).bucketed) == (PurePosixPath("Jane/Foo"), (1,))


def test_a_temporary_bucket_is_drawn_as_the_one_it_is_built_for(
    tmp_path: Path, authored: RehuDocumentModel, signals: RootsSignals
) -> None:
    """A split under way names a bucket by a token nobody reads: the row draws its prefix, and the disk is asked by
    its name.

    **Test steps:**

    * offer a bucketed place whose bucket is a temporary one
    * read it, and check the path with the temporary name and the one drawn without
    """
    root = root_at(tmp_path, BUCKETED_TITLES)
    place(authored, tmp_path / "Old" / "foo.rehu")
    mark_split(tmp_path / "Jane")
    temporary = f"{TEMPORARY_BUCKET_PREFIX}f-0a1b2c3d"
    (tmp_path / "Jane" / temporary).mkdir()
    suggestions = NameSuggestionModel(authored, catalog_of(signals, root))

    found = suggestions.resolved(offered(suggestions))

    assert found.relative == PurePosixPath("Jane", temporary, "Foo")
    assert found.shown == PurePosixPath("Jane/f/Foo")


def test_the_place_the_record_is_at_is_its_own_folders(
    tmp_path: Path, authored: RehuDocumentModel, signals: RootsSignals, mocker: MockerFixture
) -> None:
    """Where the record already sits its own path says the buckets, and the disk is not read.

    **Test steps:**

    * open a record in its bucket, the reading of the buckets failing
    * read the place it is at, and check its path
    """
    root = root_at(tmp_path, BUCKETED_TITLES)
    place(authored, tmp_path / "Jane" / "f" / "foo.rehu")
    mocker.patch("rehuco_agent.documents.name_suggestion_model.resolve_buckets", side_effect=AssertionError)
    suggestions = NameSuggestionModel(authored, catalog_of(signals, root))
    (here,) = suggestions.root_destinations()

    found = suggestions.resolved(here)

    assert (found.relative, found.bucketed) == (PurePosixPath("Jane/f/foo"), ())


def test_the_roots_own_folder_is_no_path(tmp_path: Path, authored: RehuDocumentModel, signals: RootsSignals) -> None:
    """A record that is its root's folder is shown by the root's label alone, its buckets or not (#641).

    **Test steps:**

    * open a root's own record
    * read the one place offered, and check it has no path
    """
    root = root_at(tmp_path, BUCKETED_TITLES)
    place(authored, tmp_path / "info.rehu")
    suggestions = NameSuggestionModel(authored, catalog_of(signals, root))
    (here,) = suggestions.root_destinations()

    assert not suggestions.resolved(here).relative.parts


def test_a_place_that_cannot_be_read_is_left_as_it_is(
    tmp_path: Path, authored: RehuDocumentModel, signals: RootsSignals, mocker: MockerFixture
) -> None:
    """A folder the disk refuses leaves the buckets unread, drawn as an ellipsis, for the move to say why.

    **Test steps:**

    * offer a bucketed place, the reading of its buckets failing
    * read it, and check it is the place as offered
    """
    root = root_at(tmp_path, BUCKETED_TITLES)
    place(authored, tmp_path / "Old" / "foo.rehu")
    mocker.patch("rehuco_agent.documents.name_suggestion_model.resolve_buckets", side_effect=PermissionError)
    suggestions = NameSuggestionModel(authored, catalog_of(signals, root))

    found = suggestions.resolved(offered(suggestions))

    assert found == offered(suggestions)
    assert found.shown == PurePosixPath("Jane/…/Foo")


# endregion

# region A folder no rule buckets


def test_a_place_in_a_folder_its_layout_does_not_bucket_is_blocked(
    tmp_path: Path, authored: RehuDocumentModel, signals: RootsSignals
) -> None:
    """Nothing may be put into a folder split by a rule that is gone, until a balance joins it.

    **Test steps:**

    * offer a plain place in a split folder
    * read it, and check why it is blocked; unmark the folder, and check it no longer is
    """
    root = root_at(tmp_path, BY_AUTHOR)
    place(authored, tmp_path / "Old" / "foo.rehu")
    mark_split(tmp_path / "Jane")
    suggestions = NameSuggestionModel(authored, catalog_of(signals, root))

    assert suggestions.resolved(offered(suggestions)).blocked == BLOCKED

    (tmp_path / "Jane" / BUCKETS_MARKER).unlink()
    assert not suggestions.resolved(offered(suggestions)).blocked


@mark.parametrize(
    "layouts, record, blocked",
    [
        param(BY_AUTHOR, ("Jane", "f", "foo.rehu"), True, id="in-its-old-bucket"),
        param(BY_AUTHOR, ("Jane", "foo.rehu"), True, id="beside-the-buckets"),
        param(BY_AUTHOR, ("Old", "foo.rehu"), False, id="elsewhere"),
        param(BUCKETED_TITLES, ("Jane", "f", "foo.rehu"), False, id="in-its-bucket"),
        param({"*": ("{authors}/{title}", *BUCKETED_TITLES["*"])}, ("Jane", "foo.rehu"), False, id="two-templates"),
    ],
)
# pylint: disable-next=too-many-arguments,too-many-positional-arguments  # each is what the case is made of
def test_a_record_in_a_folder_no_rule_buckets_is_not_renamed(
    tmp_path: Path,
    authored: RehuDocumentModel,
    signals: RootsSignals,
    layouts: Layouts,
    record: tuple[str, ...],
    blocked: bool,
) -> None:
    """A rename would put a name into a folder of buckets nobody buckets any more; one rule that does is enough.

    **Test steps:**

    * split a folder and open a record there, or elsewhere, under each layout
    * check whether a rename is blocked, and why
    """
    root = root_at(tmp_path, layouts)
    place(authored, tmp_path.joinpath(*record))
    mark_split(tmp_path / "Jane")

    reason = NameSuggestionModel(authored, catalog_of(signals, root)).rename_blocked()

    assert reason == (BLOCKED if blocked else "")


@mark.parametrize(
    "layouts, record",
    [
        param(BUCKETED_TITLES, ("Jane", "f", "foo.rehu"), id="in-its-bucket"),
        param({"*": ("{buckets}/{authors}/{title}",)}, ("j", "Jane", "foo.rehu"), id="an-outer-level-bucketed"),
    ],
)
@mark.parametrize("field", ["title", "authors"])
# pylint: disable-next=too-many-arguments,too-many-positional-arguments  # each is what the case is made of
def test_a_record_whose_fields_were_edited_is_still_renamed(
    tmp_path: Path,
    authored: RehuDocumentModel,
    signals: RootsSignals,
    layouts: Layouts,
    record: tuple[str, ...],
    field: str,
) -> None:
    """Editing a field is what a rename follows: the folder the layout buckets is no less bucketed for it.

    **Test steps:**

    * split a folder the layout buckets, open a record in it, and edit a field its place is rendered from
    * check a rename is not blocked
    """
    root = root_at(tmp_path, layouts)
    place(authored, tmp_path.joinpath(*record))
    mark_split(tmp_path.joinpath(*record[:-2]))

    setattr(authored, field, "Goo" if field == "title" else ["Zoe"])

    assert not NameSuggestionModel(authored, catalog_of(signals, root)).rename_blocked()


def test_a_record_its_bucketed_layout_refuses_may_be_renamed(
    tmp_path: Path, authored: RehuDocumentModel, signals: RootsSignals
) -> None:
    """A record no template takes lies, for all that is known, in a folder its own layout buckets.

    **Test steps:**

    * split a folder the layout buckets, open a record in it, and empty a field the layout needs
    * check a rename is not blocked
    """
    root = root_at(tmp_path, BUCKETED_TITLES)
    place(authored, tmp_path / "Jane" / "f" / "foo.rehu")
    mark_split(tmp_path / "Jane")

    authored.authors = []

    assert not NameSuggestionModel(authored, catalog_of(signals, root)).rename_blocked()


def test_a_rename_after_an_edited_title_lands_in_the_new_names_bucket(
    tmp_path: Path, authored: RehuDocumentModel, signals: RootsSignals
) -> None:
    """The title is edited first and the new name picked after: it goes to its own bucket, not beside the old one's.

    **Test steps:**

    * open a record in its bucket and edit its title
    * ask where a rename to the new title lands it, and read it
    """
    root = root_at(tmp_path, BUCKETED_TITLES)
    place(authored, tmp_path / "Jane" / "f" / "foo.rehu")
    mark_split(tmp_path / "Jane")
    authored.title = "Goo"
    suggestions = NameSuggestionModel(authored, catalog_of(signals, root))

    landing = suggestions.bucket_place("Goo")

    assert landing is not None
    assert suggestions.resolved(landing).relative == PurePosixPath("Jane/g/Goo")


@mark.parametrize(
    "record, split, expected",
    [
        param(("Jane", "f", "foo.rehu"), "Jane", "Jane/g/Goo", id="in-a-bucket"),
        param(("Jane", "f", "fo", "foo.rehu"), "Jane", "Jane/g/Goo", id="two-buckets-deep"),
        param(
            ("Jane", f"{TEMPORARY_BUCKET_PREFIX}f-0a1b2c3d", "foo.rehu"),
            "Jane",
            "Jane/g/Goo",
            id="a-bucket-being-built",
        ),
        param(("Jane", "f", "foo.rehu"), None, None, id="its-folder-not-split"),
        param(("Jane", "x", "foo.rehu"), "Jane", None, id="in-no-bucket-of-its-name"),
        param(("info.rehu",), "", None, id="the-roots-own-folder"),
    ],
)
# pylint: disable-next=too-many-arguments,too-many-positional-arguments  # each is what the case is made of
def test_a_rename_after_other_fields_were_edited_stays_under_its_split_folder(
    tmp_path: Path,
    authored: RehuDocumentModel,
    signals: RootsSignals,
    record: tuple[str, ...],
    split: str | None,
    expected: str | None,
) -> None:
    """With its authors edited no template's place fits where the record lies; the disk still says it lies in the
    buckets of its name, so a rename moves it to the new name's bucket under the same folder.

    **Test steps:**

    * open a record in a bucket of a split folder, or not, and edit its authors and its title
    * ask where a rename lands it, and read it
    * check the new name's bucket under the same folder, or none
    """
    root = root_at(tmp_path, BUCKETED_TITLES)
    place(authored, tmp_path.joinpath(*record))
    if split is not None:
        mark_split(tmp_path / split)
    authored.authors = ["Zoe"]
    authored.title = "Goo"
    suggestions = NameSuggestionModel(authored, catalog_of(signals, root))

    landing = suggestions.bucket_place("Goo")

    assert (landing is not None) is (expected is not None)
    if landing is not None and expected is not None:
        assert suggestions.resolved(landing).relative == PurePosixPath(expected)
        assert landing.same_root and not landing.here


def test_a_record_out_of_reach_lands_in_no_bucket(
    tmp_path: Path, authored: RehuDocumentModel, signals: RootsSignals
) -> None:
    """Under no root, or under one that cannot be reached, no disk is asked.

    **Test steps:**

    * open a record in a bucket with no catalog, then with its root unreachable
    * check a rename lands it in no bucket
    """
    root = root_at(tmp_path, BUCKETED_TITLES)
    place(authored, tmp_path / "Jane" / "f" / "foo.rehu")
    mark_split(tmp_path / "Jane")
    authored.authors = ["Zoe"]
    unreachable = catalog_of(signals, root, unreachable=frozenset((root.root_id,)))

    assert NameSuggestionModel(authored).bucket_place("Goo") is None
    assert NameSuggestionModel(authored, unreachable).bucket_place("Goo") is None


def test_a_root_that_went_away_is_asked_for_once(
    tmp_path: Path, authored: RehuDocumentModel, signals: RootsSignals, mocker: MockerFixture
) -> None:
    """A share that stops answering is not waited for at every level of a place.

    **Test steps:**

    * offer a place of a root whose folder is not there
    * read it, and check it is as offered, its buckets never asked for
    """
    root = root_at(tmp_path / "gone", BUCKETED_TITLES)
    place(authored, tmp_path / "Old" / "foo.rehu")
    resolve = mocker.patch("rehuco_agent.documents.name_suggestion_model.resolve_buckets")
    suggestions = NameSuggestionModel(authored, catalog_of(signals, root))

    assert suggestions.resolved(offered(suggestions)) == offered(suggestions)
    resolve.assert_not_called()


def test_a_record_under_no_root_may_be_renamed(authored: RehuDocumentModel, tmp_path: Path) -> None:
    """With no root there is no rule to miss.

    **Test steps:**

    * open a record with no catalog
    * check a rename is not blocked
    """
    place(authored, tmp_path / "foo.rehu")

    assert not NameSuggestionModel(authored).rename_blocked()


# endregion
