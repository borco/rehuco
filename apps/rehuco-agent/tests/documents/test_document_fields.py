"""Tests for the document's field composition ([[plugins#field-toolkit]])."""

from PySide6.QtWidgets import QLabel
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_fields import EDITOR_MAIN_TAB, VIEWER_TAB, build_document_form
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields import (
    PROVENANCE_ABANDONED_TYPE,
    PROVENANCE_NEWER_VERSION,
    PROVENANCE_NOT_CURRENT_TYPE,
)
from rehuco_agent.fields.widgets import SingleChoiceComboBox
from rehuco_core import RehuDocument


# region fixtures
@fixture
def model() -> RehuDocumentModel:
    """A tutorial document carrying an unknown field in its active block, plus two inactive blocks --
    one whose plugin is installed here (``reference_images``) and one whose isn't (``daz3d``)."""
    return RehuDocumentModel(
        RehuDocument(
            {
                "core": {"type": "tutorial", "sources": [{"title": "Foo", "primary": True}]},
                "tutorial": {"rating": 4, "mystery": 42},
                "reference_images": {"images_count": 12},
                "daz3d": {"sku": "12345"},
            }
        )
    )


def viewer_tooltips(qtbot: QtBot, model: RehuDocumentModel) -> dict[str, str]:
    """Build the viewer surface and collect each flagged value label's provenance tooltip.

    :param qtbot: the Qt fixture owning the built widgets.
    :param model: the model to build the form over.
    :returns: a ``{label text: tooltip}`` mapping of every unknown-flagged label on the viewer tab.
    """
    grids = build_document_form(model).make_viewer(model)
    qtbot.addWidget(grids[VIEWER_TAB])
    return {
        label.text(): label.toolTip() for label in grids[VIEWER_TAB].findChildren(QLabel) if label.property("unknown")
    }


# endregion


# region build_document_form tests
def test_the_form_flags_each_inactive_block_as_not_the_files_type(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Every inactive block gets a flagged row explaining it isn't the one this file's ``type`` names
    ([[plugins#plugin-blocks]], [[plugins#fallback-editor]]).

    Whether the block's plugin is installed here makes no difference -- ``reference_images`` has one and
    ``daz3d`` does not, and both are flagged identically, because only the type decides what is active.

    **Test steps:**

    * build the viewer over a tutorial document carrying ``reference_images`` and ``daz3d`` blocks
    * verify each block's contents are shown verbatim, tooltipped with the not-this-type provenance
    """
    tooltips = viewer_tooltips(qtbot, model)

    assert tooltips["{'images_count': 12}"] == PROVENANCE_NOT_CURRENT_TYPE
    assert tooltips["{'sku': '12345'}"] == PROVENANCE_NOT_CURRENT_TYPE


def test_an_unknown_field_in_the_active_block_keeps_its_own_provenance(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """An unrecognized field *inside* the active block is a different situation from a whole inactive
    block, and says so ([[plugins#fallback-editor]]).

    **Test steps:**

    * build the viewer over a document whose active block holds an unrecognized ``mystery`` key
    * verify it is flagged with the newer-version provenance, not the not-this-type one
    """
    tooltips = viewer_tooltips(qtbot, model)

    assert tooltips["42"] == PROVENANCE_NEWER_VERSION


def test_the_forms_known_fields_are_not_flagged(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A recognized field is rendered by its own field type, never through the unknown fallback.

    Guards the enumeration boundary: the active block's ``rating`` is a known field and the core block's
    fields aren't blocks at all, so neither may show up flagged.

    **Test steps:**

    * build the viewer
    * verify only the three genuinely-unrecognized values are flagged
    """
    assert len(viewer_tooltips(qtbot, model)) == 3


def test_the_type_selector_is_in_the_editor_but_not_the_viewer(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The type selector is editor-only ([[plugins#plugin-blocks]], #83) -- a combo on the main editor,
    absent from the read-only viewer.

    **Test steps:**

    * build both surfaces
    * verify the editor's main tab holds a type combo, and the viewer has none
    """
    form = build_document_form(model)
    editor = form.make_editor(model)[EDITOR_MAIN_TAB]
    viewer = form.make_viewer(model)[VIEWER_TAB]
    qtbot.addWidget(editor)
    qtbot.addWidget(viewer)

    assert editor.findChildren(SingleChoiceComboBox)
    assert not viewer.findChildren(SingleChoiceComboBox)


def test_a_type_switch_flags_the_abandoned_block_apart_from_a_foreign_one(qtbot: QtBot) -> None:
    """After a switch, a claimed-then-abandoned inactive block reads as will-drop-on-save while a
    never-claimed foreign block reads as carried ([[plugins#plugin-blocks]]'s steps 1 vs 4, #83).

    This is the "visually distinguish former-identity from foreign" the slice honours: the abandoned
    block's provenance warns it will be deleted, the foreign block's says it is kept.

    **Test steps:**

    * over a tutorial document also carrying a foreign ``reference_images`` block, switch to a third type
    * rebuild the viewer (as the widget does on a switch) and read each flagged block's provenance tooltip
    * verify the abandoned ``tutorial`` block warns of deletion and the foreign one says it is kept
    """
    model = RehuDocumentModel(
        RehuDocument(
            {
                "core": {"type": "tutorial", "sources": [{"title": "Foo", "primary": True}]},
                "tutorial": {"rating": 4},
                "reference_images": {"images_count": 12},
            }
        )
    )
    model.resource_type = "collection"

    tooltips = viewer_tooltips(qtbot, model)

    assert tooltips["{'users': {'admin': {'rating': 4}}, 'format_version': 1}"] == PROVENANCE_ABANDONED_TYPE
    assert tooltips["{'images_count': 12}"] == PROVENANCE_NOT_CURRENT_TYPE


# endregion
