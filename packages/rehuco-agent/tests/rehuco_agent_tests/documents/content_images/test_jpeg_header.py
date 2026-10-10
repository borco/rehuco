"""Tests for telling a cut-off JPEG slice from one Qt can size (#490)."""

from collections.abc import Iterator

from PySide6.QtCore import QBuffer, QIODevice, QtMsgType, qInstallMessageHandler
from PySide6.QtGui import QImage, QImageWriter
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.content_images import ArchiveCache, ContentImagesModel
from rehuco_agent.documents.content_images import content_images_model as model_module
from rehuco_agent.documents.content_images.archive_cache import HEADER_BYTES
from rehuco_agent.documents.content_images.jpeg_header import jpeg_header_is_cut
from rehuco_agent.fields.widgets.image_source import image_size

from rehuco_agent_tests.documents.content_images.conftest import PACK, REHU_DIRECTORY, entry

SOI = b"\xff\xd8"
SOF0 = b"\xff\xc0\x00\x0b\x08\x00\x10\x00\x20\x01\x01\x11\x00"


def segment(marker: int, payload_size: int) -> bytes:
    """One marker segment: the marker, its length field, and a zeroed payload."""
    return bytes([0xFF, marker]) + (payload_size + 2).to_bytes(2, "big") + bytes(payload_size)


def jpeg(width: int = 32, height: int = 16, app_segments: int = 0) -> bytes:
    """A real JPEG, with ``app_segments`` 40 KB APP1 segments between its SOI and the rest."""
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(0x336699)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert QImageWriter(buffer, b"jpeg").write(image)
    raw = bytes(buffer.data().data())
    return raw[:2] + segment(0xE1, 40_000) * app_segments + raw[2:]


@fixture
def qt_warnings() -> Iterator[list[str]]:
    """Qt's warnings for the test's duration, the way the run log would carry them.

    :returns: the list the warnings land in.
    """
    messages: list[str] = []

    def handler(kind: QtMsgType, _context: object, message: str) -> None:
        if kind == QtMsgType.QtWarningMsg:
            messages.append(message)

    previous = qInstallMessageHandler(handler)
    try:
        yield messages
    finally:
        qInstallMessageHandler(previous)


def jpeg_warnings(messages: list[str]) -> list[str]:
    """The ``qt.gui.imageio.jpeg`` lines among Qt's warnings."""
    return [message for message in messages if "jpeg" in message.lower()]


@mark.parametrize(
    ("head", "cut"),
    [
        (b"\x89PNG\r\n\x1a\n", False),
        (b"", False),
        (SOI, True),
        (SOI + b"\xff", True),
        (SOI + SOF0, False),
        (SOI + segment(0xE0, 14) + SOF0, False),
        (SOI + segment(0xC4, 20) + SOF0, False),
        (SOI + segment(0xE1, 100)[:50], True),
        (SOI + segment(0xE1, 100)[:3], True),
        (SOI + segment(0xE1, 100), True),
        (SOI + b"\xff\xff\xff" + segment(0xE0, 4) + SOF0, False),
        (SOI + b"\xff\x01" + SOF0, False),
        (SOI + b"\xff\xd0\xff\xd9", False),
        (SOI + segment(0xE0, 4) + b"\xff\xda", False),
        (SOI + segment(0xE0, 4) + b"junk", False),
        (SOI + b"\xff\xe0\x00\x00" + SOF0, False),
    ],
)
def test_jpeg_header_is_cut_walks_the_marker_segments(head: bytes, cut: bool) -> None:
    """Only a JPEG whose segments run out before a frame header counts as cut: another format, a frame
    header found, a scan or end marker, or a broken structure (junk where a marker should be, a zero
    length) is not.

    **Test steps:**

    * walk each slice and verify the verdict
    """
    assert jpeg_header_is_cut(head) is cut


def test_a_segment_ending_in_ff_is_not_mistaken_for_a_fill_byte() -> None:
    """A segment whose last payload byte is 0xFF leaves the walk at the next marker.

    **Test steps:**

    * build an APP0 segment ending in 0xFF followed by a frame header
    * verify the walk finds the frame header
    """
    app = b"\xff\xe0\x00\x04\x00\xff"
    assert not jpeg_header_is_cut(SOI + app + SOF0)


