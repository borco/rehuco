"""Shared fixtures for the Content Images dock tests (#221): encoded images, an archive that serves
them, and the model/view pair over it -- with every read going through a mocked `ArchiveCache`, never
a zip on disk."""

from collections.abc import Callable
from pathlib import Path
from typing import Final

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage, QImageWriter
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.content_images import (
    ArchiveCache,
    ContentDisplayFlags,
    ContentImagesModel,
    ContentImagesView,
)
from rehuco_agent.fields.widgets import ThumbnailLoader
from rehuco_core import ContentImageEntry

REHU_DIRECTORY: Final = Path("/fake/refimages")
PACK: Final = REHU_DIRECTORY / "pack.zip"
OTHER_PACK: Final = REHU_DIRECTORY / "sub" / "other.zip"

WIDE: Final = (200, 100)
TALL: Final = (100, 200)
"""Two proportions, so rows have something to justify."""


def png_bytes(width: int, height: int) -> bytes:
    """A real PNG of ``width`` by ``height``, for the header and decode paths to read.

    :param width: the pixel width.
    :param height: the pixel height.
    :returns: the encoded bytes.
    """
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.darkCyan)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert QImageWriter(buffer, b"png").write(image)
    return bytes(buffer.data().data())


def entry(archive: Path, name: str, size: tuple[int, int] = WIDE) -> ContentImageEntry:
    """A content image whose tier-0 key encodes its proportion, so the fake archive can serve it.

    :param archive: the archive.
    :param name: the member path.
    :param size: the pixel size the member should decode to.
    :returns: the entry, its ``size`` field carrying ``width * 1000 + height``.
    """
    width, height = size
    return ContentImageEntry(archive, name, width * 1000 + height, 0)


@fixture
def archive(mocker: MockerFixture) -> Callable[[ContentImageEntry], bytes | None]:
    """Serve every member as a PNG of the proportion its entry encodes, through the cache's own seam.

    Members whose name starts with ``broken`` read as nothing, the way an offline or re-packed
    archive's do.

    :param mocker: pytest-mock fixture.
    :returns: the reader, for a test to inspect or override.
    """

    def read(entry: ContentImageEntry, *_args: object) -> bytes | None:
        if entry.name.startswith("broken"):
            return None
        return png_bytes(entry.size // 1000, entry.size % 1000)

    mocker.patch.object(ArchiveCache, "read", side_effect=read)
    mocker.patch.object(ArchiveCache, "read_head", side_effect=read)
    return read


@fixture
def content_model(archive: Callable[[ContentImageEntry], bytes | None]) -> ContentImagesModel:
    """A model over the fake archive, empty until a test sets its entries.

    :param archive: the fake archive, already in place.
    :returns: the model.
    """
    del archive
    return ContentImagesModel()


@fixture
def loader() -> ThumbnailLoader:
    """A thumbnail loader on the global pool."""
    return ThumbnailLoader()


@fixture
def view(qtbot: QtBot, content_model: ContentImagesModel, loader: ThumbnailLoader) -> ContentImagesView:
    """A shown 1000 px wide view over ``content_model``, clamped to ``[100, 200]`` with no banners --
    a test that wants banners turns them on.

    :param qtbot: pytest-qt fixture.
    :param content_model: the model.
    :param loader: the loader.
    :returns: the view, shown and laid out.
    """
    built = ContentImagesView(
        content_model, loader, min_height=100, max_height=200, flags=ContentDisplayFlags(False, False)
    )
    qtbot.addWidget(built)
    built.resize(1000, 400)
    built.show()
    qtbot.waitExposed(built)
    return built
