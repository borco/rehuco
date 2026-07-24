"""Tests for the read-only inspection views (#111).

Covers what's specific to :class:`SavePreviewView` (the live model serialization) and
:class:`OnDiskView` (the verbatim on-disk file): that each renders the right text, re-renders on its
own triggers (model signals while shown for the Save Preview -- deferred to the next show while
hidden, #152; file-touching seams for On Disk), and uses the fixed system font so columns line up.
"""

from pathlib import Path
from typing import Final

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QLabel
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.documents.source_views import (
    NOT_ON_DISK_PLACEHOLDER,
    OnDiskView,
    SavePreviewView,
)
from rehuco_core import CURRENT_FORMAT_VERSION, RehuDocument

REHU_PATH: Final = Path("/fake/info.rehu")
TC_PATH: Final = Path("/fake/info.tc")


# region fixtures
@fixture
def model() -> RehuDocumentModel:
    """A view-model seeded with a primary source, for the inspection views to render."""
    # pylint: disable=duplicate-code
    return RehuDocumentModel(
        RehuDocument(
            {
                "type": "Tutorial",
                "sources": [
                    {"title": "Foo", "publisher": "Bar", "url": "https://example.com", "primary": True},
                ],
            }
        )
    )
    # pylint: enable=duplicate-code


@fixture
def save_preview(qtbot: QtBot, model: RehuDocumentModel) -> SavePreviewView:
    """A constructed, shown :class:`SavePreviewView` over the sample model, registered for teardown."""
    view = SavePreviewView(model)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    return view


def label(view: SavePreviewView | OnDiskView, name: str) -> QLabel:
    """Return a view's inner text label.

    :param view: the inspection view to inspect.
    :param name: the label's object name.
    :returns: the `QLabel`.
    """
    found = view.findChild(QLabel, name)
    assert isinstance(found, QLabel)
    return found


# endregion


# region SavePreviewView tests
def test_save_preview_renders_the_documents_serialized_json(
    save_preview: SavePreviewView, model: RehuDocumentModel
) -> None:
    """The Save Preview shows exactly the document's serialized form -- byte-for-byte what a save would write.

    **Test steps:**

    * build a Save Preview over the sample model
    * verify the label's text equals ``model.document.serialize()``
    """
    assert label(save_preview, SavePreviewView.LABEL_NAME).text() == model.document.serialize()


def test_save_preview_rerenders_after_a_model_edit(save_preview: SavePreviewView, model: RehuDocumentModel) -> None:
    """A field edit re-renders the preview live, reflecting the unsaved change (#111).

    **Test steps:**

    * edit the model's title
    * verify the label now shows the new serialization, and that it actually contains the new value
    """
    model.title = "Edited Title"

    text = label(save_preview, SavePreviewView.LABEL_NAME).text()
    assert text == model.document.serialize()
    assert "Edited Title" in text


def test_save_preview_rerenders_after_dropping_an_unknown_field(qtbot: QtBot) -> None:
    """Dropping an unrecognized field (``unknown_fields_changed``) re-renders the preview, so it no
    longer shows the removed key (#111).

    **Test steps:**

    * build a model whose active block carries an unrecognized key, over a shown Save Preview
    * drop that unknown field and verify the label no longer mentions it
    """
    model = RehuDocumentModel(
        RehuDocument({"type": "Tutorial", "Tutorial": {"mystery": "value"}, "sources": [{"title": "Foo"}]})
    )
    view = SavePreviewView(model)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    assert "mystery" in label(view, SavePreviewView.LABEL_NAME).text()

    model.remove_unknown_field("mystery")

    text = label(view, SavePreviewView.LABEL_NAME).text()
    assert "mystery" not in text
    assert text == model.document.serialize()


