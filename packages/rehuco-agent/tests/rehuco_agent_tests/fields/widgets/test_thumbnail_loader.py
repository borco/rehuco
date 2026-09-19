"""Tests for the thread-pool thumbnail loader and the lazy thumbnail row (#221)."""

import threading
from collections.abc import Hashable
from typing import Final

from PySide6.QtCore import QSize, Qt, QThreadPool
from PySide6.QtGui import QImage, QPixmapCache
from PySide6.QtWidgets import QStyleOptionViewItem
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.image_source import ImageDescription
from rehuco_agent.fields.widgets.thumbnail_loader import CACHE_LIMIT_KIB, ThumbnailLoader, thumbnail_cache_key
from rehuco_agent.fields.widgets.thumbnail_row import ThumbnailRow
from shiboken6 import isValid

IMAGE_HEIGHT: Final = 40
IMAGE_WIDTH: Final = 80

OWNER: Final = object()
OTHER_OWNER: Final = object()
"""Two surfaces asking the same loader, as the grid and the lightbox row it opens do."""


class RecordingSource:
    """An `ImageSource` over ``count`` synthetic images that records every decode it is asked for.

    A gate holds every decode until the test releases it, so the order requests are served in is
    observable; a name starting with ``broken`` decodes to nothing.

    :param count: how many images.
    :param names: the images' names, ``image<N>`` by default.
    """

    def __init__(self, count: int, names: list[str] | None = None) -> None:
        self.__names: Final = names if names is not None else [f"image{index}" for index in range(count)]
        self.loaded: Final[list[int]] = []
        self.gate: Final = threading.Event()
        self.gate.set()
        self.started: Final = threading.Event()
        """Set the moment a worker enters :meth:`load`, before it waits at the gate."""

    def __len__(self) -> int:
        return len(self.__names)

    def key(self, index: int) -> Hashable:
        """The name, which is stable across sources built over the same names."""
        return self.__names[index]

    def name(self, index: int) -> str:
        """The name."""
        return self.__names[index]

    def describe(self, index: int) -> ImageDescription:
        """The name and no size."""
        return ImageDescription(self.__names[index], None)

    def load(self, index: int, max_height: int | None) -> QImage:
        """Wait at the gate, record the position, and return a small image -- or a null one."""
        self.started.set()
        self.gate.wait()
        self.loaded.append(index)
        if self.__names[index].startswith("broken"):
            return QImage()
        height = IMAGE_HEIGHT if max_height is None else min(IMAGE_HEIGHT, max_height)
        return QImage(round(IMAGE_WIDTH * height / IMAGE_HEIGHT), height, QImage.Format.Format_RGB32)


@fixture(autouse=True)
def clear_pixmap_cache() -> None:
    """Start every test with an empty cache, so a hit is only ever this test's own doing."""
    QPixmapCache.clear()


@fixture
def loader() -> ThumbnailLoader:
    """A loader on the global pool."""
    return ThumbnailLoader()


@fixture
def single_worker_loader() -> ThumbnailLoader:
    """A loader on a pool of one thread, so the order requests are served in is observable: with
    several workers each takes the newest at the moment it looks, and the gate releases them together.
    """
    pool = QThreadPool()
    pool.setMaxThreadCount(1)
    return ThumbnailLoader(pool=pool)


# region loader tests


def test_a_request_decodes_off_the_gui_thread_into_the_cache(loader: ThumbnailLoader, qtbot: QtBot) -> None:
    """A miss queues a decode and announces the cache key when the pixmap lands; the next request hits.

    **Test steps:**

    * request one thumbnail and verify nothing came back yet
    * wait for the announcement and verify the cache holds it at the asked height
    * request it again and verify it comes straight back
    """
    source = RecordingSource(1)

    with qtbot.waitSignal(loader.ready, timeout=5000) as announced:
        assert loader.request(OWNER, source, 0, 20) is None

    assert announced.args == [thumbnail_cache_key("image0", 20)]
    cached = loader.cached("image0", 20)
    assert cached is not None
    assert cached.height() == 20
    assert loader.request(OWNER, source, 0, 20) is not None


