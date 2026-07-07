"""Tests for the per-document viewer/editor dock surfaces.

Editor/viewer live-binding itself ("both") is already covered at the `Field`/`FieldsForm` level
(``tests/fields/test_text_field.py``); these tests cover what's specific to :class:`DocumentWidget`:
that it wires two real surfaces from one model, exposes toggle actions for them, and stashes/restores
the closed-dock-size workaround ([[packaging-deployment#qml-regression]]).
"""

import cbor2
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QLabel, QLineEdit
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_core import RehuDocument


# region fixtures
@fixture
def model() -> RehuDocumentModel:
    """A view-model seeded with a primary source, for the surfaces to bind to."""
    # matches fields/conftest.py's `model` fixture by design (same sample document shape); this
    # file lives outside that conftest's directory, so pytest won't pick it up, and duplicating
    # the shape here is more appropriate than an awkward cross-directory conftest import for one fixture
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
def widget(qtbot: QtBot, model: RehuDocumentModel) -> DocumentWidget:
    """A constructed :class:`DocumentWidget` over the sample model, registered for teardown."""
    widget = DocumentWidget(model)
    qtbot.addWidget(widget)
    return widget


# endregion


# region DocumentWidget tests
def test_model_property_exposes_the_wrapped_model(widget: DocumentWidget, model: RehuDocumentModel) -> None:
    """The widget exposes the view-model it was constructed with by identity.

    **Test steps:**

    * build a widget over a model
    * verify ``widget.model`` is that exact model
    """
    assert widget.model is model


def test_builds_a_viewer_and_an_editor_from_the_document_field_list(widget: DocumentWidget) -> None:
    """Both surfaces are built from the same document field list (title/publisher/url).

    **Test steps:**

    * build a widget over the sample model
    * verify three editors (``QLineEdit``) exist, seeded with the model's current values
    * verify viewer labels (``QLabel``) show the same three values (distinguishing them from the
      form's own row-label widgets, which show the field names, never the values)
    """
    editor_texts = {editor.text() for editor in widget.findChildren(QLineEdit)}
    assert editor_texts == {"Foo", "Bar", "https://example.com"}

    viewer_texts = {label.text() for label in widget.findChildren(QLabel)}
    assert {"Foo", "Bar", "https://example.com"} <= viewer_texts


def test_save_action_triggers_the_models_save(
    mocker: MockerFixture, widget: DocumentWidget, model: RehuDocumentModel
) -> None:
    """The save action calls the model's ``save()`` and carries the platform save shortcut.

    **Test steps:**

    * mock ``model.save``
    * verify the action's shortcut is the platform's standard "Save" key sequence
    * trigger the save action
    * verify ``save`` was called
    """
    save = mocker.patch.object(model, "save")

    assert widget.save_action.shortcut() == QKeySequence(QKeySequence.StandardKey.Save)

    widget.save_action.trigger()

    save.assert_called_once_with()


def test_toggle_actions_start_checked_and_toggle_off(widget: DocumentWidget) -> None:
    """The viewer/editor toggle actions are checkable and start checked (both surfaces visible).

    **Test steps:**

    * build a widget
    * verify both toggle actions report checked (their docks are shown by default)
    * trigger the editor action and verify it reports unchecked
    """
    assert widget.viewer_action.isChecked() is True
    assert widget.editor_action.isChecked() is True

    widget.editor_action.trigger()

    assert widget.editor_action.isChecked() is False


def test_closing_a_dock_stashes_its_splitter_sizes(widget: DocumentWidget) -> None:
    """Hiding a dock stashes its containing splitter's sizes, keyed by the dock's object name.

    Exercises the closed-dock-size workaround's stash half ([[packaging-deployment#qml-regression]]):
    reads back the private stash via its name-mangled attribute, the same style already used for
    ``Application`` stand-ins in ``tests/test_app.py``, since :class:`DocumentWidget` deliberately
    doesn't expose its docks (only the toggle actions).

    **Test steps:**

    * build a widget, then trigger the editor toggle action off (hides its dock, firing
      ``viewToggled(False)``)
    * verify the stash gained an entry keyed ``"editor"``
    """
    widget.editor_action.trigger()

    stashed = widget._DocumentWidget__stashed_sizes  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert "editor" in stashed


def test_reopening_a_toggled_dock_restores_its_splitter_sizes(widget: DocumentWidget) -> None:
    """Showing a dock again re-applies its stashed splitter sizes.

    Exercises the closed-dock-size workaround's restore half ([[packaging-deployment#qml-regression]]).

    **Test steps:**

    * hide the editor dock (stashes its sizes), then show it again (``viewToggled(True)``)
    * verify the toggle action reports checked again and the stash still holds the entry it restored from
    """
    widget.editor_action.trigger()
    widget.editor_action.trigger()

    assert widget.editor_action.isChecked() is True
    stashed = widget._DocumentWidget__stashed_sizes  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert "editor" in stashed


def test_stash_size_is_a_noop_for_a_dock_with_no_area(mocker: MockerFixture, widget: DocumentWidget) -> None:
    """Stashing a dock that currently has no containing area (e.g. already removed) does nothing.

    Calls the private stash helper directly with a stand-in dock, since a real ``CDockWidget``
    added via the normal flow always has an area -- this null case can't be reached through the
    public API.

    **Test steps:**

    * call the private stash helper with a stand-in dock reporting no area
    * verify the stash gained no entry for it
    """
    fake_dock = mocker.MagicMock()
    fake_dock.dockAreaWidget.return_value = None
    fake_dock.objectName.return_value = "orphaned"

    widget._DocumentWidget__stash_size(fake_dock)  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    stashed = widget._DocumentWidget__stashed_sizes  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert "orphaned" not in stashed


