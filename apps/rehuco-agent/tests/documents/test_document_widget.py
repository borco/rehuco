"""Tests for the per-document viewer/editor docks.

Editor/viewer live-binding itself ("both") is already covered at the `Field`/`FieldsForm` level
(``tests/fields/test_text_field.py``); these tests cover what's specific to :class:`DocumentWidget`:
that it wires two real docks from one model, exposes toggle actions for them, and stashes/restores
the closed-dock-size workaround ([[packaging-deployment#qml-regression]]).
"""

from pathlib import Path
from typing import Final

import cbor2
import PySide6QtAds as QtAds
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QLabel, QLineEdit, QMessageBox
from pytest import fixture, raises
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_fields import EDITOR_MAIN_TAB, VIEWER_TAB
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields import FieldsTab
from rehuco_agent.fields.widgets import PathEditor
from rehuco_core import CURRENT_FORMAT_VERSION, RehuDocument

TC_PATH: Final = Path("/fake/info.tc")
TARGET_PATH: Final = Path("/fake/info.rehu")


# region fixtures
@fixture
def model() -> RehuDocumentModel:
    """A view-model seeded with a primary source, for the docks to bind to."""
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


@fixture
def legacy_model() -> RehuDocumentModel:
    """A view-model wrapping a legacy ``.tc``-backed document, locked for conversion."""
    return RehuDocumentModel(
        RehuDocument({"type": "Tutorial", "sources": [{"title": "Foo", "primary": True}]}, TC_PATH, legacy_tc=True)
    )


@fixture
def legacy_widget(qtbot: QtBot, legacy_model: RehuDocumentModel) -> DocumentWidget:
    """A constructed :class:`DocumentWidget` over the legacy ``.tc``-backed model, registered for teardown."""
    widget = DocumentWidget(legacy_model)
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
    """Both docks are built from the same document field list (title/publisher/url + flags).

    **Test steps:**

    * build a widget over the sample model
    * verify the text editors (``QLineEdit``) are seeded with the model's current values (a subset,
      since the spin-box editors carry their own internal line edits)
    * verify viewer labels (``QLabel``) show the same values (a subset; the ``url`` viewer renders
      as a hyperlink, not plain text, so it's checked separately) -- distinguishing them from the
      form's own row-label widgets, which show the field names, never the values
    """
    editor_texts = {editor.text() for editor in widget.findChildren(QLineEdit)}
    assert {"Foo", "Bar", "https://example.com"} <= editor_texts

    viewer_texts = {label.text() for label in widget.findChildren(QLabel)}
    assert {"Foo", "Bar"} <= viewer_texts
    assert '<a href="https://example.com">https://example.com</a>' in viewer_texts


def test_save_action_triggers_the_models_save(
    mocker: MockerFixture, widget: DocumentWidget, model: RehuDocumentModel
) -> None:
    """The save action calls the model's ``save()`` and carries the platform save shortcut.

    **Test steps:**

    * mock ``model.save``
    * dirty the model, so the (otherwise-disabled, #41) save action can actually fire
    * verify the action's shortcut is the platform's standard "Save" key sequence
    * trigger the save action
    * verify ``save`` was called
    """
    save = mocker.patch.object(model, "save")
    model.title = "New Title"

    assert widget.save_action.shortcut() == QKeySequence(QKeySequence.StandardKey.Save)

    widget.save_action.trigger()

    save.assert_called_once_with()


def test_save_action_is_scoped_to_this_widgets_own_subtree(widget: DocumentWidget) -> None:
    """The save action's shortcut is scoped per-widget, not to the shared top-level window (#41).

    A plain ``WindowShortcut`` (the default) resolves to the single real top-level window every
    open document shares -- with two documents dirty at once, Qt would see two enabled actions on
    the same key sequence in that one scope and call it ambiguous, firing neither. Scoping to this
    widget's own subtree (``WidgetWithChildrenShortcut``) means the shortcut only fires for
    whichever document actually has focus (confirmed empirically before this fix landed).

    **Test steps:**

    * verify the save action's shortcut context is ``WidgetWithChildrenShortcut``
    """
    assert widget.save_action.shortcutContext() == Qt.ShortcutContext.WidgetWithChildrenShortcut