def test_a_scaled_screen_gets_a_thumbnail_decoded_at_its_own_pixels(loader: ThumbnailLoader, qtbot: QtBot) -> None:
    """On a 2x desktop a 20 px row is 40 device pixels tall: the thumbnail is decoded at 40 and tagged
    with the ratio, so it paints one device pixel per pixel rather than a 20 px image blown up -- and
    it is cached apart from the 1x one.

    **Test steps:**

    * request a thumbnail at 20 px for a ratio of 2 and wait for it
    * verify the decode was asked for 40 px, the pixmap carries the ratio and reads 20 px logical
    * verify the 1x key is still a miss
    """
    source = RecordingSource(1)

    with qtbot.waitSignal(loader.ready, timeout=5000):
        loader.request(OWNER, source, 0, 20, 2.0)

    cached = loader.cached("image0", 20, 2.0)
    assert cached is not None
    assert cached.height() == 40
    assert cached.devicePixelRatio() == 2.0
    assert cached.deviceIndependentSize().toSize().height() == 20
    assert loader.cached("image0", 20) is None
    assert thumbnail_cache_key("image0", 20, 2.0) != thumbnail_cache_key("image0", 20)


def test_requests_are_served_newest_first(single_worker_loader: ThumbnailLoader, qtbot: QtBot) -> None:
    """A fast scroll queues rows the user has already left behind: the latest request is decoded first.

    **Test steps:**

    * hold the gate and queue four requests
    * release the gate
    * verify the queue was drained newest first -- whichever request the worker had already taken
      before the rest were queued, the remainder come down from the newest
    """
    source = RecordingSource(4)
    source.gate.clear()
    for index in range(4):
        single_worker_loader.request(OWNER, source, index, 20)

    source.gate.set()
    qtbot.waitUntil(lambda: len(source.loaded) == 4)

    first, *rest = source.loaded
    assert rest == sorted(rest, reverse=True)
    assert first in (0, 3)


def test_a_withdrawn_request_is_never_decoded(single_worker_loader: ThumbnailLoader, qtbot: QtBot) -> None:
    """A request the view has since withdrawn is dropped before a worker picks it up.

    **Test steps:**

    * hold the gate and queue three requests -- the worker takes the first at once and blocks on it
    * retain only that first one, release the gate
    * verify only the first was decoded, and a dropped one can be asked for again
    """
    source = RecordingSource(3)
    source.gate.clear()
    for index in range(3):
        single_worker_loader.request(OWNER, source, index, 20)

    single_worker_loader.retain(OWNER, [thumbnail_cache_key("image0", 20)])
    source.gate.set()
    qtbot.waitUntil(lambda: single_worker_loader.cached("image0", 20) is not None)
    qtbot.wait(50)

    assert source.loaded == [0]
    with qtbot.waitSignal(single_worker_loader.ready, timeout=5000):
        single_worker_loader.request(OWNER, source, 2, 20)


def test_retain_leaves_another_requesters_pending_decodes_alone(
    single_worker_loader: ThumbnailLoader, qtbot: QtBot
) -> None:
    """The grid pruning to what it shows must not withdraw the lightbox row's requests on the same
    loader, or the two would starve each other on every repaint.

    **Test steps:**

    * hold the gate, queue one request from each of two owners, then have the first retain nothing
    * release the gate and verify the other owner's request was still decoded
    """
    mine = RecordingSource(1, ["mine"])
    theirs = RecordingSource(1, ["theirs"])
    mine.gate.clear()
    theirs.gate.clear()
    single_worker_loader.request(OWNER, mine, 0, 20)
    single_worker_loader.request(OTHER_OWNER, theirs, 0, 20)

    single_worker_loader.retain(OWNER, [])
    mine.gate.set()
    theirs.gate.set()
    qtbot.waitUntil(lambda: single_worker_loader.cached("theirs", 20) is not None)

    assert theirs.loaded == [0]


