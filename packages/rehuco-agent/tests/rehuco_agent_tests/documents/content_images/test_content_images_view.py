"""Tests for the Content Images view: the justified grid painted from the packing table (#221)."""

# pylint infers `view.layout_table`'s rows as a PySide signal template rather than the `Row` dataclass
# they are (the view class body mixes `Signal(...)` attributes with the property), so every `.height`,
# `.banner` and `.y` read off a row trips no-member; pyright types them correctly.
# One cohesive suite over the grid's packing, selection, banners, keyboard and status; a scoped
# disable reads better than an arbitrary split (same precedent as test_rehu_document_model.py).
# pylint: disable=no-member,too-many-lines

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QCursor, QFontMetrics, QPainter, QPalette
from PySide6.QtWidgets import QApplication
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.content_images import (
    ContentDisplayFlags,
    ContentImagesModel,
    ContentImagesPanel,
    ContentImagesView,
)
from rehuco_agent.documents.content_images.content_images_view import (
    BANNER_HEIGHT,
    BANNER_INSET,
    BANNER_MARK_WIDTH,
    ITEM_SPACING,
    banner_parts,
)
from rehuco_agent.fields.widgets import ThumbnailLoader
from rehuco_core import ContentImageEntry

from rehuco_agent_tests.documents.content_images.conftest import (
    OTHER_PACK,
    PACK,
    REHU_DIRECTORY,
    TALL,
    WIDE,
    entry,
)


def settle(qtbot: QtBot, view: ContentImagesView, content_model: ContentImagesModel) -> None:
    """Wait for every visible header to land and the pack that follows to run.

    :param qtbot: pytest-qt fixture.
    :param view: the view under test.
    :param content_model: its model.
    """
    qtbot.waitUntil(lambda: view.layout_table is not None)
    view.grab()  # a paint asks for the headers in view
    qtbot.waitUntil(
        lambda: all(content_model.dimensions(index) is not None for index in range(content_model.rowCount()))
    )
    qtbot.waitUntil(lambda: view.layout_table is not None and len(view.layout_table.rects) == content_model.rowCount())
    qtbot.wait(20)  # the coalesced repack after the last header


def test_an_empty_model_paints_nothing_and_raises_nothing(view: ContentImagesView) -> None:
    """A resource with no archive, an unreadable one, or one with no images: the view is empty and
    a paint is a no-op.

    **Test steps:**

    * paint the view over an empty model
    * verify the table is empty and nothing was raised
    """
    view.grab()

    assert view.layout_table is not None
    assert view.layout_table.rows == ()
    assert view.layout_table.height == 0


def test_rows_are_packed_from_the_headers_once_they_land(
    view: ContentImagesView, content_model: ContentImagesModel, qtbot: QtBot
) -> None:
    """The grid lays the entries out at the placeholder first, then re-packs as each header arrives.

    **Test steps:**

    * set three wide entries and let the headers land
    * verify one flush row of three at the 2:1 flush height
    """
    content_model.set_entries([entry(PACK, f"{index}.png", WIDE) for index in range(3)], REHU_DIRECTORY)
    settle(qtbot, view, content_model)

    table = view.layout_table
    assert table is not None
    width = view.viewport().width()
    assert [row.height for row in table.rows] == [round((width - 2 * ITEM_SPACING) / 6)]
    assert table.rects[2][0] + table.rects[2][2] == width


def test_banners_follow_the_flags_and_force_breaks(
    view: ContentImagesView, content_model: ContentImagesModel, qtbot: QtBot
) -> None:
    """With zip names on, each archive opens with a banner row that breaks the flow; with both boxes
    off there is one continuous row.

    **Test steps:**

    * set one member in each of two archives with no banners and let the pack settle
    * verify one row holds both
    * turn zip names on and verify a banner row before each member
    """
    content_model.set_entries([entry(PACK, "a.png"), entry(OTHER_PACK, "b.png")], REHU_DIRECTORY)
    settle(qtbot, view, content_model)
    table = view.layout_table
    assert table is not None
    assert [(row.banner, row.first, row.last) for row in table.rows] == [(None, 0, 1)]

    view.set_flags(ContentDisplayFlags(zip_names=True, folder_names=False))
    qtbot.waitUntil(lambda: view.layout_table is not None and len(view.layout_table.rows) == 4)

    assert view.flags == ContentDisplayFlags(True, False)
    table = view.layout_table
    assert table is not None
    assert [row.banner for row in table.rows] == ["pack.zip", None, "sub/other.zip", None]
    assert table.rows[0].height == BANNER_HEIGHT
    assert view.banner_label("pack.zip") == "- pack.zip [1]"


def test_a_new_clamp_re_packs_the_open_view(
    view: ContentImagesView, content_model: ContentImagesModel, qtbot: QtBot
) -> None:
    """Applying a new row-height clamp lays the rows out again under it.

    **Test steps:**

    * pack three wide entries, which flush at 167 px inside ``[100, 200]``
    * raise the minimum above that and verify the row went ragged at the new maximum
    """
    content_model.set_entries([entry(PACK, f"{index}.png", WIDE) for index in range(3)], REHU_DIRECTORY)
    settle(qtbot, view, content_model)

    view.set_clamp(180, 190)
    qtbot.waitUntil(lambda: view.layout_table is not None and view.layout_table.rows[0].height == 190)

    assert view.clamp == (180, 190)
    table = view.layout_table
    assert table is not None
    assert table.rects[1][0] + table.rects[1][2] < view.viewport().width()


