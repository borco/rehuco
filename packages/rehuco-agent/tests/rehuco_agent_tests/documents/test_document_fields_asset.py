"""Tests for the fields an asset composes (#678): every field of its block but the ones a dock of their own edits has
a spec, in the order the form shows them, and each spec builds a viewer and an editor over an asset's model."""

from typing import Final

from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_fields import (
    MODEL_AGNOSTIC_FIELD_SPECS,
    composed_field_specs,
    declared_field_names,
)
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields import FieldRegistry
from rehuco_core import ASSET_FIELD_NAMES, RehuDocument

from rehuco_agent_tests.fields.field_testers import TEST_EDITOR_TAB, TEST_VIEWER_TAB

DOCK_FIELD_NAMES: Final = frozenset({"licenses"})
"""The asset fields the Main Editor never shows: its licenses are edited in the License dock (#705)."""

FORM_FIELD_NAMES: Final = tuple(name for name in ASSET_FIELD_NAMES if name not in DOCK_FIELD_NAMES)
"""The asset fields the Main Editor shows, each through a spec."""


def asset_model() -> RehuDocumentModel:
    """A view-model over an asset.

    :returns: the model.
    """
    return RehuDocumentModel(RehuDocument({"core": {"type": "asset"}}))


def test_every_field_an_asset_declares_has_a_spec() -> None:
    """A declared field with no spec renders nowhere -- the fallback editor skips it too -- so the asset's declaration
    and the specs are held together from this side (#678).

    **Test steps:**

    * compose the fields of an asset
    * verify every field of its block but its licenses, and the shared ones it takes, is the name of a spec
    * verify its licenses are not: they are the License dock's
    """
    model = asset_model()
    names = {name for spec in composed_field_specs(model) for name in spec.names}

    assert set(FORM_FIELD_NAMES) <= names
    assert not DOCK_FIELD_NAMES & names
    assert {"rating", "online", "favorite", "collections"} <= names
    assert names <= declared_field_names(model)


def test_an_asset_shows_its_fields_after_the_shared_ones_they_follow() -> None:
    """The asset's fields come in the order they are read: what it is, its formats and compatibility, then its dates,
    versions and sizes; its dates beside the release date.

    **Test steps:**

    * compose the fields of an asset
    * verify the order of its own fields, and that its dates follow ``released``
    """
    names = [spec.name for spec in composed_field_specs(asset_model())]

    assert [name for name in names if name in ASSET_FIELD_NAMES] == [
        "source_updated",
        "acquired",
        "kind",
        "formats",
        "compatibility",
        "advertised_version",
        "current_version",
        "advertised_size",
        "advertised_triangles",
        "advertised_texture_size",
        "triangles",
        "texture_size",
    ]
    assert names.index("released") < names.index("source_updated")


def test_no_other_type_composes_an_assets_fields() -> None:
    """A tutorial and a reference pack show none of them: the plugin's declaration is what composes a field.

    **Test steps:**

    * compose the fields of a tutorial and of a reference pack
    * verify neither holds an asset field
    """
    for resource_type in ("tutorial", "reference_images"):
        model = RehuDocumentModel(RehuDocument({"core": {"type": resource_type}}))
        assert not {spec.name for spec in composed_field_specs(model)} & set(ASSET_FIELD_NAMES)


def test_each_spec_of_an_asset_builds_a_viewer_and_an_editor(qtbot: QtBot) -> None:
    """The toolkit type of each spec is registered and takes the arguments its spec gives.

    **Test steps:**

    * for each spec an asset composes beyond the ones built by hand, create its field
    * build its viewer and editor over the asset's model
    * verify a viewer was made for each
    """
    model = asset_model()
    registry = FieldRegistry()
    own = [spec for spec in MODEL_AGNOSTIC_FIELD_SPECS if spec.name in ASSET_FIELD_NAMES]
    assert len(own) == len(FORM_FIELD_NAMES)

    for spec in own:
        field = registry.create(
            spec.type, spec.name, viewer_tab=TEST_VIEWER_TAB, editor_tab=TEST_EDITOR_TAB, **spec.kwargs
        )
        binding = model.bind(field)
        viewer = field.make_viewer(binding).viewer
        editor = field.make_editor(binding).editor
        qtbot.addWidget(viewer)
        qtbot.addWidget(editor)
        assert isinstance(viewer, QLabel)
        assert editor is not None
