"""Tests for RatingField: |value| stars via the shared Rating widget, and a bounded range-slider editor."""

from borco_pyside.widgets import Rating
from PySide6.QtWidgets import QSlider
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.rating_field import POSITIVE_STAR_GLYPH

from fields.field_testers import RatingFieldTester as RatingField


def label_text(rating: Rating) -> str:
    """Read the ``Rating`` widget's private internal label text (no public ``text()`` of its own).

    :param rating: the widget to inspect.
    :returns: the internal label's current text.
    """
    return rating._Rating__label.text()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def test_rating_field_viewer_is_a_rating_widget_tracking_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer is a ``Rating`` widget, seeded from the model and live-updating.

    **Test steps:**

    * build a ``rating`` viewer over a model seeded ``0``
    * verify it starts empty
    * set the model to a positive rating and verify the star glyph count follows
    """
    field = RatingField("rating")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, Rating)
    qtbot.addWidget(viewer)

    assert label_text(viewer) == ""

    model.rating = 3
    assert label_text(viewer) == POSITIVE_STAR_GLYPH * 3


def test_rating_field_editor_writes_back_a_negative_value(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Editing the slider writes a negative rating through to the model (§17.4).

    **Test steps:**

    * build the ``rating`` editor (a ``QSlider``)
    * set a negative value and verify ``model.rating`` follows
    """
    field = RatingField("rating")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, QSlider)
    qtbot.addWidget(editor)

    editor.setValue(-2)
    assert model.rating == -2


def test_rating_field_editor_and_viewer_echo_without_a_feedback_loop(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Editor -> model -> viewer stays live with no feedback loop (live "both").

    **Test steps:**

    * build an editor and a viewer over the same ``rating`` field and model
    * move the slider
    * verify the viewer reflects it and the slider still holds the value once (no echo loop)
    """
    field = RatingField("rating")
    editor = field.make_editor(model.bind(field)).editor
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(editor, QSlider)
    assert isinstance(viewer, Rating)
    qtbot.addWidget(editor)
    qtbot.addWidget(viewer)

    editor.setValue(4)

    assert model.rating == 4
    assert label_text(viewer) == POSITIVE_STAR_GLYPH * 4
    assert editor.value() == 4


def test_rating_field_editor_follows_an_external_model_change(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A model change from elsewhere updates the slider under the echo guard.

    **Test steps:**

    * build the ``rating`` editor
    * change ``model.rating`` directly (as another surface would)
    * verify the slider follows
    """
    field = RatingField("rating")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, QSlider)
    qtbot.addWidget(editor)

    model.rating = -3
    assert editor.value() == -3


def test_rating_field_editor_defaults_to_minus_five_to_five(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """With no explicit range, the slider defaults to ``-5``..``5``.

    **Test steps:**

    * build the editor for a ``RatingField`` with no range arguments
    * verify the slider's actual range is ``-5``..``5``
    """
    field = RatingField("rating")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, QSlider)
    qtbot.addWidget(editor)

    assert editor.minimum() == -5
    assert editor.maximum() == 5


def test_rating_field_editor_honors_an_explicit_range(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """An explicit ``minimum``/``maximum`` overrides ``RatingField``'s ``-5``/``5`` default.

    **Test steps:**

    * build the editor for a ``RatingField`` constructed with a narrower explicit range
    * verify the slider's actual range matches the explicit values, not the ``-5``/``5`` default
    """
    field = RatingField("rating", minimum=-2, maximum=3)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, QSlider)
    qtbot.addWidget(editor)

    assert editor.minimum() == -2
    assert editor.maximum() == 3