def test_a_double_click_on_an_image_reports_its_position(
    view: ContentImagesView, content_model: ContentImagesModel, qtbot: QtBot
) -> None:
    """A left double-click over an image fires ``image_activated`` with its position and selects it;
    one on a banner, a gap below the rows, or with the right button fires nothing.

    **Test steps:**

    * pack two members behind a banner and let the pack settle
    * double-click the second image's centre, the banner and the empty space below; right-double-click
      the image
    * verify one activation, for position one, which is now the selection
    """
    view.set_flags(ContentDisplayFlags(zip_names=True, folder_names=False))
    content_model.set_entries([entry(PACK, "a.png"), entry(PACK, "b.png")], REHU_DIRECTORY)
    settle(qtbot, view, content_model)
    table = view.layout_table
    assert table is not None
    assert table.rows[0].banner is not None
    x, y, w, h = table.rects[1]
    centre = QPoint(x + w // 2, y + h // 2)
    activated: list[int] = []
    view.image_activated.connect(activated.append)

    qtbot.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=centre)
    qtbot.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(5, table.rows[0].y + 2))
    qtbot.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(5, table.height + 20))
    qtbot.mouseDClick(view.viewport(), Qt.MouseButton.RightButton, pos=centre)

    assert activated == [1]
    assert view.selected == 1


def test_a_single_click_selects_and_a_second_deselects(
    view: ContentImagesView, content_model: ContentImagesModel, qtbot: QtBot
) -> None:
    """A click selects the image under it, a click elsewhere moves the selection, a click on the
    selected one clears it; each change is announced, and none opens anything.

    **Test steps:**

    * pack two members; click the first, then the second, then the second again
    * verify the selection went 0, 1, none, announced each time, and nothing was activated
    """
    content_model.set_entries([entry(PACK, "a.png"), entry(PACK, "b.png")], REHU_DIRECTORY)
    settle(qtbot, view, content_model)
    table = view.layout_table
    assert table is not None
    centres = [QPoint(x + w // 2, y + h // 2) for x, y, w, h in table.rects]
    selections: list[object] = []
    activated: list[int] = []
    view.selection_changed.connect(selections.append)
    view.image_activated.connect(activated.append)

    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=centres[0])
    assert view.selected == 0
    # the selected cell carries the highlight ring, painted over its edge
    x, y, _, _ = table.rects[0]
    assert (
        view.grab().toImage().pixelColor(x + 1, y + 1).name()
        == view.palette().color(QPalette.ColorRole.Highlight).name()
    )
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=centres[1])
    assert view.selected == 1
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=centres[1])

    assert view.selected is None
    assert selections == [0, 1, None]
    assert not activated


def test_a_real_double_click_opens_without_disturbing_the_selection(
    view: ContentImagesView, content_model: ContentImagesModel, qtbot: QtBot
) -> None:
    """A double-click on the desktop is press, release, press, double-click, release: the first
    release toggles the selection, the double-click opens and selects the image, and the trailing
    release must not toggle again -- so a double-clicked image ends up selected whether it was
    already, another was, or none. A click elsewhere, a right click, and a click on empty space
    leave the selection alone too.

    **Test steps:**

    * pack two members and send the real double-click sequence over the first, with nothing
      selected; verify it was activated once and is selected
    * select the second, double-click the first, and verify the first is now the selection
    * double-click the first while it is selected and verify it stays selected
    * right-click it, click empty space, and verify the selection stands; click it and verify it clears
    """
    content_model.set_entries([entry(PACK, "a.png"), entry(PACK, "b.png")], REHU_DIRECTORY)
    settle(qtbot, view, content_model)
    table = view.layout_table
    assert table is not None
    x, y, w, h = table.rects[0]
    centre = QPoint(x + w // 2, y + h // 2)
    activated: list[int] = []
    view.image_activated.connect(activated.append)

    def double_click_first() -> None:
        qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=centre)
        qtbot.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=centre)
        qtbot.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=centre)

    double_click_first()
    assert activated == [0]
    assert view.selected == 0

    view.set_selected(1)
    double_click_first()
    assert activated == [0, 0]
    assert view.selected == 0

    double_click_first()
    assert activated == [0, 0, 0]
    assert view.selected == 0

    qtbot.mouseClick(view.viewport(), Qt.MouseButton.RightButton, pos=centre)
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(5, table.height + 20))
    assert view.selected == 0
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=centre)
    assert view.selected is None


