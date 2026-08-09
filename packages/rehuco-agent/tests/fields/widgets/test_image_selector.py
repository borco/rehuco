"""Tests for ImageSelector: the checkable screenshot list and its hidden-filenames signal."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap, QStandardItemModel
from PySide6.QtWidgets import QLabel, QStackedWidget, QTreeView, QWidget
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.image_selector import (
    LIST_PANE,
    PREVIEW_HEIGHT,
    PREVIEW_PANE,
    ImageSelector,
    PreviewLabel,
)

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


def test_preview_sits_above_the_list(qtbot: QtBot) -> None:
    """The splitter runs top-to-bottom with the preview first and the screenshot list under it (#72).

    **Test steps:**

    * build a selector
    * verify the splitter is vertical and the tree view is its second pane
    """
    selector = ImageSelector()
    qtbot.addWidget(selector)

    assert selector.orientation() == Qt.Orientation.Vertical
    view = selector.findChild(QTreeView)
    assert isinstance(view, QTreeView)
    assert selector.indexOf(view) == LIST_PANE


def test_the_preview_opens_at_the_configured_height(qtbot: QtBot) -> None:
    """A selector with no split remembered gives the preview the height it was built with (#72).

    **Test steps:**

    * build a selector at a named preview height and show it
    * verify the preview pane got exactly that height and the list took the rest
    """
    selector = ImageSelector(preview_height=120)
    qtbot.addWidget(selector)
    selector.resize(400, 300)
    selector.show()
    qtbot.waitExposed(selector)

    assert selector.sizes()[PREVIEW_PANE] == 120
    assert sum(selector.sizes()) + selector.handleWidth() == 300


def test_the_preview_defaults_to_a_hundred_pixels(qtbot: QtBot) -> None:
    """Naming no height opens the preview at :data:`PREVIEW_HEIGHT` (#72).

    **Test steps:**

    * build and show a selector without naming a preview height
    * verify the preview pane is the module's declared default tall
    """
    selector = ImageSelector()
    qtbot.addWidget(selector)
    selector.resize(400, 300)
    selector.show()
    qtbot.waitExposed(selector)

    assert selector.sizes()[PREVIEW_PANE] == PREVIEW_HEIGHT
    assert PREVIEW_HEIGHT == 100


def test_setting_a_new_preview_height_re_splits_a_shown_selector(qtbot: QtBot) -> None:
    """An applied height reaches the selector already on screen, overriding the split it was on (#72).

    **Test steps:**

    * show a selector and drag its split away from the configured height
    * set a new preview height
    * verify the preview pane took it
    """
    selector = ImageSelector()
    qtbot.addWidget(selector)
    selector.resize(400, 300)
    selector.show()
    qtbot.waitExposed(selector)
    selector.setSizes([250, 50])

    selector.set_preview_height(140)

    assert selector.sizes()[PREVIEW_PANE] == 140


def test_setting_the_height_it_already_has_leaves_a_dragged_split_alone(qtbot: QtBot) -> None:
    """An unchanged height is not an applied one, so it never undoes the user's own drag (#72).

    Applying the settings page rewrites every choice it holds, whether or not each actually moved --
    without this guard, saving an unrelated image setting would snap every open editor back off the
    split its user had just dragged.

    **Test steps:**

    * show a selector and drag its split away from the configured height
    * set the height it already has
    * verify the dragged split survived
    """
    selector = ImageSelector(preview_height=120)
    qtbot.addWidget(selector)
    selector.resize(400, 300)
    selector.show()
    qtbot.waitExposed(selector)
    selector.setSizes([250, 50])
    dragged = selector.sizes()

    selector.set_preview_height(120)

    assert selector.sizes() == dragged


def test_a_height_set_while_hidden_lands_on_the_next_show(qtbot: QtBot) -> None:
    """A selector behind another tab has no room to divide, so the new height waits for its show (#72).

    **Test steps:**

    * set a preview height on a selector that was never shown
    * size and show it
    * verify the preview pane opened at that height
    """
    selector = ImageSelector()
    qtbot.addWidget(selector)

    selector.set_preview_height(140)
    selector.resize(400, 300)
    selector.show()
    qtbot.waitExposed(selector)

    assert selector.sizes()[PREVIEW_PANE] == 140


def test_a_restored_split_wins_over_the_configured_height(qtbot: QtBot) -> None:
    """A document's own remembered split is not overwritten by the configured height on show (#72).

    **Test steps:**

    * capture a lopsided split off a shown selector
    * restore it onto a second selector *before* that one is ever shown, then show it
    * verify the restored split survived rather than the configured height replacing it
    """
    source = ImageSelector()
    qtbot.addWidget(source)
    source.resize(400, 300)
    source.show()
    qtbot.waitExposed(source)
    source.setSizes([220, 75])

    restored = ImageSelector()
    qtbot.addWidget(restored)
    restored.restore_state(source.save_state())
    restored.resize(400, 300)
    restored.show()
    qtbot.waitExposed(restored)

    assert restored.sizes() == source.sizes()


def preview_pane(selector: ImageSelector) -> QWidget:
    """The selector's preview pane -- the splitter's top child (#71).

    :param selector: the selector under test.
    :returns: the widget holding the preview and its size overlay.
    """
    pane = selector.widget(PREVIEW_PANE)
    assert isinstance(pane, QWidget)
    return pane


def test_toggling_previews_off_folds_the_preview_pane_away(qtbot: QtBot) -> None:
    """The editor answers the app-wide previews toggle, leaving the curation list on its own (#71).

    **Test steps:**

    * show a selector
    * toggle previews off
    * verify the preview pane is hidden and the list is not
    """
    selector = ImageSelector()
    qtbot.addWidget(selector)
    selector.resize(400, 300)
    selector.show()
    qtbot.waitExposed(selector)

    selector.set_previews_visible(False)

    assert not preview_pane(selector).isVisible()
    list_pane = selector.widget(LIST_PANE)
    assert list_pane is not None
    assert list_pane.isVisible()


def test_toggling_previews_back_on_restores_the_split_it_hid_at(qtbot: QtBot) -> None:
    """The split is held while the pane is folded away, not lost to the collapse (#71, #72).

    **Test steps:**

    * show a selector, drag its split, then toggle previews off
    * toggle them back on
    * verify the pane came back at the split it left
    """
    selector = ImageSelector()
    qtbot.addWidget(selector)
    selector.resize(400, 300)
    selector.show()
    qtbot.waitExposed(selector)
    selector.setSizes([220, 75])
    dragged = selector.sizes()
    selector.set_previews_visible(False)

    selector.set_previews_visible(True)

    assert preview_pane(selector).isVisible()
    assert selector.sizes() == dragged


def test_saving_while_previews_are_off_keeps_the_split_not_the_collapse(qtbot: QtBot) -> None:
    """A document saved with previews toggled away records the split it will come back to (#71, #72).

    Without this the toggle would quietly cost every open document its split: a collapsed pane is the
    toggle's doing, not something the user asked to remember.

    **Test steps:**

    * show a selector, drag its split, and toggle previews off
    * save its state and restore it onto a fresh, previews-on selector
    * verify the dragged split came back, not a collapsed pane
    """
    selector = ImageSelector()
    qtbot.addWidget(selector)
    selector.resize(400, 300)
    selector.show()
    qtbot.waitExposed(selector)
    selector.setSizes([220, 75])
    dragged = selector.sizes()
    selector.set_previews_visible(False)

    restored = ImageSelector()
    qtbot.addWidget(restored)
    restored.resize(400, 300)
    restored.show()
    qtbot.waitExposed(restored)
    restored.restore_state(selector.save_state())

    assert restored.sizes() == dragged


def test_a_split_restored_while_previews_are_off_lands_when_they_return(qtbot: QtBot) -> None:
    """A document reopened with previews off still opens at its own split once they return (#71, #72).

    **Test steps:**

    * capture a lopsided split, then restore it onto a shown selector whose previews are off
    * toggle previews back on
    * verify the restored split is what the pane opens at
    """
    source = ImageSelector()
    qtbot.addWidget(source)
    source.resize(400, 300)
    source.show()
    qtbot.waitExposed(source)
    source.setSizes([220, 75])

    restored = ImageSelector()
    qtbot.addWidget(restored)
    restored.resize(400, 300)
    restored.show()
    qtbot.waitExposed(restored)
    restored.set_previews_visible(False)
    restored.restore_state(source.save_state())

    restored.set_previews_visible(True)

    assert restored.sizes() == source.sizes()


def test_a_height_applied_while_previews_are_off_wins_when_they_return(qtbot: QtBot) -> None:
    """An applied height beats the split held from before the pane folded away (#71, #72).

    The held split is the answer to "where was it", and a height applied since is the more recent
    statement -- coming back to the older split would ignore the setting the user just saved.

    **Test steps:**

    * show a selector, drag its split, and toggle previews off
    * apply a new preview height, then toggle previews back on
    * verify the pane opened at the applied height rather than the held split
    """
    selector = ImageSelector()
    qtbot.addWidget(selector)
    selector.resize(400, 300)
    selector.show()
    qtbot.waitExposed(selector)
    selector.setSizes([220, 75])
    selector.set_previews_visible(False)

    selector.set_preview_height(140)
    selector.set_previews_visible(True)

    assert selector.sizes()[PREVIEW_PANE] == 140


def test_a_selector_toggled_off_before_it_was_laid_out_opens_at_the_configured_height(qtbot: QtBot) -> None:
    """Toggled away before its first layout, there is no split worth holding (#71, #72).

    **Test steps:**

    * toggle previews off on a selector that was never shown, then back on
    * size and show it
    * verify the pane opened at the configured height
    """
    selector = ImageSelector(preview_height=120)
    qtbot.addWidget(selector)

    selector.set_previews_visible(False)
    selector.set_previews_visible(True)
    selector.resize(400, 300)
    selector.show()
    qtbot.waitExposed(selector)

    assert selector.sizes()[PREVIEW_PANE] == 120


def test_toggling_previews_to_the_state_they_are_in_changes_nothing(qtbot: QtBot) -> None:
    """Re-stating the current toggle is not a toggle, so it never disturbs the split (#71).

    **Test steps:**

    * show a selector and drag its split
    * set previews visible when they already are
    * verify the pane is still shown at the dragged split
    """
    selector = ImageSelector()
    qtbot.addWidget(selector)
    selector.resize(400, 300)
    selector.show()
    qtbot.waitExposed(selector)
    selector.setSizes([220, 75])
    dragged = selector.sizes()

    selector.set_previews_visible(True)

    assert preview_pane(selector).isVisible()
    assert selector.sizes() == dragged


def test_split_position_survives_a_save_restore_round_trip(qtbot: QtBot) -> None:
    """The split position is this widget's own persisted state, restored onto a fresh selector (#72).

    **Test steps:**

    * size and show a selector, then drag its split to a deliberately lopsided position
    * save its state and restore it onto a second, identically-sized selector
    * verify the second selector's panes end up the same sizes as the first's
    """
    selector = ImageSelector()
    qtbot.addWidget(selector)
    selector.resize(400, 300)
    selector.show()
    qtbot.waitExposed(selector)
    selector.setSizes([220, 80])

    restored = ImageSelector()
    qtbot.addWidget(restored)
    restored.resize(400, 300)
    restored.show()
    qtbot.waitExposed(restored)
    restored.restore_state(selector.save_state())

    assert restored.sizes() == selector.sizes()


def test_restore_state_ignores_a_blob_qt_refuses(qtbot: QtBot) -> None:
    """An unrecognized blob leaves the constructor's own split alone instead of raising (#72).

    **Test steps:**

    * record a shown selector's split
    * restore garbage onto it
    * verify the split is unchanged
    """
    selector = ImageSelector()
    qtbot.addWidget(selector)
    selector.resize(400, 300)
    selector.show()
    qtbot.waitExposed(selector)
    before = selector.sizes()

    selector.restore_state(b"not a splitter state")

    assert selector.sizes() == before


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
