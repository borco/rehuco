"""Tests for :mod:`rehuco_agent.fields.widgets.image_export` -- an image taken out of the app as a staged file and its
pixels (#395), and the sources' undecoded reads it stages from."""

from collections.abc import Iterator
from pathlib import Path
from typing import Final
from unittest.mock import MagicMock

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import QWidget
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.content_images import ArchiveCache
from rehuco_agent.documents.content_images.content_images_model import ArchiveImageSource
from rehuco_agent.fields.widgets import (
    ImageExporter,
    ImageVisibility,
    PathImageSource,
    ScreenshotRowsImageSource,
    image_mime,
)
from rehuco_agent.fields.widgets.image_export import DRAG_PIXMAP_SIZE
from rehuco_core import ContentImageEntry

pytestmark = mark.usefixtures("real_path_stat")

ID: Final = "0f8fad5b-d9cb-469f-a165-70867728950e"


def write_png(path: Path, width: int = 40, height: int = 20) -> bytes:
    """Write a real PNG and hand back its bytes.

    :param path: where to write it.
    :param width: its pixel width.
    :param height: its pixel height.
    :returns: the bytes written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.darkMagenta)
    assert image.save(str(path))
    return path.read_bytes()


@fixture
def staging(tmp_path: Path) -> Path:
    """The staging folder, not created yet."""
    return tmp_path / "staged"


@fixture
def resource(tmp_path: Path) -> Path:
    """A resource's folder, holding a screenshot under ``screenshots/``."""
    folder = tmp_path / "Pack"
    write_png(folder / "screenshots" / "a.png")
    return folder


@fixture
def clipboard() -> Iterator[None]:
    """Leave the clipboard empty after the test, whatever it put there."""
    yield
    QGuiApplication.clipboard().clear()


def test_the_mime_data_carries_the_file_and_the_pixels(tmp_path: Path) -> None:
    """One file URL to the staged copy, for a file-aware target; the decoded image, for a bitmap-only one.

    **Test steps:**

    * build the mime data of a real PNG
    * verify one local URL to it and an image of its size
    """
    data = write_png(tmp_path / "a.png", 30, 10)

    mime = image_mime(tmp_path / "a.png", data)

    assert [url.toLocalFile() for url in mime.urls()] == [(tmp_path / "a.png").as_posix()]
    assert mime.hasImage()
    image = mime.imageData()
    assert isinstance(image, QImage)
    assert (image.width(), image.height()) == (30, 10)


def test_bytes_that_do_not_decode_carry_the_file_alone(tmp_path: Path) -> None:
    """An image Qt cannot decode is still handed over as the file it is.

    **Test steps:**

    * build the mime data of bytes that are no image
    * verify the URL is there and the image is not
    """
    mime = image_mime(tmp_path / "a.webp", b"not an image")

    assert len(mime.urls()) == 1
    assert not mime.hasImage()


def test_an_export_stages_the_unchanged_bytes_under_the_resource_name(staging: Path, resource: Path) -> None:
    """The staged copy is byte-identical, named by the origin and the path relative to the record.

    **Test steps:**

    * export a screenshot named relative to its resource's folder
    * verify the URL names the scheme file in the staging folder, holding the original bytes
    """
    source = PathImageSource([resource / "screenshots" / "a.png"], resource)

    mime = ImageExporter(staging, lambda: ID).mime_data(source, 0)

    assert mime is not None
    (url,) = mime.urls()
    staged = Path(url.toLocalFile())
    assert staged == staging / f"rehu-{ID}__screenshots__a.png"
    assert staged.read_bytes() == (resource / "screenshots" / "a.png").read_bytes()


def test_a_file_outside_the_record_folder_is_named_by_its_file_name(staging: Path, tmp_path: Path) -> None:
    """A source names a file outside its base in full; the staged name keeps only the file's own name.

    **Test steps:**

    * export a file outside the source's base
    * verify the staged name is the origin and the file name
    """
    outside = tmp_path / "elsewhere" / "b.png"
    write_png(outside)
    source = PathImageSource([outside], tmp_path / "Pack")

    mime = ImageExporter(staging, lambda: "Pack").mime_data(source, 0)

    assert mime is not None
    assert Path(mime.urls()[0].toLocalFile()).name == "rehu-Pack__b.png"


def test_the_origin_is_asked_at_every_export(staging: Path, resource: Path) -> None:
    """A record saved or renamed since the exporter was built is named as it is now.

    **Test steps:**

    * export once, change what the origin says, export again
    * verify each export carries the origin of its moment
    """
    origins = iter(["first", "second"])
    exporter = ImageExporter(staging, lambda: next(origins))
    source = PathImageSource([resource / "screenshots" / "a.png"], resource)

    names = [Path(mime.urls()[0].toLocalFile()).name for mime in (exporter.mime_data(source, 0) for _ in "ab") if mime]

    assert names == ["rehu-first__screenshots__a.png", "rehu-second__screenshots__a.png"]


def test_an_image_that_cannot_be_read_or_staged_exports_nothing(
    staging: Path, resource: Path, mocker: MockerFixture
) -> None:
    """A missing file, or a staging folder that cannot be written, hands nothing over.

    **Test steps:**

    * export a file that is not there
    * export a real one with staging failing
    * verify neither gives mime data
    """
    missing = PathImageSource([resource / "gone.png"], resource)
    exporter = ImageExporter(staging, lambda: ID)
    assert exporter.mime_data(missing, 0) is None

    mocker.patch("rehuco_agent.fields.widgets.image_export.stage_image", return_value=None)
    assert exporter.mime_data(PathImageSource([resource / "screenshots" / "a.png"], resource), 0) is None


