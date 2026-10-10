"""Zips ``zipfile`` cannot read the central directory of, crafted by hand (#480)."""

# the two packages' tests cannot import each other's helpers, so each keeps this copy
# pylint: disable=duplicate-code

import zipfile
from pathlib import Path

UNSUPPORTED_EXTRACT_VERSION = 70
"""Version 7.0, above the 6.3 :mod:`zipfile` supports."""


def write_undecodable_name_zip(path: Path) -> Path:
    """Write a zip whose one member name is flagged UTF-8 and holds bytes that are not UTF-8.

    :param path: the zip.
    :returns: the path.
    """
    # a non-ASCII name makes zipfile write the UTF-8 flag itself
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("\u00e9.jpg", b"picture")
    # two bytes for two, so no offset in the headers moves
    path.write_bytes(path.read_bytes().replace(b"\xc3\xa9", b"\xff\xfe"))
    return path


def write_future_version_zip(path: Path) -> Path:
    """Write a zip whose central directory claims extract version 7.0.

    :param path: the zip.
    :returns: the path.
    """
    info = zipfile.ZipInfo("a.jpg")
    info.extract_version = UNSUPPORTED_EXTRACT_VERSION
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(info, b"picture")
    return path
