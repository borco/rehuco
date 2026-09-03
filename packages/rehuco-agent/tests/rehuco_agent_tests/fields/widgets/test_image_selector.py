"""Tests for ImageSelector: the checkable screenshot list, its split, and rearranging on disk."""

# one cohesive module: this is the curation editor's whole behaviour -- its rows, its preview, its
# split and the renames behind its move/delete buttons -- and a scoped disable reads better than an
# arbitrary file split (same precedent as test_rehu_document_model.py, [[appendices.code-conventions]])
# pylint: disable=too-many-lines

from collections.abc import Sequence
from pathlib import Path

from borco_pyside.widgets import ActionButtonColumn
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QLabel,
    QMessageBox,
    QStackedWidget,
    QToolButton,
    QTreeView,
    QWidget,
)
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.image_selector import (
    DIMENSIONS_COLUMN,
    LIST_PANE,
    NAME_COLUMN,
    PATH_ROLE,
    PREVIEW_HEIGHT,
    PREVIEW_PANE,
    SIZE_COLUMN,
    ImageSelector,
    PreviewLabel,
    ScreenshotListModel,
    ScreenshotOrdering,
)
from rehuco_core import plan_screenshot_renumbering

DIRECTORY = Path("/fake")
STEM = "info"
PATHS = [DIRECTORY / "info00.jpg", DIRECTORY / "info01.png", DIRECTORY / "info02.gif"]


# region Sample classes


class FakeResource:
    """A resource's screenshots, in memory: an `ImageScanner` and an `ImageOrganizer` in one object.

    Both halves of the contract answer from one list of filenames, which is exactly the coupling a
    real resource has -- the scanner reports what the organizer's renames left behind. The renames
    themselves come from the *real* `plan_screenshot_renumbering`, so a test here exercises the
    naming rule the app actually ships rather than a second copy of it, without a directory.
    """

    def __init__(self, names: list[str]) -> None:
        self.names = list(names)
        self.removed: list[str] = []
        self.failure: OSError | None = None
        """Set to make every rearrangement refuse, standing in for a disk that would not take it."""

    def files(self) -> list[Path]:
        """Every screenshot, in slot order (`ImageScanner`)."""
        return [DIRECTORY / name for name in self.names]

    def reorder(self, ordered: Sequence[Path]) -> dict[str, str]:
        """Renumber to ``ordered`` (`ImageOrganizer`).

        :param ordered: the screenshots in the order wanted.
        :returns: what was renamed.
        :raises OSError: when the test declared this resource unwritable.
        """
        return self.__renumber(ordered)

    def remove(self, path: Path, remaining: Sequence[Path]) -> dict[str, str]:
        """Drop ``path`` and renumber the survivors (`ImageOrganizer`).

        :param path: the screenshot deleted.
        :param remaining: the survivors, in the order wanted.
        :returns: what was renamed.
        :raises OSError: when the test declared this resource unwritable.
        """
        renames = self.__renumber(remaining)
        self.removed.append(path.name)
        return renames

    def __renumber(self, ordered: Sequence[Path]) -> dict[str, str]:
        """Apply the real rename plan for ``ordered`` to this resource's filenames.

        :param ordered: the screenshots in the order wanted.
        :returns: what was renamed.
        :raises OSError: when the test declared this resource unwritable.
        """
        if self.failure is not None:
            raise self.failure
        renames = plan_screenshot_renumbering(STEM, ordered)
        self.names = [renames.get(path.name, path.name) for path in ordered]
        return renames


def seeded(qtbot: QtBot, resource: FakeResource, hidden: list[str] | None = None) -> ImageSelector:
    """A selector wired to ``resource`` as both its scanner and its organizer, showing its rows.

    :param qtbot: pytest-qt fixture, which takes ownership of the widget.
    :param resource: the in-memory resource to show and rearrange.
    :param hidden: filenames to start curated out, if any.
    :returns: the selector under test.
    """
    selector = ImageSelector()
    qtbot.addWidget(selector)
    selector.image_scanner = resource  # type: ignore[assignment]
    selector.image_organizer = resource  # type: ignore[assignment]
    selector.set_images(resource.files(), hidden or [])
    return selector


