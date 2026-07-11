"""Tests for the RehuDocumentModel reactive view-model."""

# the model has a broad reactive surface (common-core + type fields, seeding, revert, dirty
# tracking); its test suite is correspondingly long -- one cohesive module reads better than an
# arbitrary split, so the module-length cap is lifted here rather than fragmenting it.
# pylint: disable=too-many-lines

import logging
from pathlib import Path

import pytest
from fields.field_testers import FieldTester as Field
from pytest import fixture, mark, param, raises
from pytest_mock import MockerFixture
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_core import RehuDocument


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
    """A document whose ``format_version`` exceeds ``RehuDocument.CURRENT_FORMAT_VERSION`` locks the
    model at construction (A3, [[data-model#schema-version]]'s fail-safe-on-a-newer-file rule).

    **Test steps:**

    * construct a model over a document one version newer than this build understands
    * verify the model is locked
    """
    newer_version = RehuDocument.CURRENT_FORMAT_VERSION + 1
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial", "format_version": newer_version}))
    assert model.locked is True


def test_model_is_not_locked_at_or_below_the_current_format_version() -> None:
    """A document at (or below, or missing) the current ``format_version`` is not locked.

    **Test steps:**

    * construct models over documents at the current version, an older version, and no version at all
    * verify none of them lock
    """
    assert RehuDocumentModel(RehuDocument({"format_version": RehuDocument.CURRENT_FORMAT_VERSION})).locked is False
    assert RehuDocumentModel(RehuDocument({"format_version": 0})).locked is False
    assert RehuDocumentModel(RehuDocument({})).locked is False


def test_model_is_locked_for_a_legacy_tc_document() -> None:
    """A document mapped from a legacy ``.tc`` file locks the model, independent of ``format_version``
    ([[acquisition-tooling#tc-to-rehu]]'s Phase 1) -- format_version 0 is *older* than this build's,
    so the newer-format-version rule alone would never catch it.

    **Test steps:**

    * construct a model over a document with ``legacy_tc=True`` (format_version defaults to 0)
    * verify the model is locked
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, legacy_tc=True))
    assert model.locked is True


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

    ``location`` mirrors the file path for the viewer; it isn't a document field. Rename-on-disk is
    the separate :meth:`rename_location` path, deferred to A5 (#25).

    **Test steps:**

    * set ``model.location`` to a new value
    * verify the document's path is unchanged and the model stays clean
    """
    model.location = "C:/tutorials/bar/info.rehu"

    assert document.path is None
    assert model.dirty is False


def test_rename_location_always_fails_and_logs_an_error(
    caplog: pytest.LogCaptureFixture, model: RehuDocumentModel
) -> None:
    """``rename_location`` always fails for now (the real move is deferred to A5), logging an error.

    **Test steps:**

    * call ``rename_location`` on a clean model
    * verify it returns ``False`` and an error is logged
    """
    with caplog.at_level(logging.INFO):
        result = model.rename_location("new_name")

    assert result is False
    assert any(record.levelno == logging.ERROR for record in caplog.records)


def test_rename_location_logs_the_attempt_before_the_move_fails(
    caplog: pytest.LogCaptureFixture, model: RehuDocumentModel
) -> None:
    """The attempt is logged before the (always-failing) move is even tried.

    **Test steps:**

    * call ``rename_location``
    * verify an info-level "attempting" log precedes the error-level failure log
    """
    with caplog.at_level(logging.INFO):
        model.rename_location("new_name")

    levels = [record.levelno for record in caplog.records]
    assert logging.INFO in levels
    assert logging.ERROR in levels
    assert levels.index(logging.INFO) < levels.index(logging.ERROR)


def test_rename_location_saves_first_when_dirty(mocker: MockerFixture, model: RehuDocumentModel) -> None:
    """A dirty model is saved before the move is attempted, so the file being moved isn't stale.

    **Test steps:**

    * dirty the model, then patch ``save``
    * call ``rename_location``
    * verify ``save`` was called
    """
    model.title = "New Title"
    assert model.dirty is True
    save = mocker.patch.object(model, "save")

    model.rename_location("new_name")

    save.assert_called_once()


def test_rename_location_does_not_save_when_clean(mocker: MockerFixture, model: RehuDocumentModel) -> None:
    """A clean model is not saved before attempting the move -- there is nothing to save.

    **Test steps:**

    * patch ``save`` on a clean model
    * call ``rename_location``
    * verify ``save`` was not called
    """
    assert model.dirty is False
    save = mocker.patch.object(model, "save")

    model.rename_location("new_name")

    save.assert_not_called()