def test_a_destroyed_loader_drains_its_queue_without_decoding(qtbot: QtBot) -> None:
    """Once the loader is gone -- its document closed -- a worker finds nothing more to decode rather
    than emitting into a dead signal.

    **Test steps:**

    * hold the gate, queue two requests on a one-thread loader, wait for the worker to be holding
      one at the gate, then delete the loader
    * release the gate and verify only the request the worker already held was decoded
    """
    pool = QThreadPool()
    pool.setMaxThreadCount(1)
    loader = ThumbnailLoader(pool=pool)
    source = RecordingSource(2)
    source.gate.clear()
    loader.request(OWNER, source, 0, 20)
    loader.request(OWNER, source, 1, 20)
    qtbot.waitUntil(source.started.is_set)

    loader.deleteLater()
    qtbot.waitUntil(lambda: not isValid(loader))
    source.gate.set()
    qtbot.waitUntil(lambda: pool.activeThreadCount() == 0)

    assert len(source.loaded) == 1


def test_an_undecodable_image_settles_as_failed(loader: ThumbnailLoader, qtbot: QtBot) -> None:
    """A decode that yields nothing is announced too, remembered as failed, and never asked again.

    **Test steps:**

    * request a broken image and wait for the announcement
    * verify nothing is cached, the loader reports it failed, and a second request queues nothing
    """
    source = RecordingSource(1, ["broken"])

    with qtbot.waitSignal(loader.ready, timeout=5000):
        loader.request(OWNER, source, 0, 20)

    assert loader.cached("broken", 20) is None
    assert loader.failed("broken", 20)
    assert loader.request(OWNER, source, 0, 20) is None
    qtbot.wait(50)
    assert source.loaded == [0]


def test_the_cache_limit_is_raised_never_lowered() -> None:
    """Building a loader lifts the process-wide cache limit to its floor and leaves a higher one alone.

    **Test steps:**

    * build a loader and verify the limit is at least the floor
    * raise the limit further, build another, and verify it is untouched
    """
    ThumbnailLoader(pool=QThreadPool.globalInstance())
    assert QPixmapCache.cacheLimit() >= CACHE_LIMIT_KIB

    QPixmapCache.setCacheLimit(CACHE_LIMIT_KIB * 2)
    ThumbnailLoader()
    assert QPixmapCache.cacheLimit() == CACHE_LIMIT_KIB * 2


# endregion


# region row tests