def test_revert_action_triggers_the_models_revert(
    mocker: MockerFixture, widget: DocumentWidget, model: RehuDocumentModel
) -> None:
    """The revert action calls the model's ``revert()`` (#41).

    **Test steps:**

    * mock ``model.revert``
    * trigger the revert action (enabled unconditionally, not gated on dirty)
    * verify ``revert`` was called
    """
    revert = mocker.patch.object(model, "revert")

    widget.revert_action.trigger()

    revert.assert_called_once_with()


def test_save_starts_disabled_and_revert_starts_enabled_on_a_clean_model(widget: DocumentWidget) -> None:
    """Save starts disabled (nothing to save yet); revert starts enabled regardless (#41).

    Revert also serves picking up an out-of-band change on a *clean* document, so it isn't gated on
    dirty the way save is.

    **Test steps:**

    * build a widget over a freshly-seeded (clean) model
    * verify save reports disabled and revert reports enabled
    """
    assert widget.save_action.isEnabled() is False
    assert widget.revert_action.isEnabled() is True


def test_save_enables_and_disables_with_dirty_while_revert_stays_enabled(
    widget: DocumentWidget, model: RehuDocumentModel
) -> None:
    """Save tracks the model's dirty flag live; revert is unaffected by it either way (#41).

    **Test steps:**

    * dirty the model and verify save enables while revert stays enabled
    * clean the model (as ``save()`` would) and verify save disables again while revert still stays enabled
    """
    model.title = "New Title"
    assert widget.save_action.isEnabled() is True
    assert widget.revert_action.isEnabled() is True

    model.dirty = False
    assert widget.save_action.isEnabled() is False
    assert widget.revert_action.isEnabled() is True


def test_editors_start_disabled_on_a_locked_model(qtbot: QtBot) -> None:
    """A model locked at construction (A3, [[data-model#schema-version]]) starts with its editor
    controls disabled, so a newer-format-version file can't be edited unsafely.

    **Test steps:**

    * build a model over a document whose ``format_version`` is newer than this build understands
    * build a widget over it
    * verify every editor ``QLineEdit`` reports disabled (cascades from the disabled editor dock content)
    """
    newer_version = CURRENT_FORMAT_VERSION + 1
    locked_model = RehuDocumentModel(
        RehuDocument(
            {
                "type": "Tutorial",
                "format_version": newer_version,
                "sources": [{"title": "Foo", "publisher": "Bar", "url": "https://example.com", "primary": True}],
            }
        )
    )
    locked_widget = DocumentWidget(locked_model)
    qtbot.addWidget(locked_widget)

    editors = locked_widget.findChildren(QLineEdit)
    assert editors
    assert all(not editor.isEnabled() for editor in editors)


def test_editors_disable_and_reenable_as_locked_changes(widget: DocumentWidget, model: RehuDocumentModel) -> None:
    """The editor controls track the model's ``locked`` flag live, same as save tracks dirty.

    **Test steps:**

    * lock the model and verify every editor disables
    * unlock it again and verify every editor re-enables
    """
    model.locked = True
    assert all(not editor.isEnabled() for editor in widget.findChildren(QLineEdit))

    model.locked = False
    assert all(editor.isEnabled() for editor in widget.findChildren(QLineEdit))


def test_normal_document_shows_save_revert_and_hides_convert_actions(widget: DocumentWidget) -> None:
    """A widget over a normal (non-legacy) document shows Save/Revert and hides both convert actions.

    **Test steps:**

    * build a widget over the sample (non-legacy) model
    * verify save/revert are visible and both convert actions are hidden
    """
    assert widget.save_action.isVisible() is True
    assert widget.revert_action.isVisible() is True
    keep_backups = widget._DocumentWidget__convert_keep_backups_action  # type: ignore[attr-defined]  # pylint: disable=protected-access
    discard = widget._DocumentWidget__convert_discard_originals_action  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert keep_backups.isVisible() is False
    assert discard.isVisible() is False


def test_legacy_document_hides_save_revert_and_shows_convert_actions(legacy_widget: DocumentWidget) -> None:
    """A widget over a legacy ``.tc``-backed document hides Save/Revert and shows both convert actions.

    Closes a latent crash for free: Revert would otherwise re-read the ``.tc`` path as JSON and raise.

    **Test steps:**

    * build a widget over a legacy model
    * verify save/revert are hidden and both convert actions are visible
    """
    assert legacy_widget.save_action.isVisible() is False
    assert legacy_widget.revert_action.isVisible() is False
    keep_backups = legacy_widget._DocumentWidget__convert_keep_backups_action  # type: ignore[attr-defined]  # pylint: disable=protected-access
    discard = legacy_widget._DocumentWidget__convert_discard_originals_action  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert keep_backups.isVisible() is True
    assert discard.isVisible() is True


