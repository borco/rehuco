"""Tests for naming what one directory holds, from a resource's point of view (#266).

The listing half of the content walk's rules, so the last region checks the two **agree**: every name
this calls content is one :func:`~rehuco_core.enumerate_content_files` returns, and every name it calls
anything else is one that walk leaves out. Nothing here touches the filesystem -- a test declares what a
directory holds rather than arranging for one to hold it.
"""

from pathlib import Path
from typing import Final

from pytest import fixture, mark
from pytest_mock import MockerFixture
from rehuco_core import (
    EXCLUDED_FILE_PATTERNS,
    INFO_REHU_FILENAME,
    DirectoryClassifier,
    FileKind,
    FileType,
    classify_directory,
    enumerate_content_files,
)

from rehuco_core_tests.fake_directories import FakeDirEntry, FakeScandir

DIRECTORY: Final = Path("/fake/resource")
DIRECTORY_SCOPED_PATH: Final = DIRECTORY / INFO_REHU_FILENAME
FILE_SCOPED_PATH: Final = DIRECTORY / "foo.rehu"

TREE: Final = {
    DIRECTORY: [
        "info.rehu",
        "info00.jpg",
        "info01.jpg",
        "info.checksum",
        "info.sfv",
        "info.tc.orig",
        "cover.jpg",
        "lesson.jpg",
        "lesson01.mp4",
        "song.mp3",
        "pack.zip",
        "notes.pdf",
        "Thumbs.db",
        "foo.rehu",
        "foo00.jpg",
        "foo.zip",
    ],
    DIRECTORY / "sub": ["deeper.mp4", "info00.jpg"],
    DIRECTORY / "nested": ["info.rehu", "info00.jpg", "movie.mp4"],
}
"""One directory-scoped resource's folder, holding every shape the rules distinguish: its own record and
sidecars, a retained backup, a pattern-matched legacy screenshot, content of several types, a junk name,
a file-scoped neighbour with its own sidecar and content, a plain subdirectory and a nested resource."""

DIRECTORIES: Final = (DIRECTORY / "sub", DIRECTORY / "nested")


def mock_tree(mocker: MockerFixture, tree: dict[Path, list[str]] | None = None) -> None:
    """Mock :func:`os.scandir` over a declared tree, one directory at a time.

    :param mocker: pytest-mock fixture.
    :param tree: the directories and the file names in each; :data:`TREE` by default. A directory is an
        entry of its parent's listing when it is a key here, so a test says what is a folder rather than
        leaving it to be guessed from a name.
    """
    listing = TREE if tree is None else tree
    entries = {
        directory: [
            *(FakeDirEntry(path.name, directory=True) for path in listing if path.parent == directory),
            *(FakeDirEntry(name, size=len(name), mtime=1.0) for name in names),
        ]
        for directory, names in listing.items()
    }
    mocker.patch("os.scandir", side_effect=lambda path: FakeScandir(entries.get(Path(path), [])))


def kinds(directory: Path, record: Path = DIRECTORY_SCOPED_PATH) -> dict[str, FileKind]:
    """Classify ``directory`` and return its entries' kinds by name.

    :param directory: the directory to classify.
    :param record: the asking resource's record.
    :returns: the kinds, keyed by file name.
    """
    listing = classify_directory(record, directory)
    return {entry.name: entry.kind for entry in listing.entries}


# region Kinds in the resource's own directory


@fixture
def own(mocker: MockerFixture) -> dict[str, FileKind]:
    """The resource's own directory, classified for its directory-scoped ``info.rehu``."""
    mock_tree(mocker)
    return kinds(DIRECTORY)


@mark.parametrize(
    ("name", "kind"),
    [
        ("info.rehu", FileKind.OWN_RECORD),
        ("info00.jpg", FileKind.OWN_SCREENSHOT),
        ("info01.jpg", FileKind.OWN_SCREENSHOT),
        ("info.checksum", FileKind.OWN_MANIFEST),
        ("info.sfv", FileKind.OWN_MANIFEST),
        ("info.tc.orig", FileKind.CONVERSION_BACKUP),
        ("cover.jpg", FileKind.OWN_SCREENSHOT),
        ("lesson.jpg", FileKind.CONTENT),
        ("lesson01.mp4", FileKind.CONTENT),
        ("notes.pdf", FileKind.CONTENT),
        ("Thumbs.db", FileKind.EXCLUDED),
        ("foo.rehu", FileKind.FOREIGN_RECORD),
        ("foo00.jpg", FileKind.FOREIGN_SIDECAR),
        ("foo.zip", FileKind.FOREIGN_CONTENT),
        ("sub", FileKind.DIRECTORY),
        ("nested", FileKind.DIRECTORY),
    ],
)
def test_each_entry_is_named_from_the_asking_resources_point_of_view(
    own: dict[str, FileKind], name: str, kind: FileKind
) -> None:
    """Roles, not file types: the same ``.jpg`` is a screenshot, a neighbour's, or content (#266).

    **Test steps:**

    * classify the resource's own directory
    * verify each entry carries the kind its name and its neighbours make it
    """
    assert own[name] is kind


