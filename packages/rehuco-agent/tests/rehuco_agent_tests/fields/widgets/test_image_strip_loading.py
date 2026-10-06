"""Tests for how ImageStrip gets its pictures: decoded in the background into the app's pixmap cache, never on
the GUI thread while the strip is built (#381).

Real files and the real `ThumbnailLoader`, unlike ``test_image_strip.py``, whose stand-in loader answers every
request at once.
"""

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from PySide6.QtGui import QColor, QImage, QPixmap, QPixmapCache
from PySide6.QtWidgets import QHBoxLayout, QWidget
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets import image_strip
from rehuco_agent.fields.widgets.image_strip import ImageStrip, ThumbnailLabel

STRIP_HEIGHT = 20
RED = "#E53935"
BLUE = "#1E88E5"


@fixture(name="folder")
def fixture_folder() -> Iterator[Path]:
    """A folder of its own for the screenshots, removed when the test ends.

    :yields: the folder.
    """
    with tempfile.TemporaryDirectory() as base:
        yield Path(base)


@fixture(autouse=True)
def empty_cache() -> Iterator[None]:
    """Start and end every test with nothing cached, so a picture is only ever there because this test put it."""
    QPixmapCache.clear()
    yield
    QPixmapCache.clear()


def write_picture(path: Path, colour: str) -> Path:
    """Write a small flat-coloured PNG, twice as wide as it is tall.

    :param path: where to write it.
    :param colour: its one colour.
    :returns: the path.
    """
    image = QImage(40, 20, QImage.Format.Format_RGB32)
    image.fill(QColor(colour))
    assert image.save(str(path))
    return path


def thumbnails(strip: ImageStrip) -> list[ThumbnailLabel]:
    """The strip's thumbnails, in row order.

    :param strip: the strip.
    :returns: its labels.
    """
    content = strip.widget()
    assert isinstance(content, QWidget)
    layout = content.layout()
    assert isinstance(layout, QHBoxLayout)
    labels = []
    for index in range(layout.count()):
        item = layout.itemAt(index)
        widget = item.widget() if item is not None else None
        if isinstance(widget, ThumbnailLabel):
            labels.append(widget)
    return labels


