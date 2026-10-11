"""Zips ``zipfile`` cannot read the central directory of, crafted by hand (#480)."""

# the two packages' tests cannot import each other's helpers, so each keeps this copy
# pylint: disable=duplicate-code

import zipfile
from pathlib import Path

UNSUPPORTED_EXTRACT_VERSION = 70
"""Version 7.0, above the 6.3 :mod:`zipfile` supports."""

CENTRAL_DIRECTORY_SIGNATURE = b"PK\x01\x02"
"""What starts each entry of a zip's central directory."""


def write_encrypted_member_zip(path: Path) -> Path:
    """Write a zip whose central directory flags its one member as encrypted.

    :mod:`zipfile` cannot write an encrypted member, so the flag bit is set in the directory entry afterwards; the
    member's bytes are untouched, which a directory-only read never looks at.

    :param path: the zip.
    :returns: the path.
    """
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("a.jpg", b"picture")
    data = bytearray(path.read_bytes())
    # the entry: signature (4), version made by (2), version needed (2), then the flag bits
    data[data.index(CENTRAL_DIRECTORY_SIGNATURE) + 8] |= 0x1
    path.write_bytes(bytes(data))
    return path


def write_corrupt_directory_zip(path: Path) -> Path:
    """Write a zip whose end-of-central-directory record is intact over a central directory that is not.

    :param path: the zip.
    :returns: the path.
    """
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("a.jpg", b"picture")
    path.write_bytes(path.read_bytes().replace(CENTRAL_DIRECTORY_SIGNATURE, b"PK\x00\x00", 1))
    return path


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