def test_a_legacy_manifest_with_no_record_of_its_name_is_content(mocker: MockerFixture) -> None:
    """A name is bookkeeping because a record claims it, never because of its shape -- the content
    walk's own rule, which is why a pack shipping its own checksum file keeps it counted.

    **Test steps:**

    * declare a ``yyy.sfv`` and a ``xxx00.jpg`` with no record of either name beside them
    * verify both are content
    """
    mock_tree(mocker, {DIRECTORY: ["info.rehu", "yyy.sfv", "xxx00.jpg"]})
    found = kinds(DIRECTORY)

    assert found["yyy.sfv"] is FileKind.CONTENT
    assert found["xxx00.jpg"] is FileKind.CONTENT


# endregion


# region Kinds under it


def test_a_subdirectorys_own_files_are_this_resources_content(mocker: MockerFixture) -> None:
    """A directory-scoped record covers its directory recursively, so a file one level down is its
    content like any other.

    **Test steps:**

    * classify the plain subdirectory
    * verify its video is this resource's content
    """
    mock_tree(mocker)

    assert kinds(DIRECTORY / "sub")["deeper.mp4"] is FileKind.CONTENT


def test_a_record_claims_only_its_own_directory(mocker: MockerFixture) -> None:
    """A root ``info.rehu`` does not reach down and claim a ``sub/info00.jpg`` that has no record of its
    own -- the trap the content walk documents, and the reason a sidecar's owner is looked up per
    listing.

    **Test steps:**

    * classify the subdirectory, which holds an ``info00.jpg`` and no record
    * verify that image is content rather than this resource's screenshot
    """
    mock_tree(mocker)

    assert kinds(DIRECTORY / "sub")["info00.jpg"] is FileKind.CONTENT


def test_a_nested_resources_files_are_its_own(mocker: MockerFixture) -> None:
    """A subdirectory holding an ``info.rehu`` is out of every ancestor's content wholesale (#254), so
    browsing into it shows another resource's record and another resource's content.

    **Test steps:**

    * classify the nested resource's directory
    * verify its record reads foreign, its sidecar foreign, and its video another resource's content
    """
    mock_tree(mocker)
    found = kinds(DIRECTORY / "nested")

    assert found["info.rehu"] is FileKind.FOREIGN_RECORD
    assert found["info00.jpg"] is FileKind.FOREIGN_SIDECAR
    assert found["movie.mp4"] is FileKind.FOREIGN_CONTENT


# endregion


# region Whether the folders here may be entered


def test_the_resources_own_directory_scoped_record_is_not_a_foreign_one(mocker: MockerFixture) -> None:
    """The predicate that decides navigation is *foreign* directory-scoped record, not *any* one --
    otherwise every directory-scoped resource would refuse to open its own subfolders.

    **Test steps:**

    * classify the resource's own directory, which holds its own ``info.rehu``
    * verify nothing foreign was found and the folders are navigable
    """
    mock_tree(mocker)
    listing = classify_directory(DIRECTORY_SCOPED_PATH, DIRECTORY)

    assert listing.foreign_directory_record is None


def test_a_directory_scoped_resource_keeps_its_folders_whatever_else_shares_them(
    mocker: MockerFixture,
) -> None:
    """An ``info.rehu`` covers its own directory, so the folders under it are its content and nothing
    beside it can take them -- a file-scoped neighbour claims only its same-stem siblings, and a legacy
    ``info.tc`` a conversion left behind is this same resource under its old name.

    Regression guard for the filename comparison this replaced: with an ``info.tc`` beside it, the
    resource read its own directory as covered by a neighbour and refused to browse its own folders.

    **Test steps:**

    * classify an ``info.rehu``'s own directory holding a file-scoped neighbour *and* a leftover
      ``info.tc``
    * verify nothing foreign covers it
    """
    mock_tree(
        mocker,
        {
            DIRECTORY: ["info.rehu", "info.tc", "foo.rehu", "foo.zip"],
            DIRECTORY / "sub": ["deeper.mp4"],
        },
    )
    listing = classify_directory(DIRECTORY_SCOPED_PATH, DIRECTORY)

    assert listing.foreign_directory_record is None
    assert {entry.name for entry in listing.entries if entry.is_directory} == {"sub"}


