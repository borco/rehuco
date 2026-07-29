"""Tests for the document's field composition ([[plugins#field-toolkit]])."""

from typing import cast

from PySide6.QtWidgets import QGridLayout, QLabel, QToolButton, QWidget
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_fields import (
    EDITOR_MAIN_TAB,
    MODEL_AGNOSTIC_FIELD_SPECS,
    VIEWER_TAB,
    build_document_form,
    composed_field_specs,
)
from rehuco_agent.documents.name_suggestion_model import NameSuggestionModel
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields import (
    PROVENANCE_ABANDONED_TYPE,
    PROVENANCE_NEWER_VERSION,
    PROVENANCE_NOT_CURRENT_TYPE,
    PROVENANCE_PLUGIN_ABSENT,
)
from rehuco_agent.fields.fields_form import CONTENT_COLUMN, MISC_COLUMN
from rehuco_agent.fields.widgets import SingleChoiceComboBox, TypeBadge
from rehuco_core import BUILTIN_PLUGINS, CORE_FIELD_NAMES, TUTORIAL_PLUGIN, RehuDocument


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


def typed_model(resource_type: str, blocks: dict[str, dict[str, object]] | None = None) -> RehuDocumentModel:
    """A view-model over a document of ``resource_type``, carrying ``blocks`` verbatim.

    :param resource_type: the document's ``type``, installed here or not.
    :param blocks: the plugin blocks to seed the document with, keyed by block key.
    :returns: the model to compose fields over.
    """
    return RehuDocumentModel(RehuDocument({"core": {"type": resource_type}, **(blocks or {})}))


def composed_names(model: RehuDocumentModel) -> list[str]:
    """The names of the record fields ``model``'s type composes, in composition order.

    :param model: the model to compose fields over.
    :returns: each composed spec's field name.
    """
    return [spec.name for spec in composed_field_specs(model)]


def viewer_tooltips(qtbot: QtBot, model: RehuDocumentModel) -> dict[str, str]:
    """Build the viewer surface and collect each flagged value label's provenance tooltip.

    :param qtbot: the Qt fixture owning the built widgets.
    :param model: the model to build the form over.
    :returns: a ``{label text: tooltip}`` mapping of every unknown-flagged label on the viewer tab.
    """
    grids = build_document_form(model, NameSuggestionModel(model)).make_viewer(model)
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
    editor = build_document_form(model, NameSuggestionModel(model)).make_editor(model)[EDITOR_MAIN_TAB]
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
    editor = build_document_form(model, NameSuggestionModel(model)).make_editor(model)[EDITOR_MAIN_TAB]
    qtbot.addWidget(editor)

    assert drop_button_for(editor, "{'users': {'admin': {'rating': 4}}, 'format_version': 2}") is None
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
    form = build_document_form(model, NameSuggestionModel(model))
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

    assert tooltips["{'users': {'admin': {'rating': 4}}, 'format_version': 2}"] == PROVENANCE_ABANDONED_TYPE
    assert tooltips["{'images_count': 12}"] == PROVENANCE_NOT_CURRENT_TYPE


# endregion


# region composed_field_specs tests
def test_a_reference_images_document_composes_no_duration_and_no_level() -> None:
    """A ReferenceImages resource shows only the fields its own type declares
    ([[field-schema#resource-types]], #195).

    The bug this closes: composed from one flat list for every type, a ``reference_images`` document
    rendered three durations and a ``Level`` -- all four Tutorial-only. It declares no duration at all,
    which is why the value that leaked as `720` in tc4 has nowhere to land.

    ``viewed``/``todo`` go with them: progress through timed material is not something a reference-image
    pack has. ``complete`` stays, meaning *has all its parts* -- every image of the pack.

    **Test steps:**

    * compose the record fields for a ``reference_images`` document
    * verify no duration, no ``level`` and neither progress flag is composed
    * verify the fields it does share are still there
    """
    names = composed_names(typed_model("reference_images"))

    assert not [name for name in names if name.endswith("_duration")]
    for absent in ("level", "viewed", "todo"):
        assert absent not in names
    for present in ("rating", "collections", "complete", "online", "keep", "favorite"):
        assert present in names


def test_a_reference_images_document_composes_images_count_as_an_int() -> None:
    """``images_count`` renders on ReferenceImages, through the toolkit's plain ``int`` field
    ([[field-schema#resource-types]], [[field-schema#field-types]], #196).

    The type's one field of its own: declared on the view-model, coerced by core and round-tripped for
    slices, while no `FieldSpec` named it -- so it appeared on neither surface. It maps to ``int``
    rather than a bounded type because ``None`` must render empty and a genuine ``0`` must render
    honestly, keeping an unscanned archive distinguishable from one holding no content images
    ([[field-schema#deferred-items]]).

    **Test steps:**

    * compose the record fields for a ``reference_images`` document
    * verify ``images_count`` is composed exactly once, as an ``int``
    """
    specs = [spec for spec in composed_field_specs(typed_model("reference_images")) if spec.name == "images_count"]

    assert [spec.type for spec in specs] == ["int"]


