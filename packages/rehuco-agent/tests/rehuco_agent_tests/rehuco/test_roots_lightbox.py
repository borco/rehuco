"""Tests for the lightbox the Roots view opens over a zip's images or a folder's (#456)."""

import threading
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from PySide6.QtCore import QEvent, QObject, Qt, QThreadPool
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPixmapCache
from PySide6.QtWidgets import QApplication, QWidget
from pytest import LogCaptureFixture, MonkeyPatch, fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.content_images.archive_cache import ArchiveCache
from rehuco_agent.documents.content_images.content_images_model import ArchiveImageSource
from rehuco_agent.fields.widgets import ImageLightbox, ImageViewerMode
from rehuco_agent.fields.widgets.thumbnail_loader import ThumbnailLoader
from rehuco_agent.fields.widgets.thumbnail_row import ThumbnailRow
from rehuco_agent.rehuco import roots_lightbox
from rehuco_agent.rehuco.roots_lightbox import EMPTY_PACK_MESSAGE, ImagesOwner, RootsLightbox
from rehuco_agent.settings.image_viewer_settings import shared_image_viewer_settings
from rehuco_core import RenameCoordinator

from rehuco_agent_tests.crafted_zips import write_future_version_zip, write_undecodable_name_zip

WAIT_TIMEOUT_MS: Final = 10_000

ID: Final = "0f8fad5b-d9cb-469f-a165-70867728950e"


