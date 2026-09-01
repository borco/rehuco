"""Tests for the RehuDocumentModel reactive view-model."""

# The RecordingSink double and the attach-the-bridge-to-one-logger fixture read the same here as in
# test_rehu_document_model.py and borco-pyside's test_log_bridge.py: asserting *where a record was placed*
# takes a sink that keeps what it was handed and a logger isolated from every other handler. Kept as a copy
# per module, the convention every settings test's own FakeSettings already follows here.
# pylint: disable=duplicate-code

# the model has a broad reactive surface (common-core + type fields, seeding, revert, dirty
# tracking); its test suite is correspondingly long -- one cohesive module reads better than an
# arbitrary split, so the module-length cap is lifted here rather than fragmenting it.
# pylint: disable=too-many-lines

import json
import logging
from collections.abc import Callable, Hashable, Iterator, Sequence
from pathlib import Path
from typing import Final

import pytest
from borco_pyside.logging import LogEntry
from fields.field_testers import FieldTester as Field
from pytest import fixture, mark, param, raises
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.app_logging import shared_log_bridge
from rehuco_agent.documents.rehu_document_image_scanner import RehuDocumentImageScanner
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel, path_label
from rehuco_agent.fields import FieldsTab, UnknownField
from rehuco_core import (
    CURRENT_FORMAT_VERSION,
    EXCLUDED_FILE_PATTERNS,
    FORMAT_VERSION_KEY,
    LEGACY_SCREENSHOT_RULES,
    ConversionBackups,
    LearningPathEntry,
    LockReasonKind,
    RehuDocument,
    RenameCoordinator,
    RenameYieldTimeout,
    current_block_version,
    scan_rehu_screenshot_files,
    scan_tc_screenshot_files,
    visible_learning_paths,
)


def backups_restoring(legacy: Path) -> ConversionBackups:
    """What a completed revert reports it put back, for a test mocking the core operation.

    :param legacy: where the backed-up ``.tc`` landed -- the file ``revert_conversion`` then adopts.
    :returns: a plausible inventory.
    """
    return ConversionBackups(
        rehu_path=legacy.with_suffix(".rehu"),
        backups=(legacy.with_name(legacy.name + ".orig"),),
        total_bytes=1000,
        written=(legacy.with_suffix(".rehu"),),
        obstructions=(),
        legacy_restored=legacy,
        edited_since=False,
        converted="2023-11-14T22:13:20Z",
    )


def lister_of(scanner: RehuDocumentImageScanner) -> object:
    """The screenshot lister a `RehuDocumentImageScanner` delegates :meth:`~RehuDocumentImageScanner.files` to.

    Reads the scanner's name-mangled private, so the model's wiring can be asserted without exposing
    the lister as public API.

    :param scanner: the scanner to inspect.
    :returns: the lister callable it was built with.
    """
    return scanner._RehuDocumentImageScanner__lister  # type: ignore[attr-defined]  # pylint: disable=protected-access


# region fixtures
@fixture
def document() -> RehuDocument:
    """An in-memory document with a primary source carrying title/publisher/url."""
    return RehuDocument(
        {
            "type": "Tutorial",
            "sources": [
                {"title": "Foo", "publisher": "Bar", "url": "https://example.com", "primary": True},
            ],
        }
    )


@fixture
def model(document: RehuDocument) -> RehuDocumentModel:
    """A view-model wrapping the sample document."""
    return RehuDocumentModel(document)


# endregion


# region RehuDocumentModel tests
def test_model_seeds_fields_from_document_without_dirtying(model: RehuDocumentModel) -> None:
    """A freshly constructed model mirrors the document's fields and is not dirty.

    **Test steps:**

    * construct a model over a document with a populated primary source
    * verify title/publisher/url read back the document's values
    * verify the model is not dirty (seeding must not look like an edit)
    """
    assert model.title == "Foo"
    assert model.publisher == "Bar"
    assert model.url == "https://example.com"
    assert model.dirty is False
    assert model.locked is False


def test_model_is_locked_when_the_document_format_version_is_newer_than_supported() -> None:
    """A document whose ``format_version`` exceeds ``CURRENT_FORMAT_VERSION`` locks the
    model at construction ([[data-model#schema-version]]'s fail-safe-on-a-newer-file rule).

    **Test steps:**

    * construct a model over a document one version newer than this build understands
    * verify the model is locked
    """
    newer_version = CURRENT_FORMAT_VERSION + 1
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial", "format_version": newer_version}))
    assert model.locked is True


def test_model_is_not_locked_at_or_below_the_current_format_version() -> None:
    """A document at (or below, or missing) the current ``format_version`` is not locked.

    **Test steps:**

    * construct models over documents at the current version, an older version, and no version at all
    * verify none of them lock
    """
    assert RehuDocumentModel(RehuDocument({"format_version": CURRENT_FORMAT_VERSION})).locked is False
    assert RehuDocumentModel(RehuDocument({"format_version": 0})).locked is False
    assert RehuDocumentModel(RehuDocument({})).locked is False


def test_model_is_locked_for_a_legacy_tc_document() -> None:
    """A document mapped from a legacy ``.tc`` file locks the model, independent of ``format_version``
    ([[acquisition-tooling#tc-to-rehu]]'s Phase 1).

    The newer-format-version rule can never catch it: the mapping emits the **current** layout, stamp
    included, so a real `.tc`-derived document is at this build's own version. What locks it is that no
    ``.rehu`` exists for it yet -- a fact about the file, not about any schema version -- which is why
    the flag is checked separately and holds at *any* version.

    **Test steps:**

    * construct a model over a ``legacy_tc=True`` document at the current format version
    * verify the model is locked
    """
    current = CURRENT_FORMAT_VERSION
    document = RehuDocument({"format_version": current, "core": {"type": "tutorial"}}, legacy_tc=True)
    assert document.format_version == current  # not the newer-version rule's doing
    model = RehuDocumentModel(document)

    assert model.locked is True


def test_model_lock_reasons_mirror_the_documents_reasons() -> None:
    """The model's ``lock_reasons`` are the document's, and ``locked`` derives from whether any exist
    ([[data-model#write-integrity]]).

    **Test steps:**

    * construct a model over a newer-than-supported document
    * verify ``lock_reasons`` carries the document's ``NEWER_FORMAT`` reason and ``locked`` is ``True``
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial", "format_version": CURRENT_FORMAT_VERSION + 1}))
    assert [reason.kind for reason in model.lock_reasons] == [LockReasonKind.NEWER_FORMAT]
    assert model.locked is True


def test_model_over_an_invalid_field_document_locks_and_stays_clean() -> None:
    """A document with a present-but-uncoercible owned field opens locked ``INVALID_FIELD`` and never
    dirty, so editing can't save the coerced default over the original ([[data-model#write-integrity]]).

    **Test steps:**

    * construct a model over a document whose ``authors`` is present but not skip-clean
    * verify it is locked with the ``INVALID_FIELD`` reason and is not dirty
    """
    model = RehuDocumentModel(RehuDocument({"core": {"authors": 42}}))
    assert model.locked is True
    assert [reason.kind for reason in model.lock_reasons] == [LockReasonKind.INVALID_FIELD]
    assert model.dirty is False


def test_model_over_a_load_failed_document_locks_and_stays_clean(mocker: MockerFixture) -> None:
    """A model wrapping a load-failure stub is locked and never dirty -- distinct from ``create_new``'s
    empty-**dirty** state ([[data-model#write-integrity]]).

    **Test steps:**

    * build a ``MISSING`` stub via ``open_or_locked`` over a mocked-vanished file
    * wrap it in a model
    * verify the model is locked ``MISSING``, bound to the path, and not dirty
    """
    mocker.patch.object(Path, "read_text", side_effect=FileNotFoundError("gone"))
    document = RehuDocument.open_or_locked(Path("/fake/info.rehu"))

    model = RehuDocumentModel(document)

    assert model.locked is True
    assert [reason.kind for reason in model.lock_reasons] == [LockReasonKind.MISSING]
    assert model.path == Path("/fake/info.rehu")
    assert model.dirty is False


def test_model_seeds_empty_from_a_sourceless_document() -> None:
    """A document with no sources seeds the model to empty fields without error.

    **Test steps:**

    * construct a model over a document that has no ``sources``
    * verify title/publisher/url read back as empty strings and the model is clean
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}))
    assert model.title == ""
    assert model.publisher == ""
    assert model.url == ""
    assert model.dirty is False


def test_model_seeds_location_from_the_document_path() -> None:
    """``location`` seeds from the document's file path, as a posix string.

    **Test steps:**

    * construct a model over a document loaded with an explicit path
    * verify ``model.location`` mirrors it
    """
    document = RehuDocument({"type": "Tutorial"}, Path("C:/tutorials/foo/info.rehu"))
    model = RehuDocumentModel(document)

    assert model.location == "C:/tutorials/foo/info.rehu"


def test_model_seeds_location_empty_when_the_document_has_no_path(model: RehuDocumentModel) -> None:
    """A pathless document (the shared fixture) seeds ``location`` empty.

    **Test steps:**

    * read ``model.location`` off the shared fixture, which has no path
    * verify it is empty
    """
    assert model.location == ""


def test_setting_location_does_not_write_through_or_dirty(model: RehuDocumentModel, document: RehuDocument) -> None:
    """Setting ``location`` (as the viewer binding does) never touches the document or dirties the model.

    ``location`` mirrors the file path for the viewer; it isn't a document field. Renaming on disk is
    the separate :meth:`rename_location` path.

    **Test steps:**

    * set ``model.location`` to a new value
    * verify the document's path is unchanged and the model stays clean
    """
    model.location = "C:/tutorials/bar/info.rehu"

    assert document.path is None
    assert model.dirty is False


def test_rename_location_adopts_the_new_path_on_success(mocker: MockerFixture) -> None:
    """A successful rename re-points the model **and** its document at the returned path, reseeding
    ``location`` and ``current_name`` from it and leaving the model clean.

    **Test steps:**

    * build a model over a directory-scoped document and mock the core rename to succeed
    * call ``rename_location``
    * verify it returned ``True``, the core rename got the old path and the new name, and path /
      location / current_name / the document's own path all moved to the new location
    """
    document = RehuDocument({"type": "Tutorial"}, Path("C:/tutorials/old_folder/info.rehu"))
    model = RehuDocumentModel(document)
    renamed = Path("C:/tutorials/new_name/info.rehu")
    rename = mocker.patch("rehuco_agent.documents.rehu_document_model.rename_rehu_resource", return_value=renamed)

    assert model.rename_location("new_name") is True

    rename.assert_called_once_with(Path("C:/tutorials/old_folder/info.rehu"), "new_name")
    assert model.path == renamed
    assert model.location == "C:/tutorials/new_name/info.rehu"
    assert model.current_name == "new_name"
    assert document.path == renamed
    assert model.dirty is False
    assert model.rename_error == ""


def test_rename_location_reinstalls_the_image_scanner_on_success(mocker: MockerFixture) -> None:
    """A successful rename installs a **fresh** scanner, so ``image_scanner_changed`` tells the image
    strip and the Markdown viewer that the screenshot names they hold are stale.

    **Test steps:**

    * mock the core rename to succeed on a file-scoped document
    * connect to ``image_scanner_changed`` and rename
    * verify the signal fired and the scanner object was replaced, still over the `.rehu` lister
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, Path("C:/tutorials/old_file.rehu")))
    original = model.image_scanner
    received: list[object] = []
    model.image_scanner_changed.connect(received.append)  # type: ignore[attr-defined]
    mocker.patch(
        "rehuco_agent.documents.rehu_document_model.rename_rehu_resource",
        return_value=Path("C:/tutorials/new_name.rehu"),
    )

    model.rename_location("new_name")

    assert len(received) == 1
    assert model.image_scanner is not original
    assert model.image_scanner is not None
    assert lister_of(model.image_scanner) is scan_rehu_screenshot_files


def test_rename_location_logs_the_attempt_before_the_move_runs(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    """The attempt is logged *before* the move is tried, so the log records what was asked for even
    when the move then fails.

    **Test steps:**

    * make the core rename fail, capturing the log around it
    * verify the "Attempting" info record precedes the error record
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, Path("C:/tutorials/old_file.rehu")))
    mocker.patch("rehuco_agent.documents.rehu_document_model.rename_rehu_resource", side_effect=OSError("boom"))

    with caplog.at_level(logging.INFO):
        model.rename_location("new_name")

    levels = [record.levelno for record in caplog.records]
    assert levels.index(logging.INFO) < levels.index(logging.ERROR)


def test_rename_location_reports_a_failed_move_without_touching_the_document(mocker: MockerFixture) -> None:
    """A refused rename leaves everything as it was and explains itself through ``rename_error``, using
    the OS's own ``strerror`` rather than the full ``[Errno n] ...`` rendering.

    **Test steps:**

    * make the core rename raise ``PermissionError`` on a file-scoped document
    * call ``rename_location``
    * verify it returned ``False``, path/location are unchanged, and ``rename_error`` names both names
      and the OS reason
    """
    path = Path("C:/tutorials/old_file.rehu")
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, path))
    mocker.patch(
        "rehuco_agent.documents.rehu_document_model.rename_rehu_resource",
        side_effect=PermissionError(13, "Permission denied", str(path)),
    )

    assert model.rename_location("new_name") is False

    assert model.path == path
    assert model.location == "C:/tutorials/old_file.rehu"
    assert model.rename_error == 'Could not rename "old_file" to "new_name": Permission denied.'


def test_rename_location_reports_a_refused_name(mocker: MockerFixture) -> None:
    """A name the core renamer refuses outright (a ``ValueError``, not an ``OSError``) reports through
    the same channel -- the banner explains, nothing is moved.

    **Test steps:**

    * make the core rename raise ``ValueError``
    * call ``rename_location``
    * verify ``False`` came back and ``rename_error`` carries the refusal
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, Path("C:/tutorials/old_file.rehu")))
    mocker.patch(
        "rehuco_agent.documents.rehu_document_model.rename_rehu_resource",
        side_effect=ValueError("'..' is not a plain file or folder name."),
    )

    assert model.rename_location("..") is False

    assert model.rename_error == 'Could not rename "old_file" to "..": \'..\' is not a plain file or folder name.'


def test_rename_location_clears_a_previous_error_when_a_retry_succeeds(mocker: MockerFixture) -> None:
    """``rename_error`` describes the **current** attempt: a retry that works takes the banner row away.

    **Test steps:**

    * fail one rename, then succeed the next
    * verify ``rename_error`` is set after the first and empty after the second
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, Path("C:/tutorials/old_file.rehu")))
    rename = mocker.patch(
        "rehuco_agent.documents.rehu_document_model.rename_rehu_resource",
        side_effect=[FileExistsError('"taken.rehu" already exists.'), Path("C:/tutorials/free.rehu")],
    )

    model.rename_location("taken")
    assert model.rename_error != ""

    model.rename_location("free")

    assert model.rename_error == ""
    assert rename.call_count == 2


def test_rename_location_refuses_a_document_with_no_location(mocker: MockerFixture, model: RehuDocumentModel) -> None:
    """A document with no location at all has nothing to rename: refused before any save or move is
    attempted. Distinct from a document merely not written *yet*
    (:func:`test_rename_location_renames_a_never_saved_document`), which renames fine.

    **Test steps:**

    * call ``rename_location`` on the path-less fixture model
    * verify ``False`` came back, ``rename_error`` says why, and the core rename was never called
    """
    rename = mocker.patch("rehuco_agent.documents.rehu_document_model.rename_rehu_resource")

    assert model.rename_location("new_name") is False

    assert "no location yet" in model.rename_error
    rename.assert_not_called()


def test_rename_location_renames_a_never_saved_document(mocker: MockerFixture) -> None:
    """A brand-new document -- "open in rehuco" on a folder, or an archive's companion -- renames like
    any other: it is born dirty, so the pre-move save writes its `.rehu` at the location it was bound
    to, and the rename then has a real file to move. Not being written *yet* is a reason to write it
    first, never a reason to refuse.

    **Test steps:**

    * build a ``create_new`` model bound to a folder's ``info.rehu``, never saved
    * patch ``save`` (standing in for the real write) and the core rename
    * call ``rename_location``
    * verify it saved first, then renamed, and adopted the new path
    """
    model = RehuDocumentModel.create_new(Path("C:/tutorials/My Tutorial/info.rehu"))
    assert model.dirty is True
    assert model.saved_on_disk is False
    save = mocker.patch.object(model, "save")
    renamed = Path("C:/tutorials/Renamed/info.rehu")
    mocker.patch("rehuco_agent.documents.rehu_document_model.rename_rehu_resource", return_value=renamed)

    assert model.rename_location("Renamed") is True

    save.assert_called_once()
    assert model.path == renamed
    assert model.current_name == "Renamed"
    assert model.rename_error == ""


