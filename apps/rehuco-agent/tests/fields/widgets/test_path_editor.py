"""Tests for PathEditor: current-name label (warning-colored when unmatched), collapsible clickable
rename suggestions, and the live setters.
"""

from borco_pyside.widgets import ElidedLabel
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.colors import WARNING_COLOR
from rehuco_agent.fields.widgets.path_editor import PathEditor


def name_label(editor: PathEditor) -> ElidedLabel:
    """Return the editor's private current-name label -- ``PathEditor`` exposes no accessor.

    :param editor: the widget to inspect.
    :returns: the internal current-name ``ElidedLabel``.
    """
    return editor._PathEditor__name_label  # type: ignore[attr-defined]  # pylint: disable=protected-access


def suggestion_labels(editor: PathEditor) -> dict[str, ElidedLabel]:
    """Return the editor's private suggestion-name -> label map.

    :param editor: the widget to inspect.
    :returns: the internal suggestion labels, keyed by sanitized name.
    """
    return editor._PathEditor__suggestion_labels  # type: ignore[attr-defined]  # pylint: disable=protected-access


def suggestions_widget(editor: PathEditor) -> ElidedLabel:
    """Return the editor's private collapsible suggestions panel.

    :param editor: the widget to inspect.
    :returns: the internal suggestions container widget.
    """
    return editor._PathEditor__suggestions_widget  # type: ignore[attr-defined]  # pylint: disable=protected-access


def test_set_current_name_shows_it_in_the_name_label(qtbot: QtBot) -> None:
    """``set_current_name`` renders the name in the current-name label.

    **Test steps:**

    * build an editor and set a current name
    * verify the name label shows it
    """
    editor = PathEditor()
    qtbot.addWidget(editor)

    editor.set_current_name("some_folder")

    assert name_label(editor).text() == "some_folder"


def test_current_name_warns_when_it_matches_no_suggestion(qtbot: QtBot) -> None:
    """The current name is warning-colored when it isn't one of the suggestions, and plain when it is.

    **Test steps:**

    * set a current name and suggestions that don't include it
    * verify the name label is warning-colored
    * add a suggestion equal to the current name and verify the warning clears
    """
    editor = PathEditor()
    qtbot.addWidget(editor)

    editor.set_current_name("messy_download")
    editor.set_suggestions(["Clean Title"])
    assert WARNING_COLOR in name_label(editor).styleSheet()

    editor.set_suggestions(["messy_download", "Clean Title"])
    assert WARNING_COLOR not in name_label(editor).styleSheet()


def test_empty_current_name_never_warns(qtbot: QtBot) -> None:
    """An empty current name isn't flagged, even with no matching suggestion.

    **Test steps:**

    * leave the current name empty with some suggestions
    * verify the name label is not warning-colored
    """
    editor = PathEditor()
    qtbot.addWidget(editor)

    editor.set_suggestions(["Clean Title"])

    assert WARNING_COLOR not in name_label(editor).styleSheet()


def test_suggestions_are_transliterated_sanitized_deduplicated(qtbot: QtBot) -> None:
    """Suggestions are Unidecode-transliterated, filesystem-sanitized, de-duplicated, and empties dropped.

    **Test steps:**

    * set raw suggestions with accents, an invalid character, a duplicate-after-sanitize, and a blank
    * verify the resulting labels are the sanitized, de-duplicated, non-empty names
    """
    editor = PathEditor()
    qtbot.addWidget(editor)

    editor.set_suggestions(["Café: Intro", "Cafe: Intro", "Föo", "   "])

    assert list(suggestion_labels(editor).keys()) == ["Cafe Intro", "Foo"]


def test_suggestion_matching_current_name_is_disabled_without_a_link(qtbot: QtBot) -> None:
    """A suggestion equal to the current name renders disabled and without a hyperlink.

    **Test steps:**

    * set a current name matching one of two suggestions
    * verify that suggestion is disabled and plain text, the other enabled with a link
    """
    editor = PathEditor()
    qtbot.addWidget(editor)

    editor.set_current_name("Foo")
    editor.set_suggestions(["Foo", "Bar"])
    labels = suggestion_labels(editor)

    assert labels["Foo"].isEnabled() is False
    assert "<a " not in labels["Foo"].text()
    assert labels["Bar"].isEnabled() is True
    assert "<a " in labels["Bar"].text()


def test_clicking_a_suggestion_emits_its_sanitized_name(qtbot: QtBot) -> None:
    """Activating a suggestion's link emits ``suggestion_selected`` with its sanitized name.

    **Test steps:**

    * set an accented suggestion and connect to ``suggestion_selected``
    * activate its label's link and verify the sanitized name is emitted
    """
    editor = PathEditor()
    qtbot.addWidget(editor)
    editor.set_suggestions(["Föo"])
    received: list[str] = []
    editor.suggestion_selected.connect(received.append)

    suggestion_labels(editor)["Foo"].linkActivated.emit("#")

    assert received == ["Foo"]


def test_expanded_shows_and_hides_the_suggestions_panel(qtbot: QtBot) -> None:
    """``expanded`` shows or hides the suggestions panel.

    **Test steps:**

    * build an editor (collapsed by default) with a suggestion
    * verify the panel is hidden, then expand and verify it shows, then collapse again
    """
    editor = PathEditor()
    qtbot.addWidget(editor)
    editor.set_suggestions(["Foo"])

    assert editor.expanded is False
    assert suggestions_widget(editor).isVisibleTo(editor) is False

    editor.expanded = True
    assert suggestions_widget(editor).isVisibleTo(editor) is True

    editor.expanded = False
    assert suggestions_widget(editor).isVisibleTo(editor) is False


def test_set_suggestions_updates_the_list_live(qtbot: QtBot) -> None:
    """Re-setting the suggestions rebuilds the labels to the new set.

    **Test steps:**

    * set an initial suggestion set, then set a different one
    * verify the labels reflect the new set
    """
    editor = PathEditor()
    qtbot.addWidget(editor)

    editor.set_suggestions(["Alpha"])
    assert list(suggestion_labels(editor).keys()) == ["Alpha"]

    editor.set_suggestions(["Beta", "Gamma"])
    assert list(suggestion_labels(editor).keys()) == ["Beta", "Gamma"]
