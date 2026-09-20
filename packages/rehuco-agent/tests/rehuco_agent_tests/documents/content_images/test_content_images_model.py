"""Tests for the Content Images model and its archive-backed image source (#221)."""

import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.content_images import ArchiveCache, ArchiveImageSource, ContentImagesModel
from rehuco_agent.documents.content_images import content_images_model as model_module
from rehuco_core import ContentImageEntry
from shiboken6 import isValid

from rehuco_agent_tests.documents.content_images.conftest import (
    OTHER_PACK,
    PACK,
    REHU_DIRECTORY,
    TALL,
    WIDE,
    entry,
    png_bytes,
)


def test_set_entries_resets_the_model_over_the_new_sequence(content_model: ContentImagesModel, qtbot: QtBot) -> None:
    """Entries replace the model's rows wholesale, as one reset.

    **Test steps:**

    * set two entries
    * verify the reset fired and the rows name the members
    """
    entries = [entry(PACK, "a.jpg"), entry(PACK, "sub/b.jpg")]

    with qtbot.waitSignal(content_model.modelReset):
        content_model.set_entries(entries, REHU_DIRECTORY)

    assert content_model.rowCount() == 2
    assert content_model.data(content_model.index(1, 0)) == "b.jpg"
    assert content_model.data(content_model.index(1, 0), Qt.ItemDataRole.ToolTipRole) == "sub/b.jpg"
    assert content_model.entries == entries


def test_dimensions_are_read_off_the_header_on_demand(content_model: ContentImagesModel, qtbot: QtBot) -> None:
    """An aspect is unknown until asked for, then read off the member's header on the pool and kept.

    **Test steps:**

    * set a wide and a tall entry and verify neither has an aspect
    * request both and wait for the reads to land
    * verify each aspect, and that asking again reads nothing more
    """
    content_model.set_entries([entry(PACK, "wide.png", WIDE), entry(PACK, "tall.png", TALL)], REHU_DIRECTORY)
    assert content_model.aspect(0) is None

    content_model.request_dimensions([0, 1])
    qtbot.waitUntil(lambda: content_model.aspect(0) is not None and content_model.aspect(1) is not None)

    assert content_model.aspect(0) == 2.0
    assert content_model.aspect(1) == 0.5
    dimensions = content_model.dimensions(0)
    assert dimensions is not None
    assert (dimensions.width(), dimensions.height()) == WIDE