def colour_of(label: ThumbnailLabel) -> str:
    """The colour in the middle of a thumbnail's picture.

    :param label: the thumbnail.
    :returns: the colour's name, ``#rrggbb``.
    """
    image = label.pixmap().toImage()
    return image.pixelColor(image.width() // 2, image.height() // 2).name().upper()


def no_decoding_here(mocker: MockerFixture) -> Any:
    """Make building a pixmap from a file on the GUI thread fail the test, while every other pixmap is real.

    :param mocker: pytest-mock fixture.
    :returns: the patched constructor.
    """

    def pixmap(*args: object) -> QPixmap:
        assert not any(isinstance(arg, str) for arg in args), "the strip decoded a file on the GUI thread"
        return QPixmap(*args)  # type: ignore[call-overload]

    return mocker.patch.object(image_strip, "QPixmap", side_effect=pixmap)


def test_a_strip_holds_each_place_at_once_and_paints_it_when_it_is_decoded(
    mocker: MockerFixture, qtbot: QtBot, folder: Path
) -> None:
    """Building the row decodes nothing: every thumbnail holds its place, and its picture lands later.

    **Test steps:**

    * write two screenshots, forbid decoding a file into a pixmap on the GUI thread, and set them on a strip
    * verify both places are there at once, reported as the strip's set
    * wait, and verify each painted its own picture at the strip's height
    """
    no_decoding_here(mocker)
    paths = [write_picture(folder / "info00.png", RED), write_picture(folder / "info01.png", BLUE)]
    strip = ImageStrip(height=STRIP_HEIGHT)
    qtbot.addWidget(strip)
    reported: list[list[Path]] = []
    strip.images_changed.connect(reported.append)

    strip.set_images(paths)

    assert len(thumbnails(strip)) == 2
    assert reported == [paths]
    qtbot.waitUntil(lambda: [colour_of(label) for label in thumbnails(strip)] == [RED, BLUE])
    assert all(label.pixmap().height() == STRIP_HEIGHT for label in thumbnails(strip))


def test_a_file_that_will_not_decode_leaves_the_row_and_the_set(qtbot: QtBot, folder: Path) -> None:
    """A screenshot that turns out not to decode is taken back off the row, and the set is reported again
    without it -- a viewer following the strip navigates only what can be shown.

    **Test steps:**

    * write one screenshot and one file of garbage, and set both on a strip
    * wait for the garbage to be taken off
    * verify one thumbnail is left and the last report names only the good file
    """
    good = write_picture(folder / "info00.png", RED)
    broken = folder / "info01.png"
    broken.write_bytes(b"not a picture")
    strip = ImageStrip(height=STRIP_HEIGHT)
    qtbot.addWidget(strip)
    reported: list[list[Path]] = []
    strip.images_changed.connect(reported.append)

    strip.set_images([good, broken])

    qtbot.waitUntil(lambda: len(thumbnails(strip)) == 1)
    assert reported[-1] == [good]
    qtbot.waitUntil(lambda: colour_of(thumbnails(strip)[0]) == RED)


def test_a_strip_built_again_paints_from_the_cache_at_once(qtbot: QtBot, folder: Path) -> None:
    """A resource shown again -- the preview coming back to it -- paints its pictures straight from the cache.

    **Test steps:**

    * set two screenshots on one strip and wait for them to land
    * build a second strip over the same files
    * verify its pictures are there without waiting
    """
    paths = [write_picture(folder / "info00.png", RED), write_picture(folder / "info01.png", BLUE)]
    first = ImageStrip(height=STRIP_HEIGHT)
    qtbot.addWidget(first)
    first.set_images(paths)
    qtbot.waitUntil(lambda: [colour_of(label) for label in thumbnails(first)] == [RED, BLUE])

    second = ImageStrip(height=STRIP_HEIGHT)
    qtbot.addWidget(second)
    second.set_images(paths)

    assert [colour_of(label) for label in thumbnails(second)] == [RED, BLUE]


def test_a_rearrangement_never_paints_a_neighbours_cached_picture(qtbot: QtBot, folder: Path) -> None:
    """A screenshot's name is its place, so a rearrangement swaps the files under two names. Pictures are cached
    by the file, not its name, so each name then shows the file it now holds.

    **Test steps:**

    * set two screenshots on a strip and wait for them to land
    * swap the two files' names on disk, as a move does, and rebuild the strip
    * verify each place now shows the other picture
    """
    first, second = write_picture(folder / "info00.png", RED), write_picture(folder / "info01.png", BLUE)
    strip = ImageStrip(height=STRIP_HEIGHT)
    qtbot.addWidget(strip)
    strip.set_images([first, second])
    qtbot.waitUntil(lambda: [colour_of(label) for label in thumbnails(strip)] == [RED, BLUE])

    parked = folder / "parked.png"
    os.replace(first, parked)
    os.replace(second, first)
    os.replace(parked, second)
    strip.set_images([first, second])

    qtbot.waitUntil(lambda: [colour_of(label) for label in thumbnails(strip)] == [BLUE, RED])


def test_a_picture_landing_after_a_rebuild_paints_nothing_it_no_longer_holds(qtbot: QtBot, folder: Path) -> None:
    """A rebuild withdraws what the row no longer holds; a picture another strip asked for lands without
    touching this one.

    **Test steps:**

    * set a screenshot on a strip, then at once set nothing
    * have another strip ask for the same picture, and wait for it to land there
    * verify the first strip is still empty
    """
    path = write_picture(folder / "info00.png", RED)
    strip = ImageStrip(height=STRIP_HEIGHT)
    qtbot.addWidget(strip)
    strip.set_images([path])
    strip.set_images([])
    other = ImageStrip(height=STRIP_HEIGHT)
    qtbot.addWidget(other)

    other.set_images([path])

    qtbot.waitUntil(lambda: colour_of(thumbnails(other)[0]) == RED)
    assert not thumbnails(strip)
