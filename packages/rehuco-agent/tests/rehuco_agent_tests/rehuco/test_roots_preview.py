"""Tests for the preview the Roots view shows for a file or an empty folder (#378)."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final
from uuid import uuid4

from PySide6.QtCore import QModelIndex
from PySide6.QtGui import QAction, QImage
from PySide6.QtWidgets import QFrame, QLabel, QLineEdit, QVBoxLayout
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.roots_checksum import BAD_INK, OLD_BAD_INK
from rehuco_agent.rehuco.roots_folder_model import NodeListing, RootsFolderModel
from rehuco_agent.rehuco.roots_preview import (
    EMPTY_FOLDER,
    FILE_TYPE_LABELS,
    FOLDER_LABEL,
    MINIMUM_WIDTH,
    THUMBNAIL_SIDE,
    ActionsForRow,
    RootsPreview,
    format_size,
)
from rehuco_agent.rehuco.scaled_image import ScaledImage
from rehuco_core import FileType, RehucoRoot, Relocation, RenameCoordinator, RootFolderLister, RootStorage

WAIT_TIMEOUT_MS: Final = 10_000

DETAILS_WIDTH: Final = 320
"""How wide the dock starts the pane, in pixels."""


class Shown:
    """A preview over a listed library, with the model it reads."""

    def __init__(self, qtbot: QtBot, library: Path, actions_for: ActionsForRow | None = None) -> None:
        root = RehucoRoot(uuid4(), library, "lib", RootStorage.LOCAL)
        self.model = RootsFolderModel()
        self.model.set_roots([root], RootFolderLister([root]))
        self.preview = RootsPreview(self.model, RenameCoordinator(), actions_for)
        qtbot.addWidget(self.preview)
        self.root = self.model.index(0, 0)
        qtbot.waitUntil(lambda: self.model.listing_state(self.root) is NodeListing.LISTED, timeout=WAIT_TIMEOUT_MS)

    def row(self, name: str) -> QModelIndex:
        """The row named ``name`` under the root.

        :param name: the row's name.
        :returns: its index.
        """
        return next(
            self.model.index(row, 0, self.root)
            for row in range(self.model.rowCount(self.root))
            if self.model.index(row, 0, self.root).data() == name
        )

    def text(self, name: str) -> str:
        """What a label of the preview says.

        :param name: the label's object name.
        :returns: its text.
        """
        if name == "name_label":
            # an eliding label shows what fits; the pane keeps the whole name
            return self.preview.title
        label = self.preview.findChild(QLabel, name)
        assert label is not None
        return label.text()

    def hidden(self, name: str) -> bool:
        """Whether a label of the preview is hidden.

        :param name: the label's object name.
        :returns: whether it is.
        """
        label = self.preview.findChild(QLabel, name)
        assert label is not None
        return label.isHidden()


@fixture(name="shown")
def fixture_shown(qtbot: QtBot, tmp_path: Path) -> Shown:
    """A listed library holding a video, a record, an empty folder and a large and a small picture.

    :param qtbot: pytest-qt fixture.
    :param tmp_path: pytest's temporary directory.
    :returns: the preview and its model.
    """
    library = tmp_path / "lib"
    (library / "empty").mkdir(parents=True)
    (library / "clip.mp4").write_bytes(b"x" * 2048)
    (library / "info.rehu").write_text("{}", encoding="utf-8")
    QImage(900, 600, QImage.Format.Format_RGB32).save(str(library / "big.png"))
    QImage(40, 30, QImage.Format.Format_RGB32).save(str(library / "small.png"))
    return Shown(qtbot, library)


def test_a_file_shows_its_name_type_size_time_and_place(shown: Shown) -> None:
    """Everything is what the listing gave the model, so nothing is read to show it.

    **Test steps:**

    * show the video
    * verify the name, type, size in words, a date, and the path, with every line visible
    """
    shown.preview.show_index(shown.row("clip.mp4"))

    assert shown.text("name_label") == "clip.mp4"
    assert shown.text("type_value") == FILE_TYPE_LABELS[FileType.VIDEO]
    assert shown.text("size_value") == "2.0 kB (2,048 B)"
    assert shown.text("modified_value")
    assert shown.preview.location == str(shown.model.path_of(shown.row("clip.mp4")))
    assert not any(
        shown.hidden(name) for name in ("type_label", "size_label", "modified_label", "path_label", "type_value")
    )


def test_a_rehu_record_is_named_as_one(shown: Shown) -> None:
    """The type line says what the file is to the app, not just its extension.

    **Test steps:**

    * show the record
    * verify its type
    """
    shown.preview.show_index(shown.row("info.rehu"))

    assert shown.text("type_value") == FILE_TYPE_LABELS[FileType.RECORD]


def test_an_empty_folder_says_so_and_has_no_size(qtbot: QtBot, shown: Shown) -> None:
    """A folder says what it is and that it holds nothing, and has no size of its own.

    **Test steps:**

    * list the empty folder and show it
    * verify its type, that it is empty, and that the size line is hidden
    """
    empty = shown.row("empty")
    shown.model.fetchMore(empty)
    qtbot.waitUntil(lambda: shown.model.listing_state(empty) is NodeListing.LISTED, timeout=WAIT_TIMEOUT_MS)

    shown.preview.show_index(empty)

    assert shown.text("type_value") == FOLDER_LABEL
    assert shown.text("contents_value") == EMPTY_FOLDER
    assert shown.hidden("size_label")
    assert shown.hidden("size_value")


def test_a_listed_root_counts_what_it_holds_and_an_unlisted_folder_says_nothing(shown: Shown) -> None:
    """The count comes from the rows the model already has, so a folder nobody opened has none to give. A root has no
    type line: its storage is edited, not described.

    **Test steps:**

    * show the library's root, which is listed, and then a subfolder that is not
    * verify the root counts its items, has no type line and gives its location, and the folder shows no count
    """
    shown.preview.show_index(shown.root)
    assert shown.text("contents_value") == "5 items"
    assert shown.hidden("type_label")
    assert shown.hidden("type_value")
    assert shown.preview.location == str(shown.model.path_of(shown.root))

    shown.preview.show_index(shown.row("empty"))
    assert shown.hidden("contents_label")


def test_a_root_shows_its_editors_and_nothing_else_does(shown: Shown) -> None:
    """The name and storage fields are for a root row: they take its label and storage without telling anyone, and
    go away for any other row, whose bold name header takes their place.

    **Test steps:**

    * show the root, watching the name and storage signals, then a file
    * verify the root's editors are filled and quiet, its name header is hidden, and a file has the reverse
    """
    told: list[object] = []
    shown.preview.root_name_edit.textChanged.connect(told.append)
    shown.preview.root_storage_combo.currentIndexChanged.connect(told.append)

    shown.preview.show_index(shown.root)

    assert not shown.preview.root_name_edit.isHidden()
    assert shown.preview.root_name_edit.text() == "lib"
    assert shown.preview.root_storage_combo.currentData() == RootStorage.LOCAL
    assert shown.hidden("name_label")
    assert not told

    shown.preview.show_index(shown.row("clip.mp4"))
    assert shown.preview.root_name_edit.isHidden()
    assert shown.preview.root_storage_combo.isHidden()
    assert not shown.hidden("name_label")


def test_editing_can_be_switched_off(shown: Shown) -> None:
    """A read-only catalog leaves the root's fields visible and unusable.

    **Test steps:**

    * switch editing off, then on
    * verify both fields follow
    """
    shown.preview.set_editable(False)
    assert not shown.preview.root_name_edit.isEnabled()
    assert not shown.preview.root_storage_combo.isEnabled()

    shown.preview.set_editable(True)
    assert shown.preview.root_name_edit.isEnabled()
    assert shown.preview.root_storage_combo.isEnabled()


def test_each_action_of_a_row_is_a_button_in_order_with_the_default_in_bold(qtbot: QtBot, tmp_path: Path) -> None:
    """The owner gives the pane a row's actions and its default; each becomes a button set to that action, a
    separator becomes a gap, and the default is the bold one. Clicking runs the action.

    **Test steps:**

    * build a pane whose owner offers an action, a separator and a second action, the second the default
    * show a row and read the buttons, then click each
    * verify their actions and order, the bold one, and that each click triggered its action
    """
    library = tmp_path / "lib"
    library.mkdir()
    (library / "a.txt").write_text("a", encoding="utf-8")
    first, second, gap = QAction("First"), QAction("Second"), QAction()
    gap.setSeparator(True)
    triggered: list[str] = []
    first.triggered.connect(lambda: triggered.append("first"))
    second.triggered.connect(lambda: triggered.append("second"))
    shown = Shown(qtbot, library, lambda _index: ([first, gap, second], second))

    shown.preview.show_index(shown.row("a.txt"))

    buttons = shown.preview.buttons
    assert [button.defaultAction() for button in buttons] == [first, second]
    assert [button.font().bold() for button in buttons] == [False, True]
    for button in buttons:
        button.click()
    assert triggered == ["first", "second"]
    lines = [frame for frame in shown.preview.findChildren(QFrame) if frame.frameShape() == QFrame.Shape.HLine]
    assert len([line for line in lines if not line.isHidden()]) == 1


def test_the_buttons_are_made_again_for_each_row_and_none_for_no_row(qtbot: QtBot, tmp_path: Path) -> None:
    """Showing another row replaces the buttons, and showing none leaves none.

    **Test steps:**

    * show a row whose owner offers one action, then no row
    * verify the button, then none
    """
    library = tmp_path / "lib"
    library.mkdir()
    (library / "a.txt").write_text("a", encoding="utf-8")
    action = QAction("Only")
    shown = Shown(qtbot, library, lambda _index: ([action], None))

    shown.preview.show_index(shown.row("a.txt"))
    assert len(shown.preview.buttons) == 1
    shown.preview.show_index(shown.row("a.txt"))
    assert len(shown.preview.buttons) == 1

    shown.preview.show_index(QModelIndex())
    assert not shown.preview.buttons


def test_nothing_shown_is_blank(shown: Shown) -> None:
    """An invalid index clears the preview.

    **Test steps:**

    * show a file, then nothing
    * verify the name is empty and every line hidden
    """
    shown.preview.show_index(shown.row("clip.mp4"))

    shown.preview.show_index(QModelIndex())

    assert shown.text("name_label") == ""
    assert all(shown.hidden(name) for name in ("type_value", "size_value", "modified_value", "path_value"))
    assert shown.preview.image is None
    assert not shown.preview.resolution


def test_a_large_image_shows_a_thumbnail_no_larger_than_the_limit_and_its_own_resolution(
    qtbot: QtBot, shown: Shown
) -> None:
    """The picture is read off the GUI thread, scaled as it is read, and shown once it lands; the resolution line says
    how large the file's picture is, not the thumbnail.

    **Test steps:**

    * show the large picture and wait for the thumbnail
    * verify its longest side is the limit, its proportions are kept and the resolution is the picture's own
    """
    shown.preview.show_index(shown.row("big.png"))

    qtbot.waitUntil(lambda: shown.preview.image is not None, timeout=WAIT_TIMEOUT_MS)
    image = shown.preview.image
    assert image is not None
    assert max(image.width(), image.height()) == THUMBNAIL_SIDE
    assert abs(image.width() / image.height() - 1.5) < 0.02
    assert shown.preview.resolution == "900 \u00d7 600"


def test_a_small_image_is_shown_as_it_is(qtbot: QtBot, shown: Shown) -> None:
    """Only a picture past the limit is scaled down.

    **Test steps:**

    * show the small picture
    * verify its pixels are untouched and the resolution says so
    """
    shown.preview.show_index(shown.row("small.png"))

    qtbot.waitUntil(lambda: shown.preview.image is not None, timeout=WAIT_TIMEOUT_MS)
    image = shown.preview.image
    assert image is not None
    assert (image.width(), image.height()) == (40, 30)
    assert shown.preview.resolution == "40 \u00d7 30"


def test_a_thumbnail_that_lands_after_another_row_was_shown_is_dropped(qtbot: QtBot, shown: Shown) -> None:
    """The answer of a read is for the row that asked, not for whichever is shown by then.

    **Test steps:**

    * show a picture and at once a video, then wait for the read to have ended
    * verify no picture and no resolution are shown
    """
    shown.preview.show_index(shown.row("big.png"))
    shown.preview.show_index(shown.row("clip.mp4"))

    qtbot.wait(300)

    assert shown.preview.image is None
    assert not shown.preview.resolution


def test_an_unreadable_image_shows_no_picture(qtbot: QtBot, tmp_path: Path) -> None:
    """A file that has the name of an image and none of its bytes shows its details and no picture.

    **Test steps:**

    * show a ``.png`` that is not one
    * verify the details are there and there is no picture or resolution
    """
    library = tmp_path / "lib"
    library.mkdir()
    (library / "broken.png").write_bytes(b"not an image")
    shown = Shown(qtbot, library)

    shown.preview.show_index(shown.row("broken.png"))
    qtbot.wait(300)

    assert shown.text("name_label") == "broken.png"
    assert shown.preview.image is None
    assert not shown.preview.resolution


def test_no_row_makes_the_pane_ask_for_more_width_than_it_has(qtbot: QtBot, shown: Shown) -> None:
    """Selecting rows must not make the pane jump: whatever is shown -- a root with its storage combo, a file with a
    long date and a resolution, a large picture -- what its lines need fits the minimum width the pane always has, the
    pane keeps the width it was given, and the picture is drawn to fit it.

    **Test steps:**

    * show the pane at its starting width and show the root, a video and the large picture in turn
    * verify the lines' minimum width is within the pane's own minimum each time, the pane keeps its width, and the
      picture is drawn within it, in proportion
    """
    shown.preview.resize(DETAILS_WIDTH, 500)
    shown.preview.show()
    qtbot.waitExposed(shown.preview)
    layout = shown.preview.layout()
    assert layout is not None
    assert shown.preview.minimumSize().width() == MINIMUM_WIDTH

    for index in (shown.root, shown.row("clip.mp4")):
        shown.preview.show_index(index)
        assert layout.minimumSize().width() <= MINIMUM_WIDTH

    shown.preview.show_index(shown.row("big.png"))
    qtbot.waitUntil(lambda: shown.preview.image is not None, timeout=WAIT_TIMEOUT_MS)
    qtbot.wait(50)

    assert layout.minimumSize().width() <= MINIMUM_WIDTH
    assert shown.preview.width() == DETAILS_WIDTH
    drawn = shown.preview.findChild(ScaledImage, "image_label")
    assert drawn is not None
    assert drawn.drawn_size().width() <= DETAILS_WIDTH
    assert abs(drawn.drawn_size().width() / drawn.drawn_size().height() - 1.5) < 0.05


def test_a_renamed_row_is_shown_again_and_a_change_elsewhere_is_not(shown: Shown) -> None:
    """A rename shows in the preview as the model announces it; a row changing somewhere else leaves it alone.

    **Test steps:**

    * show the video with the preview following the model, and rename the record on disk and in the model
    * verify the preview still names the video
    * rename the video the same way
    * verify the preview names the new name
    """
    shown.model.dataChanged.connect(shown.preview.follow)
    shown.preview.show_index(shown.row("clip.mp4"))
    library = shown.model.path_of(shown.root)
    assert library is not None

    (library / "info.rehu").rename(library / "zzz.rehu")
    shown.model.relocate(Relocation(((library / "info.rehu", library / "zzz.rehu"),)))
    assert shown.text("name_label") == "clip.mp4"

    (library / "clip.mp4").rename(library / "movie.mp4")
    shown.model.relocate(Relocation(((library / "clip.mp4", library / "movie.mp4"),)))
    assert shown.text("name_label") == "movie.mp4"


def test_a_row_that_is_removed_leaves_the_preview_blank(shown: Shown) -> None:
    """The preview never keeps showing a row that is gone.

    **Test steps:**

    * show a file, then drop the model's roots
    * verify the preview is blank
    """
    shown.model.rowsRemoved.connect(shown.preview.forget_if_gone)
    shown.preview.show_index(shown.row("clip.mp4"))

    shown.model.set_roots([], None)

    assert shown.text("name_label") == ""


def test_a_size_is_given_in_words_and_in_exact_bytes() -> None:
    """Two archives that read as the same human size are told apart by their byte counts.

    **Test steps:**

    * format a gigabyte, two sizes that both read as 1.0 GB, a few kilobytes and a handful of bytes
    * verify the words and the separated byte count together, and only the bytes for a small size
    """
    assert format_size(1_073_741_824) == "1.1 GB (1,073,741,824 B)"
    assert format_size(1_000_000_000) == "1.0 GB (1,000,000,000 B)"
    assert format_size(1_000_000_001) == "1.0 GB (1,000,000,001 B)"
    assert format_size(2048) == "2.0 kB (2,048 B)"
    assert format_size(999) == "999 B"
    assert format_size(0) == "0 B"


def test_a_name_being_typed_is_left_alone_while_the_same_root_stays_shown(mocker: MockerFixture, shown: Shown) -> None:
    """A listing that lands while the root's name has focus does not eat what was typed.

    **Test steps:**

    * show the root and type into its name, the field holding focus
    * show the same root again
    * verify the typed text is still there
    """
    shown.preview.show_index(shown.root)
    shown.preview.root_name_edit.setText("typing")
    mocker.patch.object(QLineEdit, "hasFocus", return_value=True)

    shown.preview.show_index(shown.root)

    assert shown.preview.root_name_edit.text() == "typing"


def test_a_layout_item_that_is_not_a_widget_is_skipped_when_the_buttons_are_made_again(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """Making the buttons again clears what is in their layout, a stretch included.

    **Test steps:**

    * add a stretch to the buttons' layout and show a row
    * verify the row's one button is all that is left
    """
    library = tmp_path / "lib"
    library.mkdir()
    (library / "a.txt").write_text("a", encoding="utf-8")
    shown = Shown(qtbot, library, lambda _index: ([QAction("Only")], None))
    layout = shown.preview.findChild(QVBoxLayout, "buttons_layout")
    assert layout is not None
    layout.addStretch()

    shown.preview.show_index(shown.row("a.txt"))

    assert len(shown.preview.buttons) == 1


def test_a_thumbnail_read_that_ends_after_the_preview_was_deleted_is_dropped(
    mocker: MockerFixture, shown: Shown
) -> None:
    """The worker's last step, telling the preview, does not raise once the preview is gone.

    **Test steps:**

    * make telling the preview raise, as a deleted C++ object does, and run the read of a picture
    * verify nothing is raised
    """
    path = shown.model.path_of(shown.row("small.png"))
    assert path is not None
    mocker.patch.object(shown.preview, "image_ready").emit.side_effect = RuntimeError
    read_image = shown.preview._RootsPreview__read_image  # type: ignore[attr-defined]  # pylint: disable=protected-access

    read_image(1, path)


# region The checksum of a covered file (#457)


def stamp(days: float) -> str:
    """When a check was made, ``days`` ago, as a record writes it.

    :param days: how long ago.
    :returns: the stamp.
    """
    return (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


@fixture(name="covered")
def fixture_covered(qtbot: QtBot, tmp_path: Path) -> Shown:
    """A library with ``pack``, a resource whose checksum record covers a fresh match, a fresh mismatch, an old
    mismatch and a file it does not list, beside a video no record covers; ``pack`` is listed.

    :param qtbot: pytest-qt fixture.
    :param tmp_path: pytest's temporary directory.
    :returns: the preview and its model.
    """
    library = tmp_path / "lib"
    pack = library / "pack"
    pack.mkdir(parents=True)
    for name in ("info.rehu", "ok.mp4", "bad.mp4", "old.mp4", "notes.txt", "info00.jpg"):
        (pack / name).write_bytes(b"x")
    (library / "loose.mp4").write_bytes(b"x")
    entries = [
        {"name": "ok.mp4", "crc32": "aabbccdd", "verified": stamp(1), "status": "matched"},
        {"name": "bad.mp4", "crc32": "aabbccdd", "verified": stamp(2), "status": "mismatched"},
        {"name": "old.mp4", "crc32": "aabbccdd", "verified": stamp(400), "status": "mismatched"},
    ]
    (pack / "info.checksum").write_text(json.dumps({"version": 1, "files": entries}), encoding="utf-8")
    shown = Shown(qtbot, library)
    pack_index = shown.row("pack")
    shown.model.fetchMore(pack_index)
    qtbot.waitUntil(lambda: shown.model.listing_state(pack_index) is NodeListing.LISTED, timeout=WAIT_TIMEOUT_MS)
    return shown


def show_in_pack(shown: Shown, name: str) -> None:
    """Show a file of ``pack`` in the pane.

    :param shown: the preview and its model.
    :param name: the file's name.
    """
    pack = shown.row("pack")
    shown.preview.show_index(
        next(
            shown.model.index(row, 0, pack)
            for row in range(shown.model.rowCount(pack))
            if shown.model.index(row, 0, pack).data() == name
        )
    )


def title_icon(shown: Shown) -> QLabel:
    """The label beside the title that holds the state's icon.

    :param shown: the preview.
    :returns: the label.
    """
    label = shown.preview.findChild(QLabel, "title_icon")
    assert label is not None
    return label


def test_a_covered_file_says_its_verdict_and_when_it_was_checked(covered: Shown) -> None:
    """Two fixed lines: the verdict, and the date with how long ago -- and the state's icon beside the title.

    **Test steps:**

    * show a file with a fresh match
    * verify the verdict, a date line ending in how long ago, an icon beside the title, and the rows shown
    """
    show_in_pack(covered, "ok.mp4")

    verdict, checked = covered.preview.checksum_texts or ("", "")
    assert verdict == "Matching"
    assert checked.endswith("(1 day ago)")
    assert not title_icon(covered).pixmap().isNull()
    assert not covered.hidden("checksum_label")
    assert not covered.hidden("checked_label")


def test_a_mismatch_is_drawn_red_and_an_expired_one_orange(covered: Shown) -> None:
    """The title and its icon take the row's warning ink, and the date line says the old finding has expired.

    **Test steps:**

    * show a recent mismatch and then one 400 days old
    * verify the title's ink and the bracketed note of each
    """
    name = covered.preview.findChild(QLabel, "name_label")
    assert name is not None

    show_in_pack(covered, "bad.mp4")
    assert covered.preview.checksum_texts is not None
    assert covered.preview.checksum_texts[0] == "Not matching"
    assert name.palette().windowText().color() == BAD_INK

    show_in_pack(covered, "old.mp4")
    texts = covered.preview.checksum_texts
    assert texts is not None
    _verdict, checked = texts
    assert checked.endswith("(expired)")
    assert name.palette().windowText().color() == OLD_BAD_INK


def test_a_file_with_nothing_to_check_says_why(covered: Shown) -> None:
    """A file its record does not list, one no record covers and a record's own files each give their reason.

    **Test steps:**

    * show an unlisted file of the resource, the record itself, a screenshot, and the loose video
    * verify the two lines of each, and that none has an icon
    """
    expected = {
        "notes.txt": ("No checksum", "Never"),
        "info.rehu": ("No checksum", "Not applicable"),
        "info00.jpg": ("No checksum", "Not applicable"),
    }
    for name, lines in expected.items():
        show_in_pack(covered, name)
        assert covered.preview.checksum_texts == lines, name
        assert (title_icon(covered).pixmap().isNull()) == (name != "notes.txt"), name

    covered.preview.show_index(covered.row("loose.mp4"))
    assert covered.preview.checksum_texts == ("No checksum", "Not covered")
    assert title_icon(covered).pixmap().isNull()


def test_a_folder_has_no_checksum_rows(covered: Shown) -> None:
    """Only a file has a checksum to read: a folder shows neither row and no icon.

    **Test steps:**

    * show a file and then the folder holding it
    * verify the rows go, with their texts, and so does the icon
    """
    show_in_pack(covered, "ok.mp4")
    covered.preview.show_index(covered.row("pack"))

    assert covered.preview.checksum_texts is None
    assert covered.hidden("checksum_label")
    assert covered.hidden("checked_label")
    assert title_icon(covered).pixmap().isNull()


# endregion


def test_the_checksum_rows_keep_one_height_whatever_a_file_says(covered: Shown) -> None:
    """Quick scanning must not have the rows below jump: both lines reserve a line's height, with a date or without.

    **Test steps:**

    * show a checked file, one with no checksum, and a record
    * verify both rows are shown each time and their reserved heights never change
    """
    checksum = covered.preview.findChild(QLabel, "checksum_value")
    checked = covered.preview.findChild(QLabel, "checked_value")
    assert checksum is not None and checked is not None

    heights = set()
    for name in ("ok.mp4", "notes.txt", "info.rehu"):
        show_in_pack(covered, name)
        assert not covered.hidden("checksum_value")
        assert not covered.hidden("checked_value")
        heights.add((checksum.minimumHeight(), checked.minimumHeight()))

    assert len(heights) == 1
    assert all(height > 0 for height in next(iter(heights)))


def test_the_picture_is_the_last_thing_in_the_pane_below_the_buttons(shown: Shown) -> None:
    """A picture's height varies by file; below the buttons, what sits above it stays put whatever is shown.

    **Test steps:**

    * find the pane's picture and its buttons in the pane's layout
    * verify the picture comes after the buttons
    """
    layout = shown.preview.layout()
    assert isinstance(layout, QVBoxLayout)
    picture = shown.preview.findChild(ScaledImage, "image_label")
    buttons = shown.preview.findChild(QVBoxLayout, "buttons_layout")
    assert picture is not None and buttons is not None
    picture_at = layout.indexOf(picture)
    buttons_at = next(
        i for i in range(layout.count()) if (item := layout.itemAt(i)) is not None and item.layout() is buttons
    )

    assert picture_at > buttons_at >= 0