def test_a_tutorial_document_composes_no_images_count() -> None:
    """The other direction: a Tutorial does not compose the ReferenceImages-only ``images_count``
    ([[field-schema#resource-types]], #195).

    Asserted over the declaration as well as the composed names: #196 gave ``images_count`` its ``int``
    field spec, and this pair of assertions is what pins that it gained it on
    ReferenceImages alone rather than on the one shared list.

    **Test steps:**

    * verify a Tutorial composes its own durations and ``level``
    * verify neither the composed specs nor the Tutorial declaration names ``images_count``
    """
    names = composed_names(typed_model("tutorial"))

    assert "advertised_duration" in names
    assert "level" in names
    assert "images_count" not in names
    assert "images_count" not in TUTORIAL_PLUGIN.field_names


def test_a_collection_composes_the_common_core_and_none_of_the_resource_fields() -> None:
    """A Collection declares no fields of its own, so it composes the common core and stops
    ([[field-schema#resource-types]], #195).

    A series node is not something rated, marked viewed, or filed under a learning path -- so none of
    the fields Tutorial and ReferenceImages share appear on it either. Which fields the type eventually
    gains is deferred until a real collection is in hand ([[field-schema#deferred-items]]).

    **Test steps:**

    * compose the record fields for a ``collection`` document
    * verify every composed name is a common-core one
    * verify the shared resource fields, the durations, and ``level`` are all absent
    """
    names = composed_names(typed_model("collection"))

    assert names
    assert all(name in CORE_FIELD_NAMES for name in names)
    for absent in ("rating", "complete", "collections", "learning_paths", "level", "current_duration"):
        assert absent not in names


def test_a_not_installed_type_composes_the_common_core_and_falls_back_for_its_whole_block() -> None:
    """A type with no plugin installed here keeps today's behavior: its block's keys reach the generic
    fallback rows ([[plugins#fallback-editor]], #195).

    The guard against a narrowed field list *swallowing* a value: a ``daz3d`` block's ``level`` renders
    on no type, so recognition has to narrow with the composition -- the same declaration answers both,
    and an undeclared key surfaces as an unknown field the user can read and drop.

    **Test steps:**

    * compose over a ``daz3d`` document whose block holds a Tutorial-only key and a foreign one
    * verify only common-core fields compose
    * verify **both** block keys reach the unknown-field fallback
    """
    model = typed_model("daz3d", {"daz3d": {"level": ["any"], "sku": "12345"}})

    assert all(name in CORE_FIELD_NAMES for name in composed_names(model))
    assert model.unknown_field_names() == ["level", "sku"]


def test_a_stray_field_of_another_type_falls_back_rather_than_going_unrendered() -> None:
    """A field its own type doesn't declare is surfaced through the fallback, not swallowed -- and is
    carried verbatim either way (#195).

    The model's `SimpleProperty` set stays whole, so it is the *composition* that is per-type, not the
    view-model: a Tutorial carrying a stray ``images_count`` still round-trips it, and the block's own
    keys are what the fallback reports.

    **Test steps:**

    * verify a Tutorial block's ``images_count`` reads as an unknown field
    * verify a ReferenceImages block's ``level`` does the same, in the other direction
    """
    tutorial = typed_model("tutorial", {"tutorial": {"images_count": 3, "level": ["any"]}})
    reference_images = typed_model("reference_images", {"reference_images": {"images_count": 3, "level": ["any"]}})

    assert tutorial.unknown_field_names() == ["images_count"]
    assert reference_images.unknown_field_names() == ["level"]


def test_a_type_switch_recomposes_to_the_incoming_types_fields_and_back() -> None:
    """Switching the type re-resolves the composition to the incoming type's declaration, both ways
    ([[plugins#plugin-blocks]], #83, #195).

    A type switch already drives a full rebuild through ``active_block_changed``; this extends *what*
    gets rebuilt rather than adding a seam, so the durations leave on the way to ReferenceImages and
    come back on the way home.

    **Test steps:**

    * compose over a Tutorial, then switch the type to ``reference_images`` and recompose
    * verify the durations and ``level`` are gone
    * switch back and verify they return
    """
    model = typed_model("tutorial")
    assert "current_duration" in composed_names(model)

    model.resource_type = "reference_images"

    names = composed_names(model)
    assert "current_duration" not in names
    assert "level" not in names

    model.resource_type = "tutorial"

    assert "current_duration" in composed_names(model)
    assert "level" in composed_names(model)


def test_every_declared_field_spec_is_claimed_by_the_core_or_a_plugin() -> None:
    """No entry in the toolkit-type map renders on **no** type ([[field-schema#resource-types]], #195).

    Guards the hole this slice found: ``images_count`` was declared on the model and coerced by core
    while no `FieldSpec` named it, so it rendered nowhere. This pins the reverse -- a spec whose name no
    declaration claims is composed for no type at all, which is the same defect seen from the other end.

    **Test steps:**

    * collect every name the core and the shipped plugins declare
    * verify each entry in the toolkit-type map is one of them
    """
    declared = {*CORE_FIELD_NAMES, *(name for plugin in BUILTIN_PLUGINS for name in plugin.field_names)}

    assert {spec.name for spec in MODEL_AGNOSTIC_FIELD_SPECS} <= declared


# endregion