def test_a_header_missing_from_the_leading_slice_is_read_off_the_whole_member(
    content_model: ContentImagesModel, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """When the partial inflate does not reach the header, the member is read in full for it.

    **Test steps:**

    * make the head read return too few bytes to size, the whole read the real PNG
    * request the dimensions and verify the aspect landed through the whole read
    """
    whole = png_bytes(*WIDE)
    mocker.patch.object(ArchiveCache, "read_head", return_value=whole[:8])
    read = mocker.patch.object(ArchiveCache, "read", return_value=whole)
    content_model.set_entries([entry(PACK, "deep.png", WIDE)], REHU_DIRECTORY)

    content_model.request_dimensions([0])
    qtbot.waitUntil(lambda: content_model.aspect(0) is not None)

    assert content_model.aspect(0) == 2.0
    read.assert_called_once()


def test_the_archive_image_source_describes_its_member_and_pixel_size(
    archive: Callable[[ContentImageEntry], bytes | None], mocker: MockerFixture
) -> None:
    """`ArchiveImageSource.describe` names the member relative to the ``.rehu`` without touching the
    archive; the pixel size is a separate header read -- the same one `HeaderJob` keeps for the
    dock's own dimensions column, reused rather than duplicated (#321).

    **Test steps:**

    * describe a member of a pack under the ``.rehu`` directory and verify the archive was not read
    * verify the archive-relative path and the stored byte size
    * ask for the pixel size and verify it came off the header
    """
    source = ArchiveImageSource([entry(PACK, "a.png", WIDE)], ArchiveCache(), REHU_DIRECTORY)
    read_head = mocker.patch.object(ArchiveCache, "read_head", side_effect=archive)

    description = source.describe(0)

    read_head.assert_not_called()
    assert description.path_text == "pack.zip:/a.png"
    assert description.byte_size == entry(PACK, "a.png", WIDE).size
    assert source.pixel_size(0).toTuple() == WIDE
    read_head.assert_called_once()


def test_the_model_exposes_its_own_archive_cache(content_model: ContentImagesModel) -> None:
    """The cache every read of this resource's archives goes through is reachable from outside, for a
    caller that wants to read through it directly.

    **Test steps:**

    * read the model's cache
    * verify it is the same cache instance the model reads its own members through
    """
    assert isinstance(content_model.archive_cache, ArchiveCache)


def test_the_model_answers_nothing_for_an_invalid_index_or_another_role(content_model: ContentImagesModel) -> None:
    """Off-model asks come back empty, the way any `QAbstractListModel` answers them.

    **Test steps:**

    * ask an invalid index for its text, and a valid one for a role the model does not carry
    """
    content_model.set_entries([entry(PACK, "a.png")], REHU_DIRECTORY)

    assert content_model.data(content_model.index(5, 0)) is None
    assert content_model.data(content_model.index(0, 0), Qt.ItemDataRole.DecorationRole) is None
    assert content_model.rowCount(content_model.index(0, 0)) == 0


def test_an_unreadable_member_settles_as_unreadable(content_model: ContentImagesModel, qtbot: QtBot) -> None:
    """A member that cannot be read settles with an invalid size -- known to be unreadable, so it is
    never asked for again -- and packs at the placeholder.

    **Test steps:**

    * set a member the fake archive refuses and request its dimensions
    * wait for the read to land and verify it is invalid, with no aspect
    """
    content_model.set_entries([entry(PACK, "broken.png")], REHU_DIRECTORY)

    content_model.request_dimensions([0])
    qtbot.waitUntil(lambda: content_model.dimensions(0) is not None)

    size = content_model.dimensions(0)
    assert size is not None
    assert not size.isValid()
    assert content_model.aspect(0) is None


def test_refresh_enumerates_off_the_gui_thread_and_adopts_the_result(
    content_model: ContentImagesModel, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """A refresh runs the enumeration on the pool and resets the model when it lands.

    **Test steps:**

    * make the enumeration return one entry, and refresh for a path
    * wait for the reset and verify the entry and the directory were adopted
    """
    found = [entry(PACK, "a.jpg")]
    enumeration = mocker.patch.object(model_module, "enumerate_content_images", return_value=found)

    with qtbot.waitSignal(content_model.modelReset, timeout=5000):
        content_model.refresh(REHU_DIRECTORY / "info.rehu", (".jpg",))

    enumeration.assert_called_once_with(REHU_DIRECTORY / "info.rehu", (".jpg",))
    assert content_model.entries == found
    assert content_model.rehu_directory == REHU_DIRECTORY


def test_a_stale_enumeration_is_dropped(content_model: ContentImagesModel, mocker: MockerFixture) -> None:
    """An answer to an older refresh never overwrites the newer request's.

    **Test steps:**

    * refresh once, so the current generation is one
    * deliver an answer tagged with generation zero
    * verify nothing was adopted
    """
    mocker.patch.object(model_module, "enumerate_content_images", return_value=[])
    mocker.patch.object(QThreadPool, "start")
    content_model.refresh(REHU_DIRECTORY / "info.rehu", (".jpg",))

    content_model.enumerated.emit(0, [entry(PACK, "stale.jpg")])

    assert content_model.entries == []


def test_a_destroyed_model_stops_and_closes_its_archives(mocker: MockerFixture, qtbot: QtBot, archive: object) -> None:
    """Once the model is gone -- its document closed -- a job on the pool that has not read yet reads
    nothing, and the archive handles it held are closed.

    **Test steps:**

    * spy on the cache's close before the model binds it, build a model, and delete it
    * verify it reads as stopped and the cache was closed
    """
    del archive
    # on the class, before construction: the model binds `close` at construction, so an instance spy
    # patched afterwards would never see the call
    closed = mocker.spy(ArchiveCache, "close")
    content_model = ContentImagesModel()

    content_model.deleteLater()
    qtbot.waitUntil(lambda: content_model.stopped)

    closed.assert_called_once()


def test_a_header_job_on_a_stopped_model_reads_nothing(
    content_model: ContentImagesModel, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """A header read still queued on the pool when its model stopped touches no archive.

    **Test steps:**

    * set an entry and request its header with the pool held, so the job is queued but not run
    * delete the model and wait for it to stop
    * run the job and verify no read happened
    """
    content_model.set_entries([entry(PACK, "a.png", WIDE)], REHU_DIRECTORY)
    read_head = mocker.spy(ArchiveCache, "read_head")
    started = mocker.patch.object(QThreadPool, "start")
    content_model.request_dimensions([0])
    ((job,), _kwargs) = started.call_args
    content_model.deleteLater()
    qtbot.waitUntil(lambda: content_model.stopped)

    job.run()

    read_head.assert_not_called()


def test_a_header_landing_after_its_model_is_gone_reaches_nobody(
    content_model: ContentImagesModel, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """A read already under way when the model goes finishes and reports through its own sender, into
    a connection Qt has severed: no crash, no traceback, nothing left on the pool.

    **Test steps:**

    * on a pool of this test's own, hold the header read at a gate, request a header, and wait for
      the worker to reach the gate
    * delete the model and wait for its C++ side to go
    * release the gate and verify the pool drains
    """
    pool = QThreadPool()
    mocker.patch.object(QThreadPool, "globalInstance", return_value=pool)
    gate = threading.Event()
    entered = threading.Event()

    def held_read(*_args: object) -> bytes:
        entered.set()
        gate.wait(5)
        return png_bytes(*WIDE)

    mocker.patch.object(ArchiveCache, "read_head", side_effect=held_read)
    content_model.set_entries([entry(PACK, "a.png", WIDE)], REHU_DIRECTORY)
    content_model.request_dimensions([0])
    qtbot.waitUntil(entered.is_set)

    content_model.deleteLater()
    qtbot.waitUntil(lambda: not isValid(content_model))

    gate.set()
    qtbot.waitUntil(lambda: pool.activeThreadCount() == 0)


def test_refreshing_for_no_path_empties_the_model(content_model: ContentImagesModel) -> None:
    """A document with no path yet has no archives to enumerate: the model empties, nothing is queued.

    **Test steps:**

    * set an entry, then refresh for ``None``
    * verify the model is empty
    """
    content_model.set_entries([entry(PACK, "a.jpg")], REHU_DIRECTORY)

    content_model.refresh(None, (".jpg",))

    assert content_model.rowCount() == 0


def test_the_source_describes_a_member_by_archive_and_path(content_model: ContentImagesModel) -> None:
    """The image source names a member as ``<archive relative to the .rehu>:/<member path>`` and its
    stored size, keys it by the tier-0 key, and decodes it through the archive.

    **Test steps:**

    * set a nested archive's member and read the source's answers
    """
    member = entry(OTHER_PACK, "sub/dir/img.png", TALL)
    content_model.set_entries([member], REHU_DIRECTORY)
    source = content_model.source

    assert len(source) == 1
    assert source.key(0) == member.key
    assert source.name(0) == "img.png"
    description = source.describe(0)
    assert description.path_text == "sub/other.zip:/sub/dir/img.png"
    assert description.byte_size == member.size
    image = source.load(0, None)
    assert (image.width(), image.height()) == TALL
    assert source.load(0, 50).height() == 50


def test_the_source_yields_a_null_image_for_an_unreadable_member(content_model: ContentImagesModel) -> None:
    """A member the archive cannot serve decodes to a null image rather than raising.

    **Test steps:**

    * set a member the fake archive refuses and load it
    * verify the image is null
    """
    content_model.set_entries([entry(PACK, "broken.png")], REHU_DIRECTORY)

    assert content_model.source.load(0, None).isNull()


def test_the_source_over_no_directory_still_names_the_archive(content_model: ContentImagesModel) -> None:
    """With no ``.rehu`` directory known, a member is named by its archive's bare name.

    **Test steps:**

    * set an entry with no directory and describe it
    """
    content_model.set_entries([entry(Path("/elsewhere/pack.zip"), "a.jpg")], None)

    assert content_model.source.describe(0).path_text == "pack.zip:/a.jpg"