def test_rename_location_saves_first_when_dirty(mocker: MockerFixture) -> None:
    """A dirty model is saved before the move is attempted, so the files being moved aren't stale.

    **Test steps:**

    * dirty a model over a real path, then patch ``save`` and the core rename
    * call ``rename_location``
    * verify ``save`` was called
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, Path("C:/tutorials/old_file.rehu")))
    model.title = "New Title"
    assert model.dirty is True
    save = mocker.patch.object(model, "save")
    mocker.patch(
        "rehuco_agent.documents.rehu_document_model.rename_rehu_resource",
        return_value=Path("C:/tutorials/new_name.rehu"),
    )

    model.rename_location("new_name")

    save.assert_called_once()


def test_rename_location_aborts_when_the_pre_move_save_fails(mocker: MockerFixture) -> None:
    """A pre-move save that raises ``OSError`` (an offline mount, #146) aborts the rename: nothing is
    moved, the document simply stays dirty, and ``rename_error`` explains -- this view-model has no
    widget to parent a retry/cancel dialog to, and a banner row is the channel every other failure here
    uses anyway.

    **Test steps:**

    * dirty a model, patch ``save`` to raise ``OSError``, and patch the core rename to detect a call
    * call ``rename_location``
    * verify ``False`` came back, ``rename_error`` names the save, the model is still dirty, and no
      rename was attempted
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, Path("C:/tutorials/old_file.rehu")))
    model.title = "New Title"
    mocker.patch.object(model, "save", side_effect=OSError(5, "offline mount"))
    rename = mocker.patch("rehuco_agent.documents.rehu_document_model.rename_rehu_resource")

    assert model.rename_location("new_name") is False

    assert model.rename_error == 'Could not save "old_file" before renaming it: offline mount.'
    assert model.dirty is True
    rename.assert_not_called()


def test_rename_location_aborts_when_the_pre_move_save_is_refused_by_a_lock(mocker: MockerFixture) -> None:
    """A save the document itself refuses raises ``ValueError``, not ``OSError`` -- a locked document's
    save is blocked ([[data-model#write-integrity]]) -- and is reported through the same channel rather
    than escaping as an unhandled error.

    **Test steps:**

    * dirty a model and patch ``save`` to raise the refusal a save-blocking lock produces
    * call ``rename_location``
    * verify ``False`` came back, ``rename_error`` carries the refusal, and no rename was attempted
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, Path("C:/tutorials/old_file.rehu")))
    model.title = "New Title"
    mocker.patch.object(model, "save", side_effect=ValueError("Refusing to save a locked document (missing)."))
    rename = mocker.patch("rehuco_agent.documents.rehu_document_model.rename_rehu_resource")

    assert model.rename_location("new_name") is False

    assert "Refusing to save a locked document" in model.rename_error
    rename.assert_not_called()


def test_rename_location_reports_a_resource_whose_file_has_gone_missing(mocker: MockerFixture) -> None:
    """A clean document whose file vanished out of band is refused by the core rename, and the refusal
    reaches the banner like any other -- nothing is renamed on a guess about what the set used to be.

    **Test steps:**

    * make the core rename raise ``FileNotFoundError``
    * call ``rename_location``
    * verify ``False`` came back and ``rename_error`` says the file is gone
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, Path("C:/tutorials/old_file.rehu")))
    mocker.patch(
        "rehuco_agent.documents.rehu_document_model.rename_rehu_resource",
        side_effect=FileNotFoundError('"old_file.rehu" is no longer on disk.'),
    )

    assert model.rename_location("new_name") is False

    assert model.rename_error == 'Could not rename "old_file" to "new_name": "old_file.rehu" is no longer on disk.'


def test_revert_clears_a_standing_rename_error(mocker: MockerFixture) -> None:
    """A revert clears a lingering rename failure along with everything else -- a revert leaves the
    model exactly as a fresh open would, and a fresh open carries no failed attempt.

    **Test steps:**

    * fail a rename so ``rename_error`` is set, then mock ``document.reload`` and revert
    * verify ``rename_error`` is empty again
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, Path("C:/tutorials/old_file.rehu")))
    mocker.patch("rehuco_agent.documents.rehu_document_model.rename_rehu_resource", side_effect=OSError("boom"))
    model.rename_location("new_name")
    assert model.rename_error != ""
    mocker.patch.object(model.document, "reload")

    model.revert()

    assert model.rename_error == ""


def test_rename_location_does_not_save_when_clean(mocker: MockerFixture) -> None:
    """A clean model is not saved before attempting the move -- there is nothing to save.

    **Test steps:**

    * patch ``save`` and the core rename on a clean model
    * call ``rename_location``
    * verify ``save`` was not called
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, Path("C:/tutorials/old_file.rehu")))
    assert model.dirty is False
    save = mocker.patch.object(model, "save")
    mocker.patch(
        "rehuco_agent.documents.rehu_document_model.rename_rehu_resource",
        return_value=Path("C:/tutorials/new_name.rehu"),
    )

    model.rename_location("new_name")

    save.assert_not_called()


def test_rename_location_goes_through_the_coordinator_when_there_is_one(mocker: MockerFixture) -> None:
    """With a coordinator, the rename asks the running jobs to stand aside rather than going straight
    to disk (#241).

    **Test steps:**

    * build a model over a coordinator whose rename is mocked to succeed
    * rename
    * verify the coordinator was asked, the bare core function was not, and the new path was adopted
    """
    coordinator = RenameCoordinator()
    renamed = Path("C:/tutorials/new_name/info.rehu")
    through = mocker.patch.object(coordinator, "rename", return_value=renamed)
    direct = mocker.patch("rehuco_agent.documents.rehu_document_model.rename_rehu_resource")
    document = RehuDocument({"type": "Tutorial"}, Path("C:/tutorials/old_folder/info.rehu"))
    model = RehuDocumentModel(document, rename_coordinator=coordinator)

    assert model.rename_location("new_name") is True

    through.assert_called_once_with(Path("C:/tutorials/old_folder/info.rehu"), "new_name")
    direct.assert_not_called()
    assert model.path == renamed


def test_a_rename_readers_will_not_release_fails_through_the_banner(mocker: MockerFixture) -> None:
    """A job that never lets go costs the rename its ceiling and then reports like any other refusal
    (#241).

    The reason this is a *failure* rather than a lock: the user is told what happened and may try
    again, where #240 would simply have refused to offer the rename at all.

    **Test steps:**

    * make the coordinator's rename time out waiting for readers
    * rename
    * verify it failed, said so in the banner, and left the document where it was
    """
    coordinator = RenameCoordinator()
    mocker.patch.object(coordinator, "rename", side_effect=RenameYieldTimeout("A task is still reading these files."))
    path = Path("C:/tutorials/old_folder/info.rehu")
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, path), rename_coordinator=coordinator)

    assert model.rename_location("new_name") is False

    assert "still reading these files" in model.rename_error
    assert model.path == path


def test_rename_location_goes_straight_to_disk_without_a_coordinator(mocker: MockerFixture) -> None:
    """With no coordinator there are no tracked readers to ask, so the barrier is skipped entirely.

    Not a lesser mode: it is the same operation with the empty case left out, which is what keeps every
    caller that has no running work -- most tests, and any headless use -- from having to build one.

    **Test steps:**

    * build a model with no coordinator and mock the core rename
    * rename
    * verify the core function did the work
    """
    renamed = Path("C:/tutorials/new_name/info.rehu")
    direct = mocker.patch("rehuco_agent.documents.rehu_document_model.rename_rehu_resource", return_value=renamed)
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, Path("C:/tutorials/old_folder/info.rehu")))

    assert model.rename_location("new_name") is True

    direct.assert_called_once_with(Path("C:/tutorials/old_folder/info.rehu"), "new_name")
    assert model.path == renamed


