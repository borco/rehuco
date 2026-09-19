"""Which boundaries in a content-image sequence get a banner row, and what it says (#221).

A banner is a full-width row and a forced row break, emitted wherever the **displayed key** changes.
Two settings decide what the key is -- the archive's path relative to the ``.rehu``'s directory, the
member's folder inside it, both, or neither:

====  =======  ======================================
zip   folders  banner at a boundary
====  =======  ======================================
off   off      none -- one continuous grid
on    off      ``[dir1/zip1.zip]`` at each archive start
off   on       ``[/path1/path2]`` at each folder change
on    on       ``[dir1/zip1.zip:/path1/path2]`` at each folder change
====  =======  ======================================

One combined banner, never two stacked. Root-level members banner as ``[dir1/zip1.zip:/]`` (or ``[/]``)
so a root batch is never read as the previous group's tail. Paths use ``/`` on every platform, with no
trailing slash. A pure function over ``(archive relative path, folder, flags)``, testable without a
widget.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from rehuco_core import ContentImageEntry


@dataclass(frozen=True, slots=True)
class ContentDisplayFlags:
    """The two banner boxes on the Images / Display settings page (#221).

    :ivar zip_names: whether each archive's start is bannered with its name.
    :ivar folder_names: whether each folder change inside an archive is bannered.
    """

    zip_names: bool = True
    folder_names: bool = False


def archive_relative_path(archive: Path, rehu_directory: Path) -> str:
    """``archive`` relative to the resource's directory, ``/``-separated.

    :param archive: the archive path.
    :param rehu_directory: the ``.rehu`` file's directory.
    :returns: the relative path, or the archive's name when it is not under that directory.
    """
    try:
        return archive.relative_to(rehu_directory).as_posix()
    except ValueError:
        return archive.name


def member_folder(name: str) -> str:
    """The folder part of a member path, as the banner shows it: ``/`` for the root, otherwise
    ``/path1/path2`` with no trailing slash.

    :param name: the member's path inside the archive, as the zip stores it.
    :returns: the folder.
    """
    parent = PurePosixPath(name).parent.as_posix()
    return "/" if parent == "." else f"/{parent}"


def banner_text(archive_relative: str, folder: str, flags: ContentDisplayFlags) -> str | None:
    """The banner for a group, or ``None`` when neither box is on.

    :param archive_relative: the archive's path relative to the ``.rehu``'s directory.
    :param folder: the member folder, as :func:`member_folder` spells it.
    :param flags: which boxes are on.
    :returns: the text, brackets included.
    """
    match (flags.zip_names, flags.folder_names):
        case (True, True):
            return f"[{archive_relative}:{folder}]"
        case (True, False):
            return f"[{archive_relative}]"
        case (False, True):
            return f"[{folder}]"
        case _:
            return None


def banner_rows(
    entries: Sequence[ContentImageEntry], rehu_directory: Path, flags: ContentDisplayFlags
) -> Iterator[tuple[int, str]]:
    """Where the banners go: one at each position whose displayed key differs from the previous one's.

    :param entries: the content images, in browse order.
    :param rehu_directory: the ``.rehu`` file's directory.
    :param flags: which boxes are on.
    :returns: ``(index, text)`` pairs -- the banner precedes the entry at ``index``.
    """
    previous: str | None = None
    for index, entry in enumerate(entries):
        text = banner_text(archive_relative_path(entry.archive, rehu_directory), member_folder(entry.name), flags)
        if text is not None and text != previous:
            yield index, text
        previous = text