def test_the_row_lists_its_source_and_paints_lazily(loader: ThumbnailLoader, qtbot: QtBot) -> None:
    """The row has one item per image, decodes only on paint, and re-lays out as thumbnails land.

    **Test steps:**

    * build a row over three images and verify nothing was decoded
    * show it, paint it, and wait for the thumbnails
    * verify every visible item was decoded at the row height and the items are thumbnail-wide
    """
    source = RecordingSource(3)
    row = ThumbnailRow(loader, height=20)
    qtbot.addWidget(row)
    row.set_source(source)
    model = row.model()
    assert model is not None
    assert model.rowCount() == 3
    delegate = row.itemDelegate()
    assert delegate is not None
    # a size hint is what the list view asks of every item when it lays the row out: it must not
    # request, or building the row would decode the whole pack
    assert delegate.sizeHint(QStyleOptionViewItem(), model.index(2, 0)) == QSize(20, 20)
    assert not source.loaded

    row.resize(400, 20)
    row.show()
    qtbot.waitExposed(row)
    row.grab()
    qtbot.waitUntil(lambda: all(loader.cached(f"image{index}", 20) is not None for index in range(3)))
    qtbot.waitUntil(lambda: row.visualRect(model.index(0, 0)).width() == IMAGE_WIDTH // 2)

    assert sorted(source.loaded) == [0, 1, 2]


def test_the_row_marks_the_current_item_and_scrolls_it_into_view(loader: ThumbnailLoader, qtbot: QtBot) -> None:
    """``set_current`` frames a position and brings it into the viewport.

    **Test steps:**

    * build a narrow row over many images, shown
    * make the last current and verify it is framed and its rect is inside the viewport
    """
    source = RecordingSource(40)
    row = ThumbnailRow(loader, height=20)
    qtbot.addWidget(row)
    row.set_source(source)
    row.resize(100, 20)
    row.show()
    qtbot.waitExposed(row)
    model = row.model()
    assert model is not None

    row.set_current(39)

    assert row.current_index == 39
    last = row.visualRect(model.index(39, 0))
    # all but the item rect's own trailing pixel, which Qt's list view counts past the viewport edge
    assert row.viewport().rect().intersected(last).width() >= last.width() - 1


def test_a_click_reports_the_position(loader: ThumbnailLoader, qtbot: QtBot) -> None:
    """A click on an item fires ``activated_index`` with its position.

    **Test steps:**

    * build a shown row over three images and click the second
    * verify the activation
    """
    source = RecordingSource(3)
    row = ThumbnailRow(loader, height=20)
    qtbot.addWidget(row)
    row.set_source(source)
    row.resize(400, 20)
    row.show()
    qtbot.waitExposed(row)
    model = row.model()
    assert model is not None
    activated: list[int] = []
    row.activated_index.connect(activated.append)

    qtbot.mouseClick(row.viewport(), Qt.MouseButton.LeftButton, pos=row.visualRect(model.index(1, 0)).center())

    assert activated == [1]


def test_a_new_height_re_requests_at_that_height(loader: ThumbnailLoader, qtbot: QtBot, mocker: MockerFixture) -> None:
    """Resizing the row changes what every thumbnail is asked for; the same height is a no-op.

    **Test steps:**

    * build a shown row, then set a new height and paint
    * verify a thumbnail landed at the new height, and the row is that tall
    * set the same height again and verify no layout was scheduled
    """
    source = RecordingSource(1)
    row = ThumbnailRow(loader, height=20)
    qtbot.addWidget(row)
    row.set_source(source)
    row.resize(400, 20)
    row.show()
    qtbot.waitExposed(row)

    row.set_height(30)
    row.grab()

    qtbot.waitUntil(lambda: loader.cached("image0", 30) is not None)
    assert row.height() == 30
    assert row.row_height == 30

    relaid = mocker.spy(row, "scheduleDelayedItemsLayout")
    row.set_height(30)
    relaid.assert_not_called()


def test_the_row_answers_nothing_without_a_source_or_for_a_stray_index(loader: ThumbnailLoader, qtbot: QtBot) -> None:
    """A row over nothing has no thumbnails to ask for; a model over a source answers only what it holds.

    **Test steps:**

    * build a row with no source and ask for a thumbnail
    * give it a source and ask its model for an invalid index and a role it does not carry
    * clear the current mark and verify it reads as none
    """
    row = ThumbnailRow(loader, height=20)
    qtbot.addWidget(row)
    model = row.model()
    assert model is not None

    assert row.thumbnail(0) is None
    assert row.cached_thumbnail(0) is None
    assert model.rowCount() == 0

    row.set_source(RecordingSource(2))
    assert model.data(model.index(0, 0)) == "image0"
    assert model.data(model.index(0, 0), Qt.ItemDataRole.ToolTipRole) == "image0"
    assert model.data(model.index(5, 0)) is None
    assert model.data(model.index(0, 0), Qt.ItemDataRole.DecorationRole) is None
    assert model.rowCount(model.index(0, 0)) == 0

    row.set_current(1)
    row.set_current(-1)
    assert row.current_index == -1


# endregion
