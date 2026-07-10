"""Tests for PathField: the native-path ElidedLabel viewer, the PathEditor editor, the misc-column
expand toggle, and the live suggestion/current-name wiring.
"""

from borco_pyside.widgets import ElidedLabel
from PySide6.QtCore import QObject, Signal
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.path_field import PathField
from rehuco_agent.fields.widgets import ExpandToggleButton, PathEditor


# region Sample classes
class Emitter(QObject):
    """A minimal signal source standing in for a model's ``name_suggestions_changed``."""

    changed = Signal()


# endregion


def editor_name_label(editor: PathEditor) -> ElidedLabel:
    """Read the editor's private current-name label.

    :param editor: the editor to inspect.
    :returns: the internal current-name label.
    """
    return editor._PathEditor__name_label  # type: ignore[attr-defined]  # pylint: disable=protected-access


def editor_suggestion_labels(editor: PathEditor) -> dict[str, ElidedLabel]:
    """Read the editor's suggestion-name -> label map.

    :param editor: the editor to inspect.
    :returns: the suggestion labels, keyed by sanitized name.
    """
    return editor._PathEditor__suggestion_labels  # type: ignore[attr-defined]  # pylint: disable=protected-access


def editor_suggestion_names(editor: PathEditor) -> list[str]:
    """Read the editor's current sanitized suggestion names.

    :param editor: the editor to inspect.
    :returns: the suggestion names, in order.
    """
    return list(editor_suggestion_labels(editor))


