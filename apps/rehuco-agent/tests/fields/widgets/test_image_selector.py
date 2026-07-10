"""Tests for ImageSelector: the checkable screenshot list and its hidden-filenames signal."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap, QStandardItemModel
from PySide6.QtWidgets import QListView, QStackedWidget, QWidget
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.image_selector import ImageSelector, PreviewLabel

PATHS = [Path("/fake/info00.jpg"), Path("/fake/info01.png"), Path("/fake/info02.gif")]


def checkable_model(selector: ImageSelector) -> QStandardItemModel:
    """The selector's list model, reached through its list view child.

    :param selector: the selector under test.
    :returns: the underlying ``QStandardItemModel``.
    """
    view = selector.findChild(QListView)
    assert isinstance(view, QListView)
    model = view.model()
    assert isinstance(model, QStandardItemModel)
    return model


def test_set_images_checks_every_row_not_hidden(qtbot: QtBot) -> None:
    """Each screenshot is a checkable row, checked unless its filename is in ``hidden``.

    **Test steps:**

    * seed three screenshots with the middle one hidden
    * verify all three rows exist, checkable, with only the hidden one unchecked
    """
    selector = ImageSelector()
    qtbot.addWidget(selector)
    selector.set_images(PATHS, ["info01.png"])

    model = checkable_model(selector)
    assert model.rowCount() == 3
    assert model.item(0).checkState() == Qt.CheckState.Checked
    assert model.item(1).checkState() == Qt.CheckState.Unchecked
    assert model.item(2).checkState() == Qt.CheckState.Checked


def test_hidden_filenames_reports_unchecked_rows(qtbot: QtBot) -> None:
    """``hidden_filenames`` lists exactly the unchecked rows, in order.

    **Test steps:**

    * seed three screenshots with two hidden
    * verify ``hidden_filenames`` returns those two names
    """
    selector = ImageSelector()
    qtbot.addWidget(selector)
    selector.set_images(PATHS, ["info00.jpg", "info02.gif"])

    assert selector.hidden_filenames() == ["info00.jpg", "info02.gif"]


def test_seeding_does_not_emit_hidden_changed(qtbot: QtBot) -> None:
    """Seeding the list never looks like a user toggle -- no ``hidden_changed`` fires.

    **Test steps:**

    * connect a recorder to ``hidden_changed``
    * seed the list
    * verify nothing was emitted
    """
    selector = ImageSelector()
    qtbot.addWidget(selector)
    emitted: list[list[str]] = []
    selector.hidden_changed.connect(emitted.append)

    selector.set_images(PATHS, ["info00.jpg"])

    assert emitted == []


def test_preview_label_scales_its_source_to_fit_preserving_aspect(qtbot: QtBot) -> None:
    """The preview scales a source pixmap down to fit the label, keeping its aspect ratio.

    Regression: seeding the source before the label has its laid-out size must still produce a correctly
    fitted first paint (the label rescales in its own resize), not an oversized one.

    **Test steps:**

    * set a 320x180 source on a preview label seeded before it is sized
    * size and show the label smaller than the source
    * verify the rendered pixmap fits the label and preserves the 16:9 aspect ratio
    """
    label = PreviewLabel()
    qtbot.addWidget(label)
    source = QPixmap(320, 180)
    source.fill(QColor("teal"))

    label.set_source(source)
    label.resize(200, 400)
    label.show()
    qtbot.waitExposed(label)

    rendered = label.pixmap()
    assert rendered.width() <= label.width()
    assert rendered.height() <= label.height()
    assert abs(rendered.width() / rendered.height() - 320 / 180) < 0.05


def test_preview_label_rescales_when_shown_after_being_hidden(qtbot: QtBot) -> None:
    """A source seeded while the label is on a hidden page still fits once the page is shown.

    Regression: a QtAds tab hidden at restore never delivers a real resize to its content, so the preview
    must rescale on show, not stay stuck at a tiny first paint when the tab is later selected.

    **Test steps:**

    * put the preview on the non-current page of a shown stack and seed a source while it is hidden
    * switch the stack to the preview's page
    * verify the rendered pixmap now fills (not a tiny stale paint) and fits the label
    """
    stack = QStackedWidget()
    qtbot.addWidget(stack)
    label = PreviewLabel()
    stack.addWidget(QWidget())
    stack.addWidget(label)
    stack.setCurrentIndex(0)
    stack.resize(600, 400)
    stack.show()
    qtbot.waitExposed(stack)
    source = QPixmap(320, 180)
    source.fill(QColor("teal"))
    label.set_source(source)

    stack.setCurrentIndex(1)

    rendered = label.pixmap()
    assert rendered.width() > 10
    assert rendered.width() <= label.width()
    assert rendered.height() <= label.height()


def test_unchecking_a_row_emits_the_new_hidden_list(qtbot: QtBot) -> None:
    """Unchecking a row re-emits ``hidden_changed`` with the current hidden filenames.

    **Test steps:**

    * seed three all-visible screenshots
    * uncheck the first row
    * verify ``hidden_changed`` fired with that filename
    """
    selector = ImageSelector()
    qtbot.addWidget(selector)
    selector.set_images(PATHS, [])
    emitted: list[list[str]] = []
    selector.hidden_changed.connect(emitted.append)

    checkable_model(selector).item(0).setCheckState(Qt.CheckState.Unchecked)

    assert emitted == [["info00.jpg"]]
