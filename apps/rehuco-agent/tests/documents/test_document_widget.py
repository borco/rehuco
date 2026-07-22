"""Tests for the per-document viewer/editor docks.

Editor/viewer live-binding itself ("both") is already covered at the `Field`/`FieldsForm` level
(``tests/fields/test_text_field.py``); these tests cover what's specific to :class:`DocumentWidget`:
that it wires two real docks from one model, exposes toggle actions for them, and stashes/restores
the closed-dock-size workaround ([[packaging-deployment#qml-regression]]).
"""

# one cohesive suite over DocumentWidget's docks/toolbar/banner/inspection surfaces; a scoped disable
# reads better than an arbitrary split (same precedent as test_rehu_document_model.py).
# pylint: disable=too-many-lines

import json
from pathlib import Path
from typing import Final

import cbor2
import PySide6QtAds as QtAds
from borco_pyside.theming import ActionIconThemeHandler, read_resource_bytes
from borco_pyside.widgets import MessageBanner
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QLabel, QLineEdit, QMessageBox, QToolBar
from pytest import fixture, raises
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_fields import EDITOR_MAIN_TAB, VIEWER_TAB
from rehuco_agent.documents.document_widget import (
    ON_DISK_ICON_RESOURCE,
    SAVE_PREVIEW_ICON_RESOURCE,
    DocumentWidget,
)
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields import PROVENANCE_ABANDONED_TYPE, FieldsForm, FieldsTab
from rehuco_agent.fields.widgets import PathEditor, SingleChoiceComboBox
from rehuco_core import CURRENT_FORMAT_VERSION, LockReason, LockReasonKind, RehuDocument

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


@fixture
def older_model(mocker: MockerFixture) -> RehuDocumentModel:
    """A view-model wrapping a document loaded from an older-format file -- clean, hence upgradable (#89)."""
    mocker.patch.object(
        Path,
        "read_text",
        return_value=json.dumps(
            {"format_version": 1, "type": "Tutorial", "sources": [{"title": "Foo", "primary": True}]}
        ),
    )
    return RehuDocumentModel(RehuDocument.load(Path("/fake/info.rehu")))


@fixture
def older_widget(qtbot: QtBot, older_model: RehuDocumentModel) -> DocumentWidget:
    """A constructed :class:`DocumentWidget` over the older-format model, registered for teardown."""
    widget = DocumentWidget(older_model)
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