def trigger(selector: ImageSelector, text: str) -> None:
    """Fire the named action the way its button and its shortcut both do.

    Goes through the action rather than calling the selector's own method, so what is tested is the
    button a user clicks -- the two action columns, their enabled rules, and the protocol adapter
    between them and the screenshots.

    :param selector: the selector under test.
    :param text: the action's text, e.g. ``"Move Up"``.
    """
    view = selector.findChild(QTreeView)
    assert isinstance(view, QTreeView)
    matching = [action for action in view.actions() if action.text() == text]
    assert len(matching) == 1
    matching[0].trigger()


def row_names(selector: ImageSelector) -> list[str]:
    """The filenames the list is currently showing, in row order.

    :param selector: the selector under test.
    :returns: one name per row.
    """
    return [path.name for path in selector.screenshot_paths()]


# endregion


def fake_scanner(mocker: MockerFixture, files: list[Path]) -> object:
    """A minimal ``ImageScanner`` stand-in returning a fixed file list.

    :param mocker: pytest-mock fixture.
    :param files: the fixed file list ``.files()`` reports.
    :returns: the stand-in scanner.
    """
    return mocker.Mock(files=mocker.Mock(return_value=files))


def checkable_model(selector: ImageSelector) -> ScreenshotListModel:
    """The selector's list model, reached through its tree view child.

    :param selector: the selector under test.
    :returns: the underlying model.
    """
    view = selector.findChild(QTreeView)
    assert isinstance(view, QTreeView)
    model = view.model()
    assert isinstance(model, ScreenshotListModel)
    return model


def check_state(model: ScreenshotListModel, row: int) -> Qt.CheckState:
    """The check state of one row's name cell.

    :param model: the model to read.
    :param row: the row to read.
    :returns: whether that screenshot is shown in the lightbox.
    """
    return model.index(row, NAME_COLUMN).data(Qt.ItemDataRole.CheckStateRole)


def cell(model: ScreenshotListModel, row: int, column: int) -> str:
    """The displayed text of one cell.

    :param model: the model to read.
    :param row: the row to read.
    :param column: the column to read.
    :returns: what the view would paint there.
    """
    return model.index(row, column).data()


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
    assert check_state(model, 0) == Qt.CheckState.Checked
    assert check_state(model, 1) == Qt.CheckState.Unchecked
    assert check_state(model, 2) == Qt.CheckState.Checked


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

    model = checkable_model(selector)
    model.setData(model.index(0, NAME_COLUMN), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)

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
    assert cell(model, 0, DIMENSIONS_COLUMN) == "320 x 180"
    assert cell(model, 0, SIZE_COLUMN) == "1.4M"


def test_preview_sits_above_the_list(qtbot: QtBot) -> None:
    """The splitter runs top-to-bottom with the preview first and the screenshot list under it (#72).

    **Test steps:**

    * build a selector
    * verify the splitter is vertical and the list pane, holding the tree view, is its second pane
    """
    selector = ImageSelector()
    qtbot.addWidget(selector)

    assert selector.orientation() == Qt.Orientation.Vertical
    view = selector.findChild(QTreeView)
    assert isinstance(view, QTreeView)
    list_pane = view.parentWidget()
    assert list_pane is not None
    assert selector.indexOf(list_pane) == LIST_PANE


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
    assert cell(model, 0, DIMENSIONS_COLUMN) == ""
    assert cell(model, 0, SIZE_COLUMN) == ""


# region rearranging on disk (#72)


def test_moving_a_screenshot_up_renames_the_pair(qtbot: QtBot) -> None:
    """A move *is* a rename: the two trade slot numbers and keep their own extensions (#72).

    **Test steps:**

    * move the second of three screenshots up
    * verify the resource's filenames swapped and the rows follow
    """
    resource = FakeResource(["info00.jpg", "info01.png", "info02.gif"])
    selector = seeded(qtbot, resource)

    assert selector.move_screenshot(1, 0) == 0

    assert resource.names == ["info00.png", "info01.jpg", "info02.gif"]
    assert row_names(selector) == ["info00.png", "info01.jpg", "info02.gif"]