def picture(path: Path, width: int = 8) -> None:
    """Save a small picture.

    :param path: where.
    :param width: its width; its height is 6.
    """
    image = QImage(width, 6, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    assert image.save(str(path))


def make_pack(path: Path, names: tuple[str, ...]) -> Path:
    """Write a stored zip holding a small picture for each name.

    :param path: the zip.
    :param names: the member names; a name not ending in an image extension holds text.
    :returns: the path.
    """
    scratch = path.parent / f"{path.stem}-pictures"
    scratch.mkdir()
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            if name.lower().endswith((".png", ".jpg")):
                picture(scratch / "p.png")
                archive.write(scratch / "p.png", name)
            else:
                archive.writestr(name, "text")
    return path


@fixture(name="host")
def fixture_host(qtbot: QtBot) -> QWidget:
    """A shown widget for the viewer to cover.

    :param qtbot: pytest-qt fixture.
    :returns: the widget.
    """
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(400, 300)
    host.show()
    return host


@fixture(name="lightbox")
def fixture_lightbox(host: QWidget) -> RootsLightbox:
    """The lightbox over the host.

    :param host: the widget it covers.
    :returns: the lightbox.
    """
    return RootsLightbox(host, RenameCoordinator())


def names_of(lightbox: RootsLightbox) -> list[str]:
    """The names of the images the open viewer navigates.

    :param lightbox: the lightbox.
    :returns: the names, in order.
    """
    viewer = lightbox.viewer
    assert viewer is not None
    source = viewer.source
    return [source.name(index) for index in range(len(source))]


def test_an_archive_opens_its_images_in_pack_order_on_the_first(
    qtbot: QtBot, tmp_path: Path, lightbox: RootsLightbox
) -> None:
    """The listing is read on the pool and the viewer opens over what it found, folders after the root's images.

    **Test steps:**

    * open a zip whose directory lists a folder's image before the root's, and a note
    * verify the viewer navigates the images in pack order and stands on the first
    """
    pack = make_pack(tmp_path / "pack.zip", ("sub/x.png", "b10.png", "b2.png", "note.txt"))

    lightbox.open_archive(pack)

    qtbot.waitUntil(lambda: lightbox.viewer is not None, timeout=WAIT_TIMEOUT_MS)
    assert names_of(lightbox) == ["b2.png", "b10.png", "x.png"]
    assert lightbox.viewer is not None and lightbox.viewer.current_index == 0


def test_an_archive_with_no_images_opens_nothing_and_says_so(
    qtbot: QtBot, tmp_path: Path, lightbox: RootsLightbox
) -> None:
    """A zip of notes is not a pack the lightbox can show: the owner is told, and no viewer appears.

    **Test steps:**

    * open a zip holding only a text file
    * verify the notice names the archive and no viewer exists
    """
    pack = make_pack(tmp_path / "notes.zip", ("note.txt",))

    with qtbot.waitSignal(lightbox.nothing_to_show, timeout=WAIT_TIMEOUT_MS) as notice:
        lightbox.open_archive(pack)

    assert notice.args == [EMPTY_PACK_MESSAGE.format(name="notes.zip")]
    assert lightbox.viewer is None


def test_a_zip_python_cannot_decode_or_support_has_nothing_to_show(
    qtbot: QtBot, tmp_path: Path, lightbox: RootsLightbox
) -> None:
    """``zipfile`` raises on these, and the owner is still told, with no viewer (#480).

    **Test steps:**

    * open a zip with a UTF-8 flagged member name that is not UTF-8, and one claiming extract version 7.0
    * verify each tells its owner there is nothing to show and no viewer exists
    """
    for pack in (write_undecodable_name_zip(tmp_path / "name.zip"), write_future_version_zip(tmp_path / "v.zip")):
        with qtbot.waitSignal(lightbox.nothing_to_show, timeout=WAIT_TIMEOUT_MS) as notice:
            lightbox.open_archive(pack)

        assert notice.args == [EMPTY_PACK_MESSAGE.format(name=pack.name)]
        assert lightbox.viewer is None


def test_a_listing_that_raises_unexpectedly_is_logged_and_nothing_is_shown(
    qtbot: QtBot, tmp_path: Path, lightbox: RootsLightbox, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """Nothing escapes the pool job: the owner is told there is nothing to show, and the failure is logged (#480).

    **Test steps:**

    * make the listing raise, and open a zip
    * verify the notice, that no viewer exists and that the error was logged
    """
    mocker.patch("rehuco_agent.rehuco.roots_lightbox.list_archive_images", side_effect=ValueError("boom"))
    pack = make_pack(tmp_path / "pack.zip", ("a.png",))

    with qtbot.waitSignal(lightbox.nothing_to_show, timeout=WAIT_TIMEOUT_MS):
        lightbox.open_archive(pack)

    assert lightbox.viewer is None
    assert "pack.zip" in caplog.text and "boom" in caplog.text


def test_a_listing_overtaken_by_a_newer_request_is_dropped(
    qtbot: QtBot, tmp_path: Path, lightbox: RootsLightbox
) -> None:
    """Asking for a second zip before the first has answered leaves only the second on screen.

    **Test steps:**

    * open one zip and then another straight away, and let both reads finish
    * verify the viewer shows the second's images alone
    """
    first = make_pack(tmp_path / "first.zip", ("one.png",))
    second = make_pack(tmp_path / "second.zip", ("two.png", "three.png"))

    lightbox.open_archive(first)
    lightbox.open_archive(second)
    qtbot.waitUntil(lambda: lightbox.viewer is not None, timeout=WAIT_TIMEOUT_MS)
    QApplication.processEvents()

    assert names_of(lightbox) == ["three.png", "two.png"]


def test_loose_images_open_on_the_one_asked_for(tmp_path: Path, lightbox: RootsLightbox) -> None:
    """A folder's images need no listing: the viewer opens at once on the clicked one.

    **Test steps:**

    * open three picture files on the second
    * verify the viewer navigates all three and stands on the second
    """
    images = [tmp_path / name for name in ("a.png", "b.png", "c.png")]
    for image in images:
        picture(image)

    lightbox.open_images(images, 1)

    viewer = lightbox.viewer
    assert viewer is not None
    assert names_of(lightbox) == ["a.png", "b.png", "c.png"]
    assert viewer.current_index == 1


def test_closing_the_viewer_lets_go_of_the_archive(
    qtbot: QtBot, tmp_path: Path, lightbox: RootsLightbox, mocker: MockerFixture
) -> None:
    """The handles an archive's viewer read through are closed when the viewer is gone, and only then.

    **Test steps:**

    * open a zip, and close the viewer
    * verify the archive cache was closed once the viewer was deleted
    """
    close = mocker.spy(ArchiveCache, "close")
    lightbox.open_archive(make_pack(tmp_path / "pack.zip", ("a.png",)))
    qtbot.waitUntil(lambda: lightbox.viewer is not None, timeout=WAIT_TIMEOUT_MS)
    viewer = lightbox.viewer
    assert viewer is not None
    close.assert_not_called()

    viewer.close()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)

    assert close.call_count == 1
    assert lightbox.viewer is None


def test_a_second_viewer_replaces_the_first_and_lets_go_of_its_archive(
    qtbot: QtBot, tmp_path: Path, lightbox: RootsLightbox, mocker: MockerFixture
) -> None:
    """One viewer at a time: opening images after a zip closes the zip's viewer and its archive handles.

    **Test steps:**

    * open a zip, then loose images over it
    * verify the zip's cache was closed and the new viewer stands
    """
    close = mocker.spy(ArchiveCache, "close")
    lightbox.open_archive(make_pack(tmp_path / "pack.zip", ("a.png",)))
    qtbot.waitUntil(lambda: lightbox.viewer is not None, timeout=WAIT_TIMEOUT_MS)
    first = lightbox.viewer
    image = tmp_path / "loose.png"
    picture(image)

    lightbox.open_images([image], 0)
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)

    assert lightbox.viewer is not None and lightbox.viewer is not first
    assert close.call_count == 1