def test_a_copy_puts_the_file_and_the_pixels_on_the_clipboard(
    staging: Path, resource: Path, clipboard: None, qtbot: QtBot
) -> None:
    """Ctrl+C's half: the clipboard holds the staged file and the image; a failed read leaves it alone.

    **Test steps:**

    * copy a screenshot and read the clipboard back
    * copy a missing one and verify the answer is no
    """
    del clipboard, qtbot
    exporter = ImageExporter(staging, lambda: ID)

    assert exporter.copy(PathImageSource([resource / "screenshots" / "a.png"], resource), 0)

    held = QGuiApplication.clipboard().mimeData()
    assert held is not None
    assert [Path(url.toLocalFile()).name for url in held.urls()] == [f"rehu-{ID}__screenshots__a.png"]
    assert held.hasImage()
    assert not exporter.copy(PathImageSource([resource / "gone.png"], resource), 0)


def test_a_drag_is_a_copy_carrying_the_staged_file_and_a_small_picture(
    staging: Path, resource: Path, mocker: MockerFixture, qtbot: QtBot
) -> None:
    """A copy and nothing else, so a file manager never moves the staged file; the picture under the pointer is
    shrunk and held by its middle.

    **Test steps:**

    * with ``QDrag`` replaced, drag a screenshot with a picture larger than the bound
    * verify one copy drag carrying the staged file's URL, the picture bounded, the hot spot at its middle
    """
    widget = QWidget()
    qtbot.addWidget(widget)
    drag_class = mocker.patch("rehuco_agent.fields.widgets.image_export.QDrag")
    picture = QPixmap(4 * DRAG_PIXMAP_SIZE, 2 * DRAG_PIXMAP_SIZE)

    started = ImageExporter(staging, lambda: ID).drag(
        widget, PathImageSource([resource / "screenshots" / "a.png"], resource), 0, picture
    )

    assert started
    drag = drag_class.return_value
    drag.exec.assert_called_once_with(Qt.DropAction.CopyAction)
    (mime,) = drag.setMimeData.call_args.args
    assert Path(mime.urls()[0].toLocalFile()).name == f"rehu-{ID}__screenshots__a.png"
    (shown,) = drag.setPixmap.call_args.args
    assert (shown.width(), shown.height()) == (DRAG_PIXMAP_SIZE, DRAG_PIXMAP_SIZE // 2)
    (hot_spot,) = drag.setHotSpot.call_args.args
    assert (hot_spot.x(), hot_spot.y()) == (DRAG_PIXMAP_SIZE // 2, DRAG_PIXMAP_SIZE // 4)


def test_a_drag_keeps_a_small_picture_and_goes_without_a_null_one(
    staging: Path, resource: Path, mocker: MockerFixture, qtbot: QtBot
) -> None:
    """A picture already inside the bound is shown as it is; with none, the platform's default cursor is.

    **Test steps:**

    * drag with a small picture, then with a null one
    * verify the first is shown unscaled and the second sets no picture
    """
    widget = QWidget()
    qtbot.addWidget(widget)
    drag_class = mocker.patch("rehuco_agent.fields.widgets.image_export.QDrag")
    exporter = ImageExporter(staging, lambda: ID)
    source = PathImageSource([resource / "screenshots" / "a.png"], resource)

    exporter.drag(widget, source, 0, QPixmap(50, 30))
    (shown,) = drag_class.return_value.setPixmap.call_args.args
    assert (shown.width(), shown.height()) == (50, 30)

    drag_class.reset_mock()
    exporter.drag(widget, source, 0, QPixmap())
    drag_class.return_value.setPixmap.assert_not_called()
    drag_class.return_value.exec.assert_called_once()


def test_an_image_that_cannot_be_read_starts_no_drag(
    staging: Path, resource: Path, mocker: MockerFixture, qtbot: QtBot
) -> None:
    """Nothing to hand over, nothing dragged.

    **Test steps:**

    * with ``QDrag`` replaced, drag a missing file
    * verify the answer is no and no drag was built
    """
    widget = QWidget()
    qtbot.addWidget(widget)
    drag_class = mocker.patch("rehuco_agent.fields.widgets.image_export.QDrag")

    assert not ImageExporter(staging, lambda: ID).drag(
        widget, PathImageSource([resource / "gone.png"], resource), 0, QPixmap(10, 10)
    )
    drag_class.assert_not_called()


def test_every_source_reads_the_bytes_as_stored(resource: Path) -> None:
    """A file's bytes from disk, a screenshot row's from its file, a content image's through the archive cache.

    **Test steps:**

    * read through a path source, a screenshot-rows source and an archive source
    * verify the bytes, and nothing for a missing file
    """
    path = resource / "screenshots" / "a.png"
    data = path.read_bytes()
    rows = ScreenshotRowsImageSource([(path, ImageVisibility.VISIBLE)], resource)
    cache = MagicMock(spec=ArchiveCache)
    cache.read.return_value = b"member"
    member = ContentImageEntry(resource / "pack.zip", "a.jpg", 6, 0)

    assert PathImageSource([path], resource).read(0) == data
    assert PathImageSource([resource / "gone.png"], resource).read(0) is None
    assert rows.read(0) == data
    assert ArchiveImageSource([member], cache, resource).read(0) == b"member"
    cache.read.assert_called_once_with(member)