# region viewer
def test_viewer_is_an_elided_native_path_link(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer is an ``ElidedLabel`` external link showing the value with native separators.

    **Test steps:**

    * seed a posix-style location and build the viewer
    * verify it's an ``ElidedLabel`` opening external links, showing the native path in a file link
    """
    model.location = "C:/tutorials/foo"
    field = PathField("location")
    viewer = field.make_viewer(model.bind(field))
    qtbot.addWidget(viewer)

    assert isinstance(viewer, ElidedLabel)
    assert viewer.openExternalLinks() is True
    assert viewer.text().startswith('<a href="file:')
    assert ">C:\\tutorials\\foo</a>" in viewer.text()


def test_viewer_renders_nothing_when_empty(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """An empty location renders as an empty label.

    **Test steps:**

    * clear the location and build the viewer
    * verify the label text is empty
    """
    model.location = ""
    field = PathField("location")
    viewer = field.make_viewer(model.bind(field))
    qtbot.addWidget(viewer)

    assert isinstance(viewer, ElidedLabel)
    assert viewer.text() == ""


def test_viewer_tracks_the_bound_value(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer re-renders when the bound value changes.

    **Test steps:**

    * build the viewer over an empty location, then set a value
    * verify the label updates to the native-path link
    """
    field = PathField("location")
    viewer = field.make_viewer(model.bind(field))
    qtbot.addWidget(viewer)
    assert isinstance(viewer, ElidedLabel)

    model.location = "C:/x/y"

    assert ">C:\\x\\y</a>" in viewer.text()


# endregion


# region editor without suggestions
def test_editor_without_suggestions_is_a_read_only_label(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """With no ``suggestions`` callback, the editor is a read-only viewer label (no rename panel).

    **Test steps:**

    * build the editor with no suggestions
    * verify it returns a single ``ElidedLabel`` (not a ``PathEditor``), and no misc widget
    """
    model.location = "C:/foo"
    field = PathField("location")
    editors = field.make_editors(model.bind(field))
    qtbot.addWidget(editors[0])

    assert len(editors) == 1
    assert isinstance(editors[0], ElidedLabel)
    assert field.make_misc(model.bind(field), editors) is None


# endregion


# region editor with suggestions
def build_editor(
    model: RehuDocumentModel,
    *,
    suggestions: list[str] | None = None,
    current_name: str = "current",
    selected: list[str] | None = None,
    changed: Emitter | None = None,
) -> tuple[PathField, PathEditor, ExpandToggleButton]:
    """Build a suggestions-enabled PathField and return it with its editor and misc toggle.

    :param model: the model to bind the field against.
    :param suggestions: the raw candidate names the field offers.
    :param current_name: the resource's current name.
    :param selected: list appended to when a suggestion is clicked.
    :param changed: optional emitter whose ``changed`` signal triggers a live refresh.
    :returns: the field, its ``PathEditor``, and its misc ``ExpandToggleButton``.
    """
    field = PathField(
        "location",
        suggestions=lambda: suggestions if suggestions is not None else ["Alpha", "Beta"],
        on_suggestion_selected=(selected.append if selected is not None else None),
        current_name=lambda: current_name,
        suggestions_changed=(changed.changed if changed is not None else None),
    )
    binding = model.bind(field)
    editors = field.make_editors(binding)
    editor = editors[0]
    misc = field.make_misc(binding, editors)
    assert isinstance(editor, PathEditor)
    assert isinstance(misc, ExpandToggleButton)
    return field, editor, misc


def test_editor_is_a_path_editor_seeded_with_current_name_and_suggestions(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """With suggestions, the editor is a ``PathEditor`` seeded with the current name and candidates.

    **Test steps:**

    * build the editor with a current name and two suggestions
    * verify the ``PathEditor`` shows the current name and lists both suggestions
    """
    _field, editor, _misc = build_editor(model, suggestions=["Alpha", "Beta"], current_name="folder")
    qtbot.addWidget(editor)

    assert editor_name_label(editor).text() == "folder"
    assert editor_suggestion_names(editor) == ["Alpha", "Beta"]


def test_misc_toggle_drives_the_editor_expand_state(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The misc-column toggle two-way binds the ``PathEditor``'s expand state.

    **Test steps:**

    * build the editor + toggle
    * check the toggle and verify the editor expands; set the editor collapsed and verify the toggle follows
    """
    _field, editor, misc = build_editor(model)
    qtbot.addWidget(editor)
    qtbot.addWidget(misc)

    misc.setChecked(True)
    assert editor.expanded is True

    editor.expanded = False
    assert misc.isChecked() is False


def test_clicking_a_suggestion_calls_the_selection_callback(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Clicking a suggestion forwards its sanitized name to ``on_suggestion_selected``.

    **Test steps:**

    * build the editor with an accented suggestion and a selection sink
    * activate its label's link and verify the sanitized name was reported
    """
    selected: list[str] = []
    _field, editor, _misc = build_editor(model, suggestions=["Föo"], selected=selected)
    qtbot.addWidget(editor)

    editor_suggestion_labels(editor)["Foo"].linkActivated.emit("#")

    assert selected == ["Foo"]


def test_suggestions_refresh_live_when_the_change_signal_fires(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The editor re-pulls suggestions when ``suggestions_changed`` fires (e.g. an edited author).

    **Test steps:**

    * build the editor over a mutable suggestion list with a change emitter
    * mutate the list and emit the signal, verifying the editor's suggestions update
    """
    changed = Emitter()
    suggestions = ["Alpha"]
    _field, editor, _misc = build_editor(model, suggestions=suggestions, changed=changed)
    qtbot.addWidget(editor)
    assert editor_suggestion_names(editor) == ["Alpha"]

    suggestions[:] = ["Beta", "Gamma"]
    changed.changed.emit()

    assert editor_suggestion_names(editor) == ["Beta", "Gamma"]


def test_current_name_refreshes_when_the_bound_value_changes(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The editor re-pulls the current name when the bound value changes.

    **Test steps:**

    * build the editor whose current-name callback reads a mutable value
    * change that value and fire the binding's change signal, verifying the editor's name updates
    """
    name = ["old_name"]
    field = PathField("location", suggestions=lambda: ["Alpha"], current_name=lambda: name[0])
    binding = model.bind(field)
    editor = field.make_editors(binding)[0]
    qtbot.addWidget(editor)
    assert isinstance(editor, PathEditor)
    assert editor_name_label(editor).text() == "old_name"

    name[0] = "new_name"
    model.location = "C:/trigger"  # fires location_changed -> refresh

    assert editor_name_label(editor).text() == "new_name"


# endregion
