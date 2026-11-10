"""Tests for PathField: the native-path link viewer, the PathEditor editor, the misc-column
expand toggle, and the live suggestion/current-name wiring.
"""

from pathlib import Path

from borco_pyside.widgets import ElidedLabel
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QLabel, QWidget
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.path_field import REVEAL_HINT
from rehuco_agent.fields.widgets import DestinationRow, ExpandToggleButton, LocationLine, PathEditor

from rehuco_agent_tests.fields.field_testers import PathFieldTester as PathField


# region Sample classes
class Emitter(QObject):
    """A minimal signal source standing in for a model's ``name_suggestions_changed``."""

    changed = Signal()


# endregion


def editor_name_label(editor: PathEditor) -> LocationLine:
    """Read the editor's private current-name label.

    :param editor: the editor to inspect.
    :returns: the internal current-name label.
    """
    return editor._PathEditor__name_line  # type: ignore[attr-defined]  # pylint: disable=protected-access


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


def location_line(widget: QWidget | None) -> LocationLine:
    """Narrow a built viewer/editor widget to the location link line.

    :param widget: the widget a field built.
    :returns: it, as a `LocationLine`.
    """
    assert isinstance(widget, LocationLine)
    return widget


# region viewer
def test_viewer_is_the_native_path_as_a_link(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer shows the native path, itself the link, with no ``(open)`` after it (#621).

    **Test steps:**

    * seed a posix-style location and build the viewer
    * verify the whole text is one anchor, in the palette's link color, and nothing follows it
    * verify the tooltip carries the reveal hint
    """
    model.location = "C:/tutorials/foo"
    field = PathField("location")
    viewer = location_line(field.make_viewer(model.bind(field)).viewer)
    qtbot.addWidget(viewer)
    viewer.resize(300, viewer.sizeHint().height())

    link_color = viewer.palette().color(QPalette.ColorRole.Link).name()
    assert viewer.textFormat() == Qt.TextFormat.RichText
    assert str(Path("C:/tutorials/foo")) in viewer.text()
    assert viewer.text().startswith("<a ")
    assert link_color in viewer.text()
    assert "(open)" not in viewer.text()
    assert viewer.toolTip() == REVEAL_HINT
    assert not viewer.findChildren(QLabel)


def test_clicking_the_location_reveals_the_path_in_the_file_browser(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """A click on the location reveals the document's path.

    **Test steps:**

    * seed a location and build the viewer
    * activate the location's link
    * verify the reveal helper was called with the location as a `Path`
    """
    reveal = mocker.patch("rehuco_agent.fields.path_field.reveal_in_file_browser")
    location = Path("/tutorials/foo").resolve()
    model.location = str(location)
    field = PathField("location")
    viewer = location_line(field.make_viewer(model.bind(field)).viewer)
    qtbot.addWidget(viewer)

    viewer.linkActivated.emit("#open")

    reveal.assert_called_once_with(location)


def test_viewer_renders_nothing_when_empty(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """An empty location shows no text, so there is nothing to click.

    **Test steps:**

    * clear the location and build the viewer
    * verify the text is empty
    """
    model.location = ""
    field = PathField("location")
    viewer = location_line(field.make_viewer(model.bind(field)).viewer)
    qtbot.addWidget(viewer)

    assert viewer.text() == ""


def test_viewer_tracks_the_bound_value(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer re-renders when the bound value changes.

    **Test steps:**

    * build the viewer over an empty location, then set a value
    * verify the text updates and is a link
    """
    field = PathField("location")
    viewer = location_line(field.make_viewer(model.bind(field)).viewer)
    qtbot.addWidget(viewer)

    model.location = "C:/x/y"

    assert str(Path("C:/x/y")) in viewer.text()
    assert viewer.text().startswith("<a ")


def test_a_narrow_line_elides_the_text(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Squeezing the line elides the link's text in the middle.

    **Test steps:**

    * seed a long location, build the viewer and show it at a narrow width
    * verify the tooltip, shown only while the text is elided, starts with the full path
    """
    model.location = "C:/" + "/".join(["a_long_folder_name"] * 8)
    field = PathField("location")
    viewer = location_line(field.make_viewer(model.bind(field)).viewer)
    qtbot.addWidget(viewer)
    viewer.resize(200, viewer.sizeHint().height())
    viewer.show()

    assert viewer.toolTip().startswith(str(Path(model.location)))


# endregion


# region editor without suggestions
def test_editor_without_suggestions_is_a_read_only_label(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """With no ``suggestions`` callback, the editor is a read-only viewer label (no rename panel).

    **Test steps:**

    * build the editor with no suggestions
    * verify its editor is the viewer's link line (not a ``PathEditor``), with no misc widget
    """
    model.location = "C:/foo"
    field = PathField("location")
    widgets = field.make_editor(model.bind(field))
    editor = location_line(widgets.editor)
    qtbot.addWidget(editor)

    assert widgets.misc is None
    assert str(Path("C:/foo")) in editor.text()
    assert editor.text().startswith("<a ")


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

    assert "folder" in editor_name_label(editor).text()
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
    assert "old_name" in editor_name_label(editor).text()

    name[0] = "new_name"
    model.location = "C:/trigger"  # fires location_changed -> refresh

    assert "new_name" in editor_name_label(editor).text()


def test_editor_name_reveals_the_path_and_needs_one(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """The editor's current name is the link revealing the bound path, and plain text for a path-less document.

    **Test steps:**

    * build an editor over an empty location and verify the name is no link
    * set a location and verify the name becomes a link
    * activate it and verify the reveal helper got the location
    """
    reveal = mocker.patch("rehuco_agent.fields.path_field.reveal_in_file_browser")
    _field, editor, _misc = build_editor(model)
    qtbot.addWidget(editor)
    name = editor_name_label(editor)
    assert "<a " not in name.text()

    location = Path("/tutorials/foo").resolve()
    model.location = str(location)
    assert name.text().startswith("<a ")

    name.linkActivated.emit("#open")

    reveal.assert_called_once_with(location)


def test_clicking_a_suggestion_still_renames_and_not_reveals(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """A click on a suggestion selects it, and reveals nothing.

    **Test steps:**

    * build an editor over a location with two suggestions
    * activate the first suggestion's link
    * verify it was selected and the reveal helper was not called
    """
    reveal = mocker.patch("rehuco_agent.fields.path_field.reveal_in_file_browser")
    selected: list[str] = []
    model.location = str(Path("/tutorials/foo").resolve())
    _field, editor, _misc = build_editor(model, suggestions=["Alpha", "Beta"], selected=selected)
    qtbot.addWidget(editor)

    editor_suggestion_labels(editor)["Alpha"].linkActivated.emit("#")

    assert selected == ["Alpha"]
    reveal.assert_not_called()


def test_a_click_with_no_location_reveals_nothing(
    qtbot: QtBot, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """A click on the line while the location is empty reveals nothing.

    **Test steps:**

    * build a viewer over an empty location
    * activate the line as a link would
    * verify the reveal helper was not called
    """
    reveal = mocker.patch("rehuco_agent.fields.path_field.reveal_in_file_browser")
    model.location = ""
    field = PathField("location")
    viewer = location_line(field.make_viewer(model.bind(field)).viewer)
    qtbot.addWidget(viewer)

    viewer.linkActivated.emit("#open")

    reveal.assert_not_called()


def test_location_link_follows_a_palette_change(qtbot: QtBot) -> None:
    """The location's anchor is re-drawn in the new link color when the palette changes.

    **Test steps:**

    * build a link line over some text and set a palette with a distinct link color
    * verify the label text carries that color
    """
    line = LocationLine()
    qtbot.addWidget(line)
    line.set_location("C:/foo")
    line.set_openable(True)
    palette = line.palette()
    palette.setColor(QPalette.ColorRole.Link, QColor("#123456"))

    line.setPalette(palette)

    assert "#123456" in line.text()


def test_set_text_on_a_location_line_is_set_location(qtbot: QtBot) -> None:
    """`ElidedLabel`'s ``set_text`` on a `LocationLine` sets the location, keeping the line's own link and hint.

    **Test steps:**

    * build an openable line with a hint and call ``set_text`` with a foreign link target and hint
    * verify the text is a link to the line's own target, with the line's own hint as its tooltip
    """
    line = LocationLine(hint="Show in Explorer")
    qtbot.addWidget(line)
    line.resize(300, line.sizeHint().height())
    line.set_openable(True)

    line.set_text("C:/foo", href="#other", hint="other")

    assert 'href="#open"' in line.text()
    assert "#other" not in line.text()
    assert line.toolTip() == "Show in Explorer"


# region the roots' places (#579, #339)
def test_the_places_are_pulled_on_build_and_refresh_and_a_click_is_forwarded(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """The roots' places are pulled on build and on every ``suggestions_changed``; a click reaches the callback with
    the place's index.

    **Test steps:**

    * build an editor with no places at first, with a change emitter and a click sink
    * add a place and fire the emitter: the editor shows it
    * click it: the sink is called with 0
    """
    changed = Emitter()
    rows: list[list[DestinationRow]] = [[]]
    clicked: list[int] = []
    field = PathField(
        "location",
        suggestions=lambda: ["Alpha"],
        current_name=lambda: "folder",
        suggestions_changed=changed.changed,
        destinations=lambda: rows[-1],
        on_destination_selected=clicked.append,
    )
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, PathEditor)
    qtbot.addWidget(editor)
    labels = editor._PathEditor__destination_labels  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert not labels

    rows.append([DestinationRow("Tutorials: Jane/Foo")])
    changed.changed.emit()
    labels = editor._PathEditor__destination_labels  # type: ignore[attr-defined]  # pylint: disable=protected-access
    labels[0].linkActivated.emit("#")

    assert len(labels) == 1
    assert clicked == [0]


# endregion