def test_a_nested_records_directory_reports_it(mocker: MockerFixture) -> None:
    """Inside a nested resource, its record is what owns the ground -- so the folders beside it are that
    resource's to browse (#254).

    **Test steps:**

    * classify the nested resource's directory
    * verify its ``info.rehu`` is named as the foreign record covering it
    """
    mock_tree(mocker)
    listing = classify_directory(DIRECTORY_SCOPED_PATH, DIRECTORY / "nested")

    assert listing.foreign_directory_record == INFO_REHU_FILENAME


@mark.parametrize("record", [DIRECTORY / "foo.rehu", DIRECTORY_SCOPED_PATH])
def test_several_file_scoped_records_and_no_info_rehu_leave_the_folders_open(
    mocker: MockerFixture, record: Path
) -> None:
    """**Only a directory-scoped record covers a directory.** A folder holding ``foo.rehu``,
    ``bar.rehu`` and ``baz.rehu`` has no record claiming the *ground* they sit on, so the subfolders
    there belong to nobody in particular and stay open -- to each of those records and to an
    ``info.rehu`` above them alike.

    The distinction this pins down is exactly the one the predicate turns on: a ``.rehu`` is not by
    itself a reason to refuse a folder; ``info.rehu``/``info.tc`` is ([[data-model#resource-scoping]],
    #254).

    **Test steps:**

    * classify a folder holding three file-scoped records, a subfolder, and no ``info.rehu``
    * verify no foreign directory-scoped record was found, asked as each of those records and as an
      enclosing directory-scoped one
    """
    mock_tree(
        mocker,
        {DIRECTORY: ["foo.rehu", "foo.zip", "bar.rehu", "bar.zip", "baz.rehu"], DIRECTORY / "sub": ["deeper.mp4"]},
    )
    listing = classify_directory(record, DIRECTORY)

    assert listing.foreign_directory_record is None
    assert {entry.name for entry in listing.entries if entry.is_directory} == {"sub"}


def test_a_file_scoped_record_sharing_a_folder_sees_the_info_rehu_as_foreign(mocker: MockerFixture) -> None:
    """[[data-model#resource-scoping]]'s tolerated coexistence, from the file-scoped side: ``foo.rehu``
    shares a directory with an ``info.rehu`` that covers it, so the folders there are that record's.

    **Test steps:**

    * classify the shared directory as ``foo.rehu``
    * verify the ``info.rehu`` is reported as the foreign record covering it
    """
    mock_tree(mocker)
    listing = classify_directory(FILE_SCOPED_PATH, DIRECTORY)

    assert listing.foreign_directory_record == INFO_REHU_FILENAME


# endregion


# region A file-scoped resource's whitelist


def test_a_file_scoped_resource_owns_its_same_stem_siblings_and_nothing_else(mocker: MockerFixture) -> None:
    """Its content is a whitelist named by the record itself, never a directory walk: everything else in
    the folder belongs to another resource or to none.

    **Test steps:**

    * classify the shared directory as ``foo.rehu``
    * verify its own record, screenshot and archive are named as its, and the ``info.*`` set is not
    """
    mock_tree(mocker)
    found = kinds(DIRECTORY, FILE_SCOPED_PATH)

    assert found["foo.rehu"] is FileKind.OWN_RECORD
    assert found["foo00.jpg"] is FileKind.OWN_SCREENSHOT
    assert found["foo.zip"] is FileKind.CONTENT
    assert found["info.rehu"] is FileKind.FOREIGN_RECORD
    assert found["info00.jpg"] is FileKind.FOREIGN_SIDECAR
    assert found["lesson01.mp4"] is FileKind.FOREIGN_CONTENT


def test_a_junk_glob_never_reaches_a_file_scoped_resources_whitelist(mocker: MockerFixture) -> None:
    """A file-scoped record's content is a whitelist of one stem, so no pattern can take a file out of
    it and none is consulted -- the content walk's own rule.

    **Test steps:**

    * declare a ``Thumbs.db`` sharing the file-scoped record's stem
    * verify it is that resource's content rather than ignored
    """
    mock_tree(mocker, {DIRECTORY: ["Thumbs.rehu", "Thumbs.db"]})

    assert kinds(DIRECTORY, DIRECTORY / "Thumbs.rehu")["Thumbs.db"] is FileKind.CONTENT


# endregion


# region Types, sizes and a directory that will not list


