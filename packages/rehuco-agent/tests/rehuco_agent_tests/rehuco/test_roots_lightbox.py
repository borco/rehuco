"""Tests for the lightbox the Roots view opens over a zip's images or a folder's (#456)."""

import zipfile
from pathlib import Path
from typing import Final

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QWidget
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.content_images.archive_cache import ArchiveCache
from rehuco_agent.fields.widgets import ImageLightbox, ImageViewerMode
from rehuco_agent.rehuco.roots_lightbox import EMPTY_PACK_MESSAGE, RootsLightbox
from rehuco_core import RenameCoordinator

WAIT_TIMEOUT_MS: Final = 10_000


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