class RecordingLoader(ThumbnailLoader):
    """A loader on a pool of two threads that records itself, so a test can reach the one the lightbox keeps."""

    INSTANCES: Final[list[RecordingLoader]] = []

    def __init__(self, parent: QObject | None = None, pool: QThreadPool | None = None) -> None:
        del pool
        own_pool = QThreadPool()
        own_pool.setMaxThreadCount(2)
        super().__init__(parent, own_pool)
        self.INSTANCES.append(self)


@dataclass
class ThumbnailGate:
    """Holds every thumbnail decode of an archive until released, and records the ones a worker has taken."""

    released: threading.Event = field(default_factory=threading.Event)
    started: list[int] = field(default_factory=list)


@fixture(name="gated_thumbnails")
def fixture_gated_thumbnails(monkeypatch: MonkeyPatch) -> ThumbnailGate:
    """Make the lightbox's loader a `RecordingLoader` and hold the thumbnails of an archive at a gate.

    The gate is on thumbnails only (``max_height`` set): the viewer's main image loads on the GUI thread through the
    same method, and holding that would deadlock the test.

    :param monkeypatch: pytest fixture.
    :returns: the gate.
    """
    QPixmapCache.clear()
    RecordingLoader.INSTANCES.clear()
    monkeypatch.setattr(roots_lightbox, "ThumbnailLoader", RecordingLoader)
    monkeypatch.setattr(shared_image_viewer_settings(), "strip_visible", True)
    gate = ThumbnailGate()
    original_load = ArchiveImageSource.load

    def gated_load(self: ArchiveImageSource, index: int, max_height: int | None) -> QImage:
        if max_height is not None:
            gate.started.append(index)
            gate.released.wait()
        return original_load(self, index, max_height)

    monkeypatch.setattr(ArchiveImageSource, "load", gated_load)
    return gate


def open_pack_with_row(qtbot: QtBot, lightbox: RootsLightbox, pack: Path) -> ImageLightbox:
    """Open a pack and paint the viewer's thumbnail row, so its decodes are asked for.

    :param qtbot: pytest-qt fixture.
    :param lightbox: the lightbox.
    :param pack: the zip.
    :returns: the viewer.
    """
    lightbox.open_archive(pack)
    qtbot.waitUntil(lambda: lightbox.viewer is not None, timeout=WAIT_TIMEOUT_MS)
    viewer = lightbox.viewer
    assert viewer is not None
    row = viewer.findChild(ThumbnailRow)
    assert row is not None and row.isVisibleTo(viewer)
    row.viewport().grab()
    return viewer


def thumbnail_states(loader: ThumbnailLoader, viewer: ImageLightbox) -> list[str]:
    """Where each of the viewer's thumbnails stands in the loader.

    :param loader: the loader the viewer's row reads through.
    :param viewer: the viewer.
    :returns: ``cached``, ``failed`` or ``pending``, one per image.
    """
    row = viewer.findChild(ThumbnailRow)
    assert row is not None
    height, ratio = row.row_height, row.devicePixelRatio()
    source = viewer.source
    keys = [source.key(index) for index in range(len(source))]
    return [
        "cached" if loader.cached(key, height, ratio) else "failed" if loader.failed(key, height, ratio) else "pending"
        for key in keys
    ]


def test_a_pack_reopened_after_its_viewer_closed_mid_decode_shows_every_thumbnail(
    qtbot: QtBot, tmp_path: Path, host: QWidget, gated_thumbnails: ThumbnailGate
) -> None:
    """The viewer's archive cache is closed before its thumbnail row is gone, so a decode a worker already took reads
    nothing; that must not stay on the panel's loader as a failure for the same pack opened again (#479).

    **Test steps:**

    * open a six-image pack with the thumbnail row shown, paint it, and hold the decodes at a gate while two are
      running
    * close the viewer, release the gate, and wait for the two decodes to land
    * open the same pack again and verify every thumbnail is decoded and none is marked failed
    """
    lightbox = RootsLightbox(host, RenameCoordinator())
    loader = RecordingLoader.INSTANCES.pop()
    landed: list[str] = []
    loader.ready.connect(landed.append)
    pack = make_pack(tmp_path / "pack.zip", tuple(f"{index}.png" for index in range(6)))
    first = open_pack_with_row(qtbot, lightbox, pack)
    qtbot.waitUntil(lambda: len(gated_thumbnails.started) >= 2, timeout=WAIT_TIMEOUT_MS)
    running = len(gated_thumbnails.started)

    first.close()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    assert lightbox.viewer is None
    gated_thumbnails.released.set()
    qtbot.waitUntil(lambda: len(landed) >= running, timeout=WAIT_TIMEOUT_MS)
    second = open_pack_with_row(qtbot, lightbox, pack)

    qtbot.waitUntil(lambda: "pending" not in thumbnail_states(loader, second), timeout=WAIT_TIMEOUT_MS)
    assert thumbnail_states(loader, second) == ["cached"] * 6