def test_save_preview_does_not_rerender_while_hidden(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """A field edit while the preview is hidden defers the re-serialization -- a large document
    shouldn't pay to re-render on every keystroke it can't be seen for (#152).

    **Test steps:**

    * build a Save Preview over the sample model, left hidden
    * spy on the document's ``serialize`` and edit a field
    * verify ``serialize`` was not called
    """
    view = SavePreviewView(model)
    qtbot.addWidget(view)
    serialize = mocker.spy(model.document, "serialize")

    model.title = "Edited While Hidden"

    serialize.assert_not_called()


def test_save_preview_catches_up_when_shown_after_a_hidden_edit(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Showing the preview renders the current state, catching up on edits that accumulated while it
    was hidden (#152).

    **Test steps:**

    * build a Save Preview over the sample model, left hidden, and edit a field
    * show the view
    * verify the label now reflects the edited state
    """
    view = SavePreviewView(model)
    qtbot.addWidget(view)

    model.title = "Edited While Hidden"
    view.show()
    qtbot.waitExposed(view)

    text = label(view, SavePreviewView.LABEL_NAME).text()
    assert text == model.document.serialize()
    assert "Edited While Hidden" in text


def test_save_preview_does_not_rerender_on_show_without_a_hidden_edit(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """Showing the preview with nothing changed since its last render doesn't re-serialize (#152).

    **Test steps:**

    * build a Save Preview over the sample model (rendered once at construction), left hidden
    * spy on the document's ``serialize`` and show the view
    * verify ``serialize`` was not called again
    """
    view = SavePreviewView(model)
    qtbot.addWidget(view)
    serialize = mocker.spy(model.document, "serialize")

    view.show()
    qtbot.waitExposed(view)

    serialize.assert_not_called()


def test_save_preview_renders_a_locked_document(qtbot: QtBot) -> None:
    """A locked document (newer format version) still renders -- ``serialize`` never checks the lock,
    unlike ``save`` (#111).

    **Test steps:**

    * build a Save Preview over a model locked by a newer ``format_version``
    * verify the label shows the document's serialization
    """
    model = RehuDocumentModel(
        RehuDocument({"type": "Tutorial", "format_version": CURRENT_FORMAT_VERSION + 1, "sources": [{"title": "Foo"}]})
    )
    view = SavePreviewView(model)
    qtbot.addWidget(view)

    assert label(view, SavePreviewView.LABEL_NAME).text() == model.document.serialize()


def test_save_preview_uses_the_fixed_system_font_family(save_preview: SavePreviewView) -> None:
    """The label is drawn in the fixed system font so JSON columns line up (#75, #111).

    **Test steps:**

    * build a Save Preview
    * verify the label's font family is the fixed system font's family
    """
    expected = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
    assert label(save_preview, SavePreviewView.LABEL_NAME).font().family() == expected


# endregion


# region OnDiskView tests
def test_on_disk_shows_a_placeholder_when_the_document_has_no_path(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A brand-new, path-less document has no on-disk bytes, so the view shows the placeholder (#111).

    **Test steps:**

    * build an On Disk view over the path-less sample model
    * verify the label shows the not-on-disk placeholder
    """
    view = OnDiskView(model)
    qtbot.addWidget(view)

    assert label(view, OnDiskView.LABEL_NAME).text() == NOT_ON_DISK_PLACEHOLDER


def test_on_disk_shows_a_placeholder_when_the_file_does_not_exist(qtbot: QtBot) -> None:
    """A document bound to a path whose file doesn't exist (never saved) still shows the placeholder (#111).

    **Test steps:**

    * build a model bound to a path, with ``read_text`` raising ``FileNotFoundError``
    * verify the On Disk view shows the placeholder
    """
    model = RehuDocumentModel.create_new(REHU_PATH)
    view = OnDiskView(model)
    qtbot.addWidget(view)

    assert label(view, OnDiskView.LABEL_NAME).text() == NOT_ON_DISK_PLACEHOLDER


def test_on_disk_shows_the_verbatim_file_bytes(qtbot: QtBot, mocker: MockerFixture) -> None:
    """The view shows the exact text on disk, unparsed -- not the model's re-serialization (#111).

    A deliberately non-canonical raw file (odd spacing, an older ``format_version``) proves the view
    reads the file verbatim rather than rendering the migrated in-memory model.

    **Test steps:**

    * build a model over a document bound to a real path, and mock ``read_text`` to a raw string
    * verify the On Disk view shows that raw string exactly
    """
    raw = '{"format_version": 1,\n   "type": "Tutorial"}\n'
    mocker.patch.object(Path, "read_text", return_value=raw)
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial", "sources": [{"title": "Foo"}]}, REHU_PATH))
    view = OnDiskView(model)
    qtbot.addWidget(view)

    assert label(view, OnDiskView.LABEL_NAME).text() == raw


def test_on_disk_shows_the_original_tc_file(qtbot: QtBot, mocker: MockerFixture) -> None:
    """For a legacy ``.tc``-backed document the on-disk path is the ``.tc``, so the view shows the
    original ``.tc`` file (#111).

    **Test steps:**

    * build a legacy ``.tc``-backed model, with ``read_text`` returning the raw ``.tc`` text
    * verify the On Disk view shows that ``.tc`` text
    """
    tc_text = '{"legacy tc": true}\n'
    mocker.patch.object(Path, "read_text", return_value=tc_text)
    model = RehuDocumentModel(
        RehuDocument({"type": "Tutorial", "sources": [{"title": "Foo"}]}, TC_PATH, legacy_tc=True)
    )
    view = OnDiskView(model)
    qtbot.addWidget(view)

    assert label(view, OnDiskView.LABEL_NAME).text() == tc_text


def test_on_disk_rereads_the_file_after_a_save(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Saving re-reads the file, so the view picks up the newly-written bytes (#111).

    Save is the seam that changes the on-disk bytes: before, the file holds the old text; after, it
    holds what was just written. The view re-reads on ``dirty`` clearing.

    **Test steps:**

    * build a dirty model bound to a path; ``read_text`` returns an "old" then a "new" text
    * verify the view first shows the old text, then the new text after a save
    """
    read = mocker.patch.object(Path, "read_text", return_value="old on disk\n")
    mocker.patch("rehuco_core.rehu_document.atomic_write_text")
    model = RehuDocumentModel.create_new(REHU_PATH)  # starts dirty, bound to a path
    view = OnDiskView(model)
    qtbot.addWidget(view)
    read.return_value = "new on disk\n"

    model.save()

    assert label(view, OnDiskView.LABEL_NAME).text() == "new on disk\n"


def test_on_disk_does_not_reread_on_a_plain_field_edit(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A per-keystroke value edit doesn't re-read the file -- only file-touching seams do, so a large
    file stays off the edit path (#111).

    The model starts dirty (create_new with a path), so a later value edit fires no ``dirty`` change;
    the view must not re-read on it.

    **Test steps:**

    * build a dirty model bound to a path, over an On Disk view (one read at construction)
    * edit a field and verify ``read_text`` was not called again
    """
    read = mocker.patch.object(Path, "read_text", return_value="on disk\n")
    model = RehuDocumentModel.create_new(REHU_PATH)  # starts dirty
    view = OnDiskView(model)
    qtbot.addWidget(view)
    reads_after_build = read.call_count

    model.title = "Edited"

    assert read.call_count == reads_after_build


def test_on_disk_uses_the_fixed_system_font_family(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The On Disk label is drawn in the fixed system font too (#75, #111).

    **Test steps:**

    * build an On Disk view
    * verify the label's font family is the fixed system font's family
    """
    view = OnDiskView(model)
    qtbot.addWidget(view)

    expected = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
    assert label(view, OnDiskView.LABEL_NAME).font().family() == expected


# endregion