@mark.parametrize(
    ("name", "file_type"),
    [
        ("info.rehu", FileType.RECORD),
        ("info.checksum", FileType.MANIFEST),
        ("info.tc.orig", FileType.BACKUP),
        ("info00.jpg", FileType.IMAGE),
        ("lesson01.mp4", FileType.VIDEO),
        ("song.mp3", FileType.AUDIO),
        ("pack.zip", FileType.ARCHIVE),
        ("notes.pdf", FileType.GENERIC),
        ("sub", FileType.DIRECTORY),
    ],
)
def test_each_entry_is_also_named_by_shape(mocker: MockerFixture, name: str, file_type: FileType) -> None:
    """The axis a glyph is chosen on, orthogonal to the kind: a record is a record whether it is this
    resource's or a neighbour's (#266).

    **Test steps:**

    * classify the resource's own directory
    * verify each entry's type follows its shape
    """
    mock_tree(mocker)
    types = {entry.name: entry.file_type for entry in classify_directory(DIRECTORY_SCOPED_PATH, DIRECTORY).entries}

    assert types[name] is file_type


def test_the_listings_own_stat_answers_size_and_time(mocker: MockerFixture) -> None:
    """Read off what the listing already returned rather than costing a round trip each, which is the
    whole reason this scandirs.

    **Test steps:**

    * classify a directory whose entries declare a size and a time
    * verify both reached the entry, and that a directory carries no size
    """
    mock_tree(mocker, {DIRECTORY: ["info.rehu", "notes.pdf"], DIRECTORY / "sub": []})
    entries = {entry.name: entry for entry in classify_directory(DIRECTORY_SCOPED_PATH, DIRECTORY).entries}

    assert entries["notes.pdf"].size == len("notes.pdf")
    assert entries["notes.pdf"].modified == 1.0
    assert entries["sub"].size is None


def test_an_entry_that_will_not_stat_is_still_listed(mocker: MockerFixture) -> None:
    """A file deleted between the listing and the question, or one on a share that went away: the entry
    is real and worth showing, and only its two metadata cells are blank.

    **Test steps:**

    * declare an entry whose ``stat`` raises
    * verify it is still classified, with no size and no time
    """
    entries = [FakeDirEntry("info.rehu"), FakeDirEntry("gone.mp4", unstattable=True)]
    mocker.patch("os.scandir", return_value=FakeScandir(entries))
    found = {entry.name: entry for entry in classify_directory(DIRECTORY_SCOPED_PATH, DIRECTORY).entries}

    assert found["gone.mp4"].kind is FileKind.CONTENT
    assert found["gone.mp4"].size is None
    assert found["gone.mp4"].modified is None


def test_a_directory_that_will_not_list_is_unreachable_rather_than_empty(mocker: MockerFixture) -> None:
    """*Empty* and *away* are not the same answer (#245) -- a browser that drew an empty table over an
    offline mount would say this resource's folder is empty.

    **Test steps:**

    * make the listing raise
    * verify the answer is unreachable with no entries, and that nothing was raised
    """
    mocker.patch("os.scandir", side_effect=OSError("mount is away"))
    listing = classify_directory(DIRECTORY_SCOPED_PATH, DIRECTORY)

    assert not listing.reachable
    assert not listing.entries


def test_the_classifier_is_reusable_across_directories(mocker: MockerFixture) -> None:
    """A browser holds one and asks it per directory, which is what keeps the screenshot patterns
    compiled once rather than per listing.

    **Test steps:**

    * classify two directories through one classifier
    * verify each answered for itself
    """
    mock_tree(mocker)
    classifier = DirectoryClassifier(DIRECTORY_SCOPED_PATH)

    assert {entry.name for entry in classifier.classify(DIRECTORY / "sub").entries} == {"deeper.mp4", "info00.jpg"}
    assert classifier.classify(DIRECTORY / "nested").foreign_directory_record == INFO_REHU_FILENAME


# endregion


# region Agreement with the content walk


@mark.parametrize("record", [DIRECTORY_SCOPED_PATH, FILE_SCOPED_PATH])
def test_what_this_calls_content_is_exactly_what_the_content_walk_returns(mocker: MockerFixture, record: Path) -> None:
    """The two are halves of one rule (#226, #254, #266), and a surface that disagreed with the walk
    would report a file as this resource's content while its checksums and its size ignored it.

    Both scopes, because they take different branches on both sides: a whitelist of one stem against a
    recursive walk.

    **Test steps:**

    * walk the tree for content files, and classify every directory of it
    * verify the names called content match the walk's, directory by directory
    """
    mock_tree(mocker)
    walked = set(enumerate_content_files(record, EXCLUDED_FILE_PATTERNS).files)
    classified = {
        directory / entry.name
        for directory in (DIRECTORY, *DIRECTORIES)
        for entry in classify_directory(record, directory, EXCLUDED_FILE_PATTERNS).entries
        if entry.kind is FileKind.CONTENT
    }

    assert classified == walked


# endregion