def test_a_move_restructures_the_rows_instead_of_resetting_them(qtbot: QtBot) -> None:
    """One row moves and the rest stay put -- the model is not rebuilt for a rearrangement (#72).

    Regression, twice over. The rearrangement used to clear and refill the whole model, which also
    re-read every file's dimensions and size off disk; and it did so with the model's signals
    blocked, so neither the reset nor the insertions reached the view at all. The view went on
    painting the rows it had last laid out -- refreshing only where a hover happened to repaint one
    -- while holding indexes into items already freed, which crashed after a few moves.

    **Test steps:**

    * record the model's structural signals, then move a screenshot
    * verify the view was told one row moved, and nothing was reset, removed or inserted
    """
    resource = FakeResource(["info00.jpg", "info01.png", "info02.gif"])
    selector = seeded(qtbot, resource)
    model = checkable_model(selector)
    reported: list[str] = []
    model.modelReset.connect(lambda: reported.append("reset"))
    model.rowsRemoved.connect(lambda *_: reported.append("removed"))
    model.rowsInserted.connect(lambda *_: reported.append("inserted"))
    moved: list[tuple[int, int, int]] = []
    model.rowsMoved.connect(
        lambda _parent, start, end, _destination, row: moved.append((start, end, row))  # noqa: PLR0913
    )

    selector.move_screenshot(2, 0)

    assert moved == [(2, 2, 0)]
    assert not reported


def test_the_model_answers_nothing_for_a_cell_that_is_not_there() -> None:
    """An index naming no row has no data and no flags, rather than raising (#72).

    A view asks about indexes a model may no longer hold -- during a reset, or from a stale
    persistent index -- so the honest answer is nothing at all.

    **Test steps:**

    * ask an empty model about an invalid index, and a populated one about a row past its end
    * verify each answers with nothing
    """
    model = ScreenshotListModel()
    model.set_rows([DIRECTORY / "info00.jpg"], [])

    assert model.data(QModelIndex()) is None
    assert model.flags(QModelIndex()) == Qt.ItemFlag.NoItemFlags
    assert model.data(model.index(0, NAME_COLUMN), Qt.ItemDataRole.ToolTipRole) is None
    assert model.rowCount(model.index(0, NAME_COLUMN)) == 0
    assert model.columnCount(model.index(0, NAME_COLUMN)) == 0
    assert model.headerData(0, Qt.Orientation.Vertical) is None
    assert model.headerData(99, Qt.Orientation.Horizontal) is None


