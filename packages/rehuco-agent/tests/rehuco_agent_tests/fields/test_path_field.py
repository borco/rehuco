"""Tests for PathField: the native-path text + ``(open)`` viewer, the PathEditor editor, the misc-column
expand toggle, and the live suggestion/current-name wiring.
"""

from pathlib import Path

from borco_pyside.widgets import ElidedLabel
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QWidget
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.path_field import REVEAL_HINT
from rehuco_agent.fields.widgets import ExpandToggleButton, OpenLinkLine, PathEditor

from rehuco_agent_tests.fields.field_testers import PathFieldTester as PathField


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
    return editor._PathEditor__name_line.text_label  # type: ignore[attr-defined]  # pylint: disable=protected-access


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


def location_line(widget: QWidget | None) -> OpenLinkLine:
    """Narrow a built viewer/editor widget to the plain-text-plus-``(open)`` line.

    :param widget: the widget a field built.
    :returns: it, as an `OpenLinkLine`.
    """
    assert isinstance(widget, OpenLinkLine)
    return widget


# region viewer
def test_viewer_is_plain_native_path_text_with_an_open_link(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer shows the native path as plain text, and only ``(open)`` is an anchor.

    **Test steps:**

    * seed a posix-style location and build the viewer
    * verify the text is the native path with no anchor around it
    * verify the ``(open)`` link is shown, its tooltip is the reveal hint
    """
    model.location = "C:/tutorials/foo"
    field = PathField("location")
    viewer = location_line(field.make_viewer(model.bind(field)).viewer)
    qtbot.addWidget(viewer)

    text = viewer.text_label
    assert text.textFormat() == Qt.TextFormat.PlainText
    assert text.text() == str(Path("C:/tutorials/foo"))
    assert "<a " not in text.text()
    assert not viewer.link_label.isHidden()
    assert "open" in viewer.link_label.text()
    assert viewer.link_label.toolTip() == REVEAL_HINT


def test_clicking_open_reveals_the_path_in_the_file_browser(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """Activating ``(open)`` reveals the document's path.

    **Test steps:**

    * seed a location and build the viewer
    * activate the ``(open)`` link
    * verify the reveal helper was called with the location as a `Path`
    """
    reveal = mocker.patch("rehuco_agent.fields.path_field.reveal_in_file_browser")
    location = Path("/tutorials/foo").resolve()
    model.location = str(location)
    field = PathField("location")
    viewer = location_line(field.make_viewer(model.bind(field)).viewer)
    qtbot.addWidget(viewer)

    viewer.link_label.linkActivated.emit("#open")

    reveal.assert_called_once_with(location)


def test_viewer_renders_nothing_when_empty(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """An empty location shows no text and no ``(open)`` link.

    **Test steps:**

    * clear the location and build the viewer
    * verify the text is empty and the link hidden
    """
    model.location = ""
    field = PathField("location")
    viewer = location_line(field.make_viewer(model.bind(field)).viewer)
    qtbot.addWidget(viewer)

    assert viewer.text_label.text() == ""
    assert viewer.link_label.isHidden()


def test_viewer_tracks_the_bound_value(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer re-renders when the bound value changes.

    **Test steps:**

    * build the viewer over an empty location, then set a value
    * verify the text updates and ``(open)`` appears
    """
    field = PathField("location")
    viewer = location_line(field.make_viewer(model.bind(field)).viewer)
    qtbot.addWidget(viewer)

    model.location = "C:/x/y"

    assert viewer.text_label.text() == str(Path("C:/x/y"))
    assert not viewer.link_label.isHidden()


def test_a_narrow_line_elides_the_text_and_keeps_open_whole(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Squeezing the line elides the text while ``(open)`` keeps its full width.

    **Test steps:**

    * seed a long location, build the viewer and show it at a narrow width
    * verify the text is elided (shorter than the path)
    * verify the ``(open)`` label is as wide as it asks to be
    """
    model.location = "C:/" + "/".join(["a_long_folder_name"] * 8)
    field = PathField("location")
    viewer = location_line(field.make_viewer(model.bind(field)).viewer)
    qtbot.addWidget(viewer)
    viewer.resize(200, viewer.sizeHint().height())
    viewer.show()

    link = viewer.link_label
    assert len(viewer.text_label.text()) < len(str(Path(model.location)))
    assert link.width() >= link.sizeHint().width()


# endregion


# region editor without suggestions
def test_editor_without_suggestions_is_a_read_only_label(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """With no ``suggestions`` callback, the editor is a read-only viewer label (no rename panel).

    **Test steps:**

    * build the editor with no suggestions
    * verify its editor is the viewer's text-plus-``(open)`` line (not a ``PathEditor``), with no misc widget
    """
    model.location = "C:/foo"
    field = PathField("location")
    widgets = field.make_editor(model.bind(field))
    editor = location_line(widgets.editor)
    qtbot.addWidget(editor)

    assert widgets.misc is None
    assert editor.text_label.text() == str(Path("C:/foo"))
    assert not editor.link_label.isHidden()


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
    widgets = field.make_editor(model.bind(field))
    editor = widgets.editor
    misc = widgets.misc
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
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, PathEditor)
    qtbot.addWidget(editor)
    assert editor_name_label(editor).text() == "old_name"

    name[0] = "new_name"
    model.location = "C:/trigger"  # fires location_changed -> refresh

    assert editor_name_label(editor).text() == "new_name"


def test_editor_open_reveals_the_path_and_needs_one(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """The editor's ``(open)`` reveals the bound path, and is absent for a path-less document.

    **Test steps:**

    * build an editor over an empty location and verify the link is hidden
    * set a location and verify the link appears
    * activate it and verify the reveal helper got the location
    """
    reveal = mocker.patch("rehuco_agent.fields.path_field.reveal_in_file_browser")
    _field, editor, _misc = build_editor(model)
    qtbot.addWidget(editor)
    link = editor._PathEditor__name_line.link_label  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert link.isHidden()

    location = Path("/tutorials/foo").resolve()
    model.location = str(location)
    assert not link.isHidden()

    link.linkActivated.emit("#open")

    reveal.assert_called_once_with(location)


def test_open_with_no_location_reveals_nothing(qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture) -> None:
    """A click on ``(open)`` while the location is empty reveals nothing.

    **Test steps:**

    * build a viewer over an empty location
    * activate the ``(open)`` link
    * verify the reveal helper was not called
    """
    reveal = mocker.patch("rehuco_agent.fields.path_field.reveal_in_file_browser")
    model.location = ""
    field = PathField("location")
    viewer = location_line(field.make_viewer(model.bind(field)).viewer)
    qtbot.addWidget(viewer)

    viewer.link_label.linkActivated.emit("#open")

    reveal.assert_not_called()


def test_open_link_follows_a_palette_change(qtbot: QtBot) -> None:
    """The ``(open)`` anchor is re-drawn in the new link color when the palette changes.

    **Test steps:**

    * build the link line and set a palette with a distinct link color
    * verify the label text carries that color
    """
    line = OpenLinkLine()
    qtbot.addWidget(line)
    palette = line.palette()
    palette.setColor(QPalette.ColorRole.Link, QColor("#123456"))

    line.link_label.setPalette(palette)

    assert "#123456" in line.link_label.text()