@mark.parametrize(
    ("path", "expected"),
    [
        param("C:/tutorials/some_folder/info.rehu", "some_folder", id="info.rehu-uses-parent-dir"),
        param("C:/tutorials/my_tutorial.rehu", "my_tutorial", id="standalone-uses-file-stem"),
        param("C:/tutorials/some_folder/info.tc", "some_folder", id="info.tc-uses-parent-dir"),
        param("C:/tutorials/my_tutorial.tc", "my_tutorial", id="standalone-tc-uses-file-stem"),
    ],
)
def test_current_name_is_the_rename_target(path: str, expected: str) -> None:
    """``current_name`` is the folder name for a directory-scoped record, the file stem otherwise.

    A legacy ``info.tc`` is one of those (#250), so the name a rename suggestion offers to replace is the
    same one the tab shows and the same one :class:`~rehuco_core.RehuRenamer` would move.

    **Test steps:**

    * build a model over a document at ``path``
    * verify ``current_name`` is the expected rename-target name
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, Path(path)))

    assert model.current_name == expected


def test_current_name_is_empty_without_a_path(model: RehuDocumentModel) -> None:
    """A pathless document has no current name.

    **Test steps:**

    * read ``current_name`` off the pathless fixture model
    * verify it is empty
    """
    assert model.current_name == ""


def test_setting_title_emits_writes_through_and_dirties(model: RehuDocumentModel, document: RehuDocument) -> None:
    """Setting title emits its notify signal, writes through to the document, and marks dirty.

    **Test steps:**

    * bind the `title` field and connect to its notify signal
    * set ``model.title`` to a new value
    * verify the signal fired once with it, the document's primary source now holds it, and dirty is set
    """
    received: list[str] = []
    model.bind(Field[str]("title")).changed.connect(received.append)

    model.title = "New Title"

    assert received == ["New Title"]
    assert document.title == "New Title"
    assert model.dirty is True


def test_setting_publisher_and_url_write_through(model: RehuDocumentModel, document: RehuDocument) -> None:
    """Publisher and url setters write through to the document's primary source too.

    **Test steps:**

    * set ``model.publisher`` and ``model.url``
    * verify both land on the document's primary source
    """
    model.publisher = "New Publisher"
    model.url = "https://changed.example"

    assert document.publisher == "New Publisher"
    assert document.url == "https://changed.example"


def test_model_seeds_released_from_the_document(document: RehuDocument) -> None:
    """The ``released`` field seeds from the document's top-level value, without dirtying.

    **Test steps:**

    * set ``released`` directly on the document, then construct a fresh model over it
    * verify the model mirrors it and is clean
    """
    document.released = "2025-03"
    fresh_model = RehuDocumentModel(document)

    assert fresh_model.released == "2025-03"
    assert fresh_model.dirty is False


def test_model_seeds_released_none_when_absent(model: RehuDocumentModel) -> None:
    """``released`` seeds ``None`` (not a coerced empty string) when the document has no value for it
    ([[field-schema#deferred-items]]).

    **Test steps:**

    * read ``released`` off the shared fixture, which sets no ``released``
    * verify it is ``None``
    """
    assert model.released is None


def test_setting_released_writes_through_and_dirties(model: RehuDocumentModel, document: RehuDocument) -> None:
    """Setting ``released`` writes through to the document (not source-scoped) and marks dirty.

    **Test steps:**

    * set ``model.released``
    * verify it lands on the document directly, and the model is dirty
    """
    model.released = "2025-03-08"

    assert document.released == "2025-03-08"
    assert model.dirty is True


def test_setting_released_to_none_removes_it(model: RehuDocumentModel, document: RehuDocument) -> None:
    """Setting ``released`` to ``None`` removes the stored key rather than writing a JSON ``null``
    ([[field-schema#deferred-items]]).

    **Test steps:**

    * set ``model.released``, then set it back to ``None``
    * verify the document reads it back as ``None`` and holds no ``released`` key
    """
    model.released = "2025-03-08"

    model.released = None

    assert document.released is None
    assert "released" not in document.data["core"]


def test_model_seeds_description_from_the_document(document: RehuDocument) -> None:
    """The ``description`` field seeds from the document's top-level value, without dirtying.

    **Test steps:**

    * set ``description`` directly on the document, then construct a fresh model over it
    * verify the model mirrors it and is clean
    """
    document.description = "# Notes\n\nsome prose"
    fresh_model = RehuDocumentModel(document)

    assert fresh_model.description == "# Notes\n\nsome prose"
    assert fresh_model.dirty is False


def test_setting_description_writes_through_and_dirties(model: RehuDocumentModel, document: RehuDocument) -> None:
    """Setting ``description`` writes through to the document (top-level, not source-scoped) and dirties.

    **Test steps:**

    * set ``model.description``
    * verify it lands on the document directly, and the model is dirty
    """
    model.description = "edited prose"

    assert document.description == "edited prose"
    assert model.dirty is True


def test_model_seeds_hidden_images_from_the_document(document: RehuDocument) -> None:
    """The ``hidden_images`` field seeds from the document's top-level list, without dirtying.

    **Test steps:**

    * set ``hidden_images`` directly on the document, then construct a fresh model over it
    * verify the model mirrors it and is clean
    """
    document.hidden_images = ["info00.jpg"]
    fresh_model = RehuDocumentModel(document)

    assert fresh_model.hidden_images == ["info00.jpg"]
    assert fresh_model.dirty is False


def test_setting_hidden_images_writes_through_and_dirties(model: RehuDocumentModel, document: RehuDocument) -> None:
    """Setting ``hidden_images`` writes through to the document (top-level) and dirties.

    **Test steps:**

    * set ``model.hidden_images``
    * verify it lands on the document directly, and the model is dirty
    """
    model.hidden_images = ["info01.png"]

    assert document.hidden_images == ["info01.png"]
    assert model.dirty is True


# image_files() listing moved to rehuco_core.scan_rehu_screenshot_files -- see rehuco-core's test_rehu_screenshots.py


@mark.parametrize("attr", [param("original_size", id="original_size"), param("current_size", id="current_size")])
def test_model_seeds_size_fields_from_the_document(attr: str, document: RehuDocument) -> None:
    """``original_size``/``current_size`` seed from the document's top-level value, without dirtying.

    **Test steps:**

    * set ``attr`` directly on the document, then construct a fresh model over it
    * verify the model mirrors it and is clean
    """
    setattr(document, attr, 5368709120)
    fresh_model = RehuDocumentModel(document)

    assert getattr(fresh_model, attr) == 5368709120
    assert fresh_model.dirty is False


@mark.parametrize("attr", [param("original_size", id="original_size"), param("current_size", id="current_size")])
def test_model_seeds_size_fields_none_when_absent(attr: str, model: RehuDocumentModel) -> None:
    """``original_size``/``current_size`` seed ``None`` (not a coerced zero) when the document has no
    value for them ([[field-schema#deferred-items]]).

    **Test steps:**

    * read ``attr`` off the shared fixture, which sets neither
    * verify it is ``None``
    """
    assert getattr(model, attr) is None


@mark.parametrize("attr", [param("original_size", id="original_size"), param("current_size", id="current_size")])
def test_setting_a_size_field_writes_through_and_dirties(
    attr: str, model: RehuDocumentModel, document: RehuDocument
) -> None:
    """Setting ``original_size``/``current_size`` writes through to the document and marks dirty.

    **Test steps:**

    * set ``model.<attr>``
    * verify it lands on the document directly, and the model is dirty
    """
    setattr(model, attr, 5368709120)

    assert getattr(document, attr) == 5368709120
    assert model.dirty is True


@mark.parametrize("attr", [param("original_size", id="original_size"), param("current_size", id="current_size")])
def test_setting_a_size_field_to_none_removes_it(attr: str, model: RehuDocumentModel, document: RehuDocument) -> None:
    """Setting ``original_size``/``current_size`` to ``None`` removes the stored key rather than
    writing a JSON ``null`` ([[field-schema#deferred-items]]).

    **Test steps:**

    * set ``model.<attr>``, then set it back to ``None``
    * verify the document reads it back as ``None`` and holds no key for it
    """
    setattr(model, attr, 5368709120)

    setattr(model, attr, None)

    assert getattr(document, attr) is None
    assert attr not in document.data["core"]


def test_model_seeds_empty_lists_from_a_document_with_none(model: RehuDocumentModel) -> None:
    """A document with no list fields seeds the model's list fields to empty, without dirtying.

    **Test steps:**

    * construct a model over a document with no ``authors``/``advertised_tags``/``extra_tags``
    * verify each reads back as an empty list and the model is clean
    """
    assert model.authors == []
    assert model.advertised_tags == []
    assert model.extra_tags == []
    assert model.dirty is False


def test_model_seeds_list_fields_from_the_document() -> None:
    """The list fields seed from the document's top-level ``authors``/``advertised_tags``/``extra_tags``.

    **Test steps:**

    * construct a model over a document carrying all three lists
    * verify each field mirrors the stored value, and the model is clean
    """
    document = RehuDocument(
        {
            "type": "Tutorial",
            "authors": ["Author One"],
            "advertised_tags": ["scraped"],
            "extra_tags": ["personal"],
        }
    )
    model = RehuDocumentModel(document)

    assert model.authors == ["Author One"]
    assert model.advertised_tags == ["scraped"]
    assert model.extra_tags == ["personal"]
    assert model.dirty is False


def test_setting_authors_advertised_tags_extra_tags_write_through(
    model: RehuDocumentModel, document: RehuDocument
) -> None:
    """Setting authors/advertised_tags/extra_tags writes through to the document (not source-scoped) and dirties.

    **Test steps:**

    * set ``model.authors``, ``model.advertised_tags``, ``model.extra_tags``
    * verify all three land on the document directly, and the model is dirty
    """
    model.authors = ["New Author"]
    model.advertised_tags = ["new-tag"]
    model.extra_tags = ["extra"]

    assert document.authors == ["New Author"]
    assert document.advertised_tags == ["new-tag"]
    assert document.extra_tags == ["extra"]
    assert model.dirty is True


def test_model_seeds_a_mixed_authors_list_untouched() -> None:
    """A string/record ``authors`` mix seeds the model verbatim ([[field-schema#authors]]) -- a record
    entry is no longer flattened to a string.

    **Test steps:**

    * construct a model over a document whose ``authors`` mixes a string and a name+url record
    * verify the model mirrors both, record intact, without dirtying
    """
    document = RehuDocument({"type": "Tutorial", "authors": ["A", {"name": "B", "url": "https://b.example"}]})
    model = RehuDocumentModel(document)

    assert model.authors == ["A", {"name": "B", "url": "https://b.example"}]
    assert model.dirty is False


def test_editing_authors_preserves_another_entry_record(document: RehuDocument) -> None:
    """Editing one ``authors`` entry never shreds another entry's record ([[field-schema#authors]]).

    **Test steps:**

    * seed a document carrying a plain name plus a name+url record
    * set the model's ``authors`` to a new list keeping the record and changing the string entry
    * verify the document keeps the record as a record and takes the edited string
    """
    document.authors = ["Old Name", {"name": "Keep", "url": "https://keep.example"}]
    model = RehuDocumentModel(document)

    model.authors = ["New Name", *model.authors[1:]]

    assert document.authors == ["New Name", {"name": "Keep", "url": "https://keep.example"}]
    assert model.dirty is True


def test_setting_authors_writes_canonical_minimal_form(model: RehuDocumentModel, document: RehuDocument) -> None:
    """A name-only record set on the model is stored as a plain string; a record with a url stays a
    record -- canonical minimal form ([[field-schema#authors]]).

    **Test steps:**

    * set the model's ``authors`` to a name-only record and a name+url record
    * verify the document stores the first as a bare string and the second as a record
    """
    model.authors = [{"name": "Bare"}, {"name": "Linked", "url": "https://linked.example"}]

    assert document.authors == ["Bare", {"name": "Linked", "url": "https://linked.example"}]
    assert model.dirty is True


def test_setting_title_to_equal_value_is_a_no_op(model: RehuDocumentModel) -> None:
    """Assigning the current value emits nothing and leaves the model clean.

    **Test steps:**

    * bind the `title` field and connect to its notify signal, then assign ``title`` its current value
    * verify no signal fired and the model stayed clean (no spurious dirty)
    """
    received: list[str] = []
    model.bind(Field[str]("title")).changed.connect(received.append)

    model.title = "Foo"

    assert not received
    assert model.dirty is False


def test_setting_title_on_sourceless_document_creates_primary() -> None:
    """Editing a sourceless document creates a primary source through the view-model.

    **Test steps:**

    * build a model over a document with no ``sources``
    * set ``model.title``
    * verify the document gained a primary source holding the value
    """
    document = RehuDocument({"type": "Tutorial"})
    model = RehuDocumentModel(document)

    model.title = "Fresh"

    assert document.primary_source is not None
    assert document.title == "Fresh"


def test_save_writes_document_and_clears_dirty(
    mocker: MockerFixture, model: RehuDocumentModel, document: RehuDocument
) -> None:
    """save() calls the document's atomic save and clears the dirty flag.

    **Test steps:**

    * dirty the model with an edit
    * patch ``document.save``
    * call ``model.save()``
    * verify the document was saved and the model is clean again
    """
    save = mocker.patch.object(document, "save")

    model.title = "New Title"
    assert model.dirty is True

    model.save()

    save.assert_called_once_with()
    assert model.dirty is False


def test_revert_reseeds_from_a_reloaded_document_and_clears_dirty(
    mocker: MockerFixture, model: RehuDocumentModel, document: RehuDocument
) -> None:
    """revert() re-reads the document and reseeds every common-core field from it, then clears dirty.

    Picks up values the model never held before (neither the original seed nor the unsaved edit),
    proving it re-reads rather than just resetting to the last-loaded snapshot (#41). Changes every
    common-core field so each write-through handler's reverting-guard early-return actually runs
    (not just title's).

    **Test steps:**

    * make an unsaved edit, dirtying the model
    * mock ``document.reload`` to simulate an out-of-band on-disk change touching every field
    * call ``model.revert()``
    * verify every field reflects the *reloaded* value (not the edit, not the original) and dirty clears
    """
    model.title = "Unsaved Edit"
    assert model.dirty is True

    def fake_reload() -> None:
        core = document.data.setdefault("core", {})
        core["sources"] = [
            {
                "title": "Reloaded Title",
                "publisher": "Reloaded Publisher",
                "url": "https://reloaded.example",
                "primary": True,
            }
        ]
        core["authors"] = ["Reloaded Author"]
        core["released"] = "2030-01"
        core["original_size"] = 5368709120
        core["current_size"] = 1073741824
        core["advertised_tags"] = ["reloaded-tag"]
        core["extra_tags"] = ["reloaded-extra"]
        core["description"] = "# Reloaded\n\nprose"
        core["hidden_images"] = ["reloaded.jpg"]

    reload = mocker.patch.object(document, "reload", side_effect=fake_reload)

    model.revert()

    reload.assert_called_once_with()
    assert model.title == "Reloaded Title"
    assert model.publisher == "Reloaded Publisher"
    assert model.url == "https://reloaded.example"
    assert model.authors == ["Reloaded Author"]
    assert model.released == "2030-01"
    assert model.original_size == 5368709120
    assert model.current_size == 1073741824
    assert model.advertised_tags == ["reloaded-tag"]
    assert model.extra_tags == ["reloaded-extra"]
    assert model.description == "# Reloaded\n\nprose"
    assert model.hidden_images == ["reloaded.jpg"]
    assert model.dirty is False


def test_revert_recomputes_locked_from_the_reloaded_format_version(
    mocker: MockerFixture, model: RehuDocumentModel, document: RehuDocument
) -> None:
    """revert() recomputes :attr:`~RehuDocumentModel.locked` from the reloaded document's
    ``format_version``, picking up an out-of-band change to it just like any other field.

    **Test steps:**

    * start with a clean, unlocked model
    * mock ``document.reload`` to simulate the on-disk file now carrying a newer ``format_version``
    * call ``model.revert()``
    * verify the model is now locked
    """
    assert model.locked is False
    newer_version = CURRENT_FORMAT_VERSION + 1

    def fake_reload() -> None:
        document.data["format_version"] = newer_version

    mocker.patch.object(document, "reload", side_effect=fake_reload)

    model.revert()

    assert model.locked is True


def test_revert_is_the_fix_retry_loop_over_a_load_failure(mocker: MockerFixture) -> None:
    """revert() is the fix-retry loop for an unreadable file: reverting onto a still-broken file locks in
    place without throwing, and reverting once it reads cleanly drops the lock and seeds the fields
    ([[data-model#write-integrity]]).

    **Test steps:**

    * open a real document from a mocked file
    * make the file vanish, then revert -- verify no throw, model now locked ``MISSING``, not dirty
    * make the file read cleanly again, then revert -- verify the lock drops and fields seed
    """
    path = Path("/fake/info.rehu")
    mocker.patch.object(Path, "read_text", return_value=json.dumps({"core": {"type": "tutorial"}}))
    model = RehuDocumentModel(RehuDocument.load(path))
    assert model.locked is False

    mocker.patch.object(Path, "read_text", side_effect=FileNotFoundError("gone"))
    model.revert()  # must not raise
    assert model.locked is True
    assert [reason.kind for reason in model.lock_reasons] == [LockReasonKind.MISSING]
    assert model.dirty is False

    mocker.patch.object(
        Path,
        "read_text",
        return_value=json.dumps({"core": {"sources": [{"title": "Fixed", "primary": True}]}}),
    )
    model.revert()
    assert model.locked is False
    assert not model.lock_reasons
    assert model.title == "Fixed"


def test_revert_reseeds_type_fields_too(
    mocker: MockerFixture, model: RehuDocumentModel, document: RehuDocument
) -> None:
    """revert() also reseeds the type-field-backed scalars (bool/int) from the reloaded document.

    ``rating`` is per-user (#99), so the simulated on-disk state carries it where a real reload's
    migration would put it: under the block's ``users`` map, keyed by this document's username
    (``admin``, the default -- [[field-schema#per-user-shared]]).

    **Test steps:**

    * mock ``document.reload`` to simulate an on-disk rating change
    * call ``model.revert()``
    * verify ``model.rating`` reflects the reloaded value
    """

    def fake_reload() -> None:
        document.data["tutorial"] = {"users": {"admin": {"rating": -3}}}

    mocker.patch.object(document, "reload", side_effect=fake_reload)

    model.revert()

    assert model.rating == -3


def test_revert_reseeds_location_from_the_document_path(mocker: MockerFixture) -> None:
    """revert() reseeds ``location`` from the document's path, discarding an in-memory change.

    **Test steps:**

    * build a model over a document with a path, then change ``location`` in memory to something else
    * mock ``reload`` as a no-op (the path stays)
    * call ``model.revert()`` and verify ``location`` snaps back to the document's path
    """
    document = RehuDocument({"type": "Tutorial"}, Path("C:/tutorials/foo/info.rehu"))
    model = RehuDocumentModel(document)
    model.location = "C:/edited/elsewhere"
    mocker.patch.object(document, "reload")

    model.revert()

    assert model.location == "C:/tutorials/foo/info.rehu"


def test_revert_does_not_write_back_to_a_sourceless_document(mocker: MockerFixture) -> None:
    """Reseeding during revert is guarded: it doesn't synthesize a primary source on a document with none.

    Without the guard, reseeding empty ``title``/``publisher``/``url`` would still call each setter,
    which creates a flagged primary source on a document that has none -- an unwanted side effect of
    a pure reseed (#41).

    **Test steps:**

    * build a model over a document with no ``sources``, and mock ``reload`` as a no-op
    * call ``model.revert()``
    * verify no primary source was synthesized
    """
    document = RehuDocument({"type": "Tutorial"})
    model = RehuDocumentModel(document)
    mocker.patch.object(document, "reload")

    model.revert()

    assert document.sources == []


def test_revert_emits_reloaded_even_when_nothing_changed(mocker: MockerFixture) -> None:
    """Every revert emits ``reloaded``, including the reverting of a clean, unlocked document that moves
    no property at all -- the file seam is the event, not a value change (#174).

    ``dirty`` is already ``False``, ``path`` reseeds to the same path and ``lock_reasons`` to an equal
    list, so no notify signal fires; without ``reloaded`` nothing would tell a file-watching consumer
    that the bytes on disk may have just been edited out of band.

    **Test steps:**

    * build a clean, unlocked model over a document with a path, and mock ``reload`` as a no-op
    * record ``reloaded`` emissions, then revert
    * verify it fired once and the model stayed clean and unlocked
    """
    document = RehuDocument({"type": "Tutorial"}, Path("/fake/info.rehu"))
    model = RehuDocumentModel(document)
    mocker.patch.object(document, "reload")
    fired: list[None] = []
    model.reloaded.connect(lambda: fired.append(None))

    model.revert()

    assert fired == [None]
    assert model.dirty is False
    assert model.locked is False


def test_revert_without_a_path_propagates(model: RehuDocumentModel, document: RehuDocument) -> None:
    """revert() propagates the document's error when it has never been loaded from a file.

    **Test steps:**

    * call ``model.revert()`` on a document with no path
    * verify ``ValueError`` propagates
    """
    assert document.path is None
    with raises(ValueError, match="no path to reload from"):
        model.revert()


def test_convert_replaces_the_document_reseeds_and_unlocks(mocker: MockerFixture) -> None:
    """convert() adopts ``convert_tc``'s result as the wrapped document, reseeds every field, clears
    dirty, and drops locked to ``False``.

    **Test steps:**

    * build a model over a legacy ``.tc``-backed document
    * mock ``convert_tc`` to return a fresh, unlocked document with a different title
    * call ``model.convert(keep_backups=True)``
    * verify the model now reflects the fresh document, and is unlocked and clean
    """
    tc_document = RehuDocument(
        {"type": "Tutorial", "sources": [{"title": "Old Title", "primary": True}]},
        Path("/fake/info.tc"),
        legacy_tc=True,
    )
    model = RehuDocumentModel(tc_document)
    assert model.locked is True

    converted = RehuDocument(
        {"type": "Tutorial", "sources": [{"title": "New Title", "primary": True}]}, Path("/fake/info.rehu")
    )
    mocker.patch("rehuco_agent.documents.rehu_document_model.convert_tc", return_value=converted)

    model.convert(keep_backups=True)

    assert model.document is converted
    assert model.title == "New Title"
    assert model.dirty is False
    assert model.locked is False


def test_convert_emits_reloaded(mocker: MockerFixture) -> None:
    """convert() emits ``reloaded`` too -- it replaces the file the model stands for, the other half of
    the file seam ``revert`` raises (#174).

    **Test steps:**

    * build a model over a legacy ``.tc``-backed document, with ``convert_tc`` mocked to a fresh document
    * record ``reloaded`` emissions, then convert
    * verify it fired once
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, Path("/fake/info.tc"), legacy_tc=True))
    mocker.patch(
        "rehuco_agent.documents.rehu_document_model.convert_tc",
        return_value=RehuDocument({"type": "Tutorial"}, Path("/fake/info.rehu")),
    )
    fired: list[None] = []
    model.reloaded.connect(lambda: fired.append(None))

    model.convert(keep_backups=True)

    assert fired == [None]


def test_convert_failure_does_not_emit_reloaded(mocker: MockerFixture) -> None:
    """A ``convert_tc`` that raises leaves the file seam uncrossed, so no ``reloaded`` fires and a
    consumer never re-reads for a conversion that didn't happen (#174).

    **Test steps:**

    * build a model over a legacy ``.tc``-backed document, with ``convert_tc`` raising ``FileExistsError``
    * record ``reloaded`` emissions, then call convert and let the error propagate
    * verify nothing fired
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, Path("/fake/info.tc"), legacy_tc=True))
    mocker.patch(
        "rehuco_agent.documents.rehu_document_model.convert_tc", side_effect=FileExistsError("already converted")
    )
    fired: list[None] = []
    model.reloaded.connect(lambda: fired.append(None))

    with raises(FileExistsError):
        model.convert(keep_backups=True)

    assert not fired


def test_convert_passes_keep_backups_and_overwrite_through(mocker: MockerFixture) -> None:
    """convert() forwards this document's path, keyword arguments, and username to ``convert_tc``.

    The username is the wrapped document's **own** -- the identity it was opened with (#99), so
    the conversion files the imported per-user flags under the same owner
    ([[field-schema#per-user-shared]]), not whatever the identity setting says by then.

    **Test steps:**

    * build a model over a legacy ``.tc``-backed document at a known path, opened as ``alice``
    * mock ``convert_tc``
    * call ``model.convert`` with specific ``keep_backups``/``overwrite`` values
    * verify ``convert_tc`` was called with the document's path, those exact values, and ``alice``
    """
    tc_path = Path("/fake/info.tc")
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, tc_path, legacy_tc=True, username="alice"))
    mock_convert = mocker.patch(
        "rehuco_agent.documents.rehu_document_model.convert_tc",
        return_value=RehuDocument({"type": "Tutorial"}, tc_path.with_suffix(".rehu")),
    )

    model.convert(keep_backups=False, overwrite=True)

    mock_convert.assert_called_once_with(
        tc_path,
        keep_backups=False,
        overwrite=True,
        username="alice",
        excluded_patterns=EXCLUDED_FILE_PATTERNS,
        legacy_screenshot_rules=LEGACY_SCREENSHOT_RULES,
    )


def test_convert_raises_for_a_non_legacy_document(mocker: MockerFixture, model: RehuDocumentModel) -> None:
    """convert() refuses to run on a document that isn't a legacy ``.tc`` mapping.

    **Test steps:**

    * mock ``convert_tc``
    * call ``model.convert()`` on the sample (non-legacy) model
    * verify ``ValueError`` and that ``convert_tc`` was never called
    """
    mock_convert = mocker.patch("rehuco_agent.documents.rehu_document_model.convert_tc")

    with raises(ValueError, match="legacy .tc"):
        model.convert(keep_backups=True)

    mock_convert.assert_not_called()


def test_convert_without_a_path_raises(mocker: MockerFixture) -> None:
    """convert() refuses to run on a legacy document that was never loaded from a file.

    **Test steps:**

    * build a model over a legacy ``.tc``-backed document with no path
    * call ``model.convert()``
    * verify ``ValueError``
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, legacy_tc=True))
    mock_convert = mocker.patch("rehuco_agent.documents.rehu_document_model.convert_tc")

    with raises(ValueError, match="no path to convert"):
        model.convert(keep_backups=True)

    mock_convert.assert_not_called()


def test_convert_failure_leaves_the_model_completely_untouched(mocker: MockerFixture) -> None:
    """A failure from ``convert_tc`` propagates and leaves ``document``/``locked``/``dirty`` exactly
    as they were before the call.

    **Test steps:**

    * build a model over a legacy ``.tc``-backed document
    * mock ``convert_tc`` to raise ``FileExistsError``
    * call ``model.convert()``
    * verify the exception propagates and the model still wraps the original document, still locked
    """
    tc_document = RehuDocument({"type": "Tutorial"}, Path("/fake/info.tc"), legacy_tc=True)
    model = RehuDocumentModel(tc_document)
    mocker.patch("rehuco_agent.documents.rehu_document_model.convert_tc", side_effect=FileExistsError("stale backup"))

    with raises(FileExistsError):
        model.convert(keep_backups=True)

    assert model.document is tc_document
    assert model.locked is True


def test_image_scanner_lists_tc_screenshots_for_a_legacy_document() -> None:
    """A model over a legacy ``.tc``-backed document scans with the tc screenshot lister.

    **Test steps:**

    * construct a model over a document with ``legacy_tc=True``
    * verify ``image_scanner`` is a ``RehuDocumentImageScanner`` over ``scan_tc_screenshot_files``
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, legacy_tc=True))
    assert isinstance(model.image_scanner, RehuDocumentImageScanner)
    assert lister_of(model.image_scanner) is scan_tc_screenshot_files


def test_image_scanner_lists_rehu_screenshots_for_a_normal_document(model: RehuDocumentModel) -> None:
    """A model over a normal (non-legacy) document scans with the rehu screenshot lister.

    **Test steps:**

    * read ``image_scanner`` off the shared (non-legacy) fixture
    * verify it is a ``RehuDocumentImageScanner`` over ``scan_rehu_screenshot_files``
    """
    assert isinstance(model.image_scanner, RehuDocumentImageScanner)
    assert lister_of(model.image_scanner) is scan_rehu_screenshot_files


def test_convert_reassigns_a_fresh_rehu_scanner(mocker: MockerFixture) -> None:
    """``convert()`` reassigns ``image_scanner`` to a **new** ``RehuDocumentImageScanner`` over the rehu lister,
    never derived from whatever scanner was already there.

    **Test steps:**

    * build a model over a legacy ``.tc``-backed document and record its original scanner
    * mock ``convert_tc`` to return a fresh, unlocked document
    * call ``model.convert()``
    * verify ``image_scanner`` is now a different ``RehuDocumentImageScanner`` over ``scan_rehu_screenshot_files``
    """
    tc_document = RehuDocument({"type": "Tutorial"}, Path("/fake/info.tc"), legacy_tc=True)
    model = RehuDocumentModel(tc_document)
    original_scanner = model.image_scanner
    mocker.patch(
        "rehuco_agent.documents.rehu_document_model.convert_tc",
        return_value=RehuDocument({"type": "Tutorial"}, Path("/fake/info.rehu")),
    )

    model.convert(keep_backups=True)

    assert isinstance(model.image_scanner, RehuDocumentImageScanner)
    assert lister_of(model.image_scanner) is scan_rehu_screenshot_files
    assert model.image_scanner is not original_scanner


def test_revert_conversion_adopts_the_restored_tc_in_place(mocker: MockerFixture) -> None:
    """``revert_conversion()`` is ``convert()``'s exact mirror: the same dock keeps showing the same
    resource, now a locked legacy ``.tc`` again, with no reopen round-trip (#193).

    **Test steps:**

    * build a model over a converted ``.rehu``
    * mock the core revert to report the restored ``.tc``, and ``load_tc`` to a legacy document
    * call ``model.revert_conversion()``
    * verify the model now stands for the ``.tc``, locked and clean, with a fresh tc scanner
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, Path("/fake/info.rehu")))
    original_scanner = model.image_scanner
    mocker.patch(
        "rehuco_agent.documents.rehu_document_model.revert_conversion",
        return_value=backups_restoring(Path("/fake/info.tc")),
    )
    restored = RehuDocument(
        {"type": "Tutorial", "sources": [{"title": "Legacy Title", "primary": True}]},
        Path("/fake/info.tc"),
        legacy_tc=True,
    )
    mocker.patch("rehuco_agent.documents.rehu_document_model.load_tc", return_value=restored)

    model.revert_conversion()

    assert model.document is restored
    assert model.path == Path("/fake/info.tc")
    assert model.title == "Legacy Title"
    assert model.dirty is False
    assert model.locked is True
    assert isinstance(model.image_scanner, RehuDocumentImageScanner)
    assert lister_of(model.image_scanner) is scan_tc_screenshot_files
    assert model.image_scanner is not original_scanner


def test_revert_conversion_reads_the_restored_tc_under_the_unknown_identity(mocker: MockerFixture) -> None:
    """A revert puts back exactly the file that was there before, whose per-user flags were not set by
    this install's identity -- the same rule every ``.tc`` open follows (#109), and the same **configured**
    name (#246): a customized unknown-username must give the adopted tab the per-user state a
    close-and-reopen of the identical file would.

    **Test steps:**

    * configure a custom unknown username, then revert a conversion with ``load_tc`` mocked
    * verify it was handed the configured name, not the built-in default
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, Path("/fake/info.rehu")))
    mocker.patch(
        "rehuco_agent.documents.rehu_document_model.revert_conversion",
        return_value=backups_restoring(Path("/fake/info.tc")),
    )
    identity = mocker.patch("rehuco_agent.documents.rehu_document_model.shared_identity_settings")
    identity.return_value.unknown_username = "guest"
    load = mocker.patch(
        "rehuco_agent.documents.rehu_document_model.load_tc",
        return_value=RehuDocument({"type": "Tutorial"}, Path("/fake/info.tc"), legacy_tc=True),
    )

    model.revert_conversion()

    load.assert_called_once_with(Path("/fake/info.tc"), username="guest")


def test_revert_conversion_emits_the_file_seam_and_rebuilds_the_form(mocker: MockerFixture) -> None:
    """It replaces the file the model stands for, and adopts one that may have diverged -- so it raises
    both ``reloaded`` and ``active_block_changed`` (#174, #83).

    **Test steps:**

    * record both signals, then revert a conversion
    * verify each fired once
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, Path("/fake/info.rehu")))
    mocker.patch(
        "rehuco_agent.documents.rehu_document_model.revert_conversion",
        return_value=backups_restoring(Path("/fake/info.tc")),
    )
    mocker.patch(
        "rehuco_agent.documents.rehu_document_model.load_tc",
        return_value=RehuDocument({"type": "Tutorial"}, Path("/fake/info.tc"), legacy_tc=True),
    )
    reloaded: list[None] = []
    rebuilt: list[None] = []
    model.reloaded.connect(lambda: reloaded.append(None))
    model.active_block_changed.connect(lambda: rebuilt.append(None))

    model.revert_conversion()

    assert reloaded == [None]
    assert rebuilt == [None]


def test_revert_conversion_refusal_leaves_the_model_untouched(mocker: MockerFixture) -> None:
    """The core operation refuses rather than half-reverts, so a refusal must leave this model standing
    for exactly the document it was.

    **Test steps:**

    * make the core revert raise, and record ``reloaded``
    * verify the error propagates, the document is unchanged, and no seam was crossed
    """
    document = RehuDocument({"type": "Tutorial"}, Path("/fake/info.rehu"))
    model = RehuDocumentModel(document)
    mocker.patch(
        "rehuco_agent.documents.rehu_document_model.revert_conversion",
        side_effect=FileNotFoundError("/fake/info.tc.orig"),
    )
    fired: list[None] = []
    model.reloaded.connect(lambda: fired.append(None))

    with raises(FileNotFoundError):
        model.revert_conversion()

    assert model.document is document
    assert model.path == Path("/fake/info.rehu")
    assert not fired


def test_revert_conversion_without_a_path_raises(mocker: MockerFixture) -> None:
    """A never-saved document has no conversion to undo, and nothing on disk to ask about.

    **Test steps:**

    * call ``revert_conversion`` on a path-less document
    * verify ``ValueError``, and that the core operation was never reached
    """
    revert = mocker.patch("rehuco_agent.documents.rehu_document_model.revert_conversion")
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}))

    with raises(ValueError, match="no conversion to revert"):
        model.revert_conversion()

    revert.assert_not_called()


def test_adopt_reverted_conversion_adopts_the_restored_tc_in_place(mocker: MockerFixture) -> None:
    """``adopt_reverted_conversion()`` catches up with a revert that already ran elsewhere -- the bulk
    conversion-backups manager's ``RevertConversionJob`` (#246) -- ending in the same state
    :meth:`revert_conversion` would, but without redoing (or failing) the file-system work a job has
    already finished.

    **Test steps:**

    * build a model over a converted ``.rehu``
    * mock ``load_tc`` to the restored legacy document; leave the core ``revert_conversion`` unmocked
    * call ``model.adopt_reverted_conversion()``
    * verify the model now stands for the ``.tc``, locked and clean, with a fresh tc scanner, and that
      the core file-system revert was never reached
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, Path("/fake/info.rehu")))
    original_scanner = model.image_scanner
    core_revert = mocker.patch("rehuco_agent.documents.rehu_document_model.revert_conversion")
    restored = RehuDocument(
        {"type": "Tutorial", "sources": [{"title": "Legacy Title", "primary": True}]},
        Path("/fake/info.tc"),
        legacy_tc=True,
    )
    mocker.patch("rehuco_agent.documents.rehu_document_model.load_tc", return_value=restored)

    model.adopt_reverted_conversion()

    core_revert.assert_not_called()
    assert model.document is restored
    assert model.path == Path("/fake/info.tc")
    assert model.title == "Legacy Title"
    assert model.dirty is False
    assert model.locked is True
    assert isinstance(model.image_scanner, RehuDocumentImageScanner)
    assert lister_of(model.image_scanner) is scan_tc_screenshot_files
    assert model.image_scanner is not original_scanner


def test_adopt_reverted_conversion_reads_the_restored_tc_under_the_unknown_identity(mocker: MockerFixture) -> None:
    """Same identity rule as :meth:`revert_conversion` (#109), same configured name (#246): the restored
    ``.tc``'s per-user flags were not set by this install's identity, and the adopted tab must match what
    a close-and-reopen of the identical file would show.

    **Test steps:**

    * configure a custom unknown username, then adopt a reverted conversion with ``load_tc`` mocked
    * verify it was handed the configured name, not the built-in default
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, Path("/fake/info.rehu")))
    identity = mocker.patch("rehuco_agent.documents.rehu_document_model.shared_identity_settings")
    identity.return_value.unknown_username = "guest"
    load = mocker.patch(
        "rehuco_agent.documents.rehu_document_model.load_tc",
        return_value=RehuDocument({"type": "Tutorial"}, Path("/fake/info.tc"), legacy_tc=True),
    )

    model.adopt_reverted_conversion()

    load.assert_called_once_with(Path("/fake/info.tc"), username="guest")


def test_adopt_reverted_conversion_emits_the_file_seam_and_rebuilds_the_form(mocker: MockerFixture) -> None:
    """It replaces the file the model stands for, so it raises both ``reloaded`` and
    ``active_block_changed``, same as :meth:`revert_conversion` (#174, #83).

    **Test steps:**

    * record both signals, then adopt a reverted conversion
    * verify each fired once
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, Path("/fake/info.rehu")))
    mocker.patch(
        "rehuco_agent.documents.rehu_document_model.load_tc",
        return_value=RehuDocument({"type": "Tutorial"}, Path("/fake/info.tc"), legacy_tc=True),
    )
    reloaded: list[None] = []
    rebuilt: list[None] = []
    model.reloaded.connect(lambda: reloaded.append(None))
    model.active_block_changed.connect(lambda: rebuilt.append(None))

    model.adopt_reverted_conversion()

    assert reloaded == [None]
    assert rebuilt == [None]


def test_adopt_reverted_conversion_without_a_restored_tc_raises(mocker: MockerFixture) -> None:
    """Nothing to adopt when the revert this was meant to catch up with never actually happened.

    **Test steps:**

    * make ``load_tc`` raise as it would for a missing file
    * call ``adopt_reverted_conversion``
    * verify the error propagates and the model is left untouched
    """
    document = RehuDocument({"type": "Tutorial"}, Path("/fake/info.rehu"))
    model = RehuDocumentModel(document)
    mocker.patch(
        "rehuco_agent.documents.rehu_document_model.load_tc",
        side_effect=FileNotFoundError("/fake/info.tc"),
    )
    fired: list[None] = []
    model.reloaded.connect(lambda: fired.append(None))

    with raises(FileNotFoundError):
        model.adopt_reverted_conversion()

    assert model.document is document
    assert model.path == Path("/fake/info.rehu")
    assert not fired


def test_adopt_reverted_conversion_without_a_path_raises(mocker: MockerFixture) -> None:
    """A never-saved document has no conversion to catch up with.

    **Test steps:**

    * call ``adopt_reverted_conversion`` on a path-less document
    * verify ``ValueError``, and that ``load_tc`` was never reached
    """
    load = mocker.patch("rehuco_agent.documents.rehu_document_model.load_tc")
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}))

    with raises(ValueError, match="no conversion to adopt"):
        model.adopt_reverted_conversion()

    load.assert_not_called()


def test_revert_leaves_the_image_scanner_untouched(mocker: MockerFixture) -> None:
    """``revert()`` never changes ``legacy_tc``-ness, so it leaves ``image_scanner`` untouched.

    **Test steps:**

    * build a model over a normal document and record its scanner
    * mock ``document.reload`` as a no-op
    * call ``model.revert()``
    * verify ``image_scanner`` is the exact same instance
    """
    document = RehuDocument({"type": "Tutorial"}, Path("/fake/info.rehu"))
    model = RehuDocumentModel(document)
    original_scanner = model.image_scanner
    mocker.patch.object(document, "reload")

    model.revert()

    assert model.image_scanner is original_scanner


def test_document_exposes_the_wrapped_document(model: RehuDocumentModel, document: RehuDocument) -> None:
    """The model exposes the wrapped document by identity.

    **Test steps:**

    * read ``model.document``
    * verify it is the exact document instance the model was constructed with
    """
    assert model.document is document


def test_sources_exposes_the_document_list(model: RehuDocumentModel, document: RehuDocument) -> None:
    """The model exposes the document's ``sources`` list explicitly (the list-aware seam).

    **Test steps:**

    * read ``model.sources``
    * verify it is the document's ``sources`` list (multi-source editor plugs in here)
    """
    assert model.sources == document.sources


def test_path_passes_through_to_the_document() -> None:
    """The model surfaces the document's path for the dock shell's reuse-by-path.

    **Test steps:**

    * build a model over a document carrying a path
    * verify ``model.path`` matches the document's path
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, Path("/fake/info.rehu")))

    assert model.path == Path("/fake/info.rehu")


def test_label_is_empty_for_a_document_with_no_path() -> None:
    """A document with no path yet has an empty label.

    **Test steps:**

    * build a model over a pathless document
    * verify ``model.label`` is an empty string
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}))

    assert model.label == ""


def test_label_uses_the_parent_directory_name_for_info_rehu() -> None:
    """An ``info.rehu`` document's label is its parent directory's name, trailing-slashed.

    **Test steps:**

    * build a model over an ``info.rehu`` path
    * verify ``model.label`` is the parent directory's name plus a trailing slash
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, Path("/fake/sculpting/info.rehu")))

    assert model.label == "sculpting/"


def test_label_uses_the_bare_filename_for_a_non_info_rehu() -> None:
    """A regular (non-``info.rehu``) document's label is its own bare filename.

    **Test steps:**

    * build a model over a non-``info.rehu`` path
    * verify ``model.label`` is that file's bare name
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, Path("/fake/sculpting/sculpting.rehu")))

    assert model.label == "sculpting.rehu"


def test_path_label_uses_the_parent_directory_name_for_info_rehu() -> None:
    """`path_label` -- the shared rule `label` and the recents menu both use (#117) -- labels an
    ``info.rehu`` path by its parent directory's name, trailing-slashed.

    **Test steps:**

    * call ``path_label`` on an ``info.rehu`` path
    * verify it returns the parent directory's name plus a trailing slash
    """
    assert path_label(Path("/fake/sculpting/info.rehu")) == "sculpting/"


def test_path_label_uses_the_bare_filename_for_a_non_info_rehu() -> None:
    """`path_label` labels a non-``info.rehu`` path by its own bare filename.

    **Test steps:**

    * call ``path_label`` on a non-``info.rehu`` path
    * verify it returns that file's bare name
    """
    assert path_label(Path("/fake/sculpting/sculpting.rehu")) == "sculpting.rehu"


def test_path_label_names_the_directory_for_a_legacy_info_tc() -> None:
    """`path_label` labels an ``info.tc`` by its folder too -- tc4 wrote one per resource directory (#250).

    Keying on ``info.rehu`` alone gave a catalog opened before conversion a tab strip reading ``info.tc``
    all the way across, with nothing to tell five documents apart -- which is the failure the label rule
    exists to prevent. A named ``foo.tc`` keeps its filename, the way ``foo.rehu`` does.

    **Test steps:**

    * call ``path_label`` on an ``info.tc`` path and on a named ``.tc``
    * verify the first names its folder and the second its own file
    """
    assert path_label(Path("/fake/sculpting/info.tc")) == "sculpting/"
    assert path_label(Path("/fake/sculpting/sculpting.tc")) == "sculpting.tc"


def test_bind_resolves_the_current_value_and_a_stable_changed_signal(model: RehuDocumentModel) -> None:
    """bind() resolves a field token into its current value and a stable (not fresh-per-call) signal.

    **Test steps:**

    * bind the same `title` field token twice
    * verify both bindings' values match `model.title` and their `changed` signal is the same object
    """
    first = model.bind(Field[str]("title"))
    second = model.bind(Field[str]("title"))

    assert first.value == model.title
    assert second.value == model.title
    assert first.changed is second.changed


def test_bind_set_value_writes_through_and_dirties(model: RehuDocumentModel, document: RehuDocument) -> None:
    """The binding's `set_value` writes through to the model (and so the document) and marks dirty.

    **Test steps:**

    * bind a `title` field token, then call the binding's `set_value` with a new value
    * verify `model.title` and the document both reflect it, and the model is dirty
    """
    binding = model.bind(Field[str]("title"))

    binding.set_value("New Title")

    assert model.title == "New Title"
    assert document.title == "New Title"
    assert model.dirty is True


def test_model_seeds_type_field_defaults_when_block_is_absent(model: RehuDocumentModel) -> None:
    """A document with no plugin block seeds the type-field-backed fields to their defaults, without dirtying.

    **Test steps:**

    * construct a model over a document with no ``tutorial`` block
    * verify ``complete`` defaults true, the other flags false, rating/current_count ``None``
      (absent, not a coerced zero -- [[field-schema#deferred-items]]), level empty, and it is clean
    """
    assert model.complete is True
    assert model.online is False
    assert model.favorite is False
    assert model.rating is None
    assert model.current_count is None
    assert model.level == []
    assert model.dirty is False


def test_model_seeds_type_field_values_from_the_document() -> None:
    """The type-field-backed fields seed from the document's ``type``-keyed plugin block.

    **Test steps:**

    * construct a model over a document whose ``tutorial`` block carries flags and a rating
    * verify each field mirrors the stored value, and the model is clean
    """
    document = RehuDocument({"type": "Tutorial", "tutorial": {"complete": False, "online": True, "rating": -2}})
    model = RehuDocumentModel(document)

    assert model.complete is False
    assert model.online is True
    assert model.rating == -2
    assert model.dirty is False


def test_model_coerces_malformed_type_field_values_to_defaults() -> None:
    """Malformed type-field values fall back to ``None`` -- absent and malformed both display as
    unset ([[field-schema#deferred-items]]) -- rather than crashing ([[data-model#write-integrity]]).

    **Test steps:**

    * construct a model over a document whose block holds a non-int rating and a null current_count
    * verify both coerce to ``None``
    """
    document = RehuDocument({"type": "ReferenceImages", "reference_images": {"rating": "junk", "current_count": None}})
    model = RehuDocumentModel(document)

    assert model.rating is None
    assert model.current_count is None


def test_setting_a_type_field_flag_writes_through_and_dirties(model: RehuDocumentModel, document: RehuDocument) -> None:
    """Setting a type-field-backed flag writes through to the document's plugin block and marks dirty.

    **Test steps:**

    * set ``model.complete`` false
    * verify the document's ``tutorial`` block now holds it, and the model is dirty
    """
    model.complete = False

    assert document.active_field("complete") is False
    assert model.dirty is True


def test_setting_rating_writes_through_to_the_type_fields(model: RehuDocumentModel, document: RehuDocument) -> None:
    """Setting the rating writes through to the document's plugin block -- into the ``users`` map,
    since ``rating`` is per-user ([[field-schema#per-user-shared]], #99), never inline.

    **Test steps:**

    * set ``model.rating`` to a negative value
    * verify the document's ``tutorial`` block holds it under this user, and not inline
    """
    model.rating = -4

    assert document.active_user_field("rating") == -4
    assert document.active_field("rating") is None


def test_setting_rating_to_none_removes_the_key_not_writes_null(
    model: RehuDocumentModel, document: RehuDocument
) -> None:
    """Setting ``rating`` to ``None`` **removes** the key from the ``users`` map rather than writing a
    JSON ``null`` -- the generic ``set_active_user_field`` this type-field write path uses has no
    such rule of its own, unlike `RehuDocument`'s own typed scalar properties
    ([[field-schema#deferred-items]]).

    **Test steps:**

    * set ``model.rating``, then set it back to ``None``
    * verify the per-user submap no longer holds the ``rating`` key at all
    """
    model.rating = -4

    model.rating = None

    assert document.active_user_field("rating") is None
    assert "rating" not in document.data["tutorial"]["users"][document.username]


def test_setting_current_count_round_trips_a_zero_and_clears_to_an_absent_key() -> None:
    """``current_count`` writes a genuine ``0`` through as ``0``, and clearing it **removes** the key
    rather than writing a JSON ``null`` ([[field-schema#deferred-items]], #196).

    The distinction the field exists to keep: an archive scanned and found to hold no content images is
    a stored ``0``, while one never scanned carries no key at all -- so the two are not told apart by a
    falsy read, and the editor's clear must land on the second rather than collapsing into the first.
    Inline in the block, not under ``users``: the count is a property of the resource, not of a reader
    ([[field-schema#per-user-shared]]).

    **Test steps:**

    * over a ReferenceImages document, set ``current_count`` to ``0``
    * verify the block stores the zero inline
    * clear it to ``None`` and verify the key is gone from the block
    """
    document = RehuDocument({"type": "ReferenceImages"})
    model = RehuDocumentModel(document)

    model.current_count = 0

    assert document.active_field("current_count") == 0
    assert document.active_user_field("current_count") is None

    model.current_count = None

    assert "current_count" not in document.active_block


def test_model_seeds_the_advertised_count_as_the_text_it_is() -> None:
    """``advertised_count`` seeds from the block as the string it is stored as -- an open-ended ``500+``
    reaches the editor intact rather than as a number ([[field-schema#field-types]], #198).

    **Test steps:**

    * construct a model over a ReferenceImages document claiming ``500+``
    * verify the model reads exactly that, and is clean
    """
    document = RehuDocument({"type": "ReferenceImages", "reference_images": {"advertised_count": "500+"}})
    model = RehuDocumentModel(document)

    assert model.advertised_count == "500+"
    assert model.dirty is False


def test_model_coerces_a_non_string_advertised_count_to_none() -> None:
    """A claim stored as anything but text reads as unset, the same absent-or-malformed treatment the
    optional integers get ([[field-schema#deferred-items]], [[data-model#write-integrity]]).

    **Test steps:**

    * construct a model over a block whose ``advertised_count`` is a number, and one where it is absent
    * verify both read ``None``
    """
    malformed = RehuDocumentModel(
        RehuDocument({"type": "ReferenceImages", "reference_images": {"advertised_count": 500}})
    )
    absent = RehuDocumentModel(RehuDocument({"type": "ReferenceImages"}))

    assert malformed.advertised_count is None
    assert absent.advertised_count is None


def test_setting_the_advertised_count_writes_through_and_clears_to_an_absent_key() -> None:
    """A claim writes through inline to the block, and clearing it **removes** the key rather than
    storing an empty string ([[field-schema#deferred-items]], #198).

    Inline, not under ``users``: what a pack claims about itself is a property of the resource, not of
    whoever read the listing ([[field-schema#per-user-shared]]).

    **Test steps:**

    * over a ReferenceImages document, set ``advertised_count`` to ``500+``
    * verify the block stores the text inline and the model went dirty
    * clear it to ``None`` and verify the key is gone from the block
    """
    document = RehuDocument({"type": "ReferenceImages"})
    model = RehuDocumentModel(document)

    model.advertised_count = "500+"

    assert document.active_field("advertised_count") == "500+"
    assert document.active_user_field("advertised_count") is None
    assert model.dirty is True

    model.advertised_count = None

    assert "advertised_count" not in document.active_block


def test_model_seeds_per_user_fields_from_the_users_map(document: RehuDocument) -> None:
    """The per-user fields seed from the active block's ``users`` map, not from inline block keys
    ([[field-schema#per-user-shared]], #99).

    **Test steps:**

    * file every per-user field under the document's user via ``set_active_user_field``
    * construct a model and verify each field mirrors the stored value, with the model clean
    """
    document.set_active_user_field("viewed", True)
    document.set_active_user_field("todo", True)
    document.set_active_user_field("keep", True)
    document.set_active_user_field("favorite", True)
    document.set_active_user_field("rating", 3)

    model = RehuDocumentModel(document)

    assert model.viewed is True
    assert model.todo is True
    assert model.keep is True
    assert model.favorite is True
    assert model.rating == 3
    assert model.dirty is False


@mark.parametrize("name", ["viewed", "todo", "keep", "favorite"])
def test_setting_a_per_user_flag_writes_through_to_the_users_map(
    model: RehuDocumentModel, document: RehuDocument, name: str
) -> None:
    """Setting a per-user flag files it in the block's ``users`` map, never inline
    ([[field-schema#per-user-shared]], #99), and marks the model dirty.

    **Test steps:**

    * set the flag on the model
    * verify the document holds it through the per-user accessor and not the shared one
    """
    setattr(model, name, True)

    assert document.active_user_field(name) is True
    assert document.active_field(name) is None
    assert model.dirty is True


def test_per_user_state_files_under_the_documents_own_username() -> None:
    """A per-user write lands under the username the document was **constructed** with -- the
    configured identity at open time ([[field-schema#per-user-shared]], #99).

    **Test steps:**

    * build a model over a document opened as ``alice``
    * set ``favorite`` and verify it sits at ``tutorial.users.alice``, and reads back per-user
    """
    document = RehuDocument({"type": "Tutorial"}, username="alice")
    model = RehuDocumentModel(document)

    model.favorite = True

    assert document.data["tutorial"]["users"]["alice"]["favorite"] is True
    assert document.active_user_field("favorite") is True


def test_model_seeds_duration_fields_none_when_block_is_absent(model: RehuDocumentModel) -> None:
    """The ``*_duration`` fields seed ``None`` (not a coerced zero) when the document has no plugin
    block for them ([[field-schema#deferred-items]]).

    **Test steps:**

    * read the three duration fields off the shared fixture, which has no ``tutorial`` block
    * verify all three are ``None``
    """
    assert model.original_duration is None
    assert model.current_duration is None
    assert model.advertised_duration is None


def test_model_seeds_duration_fields_from_the_document() -> None:
    """The ``*_duration`` fields seed from the document's ``type``-keyed plugin block.

    **Test steps:**

    * construct a model over a document whose ``tutorial`` block carries all three duration fields
    * verify each field mirrors the stored value
    """
    document = RehuDocument(
        {
            "type": "Tutorial",
            "tutorial": {"original_duration": 8100, "current_duration": 4050, "advertised_duration": 7800},
        }
    )
    model = RehuDocumentModel(document)

    assert model.original_duration == 8100
    assert model.current_duration == 4050
    assert model.advertised_duration == 7800


def test_setting_duration_fields_writes_through_to_the_type_fields(
    model: RehuDocumentModel, document: RehuDocument
) -> None:
    """Setting a ``*_duration`` field writes through to the document's plugin block.

    **Test steps:**

    * set ``model.original_duration``
    * verify the document's ``tutorial`` block holds it
    """
    model.original_duration = 8100

    assert document.active_field("original_duration") == 8100


def test_setting_a_duration_field_to_none_removes_the_key_not_writes_null(
    model: RehuDocumentModel, document: RehuDocument
) -> None:
    """Setting ``original_duration`` to ``None`` **removes** the key from the active block rather than
    writing a JSON ``null`` -- the generic ``set_active_field`` this (shared, not per-user) type-field
    write path uses has no such rule of its own, unlike `RehuDocument`'s own typed scalar properties
    ([[field-schema#deferred-items]]).

    **Test steps:**

    * set ``model.original_duration``, then set it back to ``None``
    * verify the active block no longer holds the key at all
    """
    model.original_duration = 8100

    model.original_duration = None

    assert document.active_field("original_duration") is None
    assert "original_duration" not in document.active_block


def test_model_seeds_level_from_the_document() -> None:
    """``level`` seeds from the document's ``type``-keyed plugin block as a list.

    **Test steps:**

    * construct a model over a document whose ``tutorial`` block carries a multi-valued ``level``
    * verify the model mirrors it
    """
    document = RehuDocument({"type": "Tutorial", "tutorial": {"level": ["beginner", "intermediate"]}})
    model = RehuDocumentModel(document)

    assert model.level == ["beginner", "intermediate"]


def test_model_coerces_malformed_level_to_the_default() -> None:
    """A non-list or mixed-type ``level`` coerces to the default, dropping only the bad items
    ([[data-model#write-integrity]]).

    **Test steps:**

    * construct a model whose ``tutorial`` block holds a non-list ``level``
    * verify it coerces to empty rather than crashing
    * construct another model whose ``level`` list mixes strings with a non-string item
    * verify only the string items survive
    """
    non_list_document = RehuDocument({"type": "Tutorial", "tutorial": {"level": "beginner"}})
    assert RehuDocumentModel(non_list_document).level == []

    mixed_document = RehuDocument({"type": "Tutorial", "tutorial": {"level": ["beginner", 3]}})
    assert RehuDocumentModel(mixed_document).level == ["beginner"]


def test_setting_level_writes_through_to_the_type_fields(model: RehuDocumentModel, document: RehuDocument) -> None:
    """Setting ``level`` writes through to the document's plugin block and marks dirty.

    **Test steps:**

    * set ``model.level`` to two values
    * verify the document's ``tutorial`` block holds them, and the model is dirty
    """
    model.level = ["advanced", "any"]

    assert document.active_field("level") == ["advanced", "any"]
    assert model.dirty is True


def test_create_new_without_a_path_is_clean() -> None:
    """``create_new`` with no path starts an empty, pathless, un-dirty model.

    **Test steps:**

    * call ``RehuDocumentModel.create_new()`` with no arguments
    * verify the document has no path and the model is not dirty
    """
    model = RehuDocumentModel.create_new()

    assert model.document.path is None
    assert model.dirty is False


def test_create_new_with_a_path_is_dirty_and_bound() -> None:
    """``create_new`` with a path binds the document to it and starts the model dirty.

    Nothing is written to disk by this call -- the document only gains a default save target
    (:meth:`RehuDocument.save`'s destination); dirty signals there are unsaved changes to prompt
    for (#43's directory-open-with-no-`info.rehu` flow).

    **Test steps:**

    * call ``RehuDocumentModel.create_new(path)``
    * verify the document's path matches, the model is dirty, and it is **not** locked (an empty
      dirty-editable document about to be written -- strictly distinct from a load failure's
      empty-locked stub bound to the same kind of path, [[data-model#write-integrity]])
    """
    path = Path("/fake/sculpting/info.rehu")

    model = RehuDocumentModel.create_new(path)

    assert model.document.path == path
    assert model.dirty is True
    assert model.locked is False
    assert not model.lock_reasons


def test_create_new_starts_not_saved_on_disk() -> None:
    """``create_new`` starts **not** :attr:`~RehuDocumentModel.saved_on_disk` -- with or without a path,
    the document has never been persisted, so there is nothing on disk to revert to (#147).

    **Test steps:**

    * call ``RehuDocumentModel.create_new`` with a path and without one
    * verify both report ``saved_on_disk`` False
    """
    assert RehuDocumentModel.create_new(Path("/fake/sculpting/info.rehu")).saved_on_disk is False
    assert RehuDocumentModel.create_new().saved_on_disk is False


def test_a_loaded_document_is_saved_on_disk(document: RehuDocument) -> None:
    """A document wrapped straight from a `RehuDocument` (a load, not ``create_new``) is
    ``saved_on_disk`` -- it stands for a file on disk, so its revert is the fix-retry loop (#147).

    **Test steps:**

    * wrap an existing ``RehuDocument`` in a model
    * verify it reports ``saved_on_disk`` True
    """
    assert RehuDocumentModel(document).saved_on_disk is True


def test_saving_marks_saved_on_disk(mocker: MockerFixture) -> None:
    """The first :meth:`~RehuDocumentModel.save` marks the model ``saved_on_disk`` -- the file now
    exists on disk, so Revert has something to revert to (#147).

    **Test steps:**

    * build a not-yet-saved model bound to a path, patching the document's atomic save
    * call ``model.save()``
    * verify ``saved_on_disk`` flips to True
    """
    model = RehuDocumentModel.create_new(Path("/fake/sculpting/info.rehu"))
    mocker.patch.object(model.document, "save")
    assert model.saved_on_disk is False

    model.save()

    assert model.saved_on_disk is True


def test_create_new_files_per_user_state_under_the_given_username() -> None:
    """``create_new`` hands its ``username`` to the fresh document, so the new document's per-user
    writes are filed under the configured identity ([[field-schema#per-user-shared]], #99).

    **Test steps:**

    * call ``RehuDocumentModel.create_new`` with a username
    * verify the wrapped document carries it (its per-user accessors key the ``users`` map by it)
    """
    model = RehuDocumentModel.create_new(Path("/fake/sculpting/info.rehu"), username="alice")

    assert model.document.username == "alice"


def test_create_new_mints_a_fresh_id() -> None:
    """``create_new`` gives the fresh document its own ``id`` ([[data-model#stable-identity]]) --
    minted at creation, not only at `.tc` import.

    **Test steps:**

    * call ``RehuDocumentModel.create_new`` twice
    * verify each document carries a non-empty ``id``, and the two differ
    """
    first = RehuDocumentModel.create_new()
    second = RehuDocumentModel.create_new()

    assert first.document.id != ""
    assert second.document.id != ""
    assert first.document.id != second.document.id


def test_create_pending_is_empty_clean_and_bound_without_an_identity() -> None:
    """``create_pending`` builds a session-restore placeholder (#66): bound to its path but wrapping a
    completely empty document -- in particular **no** freshly minted ``id``, which would fabricate an
    identity for a resource that already has one on disk ([[data-model#stable-identity]]) -- and,
    unlike ``create_new``, not dirty: nothing here is a document about to be written.

    **Test steps:**

    * call ``RehuDocumentModel.create_pending`` for a path
    * verify pending, path-bound, empty data, clean, and unlocked
    """
    path = Path("/fake/sculpting/info.rehu")

    model = RehuDocumentModel.create_pending(path)

    assert model.pending is True
    assert model.path == path
    assert model.document.id == ""
    # nothing but the migrator's own format stamp -- no core block, no sources, no plugin blocks
    assert set(model.document.data) <= {"format_version"}
    assert model.dirty is False
    assert model.locked is False


def test_load_pending_reads_the_file_and_clears_pending(mocker: MockerFixture) -> None:
    """``load_pending`` performs the deferred read (#66): the placeholder reseeds from what is on
    disk, ``pending`` clears, and the flag is already down by the time the reload's own signals reach
    the consumers that were holding their I/O back on it.

    **Test steps:**

    * build a pending placeholder over a mocked file, recording ``pending`` as ``reloaded`` fires
    * call ``load_pending`` and verify the fields seeded, pending cleared, and the signal saw it down
    """
    mocker.patch.object(
        Path,
        "read_text",
        return_value=json.dumps({"type": "Tutorial", "sources": [{"title": "Foo", "primary": True}]}),
    )
    model = RehuDocumentModel.create_pending(Path("/fake/sculpting/info.rehu"))
    pending_at_reload: list[bool] = []
    model.reloaded.connect(lambda: pending_at_reload.append(model.pending))

    model.load_pending()

    assert model.pending is False
    assert model.title == "Foo"
    assert pending_at_reload == [False]


def test_load_pending_is_a_no_op_once_loaded(mocker: MockerFixture) -> None:
    """A second ``load_pending`` -- a stale trigger after the first already ran -- reloads nothing, so
    it can never revert a document out from under live edits (#66).

    **Test steps:**

    * load a pending placeholder, then edit it dirty
    * call ``load_pending`` again and verify nothing was re-read and the edit survived
    """
    mocker.patch.object(
        Path,
        "read_text",
        return_value=json.dumps({"type": "Tutorial", "sources": [{"title": "Foo", "primary": True}]}),
    )
    model = RehuDocumentModel.create_pending(Path("/fake/sculpting/info.rehu"))
    model.load_pending()
    model.title = "Edited"
    reload = mocker.patch.object(model.document, "reload")

    model.load_pending()

    assert reload.call_count == 0
    assert model.title == "Edited"
    assert model.dirty is True


def test_unknown_field_names_lists_unrecognized_block_keys_sorted(document: RehuDocument) -> None:
    """``unknown_field_names`` returns the live block's unrecognized keys, sorted, excluding known ones.

    **Test steps:**

    * seed the block with a known field plus two unknown keys
    * verify only the unknown keys come back, in sorted order
    """
    document.set_active_field("rating", 5)
    document.set_active_field("zeta", 1)
    document.set_active_field("alpha", 2)
    model = RehuDocumentModel(document)

    assert model.unknown_field_names() == ["alpha", "zeta"]


def test_unknown_field_names_excludes_the_collections_record_list(document: RehuDocument) -> None:
    """``collections`` is a field the Tutorial plugin **declares**, so it never reaches the newer-version
    fallback (#189).

    A settled v1 field rehuco's own importer writes -- flagged as *"comes from a newer version"* for as
    long as the model recognized only bools, ints and string lists.

    **Test steps:**

    * seed the block with a ``collections`` record list beside one genuinely unknown key
    * verify only the unknown key is reported
    """
    document.set_active_field("collections", [{"title": "Series", "index": 2}])
    document.set_active_field("mystery", 1)
    model = RehuDocumentModel(document)

    assert model.unknown_field_names() == ["mystery"]


def test_unknown_field_names_recognizes_by_the_active_types_declaration(document: RehuDocument) -> None:
    """What counts as *known* is the **active type's** declaration, not one flat list spanning every type
    ([[field-schema#resource-types]], #195).

    This is what keeps the per-type field composition from swallowing a value: a field the active type
    doesn't declare renders on no editor row, so the fallback has to report it or it would sit in the
    file with nowhere to see or drop it. The same key therefore reads as known under one type and
    unknown under another.

    **Test steps:**

    * seed a Tutorial block with a ``level`` (its own) and an ``current_count`` (ReferenceImages')
    * verify only the undeclared one is reported
    * switch the type to ``reference_images`` and verify the verdicts swap
    """
    document.set_active_field("level", ["any"])
    document.set_active_field("current_count", 12)
    model = RehuDocumentModel(document)

    assert model.unknown_field_names() == ["current_count"]

    model.resource_type = "reference_images"
    model.document.set_active_field("level", ["any"])
    model.document.set_active_field("current_count", 12)

    assert model.unknown_field_names() == ["level"]


def test_model_seeds_the_record_lists(document: RehuDocument) -> None:
    """Both record lists seed from the document **as stored** -- the records, not the sorted projection
    the viewer shows ([[field-schema#sources]], #235).

    **Test steps:**

    * seed the block with two collections and the current identity's own learning path
    * verify each reads back as the stored records, in stored order and keyed by scope
    """
    document.set_active_field("collections", [{"title": "Second", "index": 2}, {"title": "First", "index": 1}])
    document.set_active_user_field("learning_paths", [{"title": "My Order", "index": 7, "ref": 1}])
    model = RehuDocumentModel(document)

    assert model.collections == [{"title": "Second", "index": 2}, {"title": "First", "index": 1}]
    assert model.learning_paths == {"admin": [{"title": "My Order", "index": 7, "ref": 1}]}


def test_model_learning_paths_carry_every_identitys_records(document: RehuDocument) -> None:
    """The model holds every scope's records, including another identity's private paths -- *what is in
    this file* is what the editor acts on, and resolving *what am I in* is the viewer's own step
    ([[field-schema#learning-path-ownership]], #235).

    **Test steps:**

    * file a private path under another identity, a published one, and a subscription to it
    * verify all three scopes are in the model's value, and that resolving it for ``admin`` shows the
      published path and not the private one
    """
    document.set_active_field(
        "users",
        {
            "admin": {"learning_paths": [{"ref": 1}]},
            "public": {"learning_paths": [{"title": "Shared", "index": 3, "ref": 1}]},
            "foo": {"learning_paths": [{"title": "Private", "index": 1, "ref": 2}]},
        },
    )
    model = RehuDocumentModel(document)

    assert set(model.learning_paths) == {"admin", "public", "foo"}
    assert visible_learning_paths(model.learning_paths, username="admin") == [LearningPathEntry(3, "Shared")]


def test_model_reseeds_the_record_lists_on_revert(mocker: MockerFixture, document: RehuDocument) -> None:
    """A revert re-reads both record lists from disk, like every other seeded field.

    **Test steps:**

    * construct a model over a document with no record lists
    * mock ``document.reload`` to bring in a collection membership, and revert
    * verify the list follows
    """
    model = RehuDocumentModel(document)
    assert model.collections == []

    def fake_reload() -> None:
        document.set_active_field("collections", [{"title": "Series", "index": 2}])

    mocker.patch.object(document, "reload", side_effect=fake_reload)

    model.revert()

    assert model.collections == [{"title": "Series", "index": 2}]


def test_unknown_field_names_excludes_the_users_map(document: RehuDocument) -> None:
    """The block's ``users`` map is per-user storage structure (#98), not an unknown resource field --
    excluded the same way the block's own ``format_version`` stamp is (#99).

    **Test steps:**

    * file a per-user field (materializing the block's ``users`` map) beside one unknown key
    * verify only the genuinely-unknown key is reported
    """
    document.set_active_user_field("rating", 5)
    document.set_active_field("mystery", 1)
    model = RehuDocumentModel(document)

    assert model.unknown_field_names() == ["mystery"]


def test_inactive_block_keys_lists_every_block_the_type_does_not_name(document: RehuDocument) -> None:
    """``inactive_block_keys`` reports the blocks this file is merely custodian of
    ([[plugins#plugin-blocks]]).

    Installed-ness is irrelevant: ``reference_images`` has a plugin here and ``daz3d`` does not, yet
    both are inactive purely because the document's ``type`` names neither.

    **Test steps:**

    * add a ``reference_images`` and then a ``daz3d`` block beside the tutorial document's own
    * verify both come back **sorted alphabetically** (not in insertion order), and the active block is
      not among them
    """
    document.data["reference_images"] = {"current_count": 12}
    document.data["daz3d"] = {"sku": "12345"}
    document.set_active_field("rating", 5)
    model = RehuDocumentModel(document)

    assert model.inactive_block_keys() == ["daz3d", "reference_images"]


def test_bind_resolves_an_inactive_block_to_its_verbatim_contents(document: RehuDocument) -> None:
    """``bind`` resolves a whole inactive block, not just a field inside the active one
    ([[plugins#plugin-blocks]]).

    An inactive block is a *top-level* key while an unknown field is a key *inside* the active block, so
    without this the block would bind to an absent field and read as ``None``.

    **Test steps:**

    * add an inactive block and bind a field named after it
    * verify the binding carries the block's contents verbatim
    """
    document.data["reference_images"] = {"current_count": 12}
    model = RehuDocumentModel(document)

    binding = model.bind(Field("reference_images"))

    assert binding.value == {"current_count": 12}
    assert binding.changed is model.unknown_fields_changed


def test_an_inactive_blocks_binding_refuses_to_write(caplog: pytest.LogCaptureFixture, document: RehuDocument) -> None:
    """An inactive block is carried, never edited -- its setter refuses rather than writing
    ([[plugins#plugin-blocks]]).

    Whatever affordance it eventually gets is #84's, and the drop-on-abandon rule behind it is #82's
    ([[plugins#fallback-editor]]).

    **Test steps:**

    * bind an inactive block and call its setter
    * verify the block is untouched, the model is still clean, and the refusal was logged
    """
    document.data["reference_images"] = {"current_count": 12}
    model = RehuDocumentModel(document)
    binding = model.bind(Field("reference_images"))

    with caplog.at_level(logging.ERROR):
        binding.set_value({"current_count": 99})

    assert document.data["reference_images"] == {"current_count": 12}
    assert model.dirty is False
    assert "Refusing to edit inactive block" in caplog.text


def test_bind_resolves_an_unknown_field_to_its_verbatim_value(document: RehuDocument) -> None:
    """``bind`` resolves an unknown key to its stored value and the block-change signal.

    **Test steps:**

    * seed an unknown key and bind a field named after it
    * verify the binding carries the verbatim value
    """
    document.set_active_field("mystery", [1, 2, 3])
    model = RehuDocumentModel(document)
    field = Field("mystery")

    binding = model.bind(field)

    assert binding.value == [1, 2, 3]
    assert binding.changed is model.unknown_fields_changed


def test_bind_never_gives_an_unknown_field_a_property_binding(document: RehuDocument) -> None:
    """An `UnknownField` binds the block verbatim even when its name collides with a declared property
    (#195).

    Possible since recognition went per-type: a tutorial block's stray ``current_count`` is unknown
    *here* while still being a `SimpleProperty` of the model. The property read is coerced (a malformed
    value becomes the field's default), so binding it would show a value the file never carried -- the
    fallback's whole contract is verbatim ([[plugins#fallback-editor]]) -- and its notify signal would
    leave the row deaf to ``unknown_fields_changed``.

    **Test steps:**

    * seed the tutorial block with a malformed stray ``current_count`` the property would coerce away
    * bind an `UnknownField` named after it
    * verify the binding carries the raw value and the block-change signal, not the property's pair
    """
    document.set_active_field("current_count", "raw-junk")
    model = RehuDocumentModel(document)
    tab = FieldsTab("T", ":/icons/document_viewer.svg")

    binding = model.bind(UnknownField("current_count", viewer_tab=tab, editor_tab=tab))

    assert binding.value == "raw-junk"
    assert binding.changed is model.unknown_fields_changed
    assert model.current_count is None  # the property's own coerced read, untouched by the fallback


def test_remove_unknown_field_drops_the_key_and_dirties(document: RehuDocument) -> None:
    """``remove_unknown_field`` deletes the key, emits its signal, and marks the model dirty.

    **Test steps:**

    * seed an unknown key and record ``unknown_fields_changed`` emissions
    * remove it and verify the key is gone, the signal fired, and the model is dirty
    """
    document.set_active_field("mystery", 42)
    model = RehuDocumentModel(document)
    fired: list[None] = []
    model.unknown_fields_changed.connect(lambda: fired.append(None))

    model.remove_unknown_field("mystery")

    assert "mystery" not in document.active_block
    assert fired == [None]
    assert model.dirty is True


def test_drop_inactive_block_removes_the_block_emits_and_dirties(document: RehuDocument) -> None:
    """``drop_inactive_block`` deletes a whole foreign block, emits ``unknown_fields_changed``, and marks
    the model dirty ([[plugins#fallback-editor]], #84).

    The block-level sibling of :meth:`remove_unknown_field` -- the explicit *drop* of a carried foreign
    block, on the same signal the reactive fallback rows re-read to hide themselves.

    **Test steps:**

    * add a foreign ``reference_images`` block and record ``unknown_fields_changed`` emissions
    * drop it and verify the block is gone, the signal fired, and the model is dirty
    """
    document.data["reference_images"] = {"current_count": 12}
    model = RehuDocumentModel(document)
    fired: list[None] = []
    model.unknown_fields_changed.connect(lambda: fired.append(None))

    model.drop_inactive_block("reference_images")

    assert "reference_images" not in document.data
    assert fired == [None]
    assert model.dirty is True


def test_drop_inactive_block_is_a_noop_for_the_active_block(document: RehuDocument) -> None:
    """``drop_inactive_block`` refuses the active block, staying clean and silent ([[plugins#fallback-editor]],
    #84).

    The core's :meth:`~rehuco_core.RehuDocument.remove_block` never drops the active block, so this
    reports nothing and leaves the model exactly as it was -- a stale button click is harmless.

    **Test steps:**

    * over a tutorial document whose active block is present, drop the active ``tutorial`` block
    * verify the block is untouched, no signal fired, and the model stayed clean
    """
    document.data["tutorial"] = {"rating": 4}
    model = RehuDocumentModel(document)
    fired: list[None] = []
    model.unknown_fields_changed.connect(lambda: fired.append(None))

    model.drop_inactive_block("tutorial")

    assert "tutorial" in document.data
    assert not fired
    assert model.dirty is False


def test_a_freshly_loaded_older_clean_document_is_upgradable(mocker: MockerFixture) -> None:
    """A document read from an older-``format_version`` file, still clean, is :attr:`upgradable` (#89).

    **Test steps:**

    * mock a file whose stamped ``format_version`` predates the current one
    * load it and wrap it in a model
    * verify the model reports ``upgradable``
    """
    mocker.patch.object(Path, "read_text", return_value=json.dumps({"format_version": 1, "type": "Tutorial"}))
    document = RehuDocument.load(Path("/fake/info.rehu"))

    model = RehuDocumentModel(document)

    assert model.upgradable is True


def test_a_document_at_the_current_format_version_is_not_upgradable(mocker: MockerFixture) -> None:
    """A document already at :data:`CURRENT_FORMAT_VERSION` has nothing to upgrade.

    **Test steps:**

    * mock a file already stamped at the current format version
    * load it and wrap it in a model
    * verify the model does not report ``upgradable``
    """
    mocker.patch.object(
        Path, "read_text", return_value=json.dumps({"format_version": CURRENT_FORMAT_VERSION, "type": "Tutorial"})
    )
    document = RehuDocument.load(Path("/fake/info.rehu"))

    model = RehuDocumentModel(document)

    assert model.upgradable is False


def test_a_freshly_loaded_document_with_a_stale_block_is_upgradable(mocker: MockerFixture) -> None:
    """A document whose file-wide version is current but whose active block predates its plugin is still
    :attr:`upgradable` -- one offer covers either stale layer (#81, #89, [[plugins#plugin-blocks]]).

    The real ``tutorial`` plugin's block chain is at head 1 (#98), so a v0 ``tutorial`` block on disk is
    genuinely behind -- no stand-in registry needed.

    **Test steps:**

    * mock a file at the current file-wide version whose ``tutorial`` block is unstamped (v0)
    * load it and wrap it in a model
    * verify the model reports ``upgradable``
    """
    mocker.patch.object(
        Path,
        "read_text",
        return_value=json.dumps(
            {"format_version": CURRENT_FORMAT_VERSION, "core": {"type": "tutorial"}, "tutorial": {}}
        ),
    )
    document = RehuDocument.load(Path("/fake/info.rehu"))

    model = RehuDocumentModel(document)

    assert model.upgradable is True


def test_a_document_current_at_both_layers_is_not_upgradable(mocker: MockerFixture) -> None:
    """Neither the file nor the active block is stale, so there is nothing to offer (#81, #89).

    **Test steps:**

    * mock a file at the current file-wide version, block already at the plugin's own version
    * load it and wrap it in a model
    * verify the model does not report ``upgradable``
    """
    mocker.patch.object(
        Path,
        "read_text",
        return_value=json.dumps(
            {
                "format_version": CURRENT_FORMAT_VERSION,
                "core": {"type": "tutorial"},
                "tutorial": {"format_version": current_block_version("tutorial")},
            }
        ),
    )
    document = RehuDocument.load(Path("/fake/info.rehu"))

    model = RehuDocumentModel(document)

    assert model.upgradable is False


def test_saving_a_block_only_upgradable_document_clears_the_offer(mocker: MockerFixture) -> None:
    """Saving upgrades whichever layer was stale, block included -- the same single-remedy contract the
    file-wide offer already has (:meth:`RehuDocumentModel.save`, #81).

    **Test steps:**

    * load a document whose active block alone predates its plugin, confirming it starts upgradable
    * save
    * verify the offer clears
    """
    mocker.patch.object(
        Path,
        "read_text",
        return_value=json.dumps(
            {"format_version": CURRENT_FORMAT_VERSION, "core": {"type": "tutorial"}, "tutorial": {}}
        ),
    )
    document = RehuDocument.load(Path("/fake/info.rehu"))
    model = RehuDocumentModel(document)
    assert model.upgradable is True

    mocker.patch("rehuco_core.rehu_document.atomic_write_text")
    model.save()

    assert model.upgradable is False


def test_a_pathless_document_is_never_upgradable(model: RehuDocumentModel) -> None:
    """A document with no file on disk (the shared fixture) is never upgradable -- there is no file to
    have been written at an older version.

    **Test steps:**

    * read ``upgradable`` off the pathless shared fixture model
    * verify it is ``False``
    """
    assert model.upgradable is False


def test_a_legacy_tc_document_is_never_upgradable() -> None:
    """A legacy ``.tc``-backed document is never upgradable -- it has no ``.rehu`` on disk at any
    version yet (:attr:`~rehuco_core.RehuDocument.on_disk_format_version` reads ``None`` for it).

    **Test steps:**

    * build a model over a legacy ``.tc``-backed document
    * verify ``upgradable`` is ``False``
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, Path("/fake/info.tc"), legacy_tc=True))

    assert model.upgradable is False


def test_an_older_dirty_document_is_not_upgradable(mocker: MockerFixture) -> None:
    """An older document with unsaved edits is not :attr:`upgradable` -- its remedy is Save, which
    upgrades anyway, so no separate offer is needed (the issue's own File/Dirty table).

    **Test steps:**

    * load an older-format document (clean, so upgradable) and confirm it starts upgradable
    * edit a field, dirtying the model
    * verify ``upgradable`` drops to ``False`` immediately (live, off ``dirty_changed``)
    """
    mocker.patch.object(Path, "read_text", return_value=json.dumps({"format_version": 1, "type": "Tutorial"}))
    document = RehuDocument.load(Path("/fake/info.rehu"))
    model = RehuDocumentModel(document)
    assert model.upgradable is True

    model.title = "Edited"

    assert model.upgradable is False


def test_an_older_locked_document_is_not_upgradable(mocker: MockerFixture) -> None:
    """An older document that is also locked (e.g. a present-but-uncoercible field) is not
    :attr:`upgradable` -- ``save()`` refuses a save-blocking lock, so offering Upgrade would only
    raise.

    **Test steps:**

    * mock an older-format file whose ``authors`` is present but not skip-clean (``INVALID_FIELD``)
    * load it and wrap it in a model
    * verify the model is locked and not upgradable
    """
    mocker.patch.object(
        Path,
        "read_text",
        return_value=json.dumps({"format_version": 1, "type": "Tutorial", "authors": 42}),
    )
    document = RehuDocument.load(Path("/fake/info.rehu"))

    model = RehuDocumentModel(document)

    assert model.locked is True
    assert model.upgradable is False


def test_saving_an_upgradable_document_clears_the_offer(mocker: MockerFixture) -> None:
    """``save()`` -- the upgrade mechanism itself, per its own docstring -- restamps the document and
    immediately clears :attr:`upgradable`, even though the model was never dirty (the Upgrade path).

    **Test steps:**

    * load a clean, older-format document, confirming it starts upgradable
    * call ``model.save()`` for real (the atomic write is mocked away)
    * verify ``upgradable`` is now ``False``
    """
    mocker.patch.object(Path, "read_text", return_value=json.dumps({"format_version": 1, "type": "Tutorial"}))
    mocker.patch("rehuco_core.rehu_document.atomic_write_text")
    document = RehuDocument.load(Path("/fake/info.rehu"))
    model = RehuDocumentModel(document)
    assert model.upgradable is True
    assert model.dirty is False

    model.save()

    assert model.upgradable is False


def test_revert_recomputes_upgradable_from_the_reloaded_version(mocker: MockerFixture) -> None:
    """``revert()`` recomputes :attr:`upgradable` from the reloaded document, picking up an
    out-of-band version change the same way it does for every other field.

    Drives a real reload (mocking ``Path.read_text``, not ``document.reload`` itself) rather than
    hand-setting the document's private on-disk-version bookkeeping, since that's set only by
    :meth:`~rehuco_core.RehuDocument.load`/:meth:`~rehuco_core.RehuDocument.reload`/
    :meth:`~rehuco_core.RehuDocument.save`, not by editing ``data`` directly.

    **Test steps:**

    * load a clean, older-format document
    * mock ``Path.read_text`` to now return the file stamped at the current version
    * call ``model.revert()``
    * verify ``upgradable`` dropped to ``False``
    """
    path = Path("/fake/info.rehu")
    mocker.patch.object(Path, "read_text", return_value=json.dumps({"format_version": 1, "type": "Tutorial"}))
    model = RehuDocumentModel(RehuDocument.load(path))
    assert model.upgradable is True

    mocker.patch.object(
        Path, "read_text", return_value=json.dumps({"format_version": CURRENT_FORMAT_VERSION, "type": "Tutorial"})
    )

    model.revert()

    assert model.upgradable is False


def test_remove_unknown_field_is_a_noop_when_absent(document: RehuDocument) -> None:
    """Removing an absent key changes nothing -- no signal, no dirtying.

    **Test steps:**

    * record ``unknown_fields_changed`` emissions on a clean model
    * remove a key that isn't there
    * verify nothing fired and the model stayed clean
    """
    model = RehuDocumentModel(document)
    fired: list[None] = []
    model.unknown_fields_changed.connect(lambda: fired.append(None))

    model.remove_unknown_field("nonexistent")

    assert not fired
    assert model.dirty is False


# endregion


# region Type switching (#83, [[plugins#plugin-blocks]])
def test_resource_type_seeds_from_the_documents_type_without_dirtying(document: RehuDocument) -> None:
    """The model seeds ``resource_type`` from the document's (normalized) type, clean
    ([[plugins#plugin-blocks]], #83).

    **Test steps:**

    * wrap a ``Tutorial`` document
    * verify ``resource_type`` is the normalized main key and the model is clean
    """
    model = RehuDocumentModel(document)

    assert model.resource_type == "tutorial"
    assert model.dirty is False


def test_switching_type_claims_the_new_block_reseeds_it_and_dirties(document: RehuDocument) -> None:
    """Setting ``resource_type`` switches the active block, re-seeds its known fields, marks dirty, and
    fires ``active_block_changed`` ([[plugins#plugin-blocks]], #83).

    **Test steps:**

    * seed a ``reference_images`` block with an ``current_count`` beside the tutorial document's own
    * record ``active_block_changed`` emissions, then switch the type to it
    * verify the document's active type followed, the known ``current_count`` re-seeded from the new
      block, the model dirtied, and the composition-change signal fired
    """
    document.data["reference_images"] = {"current_count": 12}
    model = RehuDocumentModel(document)
    fired: list[None] = []
    model.active_block_changed.connect(lambda: fired.append(None))

    model.resource_type = "reference_images"

    assert model.document.type == "reference_images"
    assert model.current_count == 12
    assert model.dirty is True
    assert fired == [None]


def test_switching_type_reseeds_the_record_lists(document: RehuDocument) -> None:
    """The record lists are block-scoped, so a type switch re-reads them from the newly-active block
    ([[field-schema#sources]], #189).

    **Test steps:**

    * give the tutorial block one collection and the ``reference_images`` block another
    * switch the type
    * verify the incoming block's record list is what the model holds
    """
    document.set_active_field("collections", [{"title": "Tutorial Series", "index": 1}])
    document.data["reference_images"] = {"collections": [{"title": "Image Series", "index": 5}]}
    model = RehuDocumentModel(document)
    assert model.collections == [{"title": "Tutorial Series", "index": 1}]

    model.resource_type = "reference_images"

    assert model.collections == [{"title": "Image Series", "index": 5}]


def test_switching_type_leaves_the_common_core_fields_untouched(document: RehuDocument) -> None:
    """A type switch re-seeds only the block-scoped scalars, never the common-core fields -- it is not a
    reload ([[plugins#plugin-blocks]], #83).

    **Test steps:**

    * switch the tutorial document to ``reference_images``
    * verify title/publisher/url (common core) are unchanged
    """
    model = RehuDocumentModel(document)

    model.resource_type = "reference_images"

    assert model.title == "Foo"
    assert model.publisher == "Bar"
    assert model.url == "https://example.com"


def test_switching_type_normalizes_an_alias_onto_the_property(document: RehuDocument) -> None:
    """An alias spelling normalizes to its plugin's main key, and the property reflects the stored
    spelling ([[plugins#plugin-blocks]], #83).

    **Test steps:**

    * switch the type using the ``ReferenceImages`` alias
    * verify both the document and the reconciled property carry the main key
    """
    model = RehuDocumentModel(document)

    model.resource_type = "ReferenceImages"

    assert model.document.type == "reference_images"
    assert model.resource_type == "reference_images"


def test_switching_type_away_and_back_revives_the_block_from_memory(document: RehuDocument) -> None:
    """Switching away then back is non-destructive: the block's values come back from memory
    ([[plugins#plugin-blocks]]'s resurrection, #83).

    **Test steps:**

    * seed a ``reference_images`` block, switch to it, then away to tutorial, then back
    * verify the revived block's ``current_count`` re-seeds unchanged
    """
    document.data["reference_images"] = {"current_count": 12}
    model = RehuDocumentModel(document)

    model.resource_type = "reference_images"
    model.resource_type = "tutorial"
    model.resource_type = "reference_images"

    assert model.current_count == 12


def test_switching_to_a_type_with_no_block_starts_empty(document: RehuDocument) -> None:
    """Switching to a type the file has no block for starts an empty active block -- the known scalars
    reset to their defaults ([[plugins#plugin-blocks]], #83).

    **Test steps:**

    * seed the tutorial block with a rating, then switch to a never-before-used ``reference_images`` type
    * verify the ``current_count`` reads its absent default (``None``) rather than leaking the old block
    """
    document.set_active_field("rating", 5)
    model = RehuDocumentModel(document)

    model.resource_type = "reference_images"

    assert model.current_count is None
    assert model.rating is None


def test_inactive_block_fates_splits_abandoned_from_foreign(document: RehuDocument) -> None:
    """``inactive_block_fates`` marks a claimed-then-abandoned block as dropped-on-save and a
    never-claimed foreign block as carried ([[plugins#plugin-blocks]]'s steps 1 vs 4, #83).

    **Test steps:**

    * seed an untouched foreign ``reference_images`` block beside the opening tutorial block
    * switch to a **third** type (``collection``), so both earlier blocks are now inactive
    * verify the abandoned ``tutorial`` block is flagged dropped and the never-claimed foreign one carried
    """
    document.data["reference_images"] = {"current_count": 12}
    document.set_active_field("rating", 4)  # give the tutorial block substance to abandon
    model = RehuDocumentModel(document)

    model.resource_type = "collection"

    assert model.inactive_block_fates() == [("reference_images", False), ("tutorial", True)]


def test_available_types_unions_installed_mains_with_the_documents_own_block_keys(document: RehuDocument) -> None:
    """``available_types`` offers every installed plugin's main key plus any block the document already
    carries -- so a not-installed foreign block stays selectable for resurrection
    ([[plugins#plugin-blocks]], #83).

    **Test steps:**

    * add a foreign ``audiopack`` block the build has no plugin for
    * verify the offer list leads with the installed mains, then the extra block key
    """
    document.data["audiopack"] = {"bpm": 120}
    model = RehuDocumentModel(document)

    assert model.available_types() == ["tutorial", "reference_images", "collection", "audiopack"]


def test_reverting_a_type_switch_rebuilds_the_composition_without_re_switching(mocker: MockerFixture) -> None:
    """Reverting a type switch restores the on-disk type and fires ``active_block_changed`` so the form
    rebuilds -- without the reseed being mistaken for a fresh switch ([[plugins#plugin-blocks]], #83).

    A reverted document begins a clean session: the type switched to is forgotten and the property returns
    to what the file says. Because that makes a *different* block active again, the composition must
    re-resolve (else the switched-to block lingers as a stale inactive-block row) -- but the reseed runs
    under the seed guard, so no fresh switch is claimed and the model doesn't re-dirty.

    **Test steps:**

    * load a tutorial document from disk and switch its type to ``reference_images`` (dirtying it)
    * record ``active_block_changed``, then revert
    * verify the type reseeds back to tutorial, the composition change fired once, and the model is clean
    """
    path = Path("/fake/info.rehu")
    mocker.patch.object(
        Path,
        "read_text",
        return_value=json.dumps({"format_version": CURRENT_FORMAT_VERSION, "core": {"type": "Tutorial"}}),
    )
    model = RehuDocumentModel(RehuDocument.load(path))
    model.resource_type = "reference_images"
    fired: list[None] = []
    model.active_block_changed.connect(lambda: fired.append(None))

    model.revert()

    assert model.resource_type == "tutorial"
    assert fired == [None]
    assert model.dirty is False


def test_revert_always_rebuilds_the_composition(mocker: MockerFixture) -> None:
    """Every revert fires ``active_block_changed`` so the form rebuilds from scratch, even a value-only
    revert that switched no type -- a revert is defined to leave the model as a fresh open would
    ([[plugins#plugin-blocks]], #83).

    Rather than decide which structural axis a reload moved (type, unknown fields, or inactive-block
    fates), the coarse user-driven revert just rebuilds -- correct by construction, and cheap.

    **Test steps:**

    * load a tutorial document, edit a field (dirtying it) without switching type
    * record ``active_block_changed``, then revert
    * verify the type is unchanged, the rebuild fired once, and the model is clean
    """
    path = Path("/fake/info.rehu")
    mocker.patch.object(
        Path,
        "read_text",
        return_value=json.dumps({"format_version": CURRENT_FORMAT_VERSION, "core": {"type": "Tutorial"}}),
    )
    model = RehuDocumentModel(RehuDocument.load(path))
    model.title = "Edited"
    fired: list[None] = []
    model.active_block_changed.connect(lambda: fired.append(None))

    model.revert()

    assert model.resource_type == "tutorial"
    assert fired == [None]
    assert model.dirty is False


def test_reverting_a_type_round_trip_restores_a_foreign_blocks_carry_or_drop(mocker: MockerFixture) -> None:
    """A revert restores a block's carry-vs-drop shape, so a block switched *to* and back this session
    regains its drop button ([[plugins#fallback-editor]], #84).

    A revert resets the session's claim set to the reloaded type, so a **claimed-then-abandoned** block
    (switched to, then away from) becomes **never-claimed foreign** again -- carried, with a drop button --
    even though the active type is ``tutorial`` throughout. The bug this guards: before revert rebuilt the
    form unconditionally, the block stayed flagged will-drop-on-save with no drop button until the file
    was closed and reopened; now the rebuild restores its fate, matching a fresh open.

    **Test steps:**

    * load a tutorial document also carrying a foreign ``reference_images`` block
    * switch the type to ``reference_images`` and back to ``tutorial`` -- now that block is abandoned
    * record ``active_block_changed``, then revert
    * verify the active type is unchanged, the composition change fired, and the block's fate is
      carried-again (not dropped)
    """
    path = Path("/fake/info.rehu")
    mocker.patch.object(
        Path,
        "read_text",
        return_value=json.dumps(
            {
                "format_version": CURRENT_FORMAT_VERSION,
                "core": {"type": "Tutorial"},
                "reference_images": {"current_count": 12},
            }
        ),
    )
    model = RehuDocumentModel(RehuDocument.load(path))
    model.resource_type = "reference_images"
    model.resource_type = "tutorial"
    assert ("reference_images", True) in model.inactive_block_fates()  # abandoned before revert
    fired: list[None] = []
    model.active_block_changed.connect(lambda: fired.append(None))

    model.revert()

    assert model.resource_type == "tutorial"
    assert fired == [None]
    assert ("reference_images", False) in model.inactive_block_fates()  # carried foreign again


# endregion


def test_editing_the_collections_writes_through_and_dirties(document: RehuDocument) -> None:
    """A memberships edit reaches the block and marks the model dirty, like every other write-through
    ([[field-schema#sources]], #235).

    **Test steps:**

    * set the model's collections to one record carrying a key no editor shows
    * verify the block holds exactly that record, and the model is dirty
    """
    model = RehuDocumentModel(document)

    model.collections = [{"title": "Series", "index": 2, "url": "https://example.com"}]

    assert document.active_field("collections") == [{"title": "Series", "index": 2, "url": "https://example.com"}]
    assert model.dirty is True


def test_clearing_the_collections_removes_the_key(document: RehuDocument) -> None:
    """Absent is not empty: an emptied membership list takes its key with it rather than storing ``[]``
    ([[field-schema#deferred-items]]).

    **Test steps:**

    * seed a membership, then clear it through the model
    * verify the key is gone from the block
    """
    document.set_active_field("collections", [{"title": "Series"}])
    model = RehuDocumentModel(document)

    model.collections = []

    assert "collections" not in document.active_block


def test_editing_the_learning_paths_writes_every_scope_through(document: RehuDocument) -> None:
    """A learning-path edit spans scopes: an owned record here, a subscription there
    ([[field-schema#learning-path-ownership]], #235).

    **Test steps:**

    * write one owned path for ``admin`` and a subscription for ``foo``
    * verify each landed under its own identity, and the model is dirty
    """
    model = RehuDocumentModel(document)

    model.learning_paths = {"admin": [{"title": "Mine", "index": 1, "ref": 1}], "foo": [{"ref": 1}]}

    users = document.active_block["users"]
    assert users["admin"]["learning_paths"] == [{"title": "Mine", "index": 1, "ref": 1}]
    assert users["foo"]["learning_paths"] == [{"ref": 1}]
    assert model.dirty is True


def test_seeding_the_record_lists_is_not_an_edit(document: RehuDocument) -> None:
    """The seed guard matters more here than for a scalar: a seed assigns the very records it just read,
    so an unguarded write-through would dirty every document merely by opening it.

    **Test steps:**

    * open a document already carrying both record lists
    * verify the model is clean
    """
    document.set_active_field("collections", [{"title": "Series", "index": 2}])
    document.set_active_user_field("learning_paths", [{"title": "Mine", "index": 1, "ref": 1}])

    assert RehuDocumentModel(document).dirty is False


# region what a resource's log says about it (#200)

LOGGED_PATH: Final = Path("logged-resource.rehu").resolve()
"""The path the scoped-log tests are the log *of*; nothing is ever written to it -- every filesystem
call these tests would make is mocked, the same way the save/revert tests above do it."""


class RecordingSink:
    """A `LogRecordSink` that keeps every entry it is given, for asserting on scope and level."""

    def __init__(self) -> None:
        self.entries: list[LogEntry] = []

    def handle_log_records(self, entries: Sequence[LogEntry]) -> None:
        """Keep a batch.

        :param entries: the entries handed over.
        """
        self.entries.extend(entries)

    def messages_at(self, level: int) -> list[str]:
        """The messages kept at exactly ``level``.

        :param level: the level to filter by.
        :returns: the matching messages, in order.
        """
        return [entry.message for entry in self.entries if entry.record.levelno == level]


@fixture
def scoped_sink(qtbot: QtBot) -> Iterator[Callable[[Hashable | None], RecordingSink]]:
    """Provide a way to record what the shared bridge routes to one scope.

    The model's own logger is attached to the bridge with propagation off, so these records reach the
    bridge under test and neither the console nor a handler another test left behind.

    :param qtbot: pytest-qt bot, whose event loop the bridge's queued dispatch needs.
    :returns: a callable taking a scope -- or ``None`` for a sink that sees everything, which is what a
        path-less document's records are -- and returning the sink attached under it.
    """
    del qtbot  # only needed so a QApplication and an event loop exist
    bridge = shared_log_bridge()
    logger = logging.getLogger(RehuDocumentModel.__module__)
    previous_propagate = logger.propagate
    previous_level = logger.level
    # DEBUG explicitly: this logger's own level is NOTSET, so without it the effective floor is the root
    # logger's -- which under pytest is WARNING, and would silently drop every info these tests assert on
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.addHandler(bridge)
    sinks: list[RecordingSink] = []

    def attach(scope: Hashable | None = None) -> RecordingSink:
        sink = RecordingSink()
        if scope is None:
            bridge.add_sink(sink)
        else:
            bridge.add_scoped_sink(sink, scope)
        sinks.append(sink)
        return sink

    yield attach
    for sink in sinks:
        bridge.remove_sink(sink)
    logger.removeHandler(bridge)
    logger.propagate = previous_propagate
    logger.setLevel(previous_level)


@fixture
def saved_document() -> RehuDocument:
    """A document bound to a path, so what happens to it has a scope to be logged under.

    :returns: the document.
    """
    return RehuDocument({"type": "Tutorial", "sources": [{"title": "Foo", "primary": True}]}, LOGGED_PATH)


def test_saving_logs_under_this_documents_own_scope(
    mocker: MockerFixture, saved_document: RehuDocument, scoped_sink: Callable[..., RecordingSink], qtbot: QtBot
) -> None:
    """A save is logged, and placed under the resource it saved (#200).

    **Test steps:**

    * patch the document's own save, and attach a sink for its path
    * save through the model
    * verify the save was recorded under that scope
    """
    mocker.patch.object(saved_document, "save")
    model = RehuDocumentModel(saved_document)
    sink = scoped_sink(LOGGED_PATH)

    model.save()
    qtbot.wait(10)

    assert any(str(LOGGED_PATH) in message for message in sink.messages_at(logging.INFO))


def test_reverting_logs_under_this_documents_own_scope(
    mocker: MockerFixture, saved_document: RehuDocument, scoped_sink: Callable[..., RecordingSink], qtbot: QtBot
) -> None:
    """A revert is logged, and placed under the resource it re-read (#200).

    **Test steps:**

    * patch the document's own reload, and attach a sink for its path
    * revert through the model
    * verify the revert was recorded under that scope
    """
    mocker.patch.object(saved_document, "reload")
    model = RehuDocumentModel(saved_document)
    sink = scoped_sink(LOGGED_PATH)

    model.revert()
    qtbot.wait(10)

    assert any("Reverted" in message for message in sink.messages_at(logging.INFO))


def test_a_deferred_load_logs_as_a_read_not_a_revert(
    mocker: MockerFixture, scoped_sink: Callable[..., RecordingSink], qtbot: QtBot
) -> None:
    """The deferred session-restore read logs in the eager open's exact words -- *Read ... as ...* --
    not as a *Reverted* (#66, #200): nobody reverted anything, and the record should say what
    actually happened, which is the same this-file-was-read event an eager open logs; *when* it
    happened is already the record's timestamp.

    **Test steps:**

    * attach a sink for a pending placeholder's path, with the file's content mocked
    * complete the deferred load
    * verify a *Read* record was placed under that scope, and no *Reverted* one
    """
    mocker.patch.object(
        Path,
        "read_text",
        return_value=json.dumps({"type": "Tutorial", "sources": [{"title": "Foo", "primary": True}]}),
    )
    model = RehuDocumentModel.create_pending(LOGGED_PATH)
    sink = scoped_sink(LOGGED_PATH)

    model.load_pending()
    qtbot.wait(10)

    messages = sink.messages_at(logging.INFO)
    assert any(message.startswith("Read ") for message in messages)
    assert not any("Reverted" in message for message in messages)


def test_a_lock_is_logged_as_a_warning_in_the_banners_own_words(
    scoped_sink: Callable[..., RecordingSink], qtbot: QtBot
) -> None:
    """Every lock reason the banner would show is also a warning in that resource's log (#200).

    Banner parity: a reader who dismissed a banner -- or never had one on screen, because the dock was
    closed -- can still find out why a document is locked. The same words, so the two cannot disagree.

    **Test steps:**

    * attach a sink for a locked document's path
    * build the model over it
    * verify each lock reason's own message was recorded as a warning
    """
    sink = scoped_sink(LOGGED_PATH)

    model = RehuDocumentModel(RehuDocument({FORMAT_VERSION_KEY: CURRENT_FORMAT_VERSION + 1}, LOGGED_PATH))
    qtbot.wait(10)

    assert model.lock_reasons
    assert sink.messages_at(logging.WARNING) == [reason.message for reason in model.lock_reasons]


def test_an_upgrade_offer_is_logged_as_an_info(
    mocker: MockerFixture, scoped_sink: Callable[..., RecordingSink], qtbot: QtBot
) -> None:
    """The upgrade offer the banner shows is also an info in that resource's log (#200).

    An info, not a warning, for the same reason it is one in the banner: nothing is wrong, there is
    simply something better available.

    **Test steps:**

    * mock a file stamped at an older format version, and attach a sink for its path
    * load it and wrap it in a model
    * verify the offer was recorded, and as an info rather than a warning
    """
    mocker.patch.object(Path, "read_text", return_value=json.dumps({FORMAT_VERSION_KEY: 1, "type": "Tutorial"}))
    sink = scoped_sink(LOGGED_PATH)

    model = RehuDocumentModel(RehuDocument.load(LOGGED_PATH))
    qtbot.wait(10)

    assert model.upgradable
    assert any("upgrades it" in message for message in sink.messages_at(logging.INFO))
    assert sink.messages_at(logging.WARNING) == []


def test_a_clean_current_document_reports_nothing_about_its_state(
    mocker: MockerFixture, scoped_sink: Callable[..., RecordingSink], qtbot: QtBot
) -> None:
    """A document with no lock and no upgrade offer has nothing to say about itself (#200).

    The log is what happened, not a status line: an ordinary document opening is the read record the
    dock area writes, and nothing more.

    **Test steps:**

    * mock a file at the current format version, and attach a sink for its path
    * load it and wrap it in a model
    * verify neither a warning nor an info was recorded
    """
    mocker.patch.object(
        Path, "read_text", return_value=json.dumps({FORMAT_VERSION_KEY: CURRENT_FORMAT_VERSION, "type": "Tutorial"})
    )
    sink = scoped_sink(LOGGED_PATH)

    RehuDocumentModel(RehuDocument.load(LOGGED_PATH))
    qtbot.wait(10)

    assert sink.messages_at(logging.WARNING) == []
    assert sink.messages_at(logging.INFO) == []


def test_a_failed_rename_is_logged_as_an_error(scoped_sink: Callable[..., RecordingSink], qtbot: QtBot) -> None:
    """A failed rename is an error in the log, in the words the banner shows (#200).

    The third banner source, and the only one whose record is written where it happens rather than at a
    state transition -- a failure is not a state to be recomputed.

    **Test steps:**

    * attach a sink over everything, since a path-less document's records are unscoped
    * attempt to rename a document that has no location yet
    * verify the failure was recorded as an error, saying the same thing as ``rename_error``
    """
    model = RehuDocumentModel.create_new()
    sink = scoped_sink()

    assert model.rename_location("whatever") is False
    qtbot.wait(10)

    assert model.rename_error
    assert model.rename_error in sink.messages_at(logging.ERROR)


# endregion
