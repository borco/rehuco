"""Tests for the document's field composition ([[plugins#field-toolkit]])."""

from typing import cast

from PySide6.QtWidgets import QGridLayout, QLabel, QToolButton, QWidget
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_fields import EDITOR_MAIN_TAB, VIEWER_TAB, build_document_form
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields import (
    PROVENANCE_ABANDONED_TYPE,
    PROVENANCE_NEWER_VERSION,
    PROVENANCE_NOT_CURRENT_TYPE,
    PROVENANCE_PLUGIN_ABSENT,
)
from rehuco_agent.fields.fields_form import CONTENT_COLUMN, MISC_COLUMN
from rehuco_agent.fields.widgets import SingleChoiceComboBox, TypeBadge
from rehuco_core import TUTORIAL_PLUGIN, RehuDocument


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


def drop_button_for(grid_widget: QWidget, value_text: str) -> QToolButton | None:
    """Find the drop button sharing a grid row with the flagged value label reading ``value_text``.

    The editor grid lays each row out label | misc | content, so a fallback row's value sits in the
    content column and its drop button (when present) in the misc column of the *same* row -- this maps
    one to the other rather than guessing among every button on the surface.

    :param grid_widget: an editor grid widget (one tab's ``QGridLayout`` host).
    :param value_text: the verbatim value label text identifying the row.
    :returns: that row's misc-column `QToolButton`, or ``None`` when the row has no drop button.
    """
    layout = grid_widget.layout()
    assert isinstance(layout, QGridLayout)

    def cell(index: int) -> tuple[QWidget | None, int, int]:
        # getItemPosition is (row, column, rowspan, colspan); the PySide6 stub types it as object, so
        # the cast is what lets a row/column read type-check
        item = layout.itemAt(index)
        row, column, _, _ = cast(tuple[int, int, int, int], layout.getItemPosition(index))
        return (item.widget() if item is not None else None, row, column)

    target_row: int | None = None
    for i in range(layout.count()):
        widget, row, column = cell(i)
        if isinstance(widget, QLabel) and widget.text() == value_text and column == CONTENT_COLUMN:
            target_row = row
            break
    if target_row is None:
        return None
    for i in range(layout.count()):
        widget, row, column = cell(i)
        if isinstance(widget, QToolButton) and row == target_row and column == MISC_COLUMN:
            return widget
    return None


# endregion


# region build_document_form tests
def test_the_form_flags_each_inactive_block_by_whether_its_plugin_is_installed(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """Every inactive block gets a flagged row whose provenance names *why* it's inactive, split by
    whether its plugin is installed here ([[plugins#plugin-blocks]], [[plugins#fallback-editor]], #84).

    Both are inactive purely because the file's ``type`` names neither -- but the user's remedy differs:
    ``reference_images`` has a plugin here, so the fix is "switch the type to it" (not-current-type);
    ``daz3d`` has none, so the fix is "install the plugin" (plugin-absent).

    **Test steps:**

    * build the viewer over a tutorial document carrying ``reference_images`` and ``daz3d`` blocks
    * verify each block's contents are shown verbatim, tooltipped with the provenance its
      installed-ness selects
    """
    tooltips = viewer_tooltips(qtbot, model)

    assert tooltips["{'images_count': 12}"] == PROVENANCE_NOT_CURRENT_TYPE
    assert tooltips["{'sku': '12345'}"] == PROVENANCE_PLUGIN_ABSENT


def test_a_foreign_block_can_be_dropped_from_the_editor(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A foreign inactive block's editor row carries a drop action that removes the whole block
    ([[plugins#fallback-editor]], #84).

    The explicit *drop* half of carry-vs-drop: clicking it deletes the block through the model, marks the
    document dirty, and hides the row -- the block-level counterpart of an unknown field's remove.

    **Test steps:**

    * build the editor over a document carrying a foreign ``reference_images`` block
    * click that block's drop button
    * verify the block is gone from the document, the model is dirty, and the row is hidden
    """
    editor = build_document_form(model).make_editor(model)[EDITOR_MAIN_TAB]
    qtbot.addWidget(editor)
    value = next(label for label in editor.findChildren(QLabel) if label.text() == "{'images_count': 12}")
    drop = drop_button_for(editor, "{'images_count': 12}")
    assert drop is not None

    drop.click()

    assert "reference_images" not in model.document.data
    assert model.dirty is True
    assert value.isHidden() is True


def test_an_abandoned_block_has_no_drop_button(qtbot: QtBot) -> None:
    """A claimed-then-abandoned block gets no drop button -- it is already slated to drop on save
    ([[plugins#fallback-editor]], #84).

    Offering a manual drop there would only bypass the #86 discard-log audit trail the save already
    records. A never-claimed foreign block on the same surface *does* get one, proving the button's
    presence tracks the block's fate, not merely its inactivity.

    **Test steps:**

    * over a tutorial document also carrying a foreign ``reference_images`` block, switch to a third type
      so the former ``tutorial`` block is abandoned
    * build the editor and verify the abandoned block's row has no drop button while the foreign one does
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
    editor = build_document_form(model).make_editor(model)[EDITOR_MAIN_TAB]
    qtbot.addWidget(editor)

    assert drop_button_for(editor, "{'users': {'admin': {'rating': 4}}, 'format_version': 1}") is None
    assert drop_button_for(editor, "{'images_count': 12}") is not None


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


def test_the_type_is_a_combo_in_the_editor_and_a_badge_in_the_viewer(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The type is edited by a combo on the main editor and shown as a colored badge in the viewer
    ([[plugins#plugin-blocks]], #83).

    The combo (the control) is editor-only; the viewer presents the type read-only as a badge painted
    with the plugin's declared color.

    **Test steps:**

    * build both surfaces
    * verify the editor holds the type combo (and the viewer does not)
    * verify the viewer holds a type badge showing the tutorial type in its plugin color
    """
    form = build_document_form(model)
    editor = form.make_editor(model)[EDITOR_MAIN_TAB]
    viewer = form.make_viewer(model)[VIEWER_TAB]
    qtbot.addWidget(editor)
    qtbot.addWidget(viewer)

    assert editor.findChildren(SingleChoiceComboBox)
    assert not viewer.findChildren(SingleChoiceComboBox)

    badge = viewer.findChild(TypeBadge)
    assert badge is not None
    assert badge.text() == "Tutorial"
    tutorial_color = TUTORIAL_PLUGIN.color
    assert tutorial_color is not None and tutorial_color in badge.styleSheet()


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
