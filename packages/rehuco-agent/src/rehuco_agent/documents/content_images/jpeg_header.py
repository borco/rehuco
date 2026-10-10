"""Telling a JPEG slice that stops before its frame header from one Qt can size (#490).

`member_pixel_size` sizes an image off the first :data:`~.archive_cache.HEADER_BYTES` of it. Handed a JPEG
whose APP segments (a large EXIF block, an embedded thumbnail, an ICC profile) run past that slice, libjpeg
reads the slice's end as the file's and logs a ``qt.gui.imageio.jpeg`` warning per image. Walking the marker
segments first lets the caller read the whole member instead, so Qt only ever warns about a JPEG that is
genuinely broken.
"""

from typing import Final

JPEG_SOI: Final = b"\xff\xd8"

SOF_MARKERS: Final = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
"""The start-of-frame markers, which carry the dimensions; DHT, JPG and DAC share the range but do not."""

STANDALONE_MARKERS: Final = frozenset({0x01, *range(0xD0, 0xD9)})
"""Markers with no length field: TEM, RSTn and SOI."""

END_OF_HEADERS: Final = frozenset({0xD9, 0xDA})
"""EOI and SOS: past either, no frame header will come, so the slice is not merely cut short."""


def jpeg_header_is_cut(head: bytes) -> bool:
    """Whether ``head`` is a JPEG whose frame header lies past its end.

    :param head: the leading bytes of an image.
    :returns: ``True`` only for a JPEG whose marker segments run out of ``head`` before a start-of-frame
        marker; ``False`` for any other format, for a frame header found, and for a JPEG whose structure is
        broken within the slice (Qt is left to say so on the real read).
    """
    if not head.startswith(JPEG_SOI):
        return False
    pos = len(JPEG_SOI)
    while True:
        if pos >= len(head):
            return True
        if head[pos] != 0xFF:  # not at a marker: structure broken, not cut
            return False
        while pos < len(head) and head[pos] == 0xFF:  # fill bytes may pad a marker
            pos += 1
        if pos >= len(head):
            return True
        marker = head[pos]
        pos += 1
        if marker in SOF_MARKERS or marker in END_OF_HEADERS:
            return False
        if marker in STANDALONE_MARKERS:
            continue
        if pos + 2 > len(head):
            return True
        pos += int.from_bytes(head[pos : pos + 2], "big")
