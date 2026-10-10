"""What a zip archive is made of, read from its central directory alone (#456).

One read of the directory, no member opened or inflated, so describing a many-thousand-image pack stays as cheap
as listing it. The facts are the ones 7-Zip's properties dialog shows -- how many files, their size unpacked and
packed, the compression method -- plus whether a reader built on :mod:`zipfile` can read the members at all.
"""

import zipfile
from collections.abc import Mapping
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final

from borco_core import shared_read_open

from .rehu_content_images import is_content_image
from .rename_coordination import RenameCoordinator

FLAG_ENCRYPTED: Final = 0x1
"""The general-purpose flag bit a zip sets on an encrypted member."""

READABLE_METHODS: Final = frozenset(
    {
        zipfile.ZIP_STORED,
        zipfile.ZIP_DEFLATED,
        zipfile.ZIP_BZIP2,
        zipfile.ZIP_LZMA,
        zipfile.ZIP_ZSTANDARD,
    }
)
"""The compression methods :mod:`zipfile` can inflate. Anything else (deflate64, implode, shrink, PPMd, ...) fails
a read as ``NotImplementedError``, which the app reports as an unreadable image."""

SLOW_METHODS: Final = frozenset({zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA})
"""The readable methods that are far slower to inflate than deflate, and that a pack would feel."""

METHOD_NAMES: Final = {
    zipfile.ZIP_STORED: "Stored",
    zipfile.ZIP_DEFLATED: "Deflated",
    zipfile.ZIP_BZIP2: "BZip2",
    zipfile.ZIP_LZMA: "LZMA",
    zipfile.ZIP_ZSTANDARD: "Zstandard",
    1: "Shrink",
    6: "Implode",
    9: "Deflate64",
    98: "PPMd",
}
"""What a method is called in the pane; one not here is ``Method N``."""


def method_name(method: int) -> str:
    """A compression method's name.

    :param method: the zip method number.
    :returns: its name, or ``Method N`` for one nothing here knows.
    """
    return METHOD_NAMES.get(method, f"Method {method}")


@dataclass(frozen=True, slots=True)
class ArchiveFacts:
    """What a zip's central directory says it holds.

    :param files: the members, folders not counted.
    :param images: how many of them are content images.
    :param unpacked: the members' size once inflated, in bytes.
    :param packed: the members' size as stored, in bytes.
    :param methods: how many members use each compression method, by method number.
    :param encrypted: how many members are encrypted.
    """

    files: int
    images: int
    unpacked: int
    packed: int
    methods: Mapping[int, int]
    encrypted: int = 0

    @property
    def method_text(self) -> str:
        """The members' compression, as the pane says it: ``Stored``, ``Deflated``, or ``Mixed (2 stored, 1 deflated)``
        for more than one; empty for an archive with no members."""
        if not self.methods:
            return ""
        if len(self.methods) == 1:
            return method_name(next(iter(self.methods)))
        counts = ", ".join(f"{count} {method_name(method).lower()}" for method, count in sorted(self.methods.items()))
        return f"Mixed ({counts})"

    @property
    def slow(self) -> bool:
        """Whether some member uses a method that is far slower to read than deflate."""
        return any(method in SLOW_METHODS for method in self.methods)

    @property
    def unreadable(self) -> bool:
        """Whether some member cannot be read through :mod:`zipfile`: an unsupported method, or encryption."""
        return self.encrypted > 0 or any(method not in READABLE_METHODS for method in self.methods)


def read_archive_facts(
    archive: Path, extensions: tuple[str, ...], coordinator: RenameCoordinator | None = None
) -> ArchiveFacts | None:
    """Describe a zip from its central directory.

    Read inside the coordinator's hold when one is given, so a rename waits for one directory read and never for the
    archive.

    :param archive: the archive file.
    :param extensions: the recognized image extensions, matched case-insensitively.
    :param coordinator: the rename barrier to read inside, or ``None`` for none.
    :returns: the facts; ``None`` when the file is absent, not a zip, truncated or otherwise unreadable.
    """
    wanted = tuple(extension.lower() for extension in extensions)
    hold = coordinator.holding() if coordinator is not None else nullcontext()
    try:
        with hold, shared_read_open(archive) as file, zipfile.ZipFile(file) as opened:
            infolist = opened.infolist()
    except OSError, zipfile.BadZipFile, UnicodeDecodeError, NotImplementedError:
        # UnicodeDecodeError: a member name flagged UTF-8 that is not; NotImplementedError: an extract version above
        # the 6.3 zipfile supports
        return None
    members = [info for info in infolist if not info.is_dir()]
    methods: dict[int, int] = {}
    for info in members:
        methods[info.compress_type] = methods.get(info.compress_type, 0) + 1
    return ArchiveFacts(
        files=len(members),
        images=sum(1 for info in members if is_content_image(PurePosixPath(info.filename), wanted)),
        unpacked=sum(info.file_size for info in members),
        packed=sum(info.compress_size for info in members),
        methods=methods,
        encrypted=sum(1 for info in members if info.flag_bits & FLAG_ENCRYPTED),
    )
