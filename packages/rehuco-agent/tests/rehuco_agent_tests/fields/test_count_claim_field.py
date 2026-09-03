"""Tests for CountClaimField: an open-ended claim edited as validated text, empty meaning absent."""

from typing import cast

from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QLabel
from pytest import mark, param
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.widgets import LineEdit

from rehuco_agent_tests.fields.field_testers import CountClaimFieldTester as CountClaimField


def test_count_claim_viewer_shows_and_tracks_the_claim(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer shows the claim as published and re-renders when the model changes; absent renders
    empty, not the string ``"None"`` ([[field-schema#deferred-items]]).

    **Test steps:**

    * build an ``advertised_count`` viewer over a model with no claim
    * verify the label starts empty
    * set an open-ended claim and verify the label shows it verbatim
    """
    field = CountClaimField("advertised_count")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(viewer)

    assert viewer.text() == ""

    model.advertised_count = "500+"
    assert viewer.text() == "500+"


@mark.parametrize("claim", [param("500", id="exact"), param("500+", id="open-ended")])
def test_count_claim_editor_round_trips_a_claim(qtbot: QtBot, model: RehuDocumentModel, claim: str) -> None:
    """Both shapes a claim takes survive the editor unchanged -- the ``+`` is the reason this field is
    text rather than an integer (#198).

    **Test steps:**

    * seed the model with the claim and build the editor
    * verify the editor shows it, then retype it and verify the model still holds exactly it

    :param claim: the claim to round-trip.
    """
    model.advertised_count = claim
    field = CountClaimField("advertised_count")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, LineEdit)
    qtbot.addWidget(editor)

    assert editor.text() == claim

    editor.setText(claim)
    assert model.advertised_count == claim


def test_count_claim_editor_writes_back_to_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Typing a claim writes through to the model.

    **Test steps:**

    * build the ``advertised_count`` editor and type a claim
    * verify the model followed
    """
    field = CountClaimField("advertised_count")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, LineEdit)
    qtbot.addWidget(editor)

    editor.setText("500+")

    assert model.advertised_count == "500+"


def test_count_claim_editor_clears_to_absent_rather_than_an_empty_string(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """Emptying the editor writes ``None`` -- absent is not ``""`` ([[field-schema#deferred-items]]), so
    the key is removed rather than stored blank.

    **Test steps:**

    * seed a claim, build the editor, and clear it
    * verify the model reads ``None`` and the document no longer carries the key
    """
    model.advertised_count = "500+"
    field = CountClaimField("advertised_count")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, LineEdit)
    qtbot.addWidget(editor)

    editor.setText("")

    assert model.advertised_count is None
    assert "advertised_count" not in model.document.active_block


def test_count_claim_editor_seeds_empty_from_an_absent_claim(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """An absent claim edits as an empty line, not as a placeholder to delete.

    **Test steps:**

    * build the editor over a model with no claim
    * verify the editor is empty
    """
    field = CountClaimField("advertised_count")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, LineEdit)
    qtbot.addWidget(editor)

    assert editor.text() == ""


def test_count_claim_editor_follows_an_external_model_change(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A model change from elsewhere updates the editor under the widget's echo guard.

    **Test steps:**

    * build the editor, then change ``model.advertised_count`` directly
    * verify the editor followed, and that clearing the model empties it again
    """
    field = CountClaimField("advertised_count")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, LineEdit)
    qtbot.addWidget(editor)

    model.advertised_count = "500+"
    assert editor.text() == "500+"

    model.advertised_count = None
    assert editor.text() == ""


@mark.parametrize(
    ("text", "acceptable"),
    [
        param("500", True, id="exact-count"),
        param("500+", True, id="open-ended-count"),
        param("", True, id="empty-is-absent"),
        param("5+0", False, id="digits-after-the-plus"),
        param("+500", False, id="leading-plus"),
        param("500++", False, id="two-pluses"),
        param("lots", False, id="not-a-number"),
    ],
)
def test_count_claim_editor_accepts_only_a_count_shape(
    qtbot: QtBot, model: RehuDocumentModel, text: str, acceptable: bool
) -> None:
    """The editor's validator accepts a whole number optionally followed by one ``+``, and refuses
    anything else as it is typed (#198).

    **Test steps:**

    * build the editor and ask its validator to judge each text
    * verify only the count shapes come back ``Acceptable``

    :param text: the text to judge.
    :param acceptable: whether the validator should accept it outright.
    """
    field = CountClaimField("advertised_count")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, LineEdit)
    qtbot.addWidget(editor)
    validator = editor.validator()
    assert validator is not None

    # validate() is (state, text, pos); the PySide6 stub types the whole return as object
    state, _text, _pos = cast(tuple[QValidator.State, str, int], validator.validate(text, len(text)))

    assert (state == QValidator.State.Acceptable) is acceptable
