"""Tests for the RehuDocumentModel reactive view-model."""

from pathlib import Path

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.field import Field
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
    * verify ``complete`` defaults true, the other flags false, rating/images_count zero, and it is clean
    """
    assert model.complete is True
    assert model.online is False
    assert model.favorite is False
    assert model.rating == 0
    assert model.images_count == 0
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


# endregion
