"""Tests for the file-backed image source and the decode helpers behind every source (#221)."""

import io
from pathlib import Path
from typing import Final

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice, QSize, Qt
from PySide6.QtGui import QImage, QImageReader, QImageWriter
from pytest_mock import MockerFixture
from rehuco_agent.fields.widgets.image_source import (
    PathImageSource,
    decode_image,
    image_size,
    image_size_at,
    reading_buffer,
)

PATH: Final = Path("/fake/info00.png")

EXIF_ORIENTATION: Final = 0x0112
EXIF_ROTATE_90_CW: Final = 6
"""The EXIF orientation tag and the value a camera held sideways writes into it."""


def png_bytes(width: int, height: int) -> bytes:
    """A real PNG of ``width`` by ``height``.

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


def test_decode_image_scales_down_during_the_decode_and_never_up() -> None:
    """A height cap decodes a smaller image; a cap above the image's height leaves it as is; no cap
    decodes it whole.

    **Test steps:**

    * decode a 200 by 100 PNG under a 50 px cap, a 500 px cap, and none
    * verify the three sizes
    """
    data = png_bytes(200, 100)

    assert decode_image(data, 50).size().toTuple() == (100, 50)
    assert decode_image(data, 500).size().toTuple() == (200, 100)
    assert decode_image(data, None).size().toTuple() == (200, 100)


def test_a_capped_decode_oversamples_in_the_reader_and_finishes_smoothly(mocker: MockerFixture) -> None:
    """The reader is asked for twice the target (or the whole image when that is smaller) and the last
    step is a smooth scale -- never the reader's coarse resample straight to the target.

    **Test steps:**

    * spy on the reader's scaled size and decode a 400 by 200 PNG capped at 50 px
    * verify the reader was asked for 100 px and the result is 50 px
    * cap a 200 by 100 PNG at 80 px and verify the reader was asked for its whole 100 px
    """
    asked: list[QSize] = []
    original = QImageReader.setScaledSize

    def record(reader: QImageReader, size: QSize) -> None:
        asked.append(size)
        original(reader, size)

    # a wrapper, not `mocker.spy`: spying a Shiboken descriptor loses the bound instance
    mocker.patch.object(QImageReader, "setScaledSize", record)

    assert decode_image(png_bytes(400, 200), 50).size().toTuple() == (100, 50)
    assert asked[-1] == QSize(200, 100)

    assert decode_image(png_bytes(200, 100), 80).size().toTuple() == (160, 80)
    assert asked[-1] == QSize(200, 100)


def test_undecodable_bytes_decode_to_a_null_image_and_no_size() -> None:
    """Bytes that are not an image decode to nothing and report an invalid size, rather than raising.

    **Test steps:**

    * decode and size a few junk bytes
    """
    assert decode_image(b"not an image", None).isNull()
    assert not image_size(b"not an image").isValid()


def test_image_size_reads_the_header_off_a_leading_slice() -> None:
    """The pixel size comes off the header alone: the first few dozen bytes of a PNG are enough.

    **Test steps:**

    * size the first 64 bytes of a 200 by 100 PNG
    """
    assert image_size(png_bytes(200, 100)[:64]).toTuple() == (200, 100)


def exif_rotated_jpeg(width: int, height: int) -> bytes:
    """A JPEG stored ``width`` by ``height`` whose EXIF orientation turns it a quarter turn on show --
    what a camera held sideways writes.

    :param width: the stored pixel width.
    :param height: the stored pixel height.
    :returns: the encoded bytes.
    """
    exif = Image.Exif()
    exif[EXIF_ORIENTATION] = EXIF_ROTATE_90_CW
    out = io.BytesIO()
    Image.new("RGB", (width, height), "red").save(out, "JPEG", exif=exif.tobytes())
    return out.getvalue()


def test_image_size_is_the_shown_size_under_an_exif_orientation() -> None:
    """A sideways-shot photo is sized as it will be shown -- portrait -- not as it is stored, so the
    grid packs the cell the thumbnail actually fills. Regression: every cell of a portrait pack was
    packed landscape and its thumbnail stretched into it.

    **Test steps:**

    * size a 300 by 200 JPEG carrying a 90 degree orientation, whole and off its header slice
    * verify both read 200 by 300, and that the decode agrees
    """
    data = exif_rotated_jpeg(300, 200)

    assert image_size(data).toTuple() == (200, 300)
    assert image_size(data[:4096]).toTuple() == (200, 300)
    assert decode_image(data, None).size().toTuple() == (200, 300)
    assert decode_image(data, 30).size().toTuple() == (20, 30)


def test_image_size_at_reads_the_header_off_the_path(mocker: MockerFixture) -> None:
    """The path-based size opens `QImageReader` straight on the path -- never loading the whole file
    into memory first, unlike :func:`image_size` -- and reads the same header off it (#321).

    **Test steps:**

    * redirect the reader's construction to a buffer over a real PNG's bytes, keyed by the given path
    * size the path and verify it matches the PNG's real size
    """
    # the buffer is held by this closure for the whole test: a `QImageReader` keeps only a raw
    # pointer to its device, and a buffer built and handed over in the same expression is freed by
    # Python the moment that expression returns, before the reader ever reads from it
    buffer = reading_buffer(png_bytes(200, 100))
    real_reader = QImageReader

    def reader_for_path(name: str) -> QImageReader:
        assert name == str(PATH)
        return real_reader(buffer)

    mocker.patch("rehuco_agent.fields.widgets.image_source.QImageReader", side_effect=reader_for_path)

    assert image_size_at(PATH).toTuple() == (200, 100)


def test_a_path_source_reads_and_decodes_the_file(mocker: MockerFixture) -> None:
    """The file-backed source keys by path, names by file name, and decodes the file's bytes.

    **Test steps:**

    * make the path read as a PNG and load it capped and whole
    * verify the key, the name and both sizes
    """
    mocker.patch.object(Path, "read_bytes", return_value=png_bytes(200, 100))
    source = PathImageSource([PATH])

    assert len(source) == 1
    assert source.key(0) == PATH
    assert source.name(0) == "info00.png"
    assert source.load(0, 50).size().toTuple() == (100, 50)
    assert source.load(0, None).size().toTuple() == (200, 100)


def test_a_path_source_names_a_file_relative_to_its_base(mocker: MockerFixture) -> None:
    """The description names a file relative to the base directory when it has one and the file is
    under it -- the ``.rehu``'s directory, so a screenshot reads like an archive member -- and in full
    otherwise (#221).

    **Test steps:**

    * describe a file under the base, one outside it, and one with no base
    * verify the relative, the full and the full form respectively, and the stat'ed size
    """
    mocker.patch.object(Path, "stat", return_value=mocker.Mock(st_size=42))
    under = Path("/fake/resource/shots/info00.png")
    outside = Path("/elsewhere/info00.png")

    with_base = PathImageSource([under, outside], Path("/fake/resource"))
    assert with_base.describe(0).path_text == "shots/info00.png"
    assert with_base.describe(0).byte_size == 42
    assert with_base.describe(1).path_text == str(outside)
    assert PathImageSource([under]).describe(0).path_text == str(under)


def test_a_path_source_reads_its_pixel_size_off_the_header_apart_from_describing(mocker: MockerFixture) -> None:
    """The pixel size is a header read of its own, never part of the description: a description is
    asked for on every hover and every step, and must stay free of I/O beyond a stat (#321).

    **Test steps:**

    * make the header read answer a size and describe the file
    * verify describing never touched the header, and asking for the size did
    """
    header = mocker.patch("rehuco_agent.fields.widgets.image_source.image_size_at", return_value=QSize(200, 100))
    mocker.patch.object(Path, "stat", return_value=mocker.Mock(st_size=42))
    source = PathImageSource([PATH])

    source.describe(0)
    header.assert_not_called()

    assert source.pixel_size(0).toTuple() == (200, 100)
    header.assert_called_once_with(PATH)


def test_a_path_source_yields_a_null_image_for_an_unreadable_file(mocker: MockerFixture) -> None:
    """A file that cannot be read -- an offline mount -- decodes to a null image rather than raising.

    **Test steps:**

    * make the read fail and load
    """
    mocker.patch.object(Path, "read_bytes", side_effect=OSError("offline"))

    assert PathImageSource([PATH]).load(0, None).isNull()