def test_convert_action_with_no_existing_target_calls_model_convert(
    mocker: MockerFixture, legacy_widget: DocumentWidget, legacy_model: RehuDocumentModel
) -> None:
    """Triggering a convert action with no existing target ``.rehu`` (the common case) converts
    straight away, with no confirmation dialog.

    **Test steps:**

    * mock ``model.convert`` (the target path genuinely doesn't exist on this machine, so no
      ``Path.exists`` mocking is needed)
    * trigger the "keep backups" convert action
    * verify ``model.convert`` was called with ``keep_backups=True, overwrite=False``
    """
    convert = mocker.patch.object(legacy_model, "convert")
    keep_backups = legacy_widget._DocumentWidget__convert_keep_backups_action  # type: ignore[attr-defined]  # pylint: disable=protected-access

    keep_backups.trigger()

    convert.assert_called_once_with(keep_backups=True, overwrite=False)


def test_convert_action_prompts_before_overwriting_and_cancels_on_no(
    mocker: MockerFixture, legacy_widget: DocumentWidget, legacy_model: RehuDocumentModel
) -> None:
    """Triggering a convert action when the target ``.rehu`` already exists prompts first; answering
    No leaves the document unconverted.

    **Test steps:**

    * mock the target path as already existing and the warning dialog to answer No
    * trigger the "discard originals" convert action
    * verify ``model.convert`` was never called
    """
    mocker.patch.object(Path, "exists", autospec=True, side_effect=lambda self: self == TARGET_PATH)
    mocker.patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.No)
    convert = mocker.patch.object(legacy_model, "convert")
    discard = legacy_widget._DocumentWidget__convert_discard_originals_action  # type: ignore[attr-defined]  # pylint: disable=protected-access

    discard.trigger()

    convert.assert_not_called()


def test_convert_action_prompts_before_overwriting_and_proceeds_on_yes(
    mocker: MockerFixture, legacy_widget: DocumentWidget, legacy_model: RehuDocumentModel
) -> None:
    """Answering Yes to the overwrite prompt proceeds with ``overwrite=True``.

    **Test steps:**

    * mock the target path as already existing and the warning dialog to answer Yes
    * trigger the "discard originals" convert action
    * verify ``model.convert`` was called with ``overwrite=True``
    """
    mocker.patch.object(Path, "exists", autospec=True, side_effect=lambda self: self == TARGET_PATH)
    mocker.patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Yes)
    convert = mocker.patch.object(legacy_model, "convert")
    discard = legacy_widget._DocumentWidget__convert_discard_originals_action  # type: ignore[attr-defined]  # pylint: disable=protected-access

    discard.trigger()

    convert.assert_called_once_with(keep_backups=False, overwrite=True)


def test_convert_action_shows_a_critical_dialog_on_failure(
    mocker: MockerFixture, legacy_widget: DocumentWidget, legacy_model: RehuDocumentModel
) -> None:
    """A conversion failure shows a critical dialog instead of propagating.

    **Test steps:**

    * mock ``model.convert`` to raise ``OSError``
    * mock the critical dialog
    * trigger a convert action
    * verify the critical dialog was shown
    """
    mocker.patch.object(legacy_model, "convert", side_effect=OSError("disk full"))
    critical = mocker.patch.object(QMessageBox, "critical")
    keep_backups = legacy_widget._DocumentWidget__convert_keep_backups_action  # type: ignore[attr-defined]  # pylint: disable=protected-access

    keep_backups.trigger()

    critical.assert_called_once()