def test_the_model_takes_only_a_check_state_and_only_a_changed_one() -> None:
    """The check box is the one thing a user edits here, and re-stating it is not an edit (#72).

    **Test steps:**

    * set a role the model does not take, a column it does not take, and the state already held
    * verify each is refused, then that a genuine change is taken
    """
    model = ScreenshotListModel()
    model.set_rows([DIRECTORY / "info00.jpg"], [])
    name = model.index(0, NAME_COLUMN)

    assert not model.setData(name, "renamed", Qt.ItemDataRole.EditRole)
    assert not model.setData(model.index(0, SIZE_COLUMN), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert not model.setData(QModelIndex(), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert not model.setData(name, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert not model.hidden_filenames()

    assert model.setData(name, Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert model.hidden_filenames() == ["info00.jpg"]


def test_the_model_refuses_a_move_that_names_no_second_row() -> None:
    """A row moved onto itself, or off either end, is not a move (#72).

    The selector guards these before it renames anything, so this pins the model's own answer -- it
    is public, and a caller reaching it directly should not get a silent no-op reported as done.

    **Test steps:**

    * ask a rearrangeable two-row model to move a row onto itself, past the end, and from before the
      start, then ask a model with no organizer to make a move that would otherwise be fine
    * verify each is refused, and nothing was renamed
    """
    resource = FakeResource(["info00.jpg", "info01.png"])
    model = ScreenshotListModel()
    model.set_organizer(resource)  # type: ignore[arg-type]
    model.set_rows(resource.files(), [])

    assert not model.move_row(0, 0)
    assert not model.move_row(0, 2)
    assert not model.move_row(-1, 1)

    read_only = ScreenshotListModel()
    read_only.set_rows(resource.files(), [])
    assert not read_only.can_rearrange
    assert not read_only.move_row(0, 1)
    assert not read_only.remove_row(0)

    assert [path.name for path in model.paths()] == resource.names == ["info00.jpg", "info01.png"]


def test_a_relabel_reports_a_data_change_on_the_renamed_row_alone() -> None:
    """A rename is a data change on the rows whose files moved, not on the whole list (#72).

    The roles matter as much as the rows: the curation listener answers to the check-state role, so
    a relabel that claimed to change it would report a curation edit nobody made.

    **Test steps:**

    * relabel one of two rows
    * verify only that row was reported, under the display and path roles
    """
    resource = FakeResource(["info00.jpg", "info01.png", "info02.gif"])
    model = ScreenshotListModel()
    model.set_organizer(resource)  # type: ignore[arg-type]
    model.set_rows(resource.files(), [])
    reported: list[tuple[int, int, list[int]]] = []
    model.dataChanged.connect(
        lambda top_left, bottom_right, roles: reported.append((top_left.row(), bottom_right.row(), list(roles)))
    )

    model.move_row(0, 1)

    assert reported == [(0, 1, [Qt.ItemDataRole.DisplayRole, PATH_ROLE])]
    assert [path.name for path in model.paths()] == resource.names == ["info00.png", "info01.jpg", "info02.gif"]


def test_a_move_relabels_only_the_rows_whose_files_were_renamed(qtbot: QtBot) -> None:
    """The rename reaches the rows as a data change, not as a rebuild (#72).

    **Test steps:**

    * move the last of three screenshots to the top
    * verify every row shows the filename it now has on disk, in the new order
    """
    resource = FakeResource(["info00.jpg", "info01.png", "info02.gif"])
    selector = seeded(qtbot, resource)

    selector.move_screenshot(2, 0)

    assert row_names(selector) == resource.names
    assert row_names(selector) == ["info00.gif", "info01.jpg", "info02.png"]


def test_a_rebuild_is_not_reported_as_a_curation_edit(qtbot: QtBot) -> None:
    """Seeding a row unchecked is being told what is hidden, not a user hiding it (#72).

    The guard that keeps this true moved off ``blockSignals`` when that turned out to be hiding the
    rebuild from the view as well, so it is worth pinning that the quiet half survived the change.

    **Test steps:**

    * rebuild a selector whose set has one screenshot hidden
    * verify no ``hidden_changed`` was emitted
    """
    resource = FakeResource(["info00.jpg", "info01.png"])
    selector = seeded(qtbot, resource, hidden=["info01.png"])
    emitted: list[list[str]] = []
    selector.hidden_changed.connect(emitted.append)

    selector.set_images(resource.files(), ["info00.jpg"])

    assert not emitted


def test_moving_a_screenshot_to_the_bottom_renumbers_everything_it_passed(qtbot: QtBot) -> None:
    """Moving past several slots renumbers each one it stepped over, not only the endpoints (#72).

    **Test steps:**

    * move the first of three screenshots to the last slot
    * verify all three names describe the new order
    """
    resource = FakeResource(["info00.jpg", "info01.png", "info02.gif"])
    selector = seeded(qtbot, resource)

    assert selector.move_screenshot(0, 2) == 2

    assert resource.names == ["info00.png", "info01.gif", "info02.jpg"]


def test_deleting_a_screenshot_closes_the_gap_after_it(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Deleting one unlinks it and pulls every later screenshot down a slot (#72).

    The worked case from the issue: with ``00..03``, removing ``00`` leaves ``00..02``.

    **Test steps:**

    * confirm the prompt and delete the first of four screenshots
    * verify it was removed and the survivors renumbered onto the slots from 00
    """
    mocker.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes)
    resource = FakeResource(["info00.jpg", "info01.jpg", "info02.jpg", "info03.jpg"])
    selector = seeded(qtbot, resource)

    selector.delete_screenshot(0)

    assert resource.removed == ["info00.jpg"]
    assert resource.names == ["info00.jpg", "info01.jpg", "info02.jpg"]
    # the rows too, not only the disk: a delete the model ignored leaves the list offering a
    # screenshot that is gone, and the next delete unlinks a file that no longer exists
    assert row_names(selector) == resource.names


def test_deleting_asks_first_and_declining_changes_nothing(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A delete is confirmed before it happens, and declining leaves the resource alone (#72).

    Unlike every other edit this editor makes, a delete unlinks a file and renumbers its neighbours
    -- neither half is something a document Revert can undo.

    **Test steps:**

    * decline the prompt and ask to delete
    * verify nothing was removed and nothing renamed
    """
    mocker.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No)
    resource = FakeResource(["info00.jpg", "info01.jpg"])
    selector = seeded(qtbot, resource)

    selector.delete_screenshot(0)

    assert not resource.removed
    assert resource.names == ["info00.jpg", "info01.jpg"]


def test_deleting_leaves_the_row_that_took_its_place_current(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The selection stays where the deleted screenshot was, so deleting several does not walk back
    to the top each time (#72).

    **Test steps:**

    * delete the middle of three screenshots
    * verify the row it vacated is the current one
    """
    mocker.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes)
    resource = FakeResource(["info00.jpg", "info01.jpg", "info02.jpg"])
    selector = seeded(qtbot, resource)

    selector.delete_screenshot(1)

    assert selector.current_index == 1


def test_deleting_the_last_screenshot_falls_back_to_the_one_before_it(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Deleting the bottom row leaves the new bottom row current, not an index past the end (#72).

    **Test steps:**

    * delete the last of three screenshots
    * verify the new last row is current
    """
    mocker.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes)
    resource = FakeResource(["info00.jpg", "info01.jpg", "info02.jpg"])
    selector = seeded(qtbot, resource)

    selector.delete_screenshot(2)

    assert selector.current_index == 1


def test_deleting_a_curated_out_screenshot_drops_it_from_the_hidden_set(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A deleted screenshot stops being hidden -- it stops existing (#72).

    Regression: the row was left in the list when the delete reached the model through a call the
    model did not implement, so the document went on naming a file that had been unlinked.

    **Test steps:**

    * hide the first of two screenshots, then delete it
    * verify the hidden set is empty and the rows match the disk
    """
    mocker.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes)
    resource = FakeResource(["info00.jpg", "info01.png"])
    selector = seeded(qtbot, resource, hidden=["info00.jpg"])
    emitted: list[list[str]] = []
    selector.hidden_changed.connect(emitted.append)

    selector.delete_screenshot(0)

    assert not selector.hidden_filenames()
    assert row_names(selector) == resource.names == ["info00.png"]
    assert emitted == [[]]


def test_a_curated_out_screenshot_follows_its_rename(qtbot: QtBot) -> None:
    """The hidden set is filenames, so a rearrangement remaps it or it names files that are gone (#72).

    **Test steps:**

    * hide the second of three screenshots, then move it up
    * verify the hidden name is the one it now has, and the same row is still unchecked
    """
    resource = FakeResource(["info00.jpg", "info01.png", "info02.gif"])
    selector = seeded(qtbot, resource, hidden=["info01.png"])

    selector.move_screenshot(1, 0)

    assert selector.hidden_filenames() == ["info00.png"]
    assert check_state(checkable_model(selector), 0) == Qt.CheckState.Unchecked


def test_a_remapped_hidden_set_is_reported_as_an_edit(qtbot: QtBot) -> None:
    """The remapped hidden names reach the document, or its saved list keeps the old ones (#72).

    **Test steps:**

    * hide one screenshot, then move it
    * verify ``hidden_changed`` carried the new name
    """
    resource = FakeResource(["info00.jpg", "info01.png"])
    selector = seeded(qtbot, resource, hidden=["info01.png"])
    emitted: list[list[str]] = []
    selector.hidden_changed.connect(emitted.append)

    selector.move_screenshot(1, 0)

    assert emitted == [["info00.png"]]


def test_a_rearrangement_that_renames_no_hidden_name_reports_no_edit(qtbot: QtBot) -> None:
    """Moving screenshots that are all visible is not a document edit -- there is nothing to store.

    The order lives in the filenames, not in the ``.rehu``, so reporting one here would mark the
    document dirty with the value it already held.

    **Test steps:**

    * move a screenshot in a set with nothing hidden
    * verify no ``hidden_changed`` fired
    """
    resource = FakeResource(["info00.jpg", "info01.jpg"])
    selector = seeded(qtbot, resource)
    emitted: list[list[str]] = []
    selector.hidden_changed.connect(emitted.append)

    selector.move_screenshot(1, 0)

    assert not emitted


def test_a_refused_rearrangement_keeps_the_row_and_rebuilds_from_disk(qtbot: QtBot) -> None:
    """A rename the disk refuses leaves the current row where it was, showing what is really there (#72).

    The core's rollback is best effort, so the directory -- not the rows that were on screen -- is the
    only trustworthy account of the order afterwards.

    **Test steps:**

    * make the resource refuse every rearrangement, then move a screenshot
    * verify the move reports no movement and the rows still match the resource
    """
    resource = FakeResource(["info00.jpg", "info01.png"])
    selector = seeded(qtbot, resource)
    resource.failure = OSError("refused")

    assert selector.move_screenshot(1, 0) == 1

    assert resource.names == ["info00.jpg", "info01.png"]
    assert row_names(selector) == ["info00.jpg", "info01.png"]


def test_a_move_that_goes_nowhere_never_touches_the_disk(qtbot: QtBot) -> None:
    """Moving a screenshot to the row it is already on, or off either end, writes nothing (#72).

    The move buttons are disabled at the ends, but their keys and a drag are not, so the guard is
    what stops "up" on the first row from renumbering the whole set for no reason.

    **Test steps:**

    * move the first row up and the last row down
    * verify neither reported movement and the resource is untouched
    """
    resource = FakeResource(["info00.jpg", "info01.png"])
    selector = seeded(qtbot, resource)

    assert selector.move_screenshot(0, -1) == 0
    assert selector.move_screenshot(1, 2) == 1

    assert resource.names == ["info00.jpg", "info01.png"]


def test_without_an_organizer_the_list_is_read_only(qtbot: QtBot) -> None:
    """A resource nothing can rearrange (no path yet, a legacy ``.tc``) still curates, but not more (#72).

    **Test steps:**

    * seed a selector with a scanner but no organizer
    * verify a move and a delete both do nothing
    """
    selector = ImageSelector()
    qtbot.addWidget(selector)
    selector.set_images(PATHS, [])

    assert selector.move_screenshot(1, 0) == 1
    selector.delete_screenshot(0)

    assert row_names(selector) == [path.name for path in PATHS]


def test_the_action_columns_are_disabled_without_an_organizer(qtbot: QtBot) -> None:
    """The buttons are greyed rather than hidden, so the editor does not change shape per resource (#72).

    **Test steps:**

    * seed a selector with no organizer, then give it one
    * verify the columns follow
    """
    selector = ImageSelector()
    qtbot.addWidget(selector)
    columns = selector.findChildren(ActionButtonColumn)
    assert len(columns) == 2
    assert not any(column.isEnabled() for column in columns)

    selector.image_organizer = FakeResource([])  # type: ignore[assignment]

    assert all(column.isEnabled() for column in columns)


def test_the_edit_column_offers_only_delete(qtbot: QtBot) -> None:
    """Insert, Edit and Reset mean nothing for a file on disk, so their buttons are hidden (#72).

    **Test steps:**

    * seed a selector
    * verify only the delete button is visible in the edit column
    """
    resource = FakeResource(["info00.jpg"])
    selector = seeded(qtbot, resource)
    selector.show()
    qtbot.waitExposed(selector)

    columns = selector.findChildren(ActionButtonColumn)
    edit_column = columns[-1]
    visible = [button for button in edit_column.findChildren(QToolButton) if button.isVisible()]
    assert [button.defaultAction().text() for button in visible] == ["Delete"]


def test_the_move_buttons_renumber_the_set(qtbot: QtBot) -> None:
    """The four ordering actions rearrange through the same renames, and keep the row they moved (#72).

    Fired as actions, so what is covered is the toolkit wiring a user actually reaches: the columns,
    their enabled rules, and the adapter between them and the screenshots.

    **Test steps:**

    * select the last of three screenshots and walk it up with each move action in turn
    * verify the filenames follow and the moved screenshot stays current
    """
    resource = FakeResource(["info00.jpg", "info01.png", "info02.gif"])
    selector = seeded(qtbot, resource)
    selector.set_current_index(2)

    trigger(selector, "Move Up")
    assert resource.names == ["info00.jpg", "info01.gif", "info02.png"]
    assert selector.current_index == 1

    trigger(selector, "Move to Top")
    assert resource.names == ["info00.gif", "info01.jpg", "info02.png"]
    assert selector.current_index == 0

    trigger(selector, "Move Down")
    assert resource.names == ["info00.jpg", "info01.gif", "info02.png"]
    assert selector.current_index == 1

    trigger(selector, "Move to Bottom")
    assert resource.names == ["info00.jpg", "info01.png", "info02.gif"]
    assert selector.current_index == 2


def test_the_delete_action_removes_the_current_screenshot(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The Delete action acts on the current row, like every other list editor in the app (#72).

    **Test steps:**

    * select the second of three screenshots and fire Delete
    * verify that one went and the set closed up
    """
    mocker.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes)
    resource = FakeResource(["info00.jpg", "info01.png", "info02.gif"])
    selector = seeded(qtbot, resource)
    selector.set_current_index(1)

    trigger(selector, "Delete")

    assert resource.removed == ["info01.png"]
    assert resource.names == ["info00.jpg", "info01.gif"]


def test_the_move_actions_are_disabled_at_the_ends(qtbot: QtBot) -> None:
    """Up and Down gate on where the current row sits, which is the toolkit's own rule (#72).

    **Test steps:**

    * select the first row, then the last
    * verify the actions pointing off each end are disabled
    """
    resource = FakeResource(["info00.jpg", "info01.png"])
    selector = seeded(qtbot, resource)
    view = selector.findChild(QTreeView)
    assert isinstance(view, QTreeView)
    enabled = {action.text(): action.isEnabled() for action in view.actions()}

    selector.set_current_index(0)
    enabled = {action.text(): action.isEnabled() for action in view.actions()}
    assert not enabled["Move Up"]
    assert enabled["Move Down"]

    selector.set_current_index(1)
    enabled = {action.text(): action.isEnabled() for action in view.actions()}
    assert enabled["Move Up"]
    assert not enabled["Move Down"]


def test_the_editor_protocols_no_op_calls_leave_the_set_alone(qtbot: QtBot) -> None:
    """Insert and Reset satisfy the toolkit's protocol without meaning anything for a file (#72).

    Their buttons are hidden and their keys never armed, so this pins that the protocol is answered
    rather than that anyone can reach them.

    **Test steps:**

    * call insert and reset on the adapter directly
    * verify the current row is unchanged and nothing was renamed
    """
    resource = FakeResource(["info00.jpg", "info01.png"])
    selector = seeded(qtbot, resource)
    ordering = selector.findChild(ScreenshotOrdering)
    assert isinstance(ordering, ScreenshotOrdering)

    assert ordering.insert(1) == 1
    ordering.reset()

    assert ordering.count == 2
    assert resource.names == ["info00.jpg", "info01.png"]


def test_a_delete_the_disk_refuses_leaves_the_selection_alone(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A delete that fails does not move the selection onto a row that was never vacated (#72).

    **Test steps:**

    * confirm the prompt on a resource that refuses every rearrangement, and delete the last row
    * verify the set is untouched
    """
    mocker.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes)
    resource = FakeResource(["info00.jpg", "info01.png", "info02.gif"])
    selector = seeded(qtbot, resource)
    selector.set_current_index(2)
    resource.failure = OSError("refused")

    selector.delete_screenshot(2)

    assert not resource.removed
    assert row_names(selector) == ["info00.jpg", "info01.png", "info02.gif"]


# endregion