def test_the_thumbnail_row_the_user_toggled_is_how_the_next_viewer_opens(
    tmp_path: Path, lightbox: RootsLightbox, mocker: MockerFixture
) -> None:
    """The row starts as the setting says, and a viewer's toggle carries over to the next one.

    **Test steps:**

    * open images, have the viewer report its row hidden, then open them again
    * verify the second viewer was built with the row hidden
    """
    built = mocker.patch("rehuco_agent.rehuco.roots_lightbox.ImageLightbox", wraps=ImageLightbox)
    image = tmp_path / "a.png"
    picture(image)
    lightbox.open_images([image], 0)
    viewer = lightbox.viewer
    assert viewer is not None

    viewer.strip_visible_changed.emit(False)
    lightbox.open_images([image], 0)

    assert built.call_args.kwargs["strip_visible"] is False
    viewer.strip_visible_changed.emit(True)
    lightbox.open_images([image], 0)
    assert built.call_args.kwargs["strip_visible"] is True


def test_the_keys_held_at_the_activation_pick_the_surface_though_the_listing_lands_later(
    qtbot: QtBot, tmp_path: Path, lightbox: RootsLightbox, mocker: MockerFixture
) -> None:
    """Ctrl held at the double-click covers the app window, as in a document, even when it is let go before the zip
    has been listed.

    **Test steps:**

    * open a zip with Ctrl held, and let it go before the listing lands
    * verify the viewer was built over the app window
    """
    keys = mocker.patch(
        "rehuco_agent.rehuco.roots_lightbox.QApplication.keyboardModifiers",
        return_value=Qt.KeyboardModifier.ControlModifier,
    )
    built = mocker.patch("rehuco_agent.rehuco.roots_lightbox.ImageLightbox", wraps=ImageLightbox)

    lightbox.open_archive(make_pack(tmp_path / "pack.zip", ("a.png",)))
    keys.return_value = Qt.KeyboardModifier.NoModifier
    qtbot.waitUntil(lambda: built.called, timeout=WAIT_TIMEOUT_MS)

    assert built.call_args.args[2] is ImageViewerMode.APP_WINDOW_OVERLAY


def clipboard_names() -> list[str]:
    """The file names the clipboard holds, cleared after reading.

    :returns: the names, in order.
    """
    held = QGuiApplication.clipboard().mimeData()
    assert held is not None
    names = [Path(url.toLocalFile()).name for url in held.urls()]
    QGuiApplication.clipboard().clear()
    return names


@mark.usefixtures("real_path_stat")
def test_an_image_copied_out_of_a_pack_is_named_by_its_owner_and_its_path_under_the_record(
    qtbot: QtBot, tmp_path: Path, lightbox: RootsLightbox
) -> None:
    """A pack a record manages is named as a document names it (#395): by the record's id, its path relative to the
    record's folder, the archive a segment of its own -- which the info box reads too.

    **Test steps:**

    * open a zip in a subfolder of a resource, owned by the resource's record
    * verify the image is described relative to the record's folder
    * copy it and verify the staged name
    """
    resource = tmp_path / "Pack"
    (resource / "sub").mkdir(parents=True)
    pack = make_pack(resource / "sub" / "pack.zip", ("a.png",))

    lightbox.open_archive(pack, ImagesOwner(ID, resource))
    qtbot.waitUntil(lambda: lightbox.viewer is not None, timeout=WAIT_TIMEOUT_MS)
    viewer = lightbox.viewer
    assert viewer is not None

    assert viewer.source.describe(0).path_text == "sub/pack.zip/a.png"
    viewer.copy_current()
    assert clipboard_names() == [f"rehu-{ID}__sub__pack.zip__a.png"]


@mark.usefixtures("real_path_stat")
def test_an_image_no_record_manages_is_named_by_its_folder(tmp_path: Path, lightbox: RootsLightbox) -> None:
    """With no record over it, a loose image is named by the folder it sits in (#395).

    **Test steps:**

    * open a picture file with no owner and copy it
    * verify the staged name is the folder's and the file's
    """
    (tmp_path / "Shots").mkdir()
    image = tmp_path / "Shots" / "a.png"
    picture(image)

    lightbox.open_images([image], 0)
    viewer = lightbox.viewer
    assert viewer is not None
    viewer.copy_current()

    assert clipboard_names() == ["rehu-Shots__a.png"]