def test_a_scroll_re_reads_what_is_under_the_resting_pointer(
    view: ContentImagesView, content_model: ContentImagesModel, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """Scrolling moves the rows under a pointer that has not moved: the status line follows the image
    now under it rather than waiting for the next mouse move.

    **Test steps:**

    * pack enough rows to scroll, rest the pointer on the first image and verify its path shows
    * scroll to the end and verify the status names whatever is now under the pointer instead
    """
    content_model.set_entries([entry(PACK, f"{index}.png", WIDE) for index in range(30)], REHU_DIRECTORY)
    qtbot.waitUntil(lambda: view.layout_table is not None and len(view.layout_table.rows) > 1)
    table = view.layout_table
    assert table is not None
    x, y, w, h = table.rects[0]
    resting = QPoint(x + w // 2, y + h // 2)
    qtbot.mouseMove(view.viewport(), QPoint(5, table.height + 20))
    qtbot.mouseMove(view.viewport(), resting)
    qtbot.waitUntil(lambda: view.status_text() == "pack.zip:/0.png")
    # the pointer stays exactly where it is, as read back through the cursor the scroll consults
    mocker.patch.object(QCursor, "pos", return_value=view.viewport().mapToGlobal(resting))
    mocker.patch.object(view.viewport(), "underMouse", return_value=True)

    view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())

    under = view.index_at(resting)
    assert under is not None
    assert under != 0
    assert view.status_text() == f"pack.zip:/{under}.png"

    # with the pointer elsewhere, a scroll re-reads nothing
    mocker.patch.object(view.viewport(), "underMouse", return_value=False)
    view.verticalScrollBar().setValue(0)
    assert view.status_text() == f"pack.zip:/{under}.png"


def test_hovering_a_banner_names_nothing(
    view: ContentImagesView, content_model: ContentImagesModel, qtbot: QtBot
) -> None:
    """A banner row is not an image row: the pointer resting on one reports nothing hovered, the same
    way a gap below the rows does.

    **Test steps:**

    * pack one bannered member and rest the pointer on its banner
    * verify the status line stays empty
    """
    view.set_flags(ContentDisplayFlags(zip_names=True, folder_names=False))
    content_model.set_entries([entry(PACK, "a.png")], REHU_DIRECTORY)
    settle(qtbot, view, content_model)
    table = view.layout_table
    assert table is not None
    assert table.rows[0].banner is not None

    qtbot.mouseMove(view.viewport(), QPoint(5, table.rows[0].y + 2))

    assert view.status_text() == ""


def test_the_pointer_leaving_clears_the_hover(
    view: ContentImagesView, content_model: ContentImagesModel, qtbot: QtBot
) -> None:
    """Once the pointer leaves the grid nothing is hovered, so the status line empties.

    **Test steps:**

    * hover an image, then send the grid a leave event
    * verify the status went from the path to nothing
    """
    content_model.set_entries([entry(PACK, "a.png")], REHU_DIRECTORY)
    settle(qtbot, view, content_model)
    table = view.layout_table
    assert table is not None
    x, y, w, h = table.rects[0]
    qtbot.mouseMove(view.viewport(), QPoint(x + w // 2, y + h // 2))
    qtbot.waitUntil(lambda: view.status_text() == "pack.zip:/a.png")

    QApplication.sendEvent(view, QEvent(QEvent.Type.Leave))

    assert view.status_text() == ""


def test_collapsing_what_already_is_and_asking_before_a_pack_change_nothing(
    content_model: ContentImagesModel, loader: ThumbnailLoader, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """Re-applying a group's current state schedules no pack, and a banner hit test before the first
    pack misses.

    **Test steps:**

    * build a never-shown view; expand a group that is not collapsed, and hit-test a banner
    * verify nothing was scheduled and nothing was hit
    """
    built = ContentImagesView(content_model, loader)
    qtbot.addWidget(built)
    scheduled = mocker.spy(built, "schedule_repack")

    built.set_collapsed("nothing", False)

    scheduled.assert_not_called()
    assert built.pinned_banner() is None
    assert built.banner_at(QPoint(1, 1)) is None


def test_the_status_names_the_selected_image_else_the_hovered_one(
    view: ContentImagesView, content_model: ContentImagesModel, qtbot: QtBot
) -> None:
    """The status line carries the hovered image's path while nothing is selected, the selected one's
    path once there is a selection whatever is hovered, and nothing with neither.

    **Test steps:**

    * pack two members; hover the first and verify its path is reported
    * select the second, hover the first again, and verify the selected one's path stands
    * clear the selection with the pointer gone and verify the line is empty
    """
    content_model.set_entries([entry(PACK, "a.png"), entry(PACK, "b.png")], REHU_DIRECTORY)
    settle(qtbot, view, content_model)
    table = view.layout_table
    assert table is not None
    centres = [QPoint(x + w // 2, y + h // 2) for x, y, w, h in table.rects]
    reported: list[str] = []
    view.status_changed.connect(reported.append)

    # off the images first: a pointer already resting on the first image from an earlier test
    # would make the move to it a no-op
    qtbot.mouseMove(view.viewport(), QPoint(5, table.height + 20))
    qtbot.mouseMove(view.viewport(), centres[0])
    qtbot.waitUntil(lambda: reported[-1:] == ["pack.zip:/a.png"])

    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=centres[1])
    assert view.status_text() == "pack.zip:/b.png"
    qtbot.mouseMove(view.viewport(), QPoint(5, table.height + 20))
    qtbot.mouseMove(view.viewport(), centres[0])
    qtbot.wait(20)
    assert view.status_text() == "pack.zip:/b.png"
    assert reported[-1] == "pack.zip:/b.png"

    view.set_selected(None)
    qtbot.mouseMove(view.viewport(), QPoint(5, table.height + 20))
    qtbot.waitUntil(lambda: view.status_text() == "")


def test_a_banner_click_collapses_its_group_and_a_second_expands_it(
    view: ContentImagesView, content_model: ContentImagesModel, qtbot: QtBot
) -> None:
    """Clicking a banner folds the images under it away -- the banner row stays, marked ``+`` -- and
    clicking it again brings them back; an image selected inside a folding group is deselected.

    **Test steps:**

    * pack one member in each of two archives with zip names on, select the first
    * click the first banner and verify only its images went, its label reads ``+``, and the
      selection cleared
    * click it again and verify the rows are back
    """
    view.set_flags(ContentDisplayFlags(zip_names=True, folder_names=False))
    content_model.set_entries([entry(PACK, "a.png"), entry(OTHER_PACK, "b.png")], REHU_DIRECTORY)
    settle(qtbot, view, content_model)
    view.set_selected(0)
    table = view.layout_table
    assert table is not None
    first_banner = QPoint(5, table.rows[0].y + 2)

    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=first_banner)
    qtbot.waitUntil(lambda: view.layout_table is not None and len(view.layout_table.rows) == 3)

    table = view.layout_table
    assert table is not None
    assert [row.banner for row in table.rows] == ["pack.zip", "sub/other.zip", None]
    assert view.collapsed == {"pack.zip"}
    assert view.banner_label("pack.zip") == "+ pack.zip [1]"
    assert view.selected is None
    assert table.rects[0] == (0, 0, 0, 0)

    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=first_banner)
    qtbot.waitUntil(lambda: view.layout_table is not None and len(view.layout_table.rows) == 4)

    assert view.collapsed == frozenset()
    assert view.banner_label("pack.zip") == "- pack.zip [1]"


def test_the_banner_label_stands_still_when_its_mark_changes(
    view: ContentImagesView, content_model: ContentImagesModel, qtbot: QtBot
) -> None:
    """The mark sits in a column of its own, so ``-`` becoming ``+`` (a narrower glyph becoming a wider
    one) moves the label not one pixel: the two parts are painted in fixed columns.

    **Test steps:**

    * pack one bannered member and grab its banner row, then collapse the group and grab again
    * verify the label column is pixel-identical (the mark column itself is not compared: the
      offscreen platform draws every glyph as the same box)
    """
    view.set_flags(ContentDisplayFlags(zip_names=True, folder_names=False))
    content_model.set_entries([entry(PACK, "a.png")], REHU_DIRECTORY)
    settle(qtbot, view, content_model)
    label_left = BANNER_INSET + BANNER_MARK_WIDTH
    label_column = QRect(label_left, 0, view.viewport().width() - label_left, BANNER_HEIGHT)
    expanded = view.viewport().grab().toImage()

    view.set_collapsed("pack.zip", True)
    qtbot.waitUntil(lambda: view.layout_table is not None and len(view.layout_table.rows) == 1)
    collapsed = view.viewport().grab().toImage()

    assert expanded.copy(label_column) == collapsed.copy(label_column)
    assert banner_parts("pack.zip", 1, collapsed=True) == ("+", "pack.zip [1]")
    assert banner_parts("pack.zip", 1, collapsed=False) == ("-", "pack.zip [1]")


def test_a_banner_too_long_for_the_width_is_elided_not_cut(
    view: ContentImagesView, content_model: ContentImagesModel, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """A label longer than the row is elided in the middle, so it stops a margin short of the edge
    rather than being clipped at it.

    **Asserted on the string handed to the painter, measured in this run's own font**, not on ink:
    the offscreen platform starts with no fonts, and once ``borco-pyside``'s theming tests load an
    icon font into that empty database it becomes the fallback for plain text for the rest of the
    process, at which point letters paint nothing at all -- the `test_task_row_delegate.py` elision
    test names the same trap. Which happens in one test order and not another (serial ``make cov``
    on Windows, never a parallel worker that skipped those tests), so ink is not a premise here.

    **Test steps:**

    * pack one member under a very deep folder with both boxes on, in a narrow view
    * capture what the banner paint hands ``drawText`` and verify the label was shortened in the
      middle, keeps its count, and measures no wider than the row less its right inset
    * grab the row and verify the inset at its right edge carries no ink
    """
    view.set_flags(ContentDisplayFlags(zip_names=True, folder_names=True))
    view.resize(200, 400)
    content_model.set_entries([entry(PACK, "/".join(["folder"] * 40) + "/a.png")], REHU_DIRECTORY)
    settle(qtbot, view, content_model)
    painted = view.viewport().grab().toImage()
    window = view.palette().color(QPalette.ColorRole.Window).name()
    width = view.viewport().width()
    assert view.layout_table is not None
    _mark, full_text = banner_parts(view.layout_table.rows[0].banner or "", 1, collapsed=False)

    drawn = mocker.patch.object(QPainter, "drawText")
    view.viewport().grab()
    ((rect, _flags, elided),) = [call.args for call in drawn.call_args_list if "…" in call.args[-1]]
    assert elided != full_text
    assert elided.endswith(full_text[-4:])
    bold = view.font()
    bold.setBold(True)
    assert QFontMetrics(bold).horizontalAdvance(elided) <= rect.width() == width - rect.left() - BANNER_INSET
    margin = {painted.pixelColor(x, y).name() for x in range(width - BANNER_INSET, width) for y in range(BANNER_HEIGHT)}
    assert margin == {window}


def test_a_double_click_on_a_banner_toggles_its_group_once(
    view: ContentImagesView, content_model: ContentImagesModel, qtbot: QtBot
) -> None:
    """A double-click on a banner -- press, release, press, double-click, release -- collapses the
    group once: the trailing release must not expand it again, and the double-click opens nothing.

    **Test steps:**

    * pack one bannered member and send the real double-click sequence over its banner
    * verify the group is collapsed and nothing was activated
    """
    view.set_flags(ContentDisplayFlags(zip_names=True, folder_names=False))
    content_model.set_entries([entry(PACK, "a.png")], REHU_DIRECTORY)
    settle(qtbot, view, content_model)
    activated: list[int] = []
    view.image_activated.connect(activated.append)
    banner = QPoint(5, 2)

    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=banner)
    qtbot.waitUntil(lambda: view.collapsed == {"pack.zip"})
    qtbot.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=banner)
    qtbot.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=banner)
    qtbot.wait(20)

    assert view.collapsed == {"pack.zip"}
    assert not activated


def test_the_current_groups_banner_is_pinned_while_its_own_row_is_scrolled_off(
    view: ContentImagesView, content_model: ContentImagesModel, qtbot: QtBot
) -> None:
    """Scrolled into the middle of a long group, its banner stays pinned at the top -- painted over the
    rows -- and a click on it collapses the group from there; with the banner's own row in view, or
    nothing scrolled, nothing is pinned.

    **Test steps:**

    * pack a long bannered group and verify nothing is pinned at the top
    * scroll to its middle and verify the group is pinned and painted at the top
    * click the pinned banner and verify the group collapsed
    """
    view.set_flags(ContentDisplayFlags(zip_names=True, folder_names=False))
    content_model.set_entries([entry(PACK, f"{index}.png", WIDE) for index in range(30)], REHU_DIRECTORY)
    qtbot.waitUntil(lambda: view.layout_table is not None and len(view.layout_table.rows) > 3)
    assert view.pinned_banner() is None
    assert view.banner_at(QPoint(5, 5)) == "pack.zip"

    scrollbar = view.verticalScrollBar()
    scrollbar.setValue(scrollbar.maximum() // 2)
    assert view.pinned_banner() == "pack.zip"
    painted = view.grab().toImage()
    assert (
        painted.pixelColor(view.viewport().width() - 5, 2).name()
        == view.palette().color(QPalette.ColorRole.Window).name()
    )
    assert view.banner_at(QPoint(5, 5)) == "pack.zip"
    assert view.index_at(QPoint(5, 5)) is None  # the pinned banner covers the row under it

    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
    qtbot.waitUntil(lambda: view.collapsed == {"pack.zip"})


def test_collapsing_a_group_from_inside_it_scrolls_back_to_its_banner(
    view: ContentImagesView, content_model: ContentImagesModel, qtbot: QtBot
) -> None:
    """A group collapsed through its pinned banner lands with that banner at the top, so what follows
    is the next group from its own banner on -- not the scroll offset kept over a shorter layout,
    which would show the middle of the next group; a banner already on screen when clicked leaves
    the scroll alone.

    **Test steps:**

    * pack two long bannered groups and scroll into the middle of the first
    * collapse it through its pinned banner and verify the scroll landed on its banner row, with the
      second group's banner right under it
    * expand it again and verify the scroll stayed
    * scroll into the middle of the second group, collapse it and verify the scroll landed as close
      to its banner row as the shortened layout allows, the row in view
    """
    view.set_flags(ContentDisplayFlags(zip_names=True, folder_names=False))
    content_model.set_entries(
        [entry(PACK, f"{index}.png", WIDE) for index in range(30)]
        + [entry(OTHER_PACK, f"{index}.png", WIDE) for index in range(30)],
        REHU_DIRECTORY,
    )
    qtbot.waitUntil(lambda: view.layout_table is not None and len(view.layout_table.rows) > 6)
    table = view.layout_table
    assert table is not None
    second_banner = next(row for row in table.rows if row.banner == "sub/other.zip")
    scrollbar = view.verticalScrollBar()
    scrollbar.setValue(second_banner.y // 2)
    assert view.pinned_banner() == "pack.zip"

    view.set_collapsed("pack.zip", True)
    qtbot.waitUntil(lambda: view.collapsed == {"pack.zip"} and scrollbar.value() == 0)

    assert view.pinned_banner() is None
    assert view.banner_at(QPoint(5, 2)) == "pack.zip"
    table = view.layout_table
    assert table is not None
    assert [row.banner for row in table.rows[:2]] == ["pack.zip", "sub/other.zip"]
    assert view.banner_at(QPoint(5, table.rows[1].y + 2)) == "sub/other.zip"

    view.set_collapsed("pack.zip", False)
    qtbot.waitUntil(lambda: view.layout_table is not None and len(view.layout_table.rows) > 6)
    assert scrollbar.value() == 0

    scrollbar.setValue(second_banner.y + BANNER_HEIGHT * 3)
    assert view.pinned_banner() == "sub/other.zip"
    view.set_collapsed("sub/other.zip", True)
    qtbot.waitUntil(lambda: view.layout_table is not None and view.layout_table.rows[-1].banner == "sub/other.zip")
    # the scrollbar's appearance or disappearance reflows the rows once more; let that settle
    qtbot.wait(50)
    table = view.layout_table
    assert table is not None
    collapsed_banner = next(row for row in table.rows if row.banner == "sub/other.zip")
    assert scrollbar.maximum() < collapsed_banner.y  # the collapsed tail no longer fills a viewport
    assert scrollbar.value() <= collapsed_banner.y
    assert view.banner_at(QPoint(5, collapsed_banner.y - scrollbar.value() + 2)) == "sub/other.zip"


def test_reveal_selects_scrolls_to_and_uncollapses_an_image(
    view: ContentImagesView, content_model: ContentImagesModel, qtbot: QtBot
) -> None:
    """``reveal`` selects the image, brings its cell into the viewport with the least scroll -- none
    when it is already in view -- and expands its group when that is collapsed; an index outside the
    source is ignored, and one asked for before any pack still selects (#221).

    **Test steps:**

    * pack two long bannered groups, collapse the second, and reveal an image deep inside it
    * verify it is selected, its group expanded, and its cell inside the viewport
    * reveal an image near the top and verify the view scrolled back up to it; reveal it again and
      verify the scroll did not move
    * reveal a stray index and verify nothing changed
    """
    view.set_flags(ContentDisplayFlags(zip_names=True, folder_names=False))
    content_model.set_entries(
        [entry(PACK, f"{index}.png", WIDE) for index in range(30)]
        + [entry(OTHER_PACK, f"{index}.png", WIDE) for index in range(30)],
        REHU_DIRECTORY,
    )
    qtbot.waitUntil(lambda: view.layout_table is not None and len(view.layout_table.rows) > 6)
    view.set_collapsed("sub/other.zip", True)
    qtbot.waitUntil(lambda: view.layout_table is not None and view.layout_table.rects[59] == (0, 0, 0, 0))
    scrollbar = view.verticalScrollBar()

    view.reveal(59)
    qtbot.waitUntil(lambda: view.layout_table is not None and view.layout_table.rects[59] != (0, 0, 0, 0))

    # headers still landing re-pack the rows under the selection; it is kept in view through those.
    # Only the headers on screen (and one screen ahead) are ever asked for, so wait for those alone
    def on_screen_headers_landed() -> bool:
        table = view.layout_table
        if table is None:
            return False
        view.grab()
        offset = view.verticalScrollBar().value()
        rows = table.rows_between(offset, offset + view.viewport().height())
        return all(
            content_model.dimensions(index) is not None
            for row in rows
            if row.banner is None
            for index in range(row.first, row.last + 1)
        )

    qtbot.waitUntil(on_screen_headers_landed)
    qtbot.wait(50)
    table = view.layout_table
    assert table is not None
    assert view.selected == 59
    assert view.collapsed == frozenset()
    _, top, _, height = table.rects[59]
    assert scrollbar.value() <= top
    assert top + height <= scrollbar.value() + view.viewport().height()

    view.reveal(1)
    qtbot.waitUntil(lambda: scrollbar.value() <= view.layout_table.rects[1][1] if view.layout_table else False)
    assert view.selected == 1
    settled = scrollbar.value()
    view.reveal(1)
    qtbot.wait(50)
    assert scrollbar.value() == settled

    view.reveal(60)
    assert view.selected == 1


def test_a_resize_keeps_the_selected_image_on_screen(
    view: ContentImagesView, content_model: ContentImagesModel, qtbot: QtBot
) -> None:
    """Narrowing the view re-flows every row, so the scroll offset alone would land on other images:
    a selected image that was on screen is kept there; one the user had scrolled away from is left
    where it was (#221).

    **Test steps:**

    * pack a long set, reveal an image deep in it, then halve the width
    * verify the selected cell still intersects the viewport
    * scroll to the top and widen the view again; verify the scroll stayed at the top
    """
    content_model.set_entries([entry(PACK, f"{index}.png", WIDE) for index in range(60)], REHU_DIRECTORY)
    qtbot.waitUntil(lambda: view.layout_table is not None and len(view.layout_table.rows) > 10)
    view.reveal(45)
    qtbot.waitUntil(lambda: view.verticalScrollBar().value() > 0)
    qtbot.wait(50)

    view.resize(500, 400)
    qtbot.wait(50)

    table = view.layout_table
    assert table is not None
    _, top, _, height = table.rects[45]
    scrollbar = view.verticalScrollBar()
    assert top < scrollbar.value() + view.viewport().height()
    assert top + height > scrollbar.value()

    scrollbar.setValue(0)
    view.resize(1000, 400)
    qtbot.wait(50)
    assert scrollbar.value() == 0


def test_the_keyboard_moves_the_selection_folds_the_group_and_clears(
    view: ContentImagesView, content_model: ContentImagesModel, qtbot: QtBot
) -> None:
    """LEFT/RIGHT step the selection along the shown sequence (the first image with none selected,
    stopping at the ends), UP/DOWN move to the nearest image in the neighbouring row, ``-`` and ``+``
    collapse and expand the current group -- the selection's, else the first on screen -- and ESC
    clears the selection; an unrelated key passes on (#221).

    **Test steps:**

    * pack two bannered groups of wide images and press RIGHT with nothing selected; verify the first
    * step RIGHT twice and LEFT once; verify; press LEFT past the start and verify it stays
    * press DOWN and verify the nearest image in the row below; UP brings it back
    * press ``-``: the group collapses and the selection clears; ``+``: it expands again
    * select and press ESC; verify nothing is selected; press a letter and verify nothing changed
    * press DOWN with nothing selected and verify the first image; press UP at the top and verify it stays
    """
    view.set_flags(ContentDisplayFlags(zip_names=True, folder_names=False))
    content_model.set_entries(
        [entry(PACK, f"{index}.png", WIDE) for index in range(6)] + [entry(OTHER_PACK, "z.png", WIDE)],
        REHU_DIRECTORY,
    )
    settle(qtbot, view, content_model)
    table = view.layout_table
    assert table is not None
    first_row = next(row for row in table.rows if row.banner is None)
    per_row = first_row.last - first_row.first + 1
    assert per_row > 1

    qtbot.keyClick(view, Qt.Key.Key_Right)
    assert view.selected == 0
    qtbot.keyClick(view, Qt.Key.Key_Right)
    qtbot.keyClick(view, Qt.Key.Key_Right)
    qtbot.keyClick(view, Qt.Key.Key_Left)
    assert view.selected == 1
    qtbot.keyClick(view, Qt.Key.Key_Left)
    qtbot.keyClick(view, Qt.Key.Key_Left)
    assert view.selected == 0

    qtbot.keyClick(view, Qt.Key.Key_Down)
    assert view.selected == per_row
    qtbot.keyClick(view, Qt.Key.Key_Up)
    assert view.selected == 0

    qtbot.keyClick(view, Qt.Key.Key_Minus)
    qtbot.waitUntil(lambda: view.collapsed == {"pack.zip"})
    assert view.selected is None
    assert view.current_group() == "pack.zip"
    qtbot.keyClick(view, Qt.Key.Key_Plus)
    qtbot.waitUntil(lambda: view.collapsed == frozenset())

    view.set_selected(2)
    qtbot.keyClick(view, Qt.Key.Key_Escape)
    assert view.selected is None
    qtbot.keyClick(view, Qt.Key.Key_A)
    assert view.selected is None

    qtbot.keyClick(view, Qt.Key.Key_Down)
    assert view.selected == 0
    qtbot.keyClick(view, Qt.Key.Key_Up)
    assert view.selected == 0
    view.set_selected(6)
    qtbot.keyClick(view, Qt.Key.Key_Down)
    qtbot.keyClick(view, Qt.Key.Key_Right)
    assert view.selected == 6


def test_the_keyboard_does_nothing_over_an_empty_or_unbannered_grid(
    view: ContentImagesView, content_model: ContentImagesModel, qtbot: QtBot
) -> None:
    """Over nothing packed the arrows select nothing; over a grid with no banners ``+`` has no group
    to act on; with nothing selected and nothing pinned the group is the first row's (#221).

    **Test steps:**

    * press RIGHT and DOWN over an empty grid and verify nothing is selected
    * pack one unbannered member, press ``+`` and verify nothing collapsed, nothing raised
    * banner it and verify the current group is the first row's banner with nothing selected
    """
    qtbot.keyClick(view, Qt.Key.Key_Right)
    qtbot.keyClick(view, Qt.Key.Key_Down)
    assert view.selected is None
    assert view.current_group() is None

    content_model.set_entries([entry(PACK, "a.png")], REHU_DIRECTORY)
    settle(qtbot, view, content_model)
    assert view.current_group() is None
    qtbot.keyClick(view, Qt.Key.Key_Plus)
    assert view.collapsed == frozenset()

    view.set_flags(ContentDisplayFlags(zip_names=True, folder_names=False))
    qtbot.waitUntil(lambda: view.layout_table is not None and len(view.layout_table.rows) == 2)
    assert view.current_group() == "pack.zip"


def test_reveal_before_any_pack_selects_without_a_group(
    view: ContentImagesView, content_model: ContentImagesModel, qtbot: QtBot
) -> None:
    """Asked before the first pack has run, ``reveal`` has no groups to consult yet and simply selects.

    **Test steps:**

    * set entries and reveal one before the pack timer fires
    * verify it is selected, and that a resize, an arrow key and the current-group question in that
      state (no table yet) raise nothing and change nothing
    """
    content_model.set_entries([entry(PACK, "a.png")], REHU_DIRECTORY)
    view.reveal(0)
    assert view.selected == 0
    view.resize(900, 400)
    assert view.current_group() is None
    qtbot.keyClick(view, Qt.Key.Key_Right)
    assert view.selected == 0


def test_new_flags_open_every_group(view: ContentImagesView, content_model: ContentImagesModel, qtbot: QtBot) -> None:
    """The groups change with the banner boxes, so what was collapsed under the old ones is forgotten.

    **Test steps:**

    * collapse a group, then apply other flags
    * verify nothing is collapsed
    """
    view.set_flags(ContentDisplayFlags(zip_names=True, folder_names=False))
    content_model.set_entries([entry(PACK, "a.png")], REHU_DIRECTORY)
    settle(qtbot, view, content_model)
    view.set_collapsed("pack.zip", True)

    view.set_flags(ContentDisplayFlags(zip_names=True, folder_names=True))

    assert view.collapsed == frozenset()


def test_the_panel_shows_the_status_under_the_grid(
    content_model: ContentImagesModel, loader: ThumbnailLoader, qtbot: QtBot
) -> None:
    """The dock's content is the grid over a status label that follows the grid's reports.

    **Test steps:**

    * build a panel and have the grid report a status
    * verify the label shows it, below the grid
    * report a path far wider than the panel and verify it is elided rather than widening the panel
    """
    grid = ContentImagesView(content_model, loader)
    panel = ContentImagesPanel(grid)
    qtbot.addWidget(panel)
    panel.resize(400, 300)
    panel.show()
    qtbot.waitExposed(panel)

    grid.status_changed.emit("pack.zip:/a.png")

    assert panel.status.text() == "pack.zip:/a.png"
    assert panel.status.mapTo(panel, QPoint(0, 0)).y() >= grid.geometry().bottom()
    assert panel.view is grid

    long_path = "pack.zip:/" + "/".join(["folder"] * 40) + "/a.png"
    grid.status_changed.emit(long_path)
    shown = panel.status.text()
    assert shown != long_path
    assert "…" in shown
    assert shown.startswith("pack.zip:/") and shown.endswith("/a.png")
    assert panel.status.width() < 400


def test_re_applying_the_same_clamp_or_flags_packs_nothing(view: ContentImagesView, mocker: MockerFixture) -> None:
    """Applying the values the view already has is a no-op, not a needless pack.

    **Test steps:**

    * spy on the repack scheduling and re-apply the current clamp and flags
    * verify nothing was scheduled
    """
    scheduled = mocker.spy(view, "schedule_repack")

    view.set_clamp(*view.clamp)
    view.set_flags(view.flags)

    scheduled.assert_not_called()


def test_before_the_first_pack_the_view_answers_and_paints_nothing(
    content_model: ContentImagesModel, loader: ThumbnailLoader, qtbot: QtBot
) -> None:
    """A view that has not packed yet -- built, never shown -- has no table, hits nothing and paints
    nothing, without raising.

    **Test steps:**

    * build a view and neither show nor lay it out
    * verify there is no table, a hit test misses, and a paint is a no-op
    """
    built = ContentImagesView(content_model, loader)
    qtbot.addWidget(built)

    assert built.layout_table is None
    assert built.index_at(QPoint(1, 1)) is None
    built.grab()
    # the pack a paint's resize schedules runs on the next event-loop turn, which this test never spins
    assert built.layout_table is None


def test_a_reset_drops_the_old_table_before_the_repack(
    view: ContentImagesView, content_model: ContentImagesModel, qtbot: QtBot
) -> None:
    """Between a reset and the pack that follows it, the old rects would index the new sequence:
    a paint or a click in that window must find no table rather than the stale one.

    **Test steps:**

    * pack three entries, then reset the model to one
    * before the event loop turns, paint and hit-test, and verify neither raised and the table is gone
    * let the pack run and verify one entry is laid out
    """
    content_model.set_entries([entry(PACK, f"{index}.png", WIDE) for index in range(3)], REHU_DIRECTORY)
    settle(qtbot, view, content_model)

    content_model.set_entries([entry(PACK, "only.png", WIDE)], REHU_DIRECTORY)

    assert view.layout_table is None
    assert view.index_at(QPoint(5, 5)) is None
    view.grab()
    qtbot.waitUntil(lambda: view.layout_table is not None and len(view.layout_table.rects) == 1)


def test_the_view_offers_no_editing_affordance(view: ContentImagesView) -> None:
    """Read-only, visibly so: no context menu, no drag, and focus only by a click -- for the keyboard
    navigation, never to type into. (Selection is a view state, not an edit.)

    **Test steps:**

    * verify the context-menu policy, the focus policy and the absence of a drag start
    """
    assert view.contextMenuPolicy() == Qt.ContextMenuPolicy.NoContextMenu
    assert view.focusPolicy() == Qt.FocusPolicy.ClickFocus
    assert not hasattr(view, "startDrag")


def test_visible_thumbnails_are_decoded_and_painted(
    view: ContentImagesView, content_model: ContentImagesModel, loader: ThumbnailLoader, qtbot: QtBot
) -> None:
    """A paint asks the loader for the visible thumbnails, and they land in the cache at the row height.

    **Test steps:**

    * pack one member and let the headers land, which paints and so asks for the thumbnail
    * wait for the cache to hold it
    * verify it is decoded at the row's height
    """
    content_model.set_entries([entry(PACK, "a.png", WIDE)], REHU_DIRECTORY)
    settle(qtbot, view, content_model)
    table = view.layout_table
    assert table is not None
    height = table.rows[0].height
    key = content_model.source.key(0)

    view.grab()
    qtbot.waitUntil(lambda: loader.cached(key, height) is not None)

    cached = loader.cached(key, height)
    assert cached is not None
    # decoded *down* to the row, never up: a member shorter than the row keeps its own height
    assert cached.height() == min(height, WIDE[1])


def test_hidden_previews_leave_only_the_banners(
    view: ContentImagesView,
    content_model: ContentImagesModel,
    loader: ThumbnailLoader,
    qtbot: QtBot,
    mocker: MockerFixture,
) -> None:
    """With previews hidden app-wide the grid packs only its banner rows -- every image goes the way a
    collapsed group's do, and nothing is asked of the loader; showing them again brings the rows back
    (#71, #221).

    **Test steps:**

    * pack one bannered member, hide previews, and verify the table holds the banner row alone and
      no decode was requested on a paint
    * reveal the member while hidden (a viewer closing) and verify it is selected and nothing raised
    * show previews and verify the image row is back
    """
    view.set_flags(ContentDisplayFlags(zip_names=True, folder_names=False))
    content_model.set_entries([entry(PACK, "a.png", WIDE)], REHU_DIRECTORY)
    settle(qtbot, view, content_model)
    requested = mocker.spy(loader, "request")

    view.set_previews_visible(False)
    assert not view.previews_visible
    view.set_previews_visible(False)  # a repeat is a no-op
    qtbot.waitUntil(lambda: view.layout_table is not None and len(view.layout_table.rows) == 1)
    table = view.layout_table
    assert table is not None
    assert table.rows[0].banner == "pack.zip"
    assert table.rects[0] == (0, 0, 0, 0)
    view.viewport().grab()
    requested.assert_not_called()

    view.reveal(0)
    qtbot.wait(50)
    assert view.selected == 0
    assert view.verticalScrollBar().value() == 0

    view.set_previews_visible(True)
    qtbot.waitUntil(lambda: view.layout_table is not None and len(view.layout_table.rows) == 2)


def test_a_thumbnail_is_fitted_into_its_cell_never_stretched(
    view: ContentImagesView, content_model: ContentImagesModel, loader: ThumbnailLoader, qtbot: QtBot
) -> None:
    """A thumbnail whose proportions disagree with its cell is drawn fitted and centred inside it,
    leaving the cell's backdrop either side, rather than stretched to the cell.

    Regression: a portrait pack whose headers read landscape was drawn stretched into landscape cells.

    **Test steps:**

    * pack one member whose header says wide but whose pixels decode tall, and let the thumbnail land
    * verify the cell's left and right margins carry the backdrop, and its centre the image
    """
    tall_pixels = ContentImageEntry(PACK, "tall.png", TALL[0] * 1000 + TALL[1], 0)
    content_model.set_entries([tall_pixels], REHU_DIRECTORY)
    settle(qtbot, view, content_model)
    # the header the model read is what the cache served: overwrite it with a wide one, as a stored
    # size disagreeing with the shown one would, and re-pack
    header_key = tall_pixels.key
    content_model.header_read.emit(header_key, QSize(*WIDE))
    qtbot.waitUntil(lambda: content_model.aspect(0) == 2.0)
    qtbot.waitUntil(
        lambda: view.layout_table is not None and view.layout_table.rects[0][2] > view.layout_table.rects[0][3]
    )
    table = view.layout_table
    assert table is not None
    x, y, w, h = table.rects[0]
    view.grab()
    qtbot.waitUntil(lambda: loader.cached(header_key, h) is not None)

    painted = view.grab().toImage()

    backdrop = view.palette().color(QPalette.ColorRole.Window)
    assert painted.pixelColor(x + 2, y + h // 2) != Qt.GlobalColor.darkCyan
    assert painted.pixelColor(x + w // 2, y + h // 2) == Qt.GlobalColor.darkCyan
    assert painted.pixelColor(x + w - 3, y + h // 2).name() == backdrop.name()


def test_a_scroll_repaints(view: ContentImagesView, content_model: ContentImagesModel, qtbot: QtBot) -> None:
    """Enough rows to overflow give the scrollbar a range; scrolling moves what is painted.

    **Test steps:**

    * pack thirty members into a 400 px tall view -- at the placeholder aspect, before any header lands
    * verify the scrollbar has a range and a scroll reaches rows the first paint did not
    """
    content_model.set_entries([entry(PACK, f"{index}.png", WIDE) for index in range(30)], REHU_DIRECTORY)
    qtbot.waitUntil(lambda: view.layout_table is not None and len(view.layout_table.rows) > 1)
    scrollbar = view.verticalScrollBar()
    assert scrollbar.maximum() > 0

    scrollbar.setValue(scrollbar.maximum())
    view.grab()

    table = view.layout_table
    assert table is not None
    last = table.rows[-1]
    assert view.index_at(QPoint(10, last.y + last.height // 2 - scrollbar.value())) == last.first
    assert last.first != 0