def test_rename_location_returns_whether_the_move_succeeded(mocker: MockerFixture, model: RehuDocumentModel) -> None:
    """``rename_location`` returns the (deferred) move's result -- ``True`` when it would succeed.

    The move itself always fails today (#25/A5) and owns committing :attr:`location`; this drives the
    success branch by patching the private move to report success.

    **Test steps:**

    * patch the private move to report success
    * call ``rename_location`` and verify it returns ``True``
    """
    move = mocker.patch.object(model, "_RehuDocumentModel__move", return_value=True)

    result = model.rename_location("new_name")

    assert result is True
    move.assert_called_once_with("new_name")


@mark.parametrize(
    ("path", "expected"),
    [
        param("C:/tutorials/some_folder/info.rehu", "some_folder", id="info.rehu-uses-parent-dir"),
        param("C:/tutorials/my_tutorial.rehu", "my_tutorial", id="standalone-uses-file-stem"),
    ],
)
def test_current_name_is_the_rename_target(path: str, expected: str) -> None:
    """``current_name`` is the folder name for ``info.rehu``, the file stem otherwise.

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


def test_setting_released_writes_through_and_dirties(model: RehuDocumentModel, document: RehuDocument) -> None:
    """Setting ``released`` writes through to the document (not source-scoped) and marks dirty.

    **Test steps:**

    * set ``model.released``
    * verify it lands on the document directly, and the model is dirty
    """
    model.released = "2025-03-08"

    assert document.released == "2025-03-08"
    assert model.dirty is True


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


def test_image_files_returns_empty_without_a_path(model: RehuDocumentModel) -> None:
    """A pathless document has no screenshot siblings to enumerate.

    **Test steps:**

    * use a model whose document was never given a path
    * verify ``image_files`` is empty
    """
    assert model.image_files() == []


def test_image_files_matches_stem_numbered_siblings(mocker: MockerFixture) -> None:
    """``image_files`` returns the ``<stem>NN`` image siblings, sorted, ignoring everything else.

    **Test steps:**

    * wrap a document at ``/fake/info.rehu`` and mock its directory listing
    * include matching ``info00``/``info01`` screenshots, a non-image and a mismatched-stem sibling
    * verify only the two screenshots come back, sorted by name
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, Path("/fake/info.rehu")))
    siblings = [
        Path("/fake/info01.png"),
        Path("/fake/info00.jpg"),
        Path("/fake/info.rehu"),
        Path("/fake/info00.txt"),
        Path("/fake/cover.jpg"),
        Path("/fake/info0.jpg"),
    ]
    mocker.patch.object(Path, "iterdir", return_value=siblings)

    assert model.image_files() == [Path("/fake/info00.jpg"), Path("/fake/info01.png")]


def test_image_files_tolerates_a_missing_directory(mocker: MockerFixture) -> None:
    """A missing/offline directory yields no screenshots rather than raising.

    **Test steps:**

    * wrap a document with a path and mock ``iterdir`` to raise ``FileNotFoundError``
    * verify ``image_files`` swallows it and returns empty
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, Path("/fake/info.rehu")))
    mocker.patch.object(Path, "iterdir", side_effect=FileNotFoundError)

    assert model.image_files() == []


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
        document.data["sources"] = [
            {
                "title": "Reloaded Title",
                "publisher": "Reloaded Publisher",
                "url": "https://reloaded.example",
                "primary": True,
            }
        ]
        document.data["authors"] = ["Reloaded Author"]
        document.data["released"] = "2030-01"
        document.data["original_size"] = 5368709120
        document.data["current_size"] = 1073741824
        document.data["advertised_tags"] = ["reloaded-tag"]
        document.data["extra_tags"] = ["reloaded-extra"]
        document.data["description"] = "# Reloaded\n\nprose"
        document.data["hidden_images"] = ["reloaded.jpg"]

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
    newer_version = RehuDocument.CURRENT_FORMAT_VERSION + 1

    def fake_reload() -> None:
        document.data["format_version"] = newer_version

    mocker.patch.object(document, "reload", side_effect=fake_reload)

    model.revert()

    assert model.locked is True


def test_revert_reseeds_type_fields_too(
    mocker: MockerFixture, model: RehuDocumentModel, document: RehuDocument
) -> None:
    """revert() also reseeds the type-field-backed scalars (bool/int) from the reloaded document.

    **Test steps:**

    * mock ``document.reload`` to simulate an on-disk rating change
    * call ``model.revert()``
    * verify ``model.rating`` reflects the reloaded value
    """

    def fake_reload() -> None:
        document.data["tutorial"] = {"rating": -3}

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


def test_revert_without_a_path_propagates(model: RehuDocumentModel, document: RehuDocument) -> None:
    """revert() propagates the document's error when it has never been loaded from a file.

    **Test steps:**

    * call ``model.revert()`` on a document with no path
    * verify ``ValueError`` propagates
    """
    assert document.path is None
    with raises(ValueError, match="no path to reload from"):
        model.revert()


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
    * verify ``complete`` defaults true, the other flags false, rating/images_count zero, level
      empty, and it is clean
    """
    assert model.complete is True
    assert model.online is False
    assert model.favorite is False
    assert model.rating == 0
    assert model.images_count == 0
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
    """Malformed type-field values fall back to the field default rather than crashing (#35).

    **Test steps:**

    * construct a model over a document whose block holds a non-int rating and a null images_count
    * verify both coerce to their defaults
    """
    document = RehuDocument({"type": "ReferenceImages", "reference_images": {"rating": "junk", "images_count": None}})
    model = RehuDocumentModel(document)

    assert model.rating == 0
    assert model.images_count == 0