def test_restore_size_is_a_noop_for_a_dock_with_no_area(mocker: MockerFixture, widget: DocumentWidget) -> None:
    """Restoring a dock that currently has no containing area does nothing, even with a stashed entry.

    **Test steps:**

    * seed a stashed entry, then call the private restore helper with a stand-in dock reporting
      no area
    * verify ``setSplitterSizes`` was never called
    """
    stashed = widget._DocumentWidget__stashed_sizes  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    stashed["orphaned"] = [100, 200]
    fake_dock = mocker.MagicMock()
    fake_dock.dockAreaWidget.return_value = None
    fake_dock.objectName.return_value = "orphaned"
    dock_manager = widget._DocumentWidget__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    set_sizes = mocker.patch.object(dock_manager, "setSplitterSizes")

    widget._DocumentWidget__restore_size(fake_dock)  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    set_sizes.assert_not_called()


def test_save_state_round_trips_through_restore_state(widget: DocumentWidget) -> None:
    """A dock layout saved via ``save_state`` restores cleanly through ``restore_state``.

    **Test steps:**

    * hide the editor dock (so its stash and dock-manager state both reflect a change)
    * save the widget's state, then restore it into a fresh widget over the same model
    * verify the restore reports success and the stash carried over
    """
    widget.editor_action.trigger()

    state = widget.save_state()

    assert widget.restore_state(state) is True
    stashed = widget._DocumentWidget__stashed_sizes  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert "editor" in stashed


def test_restore_state_reselects_the_surface_that_was_current(widget: DocumentWidget) -> None:
    """The surface (viewer/editor) that was current is re-selected on restore, even when split.

    QtAds' own ``restoreState`` recovers only the current tab within each area, not which of the two
    split areas held focus -- so this covers the extra state ``QtAdsFocusTracker.save_state`` adds
    for that (the reported bug: a split editor/viewer always came back with the viewer current).

    **Test steps:**

    * make the editor the current surface, and save the state
    * move current away to the viewer, then restore the saved state
    * verify the editor is the current surface again, not the viewer it had moved to
    """
    manager = widget._DocumentWidget__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    tracker = widget._DocumentWidget__tracker  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    tracker.set_current_dock(manager.findDockWidget("editor"))
    state = widget.save_state()
    tracker.set_current_dock(manager.findDockWidget("viewer"))
    assert tracker.current_dock.objectName() == "viewer"

    assert widget.restore_state(state) is True

    assert tracker.current_dock.objectName() == "editor"


def test_restore_state_tolerates_a_non_bytes_current_dock_entry(widget: DocumentWidget) -> None:
    """A dict payload whose ``current_dock`` entry isn't bytes is ignored, not fed to the tracker.

    **Test steps:**

    * save the widget's real state, then replace its ``current_dock`` entry with a non-bytes value
    * call ``restore_state`` with that payload
    * verify it still reports success (the malformed current-dock entry was skipped)
    """
    payload = cbor2.loads(widget.save_state())
    payload["current_dock"] = 123

    assert widget.restore_state(cbor2.dumps(payload)) is True


def test_restore_state_rejects_malformed_bytes(widget: DocumentWidget) -> None:
    """Malformed (non-cbor2) bytes are rejected rather than raising.

    **Test steps:**

    * call ``restore_state`` with bytes that aren't valid cbor2
    * verify it reports failure
    """
    assert widget.restore_state(b"not cbor2") is False


def test_restore_state_rejects_a_non_dict_payload(widget: DocumentWidget) -> None:
    """A validly-encoded but wrongly-shaped payload (not a dict) is rejected rather than raising.

    **Test steps:**

    * call ``restore_state`` with cbor2-encoded bytes that decode to a list, not a dict
    * verify it reports failure
    """
    assert widget.restore_state(cbor2.dumps([1, 2, 3])) is False


def test_restore_state_rejects_a_dict_with_garbage_dock_manager_bytes(widget: DocumentWidget) -> None:
    """A validly-encoded dict payload whose dock-manager bytes aren't a real saved state is
    rejected by QtAds's own ``restoreState``, rather than refreshing the toggle icons for it.

    **Test steps:**

    * call ``restore_state`` with a dict payload whose ``dock_manager`` entry is garbage bytes
    * verify it reports failure
    """
    payload = cbor2.loads(widget.save_state())
    payload["dock_manager"] = b"not a real dock manager state"

    assert widget.restore_state(cbor2.dumps(payload)) is False


def test_restore_state_tolerates_a_payload_without_stashed_sizes(widget: DocumentWidget) -> None:
    """A dict payload missing the stashed-sizes entry still restores the dock manager's own state.

    **Test steps:**

    * save the widget's real state, then strip its ``stashed_sizes`` entry
    * call ``restore_state`` with that payload
    * verify it still reports success and leaves the (empty) stash untouched
    """
    payload = cbor2.loads(widget.save_state())
    del payload["stashed_sizes"]

    assert widget.restore_state(cbor2.dumps(payload)) is True
    stashed = widget._DocumentWidget__stashed_sizes  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert not stashed


# endregion