def test_successful_convert_flips_the_toolbar_back_to_save_revert(
    mocker: MockerFixture, legacy_widget: DocumentWidget, legacy_model: RehuDocumentModel
) -> None:
    """A real, successful conversion flips the toolbar in place: Save/Revert reappear, the convert
    actions hide, with no new dock and no reload round-trip.

    **Test steps:**

    * mock ``convert_tc`` (the underlying core call ``model.convert`` delegates to) to return a
      fresh, unlocked document
    * trigger a convert action for real
    * verify save/revert are visible again and both convert actions are hidden
    """
    converted = RehuDocument({"type": "Tutorial", "sources": [{"title": "Foo", "primary": True}]}, TARGET_PATH)
    mocker.patch("rehuco_agent.documents.rehu_document_model.convert_tc", return_value=converted)
    keep_backups = legacy_widget._DocumentWidget__convert_keep_backups_action  # type: ignore[attr-defined]  # pylint: disable=protected-access

    keep_backups.trigger()

    assert legacy_model.locked is False
    assert legacy_widget.save_action.isVisible() is True
    assert legacy_widget.revert_action.isVisible() is True
    assert keep_backups.isVisible() is False
    discard = legacy_widget._DocumentWidget__convert_discard_originals_action  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert discard.isVisible() is False


def test_toggle_actions_start_checked_and_toggle_off(widget: DocumentWidget) -> None:
    """The viewer/editor toggle actions are checkable and start checked (both docks visible).

    **Test steps:**

    * build a widget
    * verify both toggle actions report checked (their docks are shown by default)
    * trigger the editor action and verify it reports unchecked
    """
    assert widget.toggle_action(VIEWER_TAB).isChecked() is True
    assert widget.toggle_action(EDITOR_MAIN_TAB).isChecked() is True

    widget.toggle_action(EDITOR_MAIN_TAB).trigger()

    assert widget.toggle_action(EDITOR_MAIN_TAB).isChecked() is False


def test_toggle_action_raises_for_a_tab_no_dock_hosts(widget: DocumentWidget) -> None:
    """Asking for the toggle action of a tab that neither the viewer nor editor hosts raises ``KeyError``.

    **Test steps:**

    * build a widget and ask for the toggle action of an unrelated tab
    * verify it raises ``KeyError``
    """
    with raises(KeyError):
        widget.toggle_action(FieldsTab("Nonexistent", ":/nope.svg"))


def test_adding_docks_from_an_empty_grid_map_builds_nothing(widget: DocumentWidget) -> None:
    """Building docks from an empty ``{tab: grid}`` mapping adds no docks and selects no current tab.

    **Test steps:**

    * invoke the dock builder with an empty grid map
    * verify it returns an empty mapping (the ``setAsCurrentTab`` step is skipped)
    """
    docks = widget._DocumentWidget__add_docks({}, "viewer", QtAds.LeftDockWidgetArea)  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert docks == {}


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
    widget.toggle_action(EDITOR_MAIN_TAB).trigger()

    stashed = widget._DocumentWidget__stashed_sizes  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert "editor:Main Editor" in stashed


def test_reopening_a_toggled_dock_restores_its_splitter_sizes(widget: DocumentWidget) -> None:
    """Showing a dock again re-applies its stashed splitter sizes.

    Exercises the closed-dock-size workaround's restore half ([[packaging-deployment#qml-regression]]).

    **Test steps:**

    * hide the editor dock (stashes its sizes), then show it again (``viewToggled(True)``)
    * verify the toggle action reports checked again and the stash still holds the entry it restored from
    """
    widget.toggle_action(EDITOR_MAIN_TAB).trigger()
    widget.toggle_action(EDITOR_MAIN_TAB).trigger()

    assert widget.toggle_action(EDITOR_MAIN_TAB).isChecked() is True
    stashed = widget._DocumentWidget__stashed_sizes  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert "editor:Main Editor" in stashed


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
    widget.toggle_action(EDITOR_MAIN_TAB).trigger()

    state = widget.save_state()

    assert widget.restore_state(state) is True
    stashed = widget._DocumentWidget__stashed_sizes  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert "editor:Main Editor" in stashed


def test_restore_state_reselects_the_dock_that_was_current(widget: DocumentWidget) -> None:
    """The dock (viewer/editor) that was current is re-selected on restore, even when split.

    QtAds' own ``restoreState`` recovers only the current tab within each area, not which of the two
    split areas held focus -- so this covers the extra state ``QtAdsFocusTracker.save_state`` adds
    for that (the reported bug: a split editor/viewer always came back with the viewer current).

    **Test steps:**

    * make the editor the current dock, and save the state
    * move current away to the viewer, then restore the saved state
    * verify the editor is the current dock again, not the viewer it had moved to
    """
    manager = widget._DocumentWidget__dock_manager  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    tracker = widget._DocumentWidget__tracker  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    tracker.set_current_dock(manager.findDockWidget("editor:Main Editor"))
    state = widget.save_state()
    tracker.set_current_dock(manager.findDockWidget("viewer:Viewer"))
    assert tracker.current_dock.objectName() == "viewer:Viewer"

    assert widget.restore_state(state) is True

    assert tracker.current_dock.objectName() == "editor:Main Editor"


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