def test_setting_a_type_field_flag_writes_through_and_dirties(model: RehuDocumentModel, document: RehuDocument) -> None:
    """Setting a type-field-backed flag writes through to the document's plugin block and marks dirty.

    **Test steps:**

    * set ``model.complete`` false
    * verify the document's ``tutorial`` block now holds it, and the model is dirty
    """
    model.complete = False

    assert document.type_field("complete") is False
    assert model.dirty is True


def test_setting_rating_writes_through_to_the_type_fields(model: RehuDocumentModel, document: RehuDocument) -> None:
    """Setting the rating writes through to the document's plugin block.

    **Test steps:**

    * set ``model.rating`` to a negative value
    * verify the document's ``tutorial`` block holds it
    """
    model.rating = -4

    assert document.type_field("rating") == -4


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

    assert document.type_field("original_duration") == 8100


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
    """A non-list or mixed-type ``level`` coerces to the default, dropping only the bad items (#35).

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

    assert document.type_field("level") == ["advanced", "any"]
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
    * verify the document's path matches and the model is dirty
    """
    path = Path("/fake/sculpting/info.rehu")

    model = RehuDocumentModel.create_new(path)

    assert model.document.path == path
    assert model.dirty is True


def test_unknown_field_names_lists_unrecognized_block_keys_sorted(document: RehuDocument) -> None:
    """``unknown_field_names`` returns the live block's unrecognized keys, sorted, excluding known ones.

    **Test steps:**

    * seed the block with a known field plus two unknown keys
    * verify only the unknown keys come back, in sorted order
    """
    document.set_type_field("rating", 5)
    document.set_type_field("zeta", 1)
    document.set_type_field("alpha", 2)
    model = RehuDocumentModel(document)

    assert model.unknown_field_names() == ["alpha", "zeta"]


def test_bind_resolves_an_unknown_field_to_its_verbatim_value(document: RehuDocument) -> None:
    """``bind`` resolves an unknown key to its stored value and the block-change signal.

    **Test steps:**

    * seed an unknown key and bind a field named after it
    * verify the binding carries the verbatim value
    """
    document.set_type_field("mystery", [1, 2, 3])
    model = RehuDocumentModel(document)
    field = Field("mystery")

    binding = model.bind(field)

    assert binding.value == [1, 2, 3]
    assert binding.changed is model.unknown_fields_changed


def test_remove_unknown_field_drops_the_key_and_dirties(document: RehuDocument) -> None:
    """``remove_unknown_field`` deletes the key, emits its signal, and marks the model dirty.

    **Test steps:**

    * seed an unknown key and record ``unknown_fields_changed`` emissions
    * remove it and verify the key is gone, the signal fired, and the model is dirty
    """
    document.set_type_field("mystery", 42)
    model = RehuDocumentModel(document)
    fired: list[None] = []
    model.unknown_fields_changed.connect(lambda: fired.append(None))

    model.remove_unknown_field("mystery")

    assert "mystery" not in document.type_fields
    assert fired == [None]
    assert model.dirty is True


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