def test_a_field_status_message_bubbles_up_through_the_widget(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A field's transient status message (the ``authors`` viewer's hovered-link URL) is re-emitted by the
    widget for the owner above to route -- the widget never drives a status bar of its own (the
    ``.window()`` trap; it reads as its own top-level ``QMainWindow`` while embedded in a dock).

    **Test steps:**

    * seed one ``authors`` record with a URL, so its viewer renders a hoverable anchor
    * build the widget and locate that anchor's ``QLabel``
    * record the widget's ``status_message`` emissions and emit the label's ``linkHovered``
    * verify the href surfaced on the widget's own signal
    """
    model.authors = [{"name": "Alice", "url": "https://example.com/alice"}]
    widget = DocumentWidget(model)
    qtbot.addWidget(widget)

    label = next(child for child in widget.findChildren(QLabel) if 'href="https://example.com/alice"' in child.text())
    messages: list[str] = []
    widget.status_message.connect(messages.append)

    label.linkHovered.emit("https://example.com/alice")

    assert messages == ["https://example.com/alice"]


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
    """The editor controls track the model's lock reasons live, same as save tracks dirty.

    **Test steps:**

    * give the model a lock reason and verify every editor disables
    * clear the reasons again and verify every editor re-enables
    """
    model.lock_reasons = [LockReason(LockReasonKind.NEWER_FORMAT, "from a newer build")]
    assert all(not editor.isEnabled() for editor in widget.findChildren(QLineEdit))

    model.lock_reasons = []
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


# region inspection docks (#111)
def save_preview_dock(widget: DocumentWidget) -> QtAds.CDockWidget:
    """Return the widget's private Save Preview dock.

    :param widget: the document widget to inspect.
    :returns: the Save Preview `CDockWidget`.
    """
    return widget._DocumentWidget__save_preview_dock  # type: ignore[attr-defined]  # pylint: disable=protected-access


def on_disk_dock(widget: DocumentWidget) -> QtAds.CDockWidget:
    """Return the widget's private On Disk dock.

    :param widget: the document widget to inspect.
    :returns: the On Disk `CDockWidget`.
    """
    return widget._DocumentWidget__on_disk_dock  # type: ignore[attr-defined]  # pylint: disable=protected-access


def test_inspection_docks_exist_and_start_hidden(widget: DocumentWidget) -> None:
    """Both inspection docks (Save Preview, On Disk) are built, but hidden by default -- a first-run
    layout shows every other dock but these (#111).

    **Test steps:**

    * build a widget over the sample model
    * verify both docks' toggle actions report unchecked (hidden)
    """
    assert save_preview_dock(widget).toggleViewAction().isChecked() is False
    assert on_disk_dock(widget).toggleViewAction().isChecked() is False


def test_inspection_dock_toggles_carry_their_own_icons(widget: DocumentWidget) -> None:
    """Each inspection dock's toggle action is themed from its own SVG, like every other dock toggle (#111).

    **Test steps:**

    * for each dock, find the ``ActionIconThemeHandler`` instances parented to its toggle action
    * verify one was built from that dock's own icon SVG bytes
    """
    for dock, icon in (
        (save_preview_dock(widget), SAVE_PREVIEW_ICON_RESOURCE),
        (on_disk_dock(widget), ON_DISK_ICON_RESOURCE),
    ):
        handlers = dock.toggleViewAction().findChildren(ActionIconThemeHandler)
        svgs = {handler._ActionIconThemeHandler__svg for handler in handlers}  # type: ignore[attr-defined]  # pylint: disable=protected-access
        assert read_resource_bytes(icon) in svgs


def test_inspection_dock_toggles_are_on_the_toolbar(widget: DocumentWidget) -> None:
    """Both inspection docks' toggle actions sit on the View toolbar alongside the viewer/editor toggles (#111).

    **Test steps:**

    * gather every action across the widget's toolbars
    * verify both docks' toggle actions are among them
    """
    actions = {action for toolbar in widget.findChildren(QToolBar) for action in toolbar.actions()}
    assert save_preview_dock(widget).toggleViewAction() in actions
    assert on_disk_dock(widget).toggleViewAction() in actions


def test_building_the_inspection_docks_leaves_the_main_viewer_current(widget: DocumentWidget) -> None:
    """Adding the inspection docks doesn't disturb which viewer tab is current -- the main viewer stays
    current after both are built and hidden (#111).

    **Test steps:**

    * build a widget over the sample model (both inspection docks added, then hidden)
    * verify the main viewer dock is the current tab in its area, not an inspection dock
    """
    viewer = widget._DocumentWidget__viewer_docks[VIEWER_TAB]  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert viewer.isCurrentTab() is True  # pylint: disable=no-member  # inferred type is lost through the mangled-dict access


def test_restore_state_rejects_a_pre_inspection_dock_blob_and_keeps_them_hidden(widget: DocumentWidget) -> None:
    """A blob from before the inspection docks existed (an older ``version``) is ignored, keeping the
    default layout -- so both stay hidden rather than restoring to some invented state (#111).

    The ``STATE_VERSION`` bump is what draws that line: an older blob knows nothing of these docks.

    **Test steps:**

    * save the widget's real (v4) state, then roll its ``version`` back to the pre-inspection-dock 3
    * verify restore reports failure and both inspection docks are still hidden
    """
    payload = cbor2.loads(widget.save_state())
    payload["version"] = 3

    assert widget.restore_state(cbor2.dumps(payload)) is False
    assert save_preview_dock(widget).toggleViewAction().isChecked() is False
    assert on_disk_dock(widget).toggleViewAction().isChecked() is False


def test_inspection_docks_open_their_own_area_when_there_are_no_viewer_docks(
    qtbot: QtBot, mocker: MockerFixture, model: RehuDocumentModel
) -> None:
    """With no viewer docks to stack into, the inspection docks fall back to opening a fresh right-side
    area rather than centering on a viewer tab, and are still built and hidden (#111).

    The document form always emits viewer tabs in practice, so this exercises the defensive fallback by
    forcing an empty viewer set.

    **Test steps:**

    * build a widget whose viewer form is empty (``make_viewer`` patched to yield no tabs)
    * verify no viewer docks exist, yet both inspection docks were still built and start hidden
    """
    mocker.patch.object(FieldsForm, "make_viewer", return_value={})
    widget = DocumentWidget(model)
    qtbot.addWidget(widget)

    assert widget._DocumentWidget__viewer_docks == {}  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert save_preview_dock(widget).toggleViewAction().isChecked() is False
    assert on_disk_dock(widget).toggleViewAction().isChecked() is False


# endregion


# region inline notice banner (#94)
def banner(widget: DocumentWidget) -> MessageBanner:
    """Return the widget's private inline notice strip.

    :param widget: the document widget to inspect.
    :returns: the widget's `MessageBanner`.
    """
    return widget._DocumentWidget__banner  # type: ignore[attr-defined]  # pylint: disable=protected-access


def test_a_clean_document_shows_no_banner_rows(widget: DocumentWidget) -> None:
    """An unlocked document's banner starts with no rows.

    **Test steps:**

    * build a widget over the clean sample model
    * verify the banner shows no message labels
    """
    assert banner(widget).findChildren(QLabel) == []


def test_a_newer_format_reason_shows_its_message(widget: DocumentWidget, model: RehuDocumentModel) -> None:
    """A ``newer_format`` lock reason renders its message -- there is nothing to do about it directly
    (no remedy action exists at all, on the toolbar or otherwise).

    **Test steps:**

    * give the model a ``newer_format`` lock reason
    * verify its message shows
    """
    model.lock_reasons = [LockReason(LockReasonKind.NEWER_FORMAT, "from a newer build")]

    texts = {label.text() for label in banner(widget).findChildren(QLabel)}
    assert "from a newer build" in texts


def test_an_invalid_field_reason_shows_its_message(widget: DocumentWidget, model: RehuDocumentModel) -> None:
    """An ``invalid_field`` lock reason renders its message -- Revert (its remedy) is already on this
    widget's own toolbar.

    **Test steps:**

    * give the model an ``invalid_field`` lock reason
    * verify its message shows
    """
    model.lock_reasons = [LockReason(LockReasonKind.INVALID_FIELD, "invalid authors")]

    texts = {label.text() for label in banner(widget).findChildren(QLabel)}
    assert "invalid authors" in texts


def test_a_legacy_tc_reason_shows_its_message(legacy_widget: DocumentWidget) -> None:
    """A ``legacy_tc`` lock reason renders its message -- the convert actions (its remedy) are already
    on this widget's own toolbar, shown exactly while ``legacy_tc``.

    **Test steps:**

    * build a widget over a legacy ``.tc``-backed model
    * verify the banner shows its message
    """
    texts = {label.text() for label in banner(legacy_widget).findChildren(QLabel)}
    assert any("legacy .tc" in text for text in texts)


def test_the_banner_rebuilds_as_lock_reasons_change(widget: DocumentWidget, model: RehuDocumentModel) -> None:
    """The banner tracks the model's lock reasons live, same as the editor docks.

    **Test steps:**

    * give the model a lock reason and verify the banner shows its message
    * clear the reasons and verify the banner shows nothing again
    """
    model.lock_reasons = [LockReason(LockReasonKind.MISSING, "file not found: /fake/info.rehu")]
    assert "file not found: /fake/info.rehu" in {label.text() for label in banner(widget).findChildren(QLabel)}

    model.lock_reasons = []

    assert banner(widget).findChildren(QLabel) == []


def test_a_successful_convert_clears_the_banner(
    mocker: MockerFixture, legacy_widget: DocumentWidget, legacy_model: RehuDocumentModel
) -> None:
    """A real, successful conversion clears the banner along with the lock (mirrors the toolbar flip).

    **Test steps:**

    * mock the underlying core convert call (``convert_tc``) to return a fresh, unlocked document
    * trigger the toolbar's keep-backups convert action for real
    * verify the model unlocked and the banner shows no rows
    """
    converted = RehuDocument({"type": "Tutorial", "sources": [{"title": "Foo", "primary": True}]}, TARGET_PATH)
    mocker.patch("rehuco_agent.documents.rehu_document_model.convert_tc", return_value=converted)
    keep_backups = legacy_widget._DocumentWidget__convert_keep_backups_action  # type: ignore[attr-defined]  # pylint: disable=protected-access

    keep_backups.trigger()

    assert legacy_model.locked is False
    assert banner(legacy_widget).findChildren(QLabel) == []


# endregion


# region upgrade offer (#89)
def test_a_clean_older_document_shows_the_upgrade_action_and_its_banner_message(
    older_widget: DocumentWidget,
) -> None:
    """A clean, older-format document shows its upgrade toolbar button, visible exactly like the
    convert actions are during ``legacy_tc`` -- plus a message-only banner row explaining it, the same
    shape every lock reason already uses (a toolbar remedy, plus an explanatory row).

    **Test steps:**

    * build a widget over the older-format fixture
    * verify the upgrade action reports visible and the banner shows its message
    """
    assert older_widget.upgrade_action.isVisible() is True
    texts = {label.text() for label in banner(older_widget).findChildren(QLabel)}
    assert any("older format" in text for text in texts)


def test_a_clean_older_document_hides_save_in_favor_of_upgrade(older_widget: DocumentWidget) -> None:
    """Save hides while the upgrade offer stands -- the meaningful write action on a clean,
    older-format document is Upgrade, not a no-op Save, the same swap ``legacy_tc`` already makes for
    Save/Revert vs. the convert actions. Revert stays visible regardless: re-reading a clean file from
    disk is still useful no matter its format version.

    **Test steps:**

    * build a widget over the older-format fixture
    * verify Save reports hidden and Revert stays visible
    """
    assert older_widget.save_action.isVisible() is False
    assert older_widget.revert_action.isVisible() is True


def test_a_current_format_document_hides_the_upgrade_action_and_shows_no_banner_row(
    widget: DocumentWidget,
) -> None:
    """A document already at the current format version has nothing to upgrade -- the sample fixture
    model, seeded with no explicit ``format_version``, is at the current one.

    **Test steps:**

    * build a widget over the sample (current-version) model
    * verify the upgrade action reports hidden and the banner shows no upgrade message
    """
    assert widget.upgrade_action.isVisible() is False
    texts = {label.text() for label in banner(widget).findChildren(QLabel)}
    assert not any("older format" in text for text in texts)


def test_upgrade_action_is_on_the_toolbar(older_widget: DocumentWidget) -> None:
    """The upgrade action is a real toolbar button, same as Save/Revert/Convert -- not banner-only.

    **Test steps:**

    * build a widget over the older-format fixture (whose upgrade offer is showing)
    * verify one of the widget's toolbars carries ``upgrade_action``
    """
    actions = {action for toolbar in older_widget.findChildren(QToolBar) for action in toolbar.actions()}
    assert older_widget.upgrade_action in actions


def test_clicking_the_upgrade_action_saves_the_document(
    mocker: MockerFixture, older_widget: DocumentWidget, older_model: RehuDocumentModel
) -> None:
    """Triggering the upgrade action saves the document -- saving is the whole upgrade mechanism
    (:meth:`RehuDocumentModel.save`'s own docstring); there is no separate migrate call.

    **Test steps:**

    * mock ``model.save``
    * trigger the widget's upgrade action
    * verify ``save`` was called
    """
    save = mocker.patch.object(older_model, "save")

    older_widget.upgrade_action.trigger()

    save.assert_called_once_with()


def test_the_upgrade_offer_clears_once_the_document_is_saved(
    mocker: MockerFixture, older_widget: DocumentWidget
) -> None:
    """A real save clears the offer -- the toolbar button hides and the banner rebuilds to drop its
    message -- live, the same as every lock reason already does (#89).

    **Test steps:**

    * mock the atomic write and trigger the upgrade action for real
    * verify the upgrade action is now hidden and the banner shows no upgrade message
    """
    mocker.patch("rehuco_core.rehu_document.atomic_write_text")

    older_widget.upgrade_action.trigger()

    assert older_widget.upgrade_action.isVisible() is False
    texts = {label.text() for label in banner(older_widget).findChildren(QLabel)}
    assert not any("older format" in text for text in texts)


def test_dirtying_an_upgradable_document_hides_the_upgrade_offer(
    older_widget: DocumentWidget, older_model: RehuDocumentModel
) -> None:
    """Editing an upgradable document hides its offer immediately -- toolbar button and banner message
    together -- since once dirty, the meaningful action is Save (which upgrades anyway), not a
    separate Upgrade offer.

    **Test steps:**

    * dirty the older-format model with an edit
    * verify the upgrade action is now hidden and the banner shows no upgrade message
    """
    older_model.title = "Edited"

    assert older_widget.upgrade_action.isVisible() is False
    texts = {label.text() for label in banner(older_widget).findChildren(QLabel)}
    assert not any("older format" in text for text in texts)


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


# region type switching (#83)
def test_destroying_the_widget_severs_its_forms_field_connections(qtbot: QtBot) -> None:
    """When the widget is destroyed, its form's fields' long-lived-signal connections are cleared, so a
    model that outlives it never fires into the destroyed widgets ([[plugins#field-toolkit]], #114).

    **Test steps:**

    * build a widget over a model, then destroy the widget and let ``destroyed`` fire
    * change a model field (the model outlives the widget), forcing its signal to emit
    * verify it does not fire into a destroyed widget (no crash)
    """
    model = RehuDocumentModel(
        RehuDocument(
            {
                "core": {"type": "tutorial", "sources": [{"title": "Foo", "primary": True}]},
                "tutorial": {"original_duration": 60},
            }
        )
    )
    widget = DocumentWidget(model)
    widget.deleteLater()
    qtbot.wait(1)  # destroyed fires -> the form's connections are cleared while the fields are still alive

    model.original_duration = 120

    assert model.original_duration == 120  # reached here without a RuntimeError from a destroyed widget


def test_field_signals_after_a_switch_do_not_fire_into_deleted_widgets(qtbot: QtBot) -> None:
    """A type switch rebuilds the form, deleting every field's old widgets; the model's field signals
    firing afterwards must not reach those deleted widgets ([[plugins#field-toolkit]], #114).

    The form is retained and its outgoing fields' long-lived-signal connections are cleared on the
    rebuild (`FieldsForm.clear_external`), so a lambda viewer/editor never outlives its widget. Without
    that, emitting e.g. ``complete``/``original_duration`` after the switch would crash in the old
    boolean/duration lambdas.

    **Test steps:**

    * build a widget over a document carrying boolean and duration fields, then switch its type
    * let the event loop actually destroy the old widgets
    * change several model fields (boolean, duration, tags), forcing their signals to emit
    * verify none of it fires into a deleted widget (no crash) and the live widgets reflect the change
    """
    model = RehuDocumentModel(
        RehuDocument(
            {
                "core": {"type": "tutorial", "sources": [{"title": "Foo", "primary": True}]},
                "tutorial": {"complete": False, "original_duration": 60, "extra_tags": ["a"]},
            }
        )
    )
    widget = DocumentWidget(model)
    qtbot.addWidget(widget)

    model.resource_type = "reference_images"
    qtbot.wait(1)  # destroy the old widgets, so a stale lambda would fire on a deleted widget

    model.complete = True
    model.original_duration = 120
    model.extra_tags = ["a", "b"]

    assert model.complete is True  # got here without a RuntimeError from a deleted widget


def type_combo(widget: DocumentWidget) -> SingleChoiceComboBox:
    """Return the widget's editor-dock type selector combo.

    :param widget: the document widget to inspect.
    :returns: the type field's editor combo.
    """
    combos = widget.findChildren(SingleChoiceComboBox)
    assert len(combos) == 1
    return combos[0]


def flagged_tooltips(widget: DocumentWidget) -> dict[str, str]:
    """Collect every flagged (unknown/inactive) value label's text and provenance tooltip.

    :param widget: the document widget to inspect.
    :returns: a ``{label text: tooltip}`` mapping over the widget's flagged labels.
    """
    return {label.text(): label.toolTip() for label in widget.findChildren(QLabel) if label.property("unknown")}


@fixture
def block_model() -> RehuDocumentModel:
    """A tutorial document carrying a real ``tutorial`` block, so switching away leaves an abandoned one."""
    return RehuDocumentModel(
        RehuDocument(
            {
                "core": {"type": "tutorial", "sources": [{"title": "Foo", "primary": True}]},
                "tutorial": {"rating": 4},
            }
        )
    )


def test_switching_type_rebuilds_the_docks_with_the_abandoned_block_flagged(
    qtbot: QtBot, block_model: RehuDocumentModel
) -> None:
    """A type switch re-resolves the docks: the former-active block, absent as a flagged row before the
    switch, appears as a will-drop-on-save row afterwards ([[plugins#plugin-blocks]], #83).

    This is the whole point of rebuilding rather than reactive show/hide -- the abandoned block's row
    did not exist in the pre-switch composition, so only a rebuild can add it.

    **Test steps:**

    * build a widget over a tutorial document with a real ``tutorial`` block (active, so unflagged)
    * verify nothing is flagged yet
    * switch the type to ``reference_images``
    * verify the now-inactive ``tutorial`` block appears flagged with the abandoned-type provenance
    """
    widget = DocumentWidget(block_model)
    qtbot.addWidget(widget)
    assert not flagged_tooltips(widget)

    block_model.resource_type = "reference_images"

    tooltips = flagged_tooltips(widget)
    assert tooltips["{'users': {'admin': {'rating': 4}}, 'format_version': 1}"] == PROVENANCE_ABANDONED_TYPE


def test_a_rebuilt_unknown_field_row_stays_reactive_after_a_round_trip_switch(qtbot: QtBot) -> None:
    """After a round-trip switch destroys the old unknown-field row and builds a new one, the new row is
    still reactive -- clearing the old instance's `ConnectionList` does not sever the new one's
    ([[plugins#fallback-editor]], #83).

    Each `UnknownField` instance owns its own connection list, so the old row's ``clear_on_destroyed``
    only disconnects the old connections; the freshly-built row keeps its own live ones.

    **Test steps:**

    * build a widget over a tutorial document carrying an unrecognized ``mystery`` field
    * switch away and back, then let the old rows be destroyed (old connections severed)
    * verify the rebuilt ``mystery`` row is shown, then drop the field and verify it reacts by hiding --
      proving the new connection is live
    """
    model = RehuDocumentModel(
        RehuDocument(
            {
                "core": {"type": "tutorial", "sources": [{"title": "Foo", "primary": True}]},
                "tutorial": {"mystery": 1},
            }
        )
    )
    widget = DocumentWidget(model)
    qtbot.addWidget(widget)

    model.resource_type = "reference_images"
    qtbot.wait(1)
    model.resource_type = "tutorial"  # mystery is an active-block unknown again; a new row is built
    qtbot.wait(1)  # destroy the old rows, firing their clear_on_destroyed

    unknown_labels = [
        label for label in widget.findChildren(QLabel) if label.property("unknown") and label.text() == "1"
    ]
    assert unknown_labels and not any(label.isHidden() for label in unknown_labels)

    model.remove_unknown_field("mystery")

    assert all(label.isHidden() for label in unknown_labels)


def test_switching_type_updates_the_combo_selection(qtbot: QtBot, block_model: RehuDocumentModel) -> None:
    """After a switch, the rebuilt type combo shows the newly-selected type ([[plugins#plugin-blocks]], #83).

    **Test steps:**

    * build a widget over a tutorial document and switch its type
    * verify the (rebuilt) combo's selected value is the new type
    """
    widget = DocumentWidget(block_model)
    qtbot.addWidget(widget)

    block_model.resource_type = "reference_images"

    assert type_combo(widget).value == "reference_images"


def test_switching_type_preserves_the_path_field_expand_state(qtbot: QtBot, block_model: RehuDocumentModel) -> None:
    """A rebuilt dock keeps a stateful widget's own UI state -- the path editor stays expanded across a
    type switch ([[plugins#plugin-blocks]], #83).

    **Test steps:**

    * build a widget, expand its location editor
    * switch the type (rebuilding the docks)
    * verify the freshly-built location editor is still expanded
    """
    widget = DocumentWidget(block_model)
    qtbot.addWidget(widget)
    location_editor(widget).expanded = True

    block_model.resource_type = "reference_images"

    assert location_editor(widget).expanded is True


def test_switching_type_then_reverting_does_not_fire_into_deleted_widgets(qtbot: QtBot, mocker: MockerFixture) -> None:
    """After a switch rebuilds (and deletes) the field widgets, a later model emit (a **revert**) must
    not fire into the deleted widgets ([[plugins#plugin-blocks]], #83).

    The rebuild deletes the old badge/rating/unknown-field widgets. Their ``binding.changed`` slots are
    bound methods (badge, rating) or tracked in a `ConnectionList` cleared on destruction (unknown), so
    Qt/the list severs them when the widgets die -- where a lambda capturing the widget would dangle and
    crash when revert reseeds ``resource_type``/``rating``/the unknown fields into it.

    **Test steps:**

    * build a widget over a tutorial document (with a rating and an unknown field) bound to a save path
    * switch the type, then let the event loop actually delete the old widgets
    * revert (re-reading the on-disk tutorial), and verify it reseeds back with no crash into a deleted widget
    """
    document = RehuDocument(
        {
            "core": {"type": "tutorial", "sources": [{"title": "Foo", "primary": True}]},
            "tutorial": {"rating": 4, "mystery": 1},
        },
        Path("/fake/info.rehu"),
    )
    model = RehuDocumentModel(document)
    # build the widget before any read_text mock, so the description view's first markdown load isn't
    # served the mocked JSON; the mock is scoped to the revert's on-disk re-read alone
    widget = DocumentWidget(model)
    qtbot.addWidget(widget)

    model.resource_type = "reference_images"
    qtbot.wait(1)  # let deleteLater actually destroy the old widgets, so a stale slot would fire on delete

    # revert re-reads the original tutorial from disk (a fixed payload, not the now-switched in-memory data)
    # pylint: disable=duplicate-code
    mocker.patch.object(
        Path,
        "read_text",
        return_value=json.dumps(
            {
                "format_version": CURRENT_FORMAT_VERSION,
                "core": {"type": "tutorial", "sources": [{"title": "Foo", "primary": True}]},
                "tutorial": {"rating": 4, "mystery": 1},
            }
        ),
    )
    # pylint: enable=duplicate-code
    model.revert()

    assert model.resource_type == "tutorial"
    assert type_combo(widget).value == "tutorial"


def test_reverting_a_type_switch_drops_the_stale_inactive_block_row(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Reverting a type switch must not leave the original block showing as an inactive-block row now that
    it is the active type again ([[plugins#plugin-blocks]], #83).

    After switching away, the outgoing ``tutorial`` block shows as a flagged inactive-block row. Reverting
    restores ``tutorial`` as the active type -- and because that fires ``active_block_changed``, the form
    rebuilds, so the block renders only through its own active editors, not also as a stale inactive row.

    **Test steps:**

    * build a widget over a tutorial document (with a real tutorial block) bound to a save path
    * switch away, and confirm the tutorial block now shows as a flagged inactive-block row
    * revert (re-reading the tutorial from disk) and let the rebuild settle
    * verify the type is tutorial again and nothing is flagged as inactive/unknown
    """
    document = RehuDocument(
        {"core": {"type": "tutorial", "sources": [{"title": "Foo", "primary": True}]}, "tutorial": {"rating": 4}},
        Path("/fake/info.rehu"),
    )
    model = RehuDocumentModel(document)
    widget = DocumentWidget(model)  # built before any read_text mock, so the markdown view loads normally
    qtbot.addWidget(widget)

    model.resource_type = "reference_images"
    qtbot.wait(1)
    assert flagged_tooltips(widget)  # the abandoned tutorial block shows as a flagged inactive row

    # pylint: disable=duplicate-code
    mocker.patch.object(
        Path,
        "read_text",
        return_value=json.dumps(
            {
                "format_version": CURRENT_FORMAT_VERSION,
                "core": {"type": "tutorial", "sources": [{"title": "Foo", "primary": True}]},
                "tutorial": {"rating": 4},
            }
        ),
    )
    # pylint: enable=duplicate-code
    model.revert()
    qtbot.wait(1)

    assert type_combo(widget).value == "tutorial"
    assert not flagged_tooltips(widget)


def test_switching_type_re_locks_the_rebuilt_editors_when_the_model_is_locked(
    qtbot: QtBot, block_model: RehuDocumentModel
) -> None:
    """A rebuilt editor grid re-applies the model's lock state, so a locked document's freshly-built
    editors start disabled ([[plugins#plugin-blocks]], #83).

    **Test steps:**

    * build a widget, then simulate a lock and switch the type
    * verify the rebuilt type combo (on the main editor) is disabled
    """
    widget = DocumentWidget(block_model)
    qtbot.addWidget(widget)
    block_model.lock_reasons = [LockReason(LockReasonKind.NEWER_FORMAT, "newer")]

    block_model.resource_type = "reference_images"

    assert type_combo(widget).isEnabled() is False


# endregion