def test_a_real_jpeg_with_big_app_segments_is_cut_in_the_leading_slice(qt_warnings: list[str]) -> None:
    """The slice of a JPEG with 80 KB of APP segments stops before its frame header, the whole does not,
    and the slice is the very thing Qt warns about.

    **Test steps:**

    * build a JPEG with two 40 KB APP1 segments
    * verify its first 64 KiB is cut, its whole is not, and a plain JPEG's slice is not
    * verify Qt sizes the whole silently and warns on the slice
    """
    data = jpeg(app_segments=2)
    assert jpeg_header_is_cut(data[:HEADER_BYTES])
    assert not jpeg_header_is_cut(data)
    assert not jpeg_header_is_cut(jpeg()[:HEADER_BYTES])

    assert image_size(data).toTuple() == (32, 16)
    assert not qt_warnings
    assert not image_size(data[:HEADER_BYTES]).isValid()
    assert jpeg_warnings(qt_warnings)


def test_a_cut_jpeg_is_sized_off_the_whole_member_without_a_qt_warning(
    content_model: ContentImagesModel, qtbot: QtBot, mocker: MockerFixture, qt_warnings: list[str]
) -> None:
    """The slice never reaches Qt, so libjpeg has no cut-off datastream to warn about.

    **Test steps:**

    * serve a JPEG with 80 KB of APP segments, its head read cut at 64 KiB
    * request the dimensions
    * verify the size, that Qt sized only the whole member, and that no JPEG warning was logged
    """
    data = jpeg(app_segments=2)
    mocker.patch.object(ArchiveCache, "read_head", return_value=data[:HEADER_BYTES])
    mocker.patch.object(ArchiveCache, "read", return_value=data)
    sized = mocker.spy(model_module, "image_size")
    content_model.set_entries([entry(PACK, "big.jpg")], REHU_DIRECTORY)

    content_model.request_dimensions([0])
    qtbot.waitUntil(lambda: content_model.aspect(0) is not None)

    assert content_model.aspect(0) == 2.0
    sized.assert_called_once_with(data)
    assert not jpeg_warnings(qt_warnings)


def test_a_jpeg_cut_short_on_disk_still_logs_qts_warning_on_its_real_read(
    content_model: ContentImagesModel, qtbot: QtBot, mocker: MockerFixture, qt_warnings: list[str]
) -> None:
    """A file that ends inside its APP segment reads as cut, so the whole member is read -- and that is
    the same bytes, which Qt is left to warn about, once.

    **Test steps:**

    * serve a JPEG truncated inside its first APP segment as both the head and the whole member
    * request the dimensions
    * verify it settles unreadable, that Qt saw only the whole read, and that it warned
    """
    truncated = jpeg(app_segments=1)[:20_000]
    mocker.patch.object(ArchiveCache, "read_head", return_value=truncated)
    mocker.patch.object(ArchiveCache, "read", return_value=truncated)
    sized = mocker.spy(model_module, "image_size")
    content_model.set_entries([entry(PACK, "short.jpg")], REHU_DIRECTORY)

    content_model.request_dimensions([0])
    qtbot.waitUntil(lambda: content_model.dimensions(0) is not None)

    size = content_model.dimensions(0)
    assert size is not None and not size.isValid()
    sized.assert_called_once_with(truncated)
    assert jpeg_warnings(qt_warnings)


def test_a_corrupt_jpeg_whole_in_the_slice_is_qts_to_warn_about(
    content_model: ContentImagesModel, qtbot: QtBot, mocker: MockerFixture, qt_warnings: list[str]
) -> None:
    """A JPEG with junk where its next marker should be is not cut, so the slice goes to Qt as today
    and its warning is not hidden.

    **Test steps:**

    * serve a JPEG whose APP0 segment is followed by junk
    * request the dimensions
    * verify it settles unreadable and that Qt warned on the slice
    """
    corrupt = SOI + segment(0xE0, 14) + b"junk" * 100
    mocker.patch.object(ArchiveCache, "read_head", return_value=corrupt)
    mocker.patch.object(ArchiveCache, "read", return_value=corrupt)
    sized = mocker.spy(model_module, "image_size")
    content_model.set_entries([entry(PACK, "corrupt.jpg")], REHU_DIRECTORY)

    content_model.request_dimensions([0])
    qtbot.waitUntil(lambda: content_model.dimensions(0) is not None)

    size = content_model.dimensions(0)
    assert size is not None and not size.isValid()
    sized.assert_any_call(corrupt)
    assert jpeg_warnings(qt_warnings)
