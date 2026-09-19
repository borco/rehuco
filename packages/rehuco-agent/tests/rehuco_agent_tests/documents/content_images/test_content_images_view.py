"""Tests for the Content Images view: the justified grid painted from the packing table (#221)."""

# pylint infers `view.layout_table`'s rows as a PySide signal template rather than the `Row` dataclass
# they are (the view class body mixes `Signal(...)` attributes with the property), so every `.height`,
# `.banner` and `.y` read off a row trips no-member; pyright types them correctly
# pylint: disable=no-member

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QPalette
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.content_images import ContentDisplayFlags, ContentImagesModel, ContentImagesView
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
    assert [row.banner for row in table.rows] == ["[pack.zip]", None, "[sub/other.zip]", None]
    assert table.rows[0].height == BANNER_HEIGHT


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


def test_a_click_on_an_image_reports_its_position(
    view: ContentImagesView, content_model: ContentImagesModel, qtbot: QtBot
) -> None:
    """A left click over an image fires ``image_activated`` with its position; a click on a banner,
    a gap below the rows, or with the right button fires nothing.

    **Test steps:**

    * pack two members behind a banner and let the pack settle
    * left-click the second image's centre, the banner and the empty space below; right-click the image
    * verify one activation, for position one
    """
    view.set_flags(ContentDisplayFlags(zip_names=True, folder_names=False))
    content_model.set_entries([entry(PACK, "a.png"), entry(PACK, "b.png")], REHU_DIRECTORY)
    settle(qtbot, view, content_model)
    table = view.layout_table
    assert table is not None
    assert table.rows[0].banner is not None
    x, y, w, h = table.rects[1]
    activated: list[int] = []
    view.image_activated.connect(activated.append)

    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(x + w // 2, y + h // 2))
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(5, table.rows[0].y + 2))
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(5, table.height + 20))
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.RightButton, pos=QPoint(x + w // 2, y + h // 2))

    assert activated == [1]


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
    """Read-only, visibly so: no context menu, no focus to type into, no drag.

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

    backdrop = view.palette().color(QPalette.ColorRole.Base)
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
