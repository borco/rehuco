"""Tests for ImageSelector: the checkable screenshot list and its hidden-filenames signal."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap, QStandardItemModel
from PySide6.QtWidgets import QLabel, QStackedWidget, QTreeView, QWidget
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.image_selector import ImageSelector, PreviewLabel

PATHS = [Path("/fake/info00.jpg"), Path("/fake/info01.png"), Path("/fake/info02.gif")]


def fake_scanner(mocker: MockerFixture, files: list[Path]) -> object:
    """A minimal ``ImageScanner`` stand-in returning a fixed file list.

    :param mocker: pytest-mock fixture.
    :param files: the fixed file list ``.files()`` reports.
    :returns: the stand-in scanner.
    """
    return mocker.Mock(files=mocker.Mock(return_value=files))


def checkable_model(selector: ImageSelector) -> QStandardItemModel:
    """The selector's list model, reached through its tree view child.

    :param selector: the selector under test.
    :returns: the underlying ``QStandardItemModel``.
    """
    view = selector.findChild(QTreeView)
    assert isinstance(view, QTreeView)
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

    assert not emitted


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


def test_set_hidden_skips_a_rebuild_when_unchanged(qtbot: QtBot) -> None:
    """``set_hidden`` is a no-op when ``hidden`` already matches what's shown -- the echo-suppression
    for the selector's own toggle coming back through the model binding.

    No scanner is ever attached here (stays the default ``None``): if the guard failed to skip, the
    rebuild would run against that ``None`` scanner and empty the list -- so an empty list would prove
    the guard didn't fire, while the original three rows surviving proves it did.

    **Test steps:**

    * seed the selector directly via ``set_images``, with no scanner attached
    * call ``set_hidden`` with the *same* hidden list already shown
    * verify the rows are untouched (still the original ``set_images`` seed)
    """
    selector = ImageSelector()
    qtbot.addWidget(selector)
    selector.set_images(PATHS, ["info01.png"])

    selector.set_hidden(["info01.png"])

    assert checkable_model(selector).rowCount() == 3


def test_set_hidden_rebuilds_from_the_current_scanner_when_it_actually_changes(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """``set_hidden`` rebuilds from the current scanner's files when ``hidden`` actually changes.

    **Test steps:**

    * seed the selector, attach a scanner reporting a different, smaller file set
    * call ``set_hidden`` with a genuinely different hidden list
    * verify the rebuild reflects the scanner's files, not the original seed
    """
    selector = ImageSelector()
    qtbot.addWidget(selector)
    selector.set_images(PATHS, [])
    selector.image_scanner = fake_scanner(mocker, PATHS[:1])  # type: ignore[assignment]

    selector.set_hidden(["info01.png"])

    assert checkable_model(selector).rowCount() == 1


def test_assigning_a_new_scanner_rebuilds_unconditionally(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Assigning a new ``image_scanner`` always rebuilds, even with an unchanged hidden list.

    **Test steps:**

    * seed the selector via ``set_images`` with nothing hidden
    * assign a scanner reporting a different, smaller file set
    * verify the rebuild reflects the new scanner despite ``hidden_filenames()`` staying ``[]``
    """
    selector = ImageSelector()
    qtbot.addWidget(selector)
    selector.set_images(PATHS, [])
    assert selector.hidden_filenames() == []

    selector.image_scanner = fake_scanner(mocker, PATHS[:1])  # type: ignore[assignment]

    assert checkable_model(selector).rowCount() == 1


def test_no_scanner_shows_nothing(qtbot: QtBot) -> None:
    """A scanner change to ``None``-backed refresh paths show nothing rather than raising.

    **Test steps:**

    * call ``set_hidden`` on a selector with no scanner assigned (the default)
    * verify the list stays empty
    """
    selector = ImageSelector()
    qtbot.addWidget(selector)

    selector.set_hidden([])

    assert checkable_model(selector).rowCount() == 0


def size_overlay(selector: ImageSelector) -> QLabel:
    """The selector's preview size-overlay label.

    :param selector: the selector under test.
    :returns: the ``QLabel`` overlaying the preview with its pixel dimensions.
    """
    return selector._ImageSelector__size_overlay  # type: ignore[attr-defined]  # pylint: disable=protected-access


def test_selecting_a_loadable_screenshot_shows_its_dimensions(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Selecting a screenshot that loads previews it and labels the overlay with its pixel size.

    **Test steps:**

    * seed screenshots with a stubbed loader yielding a 320x180 pixmap
    * select the first row
    * verify the size overlay reads its dimensions
    """
    mocker.patch("rehuco_agent.fields.widgets.image_selector.QPixmap", side_effect=lambda *_: QPixmap(320, 180))
    selector = ImageSelector()
    qtbot.addWidget(selector)
    selector.set_images(PATHS, [])

    view = selector.findChild(QTreeView)
    assert isinstance(view, QTreeView)
    view.setCurrentIndex(view.model().index(0, 0))

    assert size_overlay(selector).text() == "320 x 180"


def test_set_images_populates_dimensions_and_size_columns_from_disk(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A row's dimensions/size columns come from ``PIL.Image.open`` and ``Path.stat``, humanized GNU-style.

    **Test steps:**

    * stub ``Image.open`` to report a fixed 320x180 size and ``Path.stat`` to report a fixed byte count
    * seed one screenshot
    * verify the dimensions and size columns render the expected text
    """
    image = mocker.MagicMock(size=(320, 180))
    image.__enter__.return_value = image
    mocker.patch("rehuco_agent.fields.widgets.image_selector.Image.open", return_value=image)
    mocker.patch.object(Path, "stat", return_value=mocker.Mock(st_size=1_500_000))
    selector = ImageSelector()
    qtbot.addWidget(selector)

    selector.set_images(PATHS[:1], [])

    model = checkable_model(selector)
    assert model.item(0, 1).text() == "320 x 180"
    assert model.item(0, 2).text() == "1.4M"


def test_set_images_blanks_dimensions_and_size_for_unreadable_files(qtbot: QtBot) -> None:
    """A path that doesn't resolve to a real, decodable image blanks both columns instead of raising.

    **Test steps:**

    * seed a screenshot at a nonexistent fake path (no stubbing)
    * verify the dimensions and size columns are both blank
    """
    selector = ImageSelector()
    qtbot.addWidget(selector)

    selector.set_images(PATHS[:1], [])

    model = checkable_model(selector)
    assert model.item(0, 1).text() == ""
    assert model.item(0, 2).text() == ""