def test_restore_state_rejects_an_incompatible_version_and_keeps_docks_visible(widget: DocumentWidget) -> None:
    """A blob from an incompatible schema version is ignored, keeping the default all-visible layout.

    An older blob (e.g. from before the docks were renamed, #26) would otherwise ``restoreState``
    cleanly yet hide the current docks -- a blank window -- and a subsequently shown dock would float.

    **Test steps:**

    * save the widget's real state, then strip its ``version`` key (as an older blob would lack it)
    * verify restore reports failure and both docks stay visible
    """
    payload = cbor2.loads(widget.save_state())
    del payload["version"]

    assert widget.restore_state(cbor2.dumps(payload)) is False
    assert widget.toggle_action(VIEWER_TAB).isChecked() is True
    assert widget.toggle_action(EDITOR_MAIN_TAB).isChecked() is True


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


# region location path field
def location_editor(widget: DocumentWidget) -> PathEditor:
    """Return the widget's editor-dock location `PathEditor`.

    :param widget: the document widget to inspect.
    :returns: the location field's editor.
    """
    editors = widget.findChildren(PathEditor)
    assert len(editors) == 1
    return editors[0]


def test_save_state_round_trips_the_path_field_expand_state(qtbot: QtBot, widget: DocumentWidget) -> None:
    """The location field's expand state is persisted per-``.rehu`` and restored on a fresh widget.

    **Test steps:**

    * expand the location editor and save the widget's state
    * build a fresh widget (collapsed) and restore that state
    * verify the fresh widget's location editor is now expanded
    """
    location_editor(widget).expanded = True
    state = widget.save_state()

    fresh = DocumentWidget(
        RehuDocumentModel(RehuDocument({"type": "Tutorial", "sources": [{"title": "Foo", "primary": True}]}))
    )
    qtbot.addWidget(fresh)
    assert location_editor(fresh).expanded is False

    fresh.restore_state(state)

    assert location_editor(fresh).expanded is True


def test_restore_state_tolerates_a_payload_without_widget_state(widget: DocumentWidget) -> None:
    """A dict payload missing the per-widget state entry still restores cleanly.

    **Test steps:**

    * save the widget's real state, then strip its ``widget_state`` entry
    * verify ``restore_state`` still reports success
    """
    payload = cbor2.loads(widget.save_state())
    del payload["widget_state"]

    assert widget.restore_state(cbor2.dumps(payload)) is True


def test_restore_state_ignores_a_widget_state_entry_for_an_unknown_widget(widget: DocumentWidget) -> None:
    """A saved widget-state entry naming no current widget is ignored, and the known one still applies.

    **Test steps:**

    * save state, then add a bogus widget name to the ``widget_state`` entry and expand the real one
    * restore it and verify the real editor expanded and no error was raised for the bogus name
    """
    payload = cbor2.loads(widget.save_state())
    payload["widget_state"] = {"location": b"\x01", "no_such_widget": b"\x01"}

    assert widget.restore_state(cbor2.dumps(payload)) is True
    assert location_editor(widget).expanded is True


def test_clicking_a_location_suggestion_renames_through_the_model(
    mocker: MockerFixture, widget: DocumentWidget, model: RehuDocumentModel
) -> None:
    """Activating a location rename suggestion calls ``model.rename_location`` with its name.

    **Test steps:**

    * patch ``model.rename_location`` and find a suggestion label on the location editor
    * activate its link and verify the model was asked to rename to that suggestion
    """
    rename = mocker.patch.object(model, "rename_location")
    editor = location_editor(widget)
    labels = editor._PathEditor__suggestion_labels  # type: ignore[attr-defined]  # pylint: disable=protected-access
    name, label = next(iter(labels.items()))

    label.linkActivated.emit("#")

    rename.assert_called_once_with(name)


# endregion
