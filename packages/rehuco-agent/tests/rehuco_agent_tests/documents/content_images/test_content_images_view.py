"""Tests for the Content Images view: the justified grid painted from the packing table (#221)."""

# pylint infers `view.layout_table`'s rows as a PySide signal template rather than the `Row` dataclass
# they are (the view class body mixes `Signal(...)` attributes with the property), so every `.height`,
# `.banner` and `.y` read off a row trips no-member; pyright types them correctly
# pylint: disable=no-member

from PySide6.QtCore import QEvent, QPoint, QSize, Qt
from PySide6.QtGui import QCursor, QPalette
from PySide6.QtWidgets import QApplication
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.content_images import (
    ContentDisplayFlags,
    ContentImagesModel,
    ContentImagesPanel,
    ContentImagesView,
)
from rehuco_agent.documents.content_images.content_images_view import BANNER_HEIGHT, ITEM_SPACING
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
    """A left double-click over an image fires ``image_activated`` with its position; one on a banner,
    a gap below the rows, or with the right button fires nothing -- and the double-click leaves the
    selection where it was.

    **Test steps:**

    * pack two members behind a banner and let the pack settle
    * double-click the second image's centre, the banner and the empty space below; right-double-click
      the image
    * verify one activation, for position one, and nothing selected
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
    assert view.selected is None


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
    release selects, the double-click opens, and the trailing release must not deselect again. A
    click elsewhere, a right click, and a click on empty space leave the selection alone too.

    **Test steps:**

    * pack one member and send the real double-click sequence over it
    * verify it was activated once and is still selected
    * right-click it, click empty space, and verify the selection stands; click it and verify it clears
    """
    content_model.set_entries([entry(PACK, "a.png")], REHU_DIRECTORY)
    settle(qtbot, view, content_model)
    table = view.layout_table
    assert table is not None
    x, y, w, h = table.rects[0]
    centre = QPoint(x + w // 2, y + h // 2)
    activated: list[int] = []
    view.image_activated.connect(activated.append)

    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=centre)
    qtbot.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=centre)
    qtbot.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=centre)

    assert activated == [0]
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
    table = view.layout_table
    assert table is not None
    assert scrollbar.value() == scrollbar.maximum()
    collapsed_banner = next(row for row in table.rows if row.banner == "sub/other.zip")
    assert scrollbar.maximum() < collapsed_banner.y  # the collapsed tail no longer fills a viewport
    assert view.banner_at(QPoint(5, collapsed_banner.y - scrollbar.value() + 2)) == "sub/other.zip"


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
    """
    grid = ContentImagesView(content_model, loader)
    panel = ContentImagesPanel(grid)
    qtbot.addWidget(panel)
    panel.resize(400, 300)
    panel.show()
    qtbot.waitExposed(panel)

    grid.status_changed.emit("pack.zip:/a.png")

    assert panel.status.text() == "pack.zip:/a.png"
    assert panel.status.geometry().top() >= grid.geometry().bottom()
    assert panel.view is grid


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
    """Read-only, visibly so: no context menu, no focus to type into, no drag. (Selection is a view
    state, not an edit.)

    **Test steps:**

    * verify the context-menu policy, the focus policy and the absence of a drag start
    """
    assert view.contextMenuPolicy() == Qt.ContextMenuPolicy.NoContextMenu
    assert view.focusPolicy() == Qt.FocusPolicy.NoFocus
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
