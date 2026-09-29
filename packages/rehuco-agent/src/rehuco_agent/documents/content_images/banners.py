"""Which boundaries in a content-image sequence get a banner row, and what it says (#221).

A banner is a full-width row and a forced row break, emitted wherever the **displayed key** changes.
Two settings decide what the key is -- the archive's path relative to the ``.rehu``'s directory, the
member's folder inside it, both, or neither:

====  =======  ======================================
zip   folders  banner at a boundary
====  =======  ======================================
off   off      none -- one continuous grid
on    off      ``dir1/zip1.zip`` at each archive start
off   on       ``/path1/path2`` at each folder change
on    on       ``dir1/zip1.zip:/path1/path2`` at each folder change
====  =======  ======================================

One combined banner, never two stacked. Root-level members banner as ``dir1/zip1.zip:/`` (or ``/``)
so a root batch is never read as the previous group's tail. Paths use ``/`` on every platform, with no
trailing slash. A pure function over ``(archive relative path, folder, flags)``, testable without a
widget. The text is the group's **key**; the view decorates it with its collapse mark and count as it
paints.

With both boxes on, a third drops a top folder that only repeats its archive's name (#367): ``foo.zip``
holding ``foo/bar/*.jpg`` banners as ``foo.zip:/bar``, not ``foo.zip:/foo/bar``. The folder must match
the archive's stem case-insensitively -- the way the scanner pairs a ``.rehu`` with its archive -- and
hold every content image of that archive, so none sits loose at the root or under a sibling folder:

===========  =================================  ============================
archive      content images                     banner (zip + folders)
===========  =================================  ============================
``foo.zip``  ``foo/*.jpg``                      ``foo.zip:/``
``foo.zip``  ``foo/bar/*.jpg``                  ``foo.zip:/bar``
``baz.zip``  ``baz/*.jpg`` + ``baz.jpg``        ``baz.zip:/baz`` (unchanged)
``baz.zip``  ``baz/*.jpg`` + ``other/*.jpg``    ``baz.zip:/baz`` (unchanged)
``qux.zip``  ``quux/*.jpg``                     ``qux.zip:/quux`` (unchanged)
===========  =================================  ============================

Since the folder must be the archive's only root item, the stripped ``/`` never merges with a real root
group, and banner texts stay unique collapse keys. Folders-only mode keeps the prefix: there the top
folder is the only hint of which pack a group belongs to.
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
    :ivar strip_zip_folder: whether a top folder named like its archive is dropped from the banner,
        with both other boxes on (#367).
    """

    zip_names: bool = True
    folder_names: bool = False
    strip_zip_folder: bool = True


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


def redundant_top_folders(entries: Sequence[ContentImageEntry]) -> set[Path]:
    """The archives whose content images all sit under one top folder named like the archive (#367).

    :param entries: the content images.
    :returns: the archives whose top folder only repeats their name.
    """
    tops: dict[Path, set[str | None]] = {}
    for entry in entries:
        parts = PurePosixPath(entry.name).parts
        tops.setdefault(entry.archive, set()).add(parts[0].lower() if len(parts) > 1 else None)
    return {archive for archive, names in tops.items() if names == {archive.stem.lower()}}


def strip_top_folder(folder: str) -> str:
    """``folder`` without its first component: ``/foo/bar`` becomes ``/bar``, ``/foo`` becomes ``/``.

    :param folder: the member folder, as :func:`member_folder` spells it, below a top folder.
    :returns: the folder relative to that top folder.
    """
    _, _, rest = folder[1:].partition("/")
    return f"/{rest}"


def banner_text(archive_relative: str, folder: str, flags: ContentDisplayFlags) -> str | None:
    """The banner for a group, or ``None`` when neither box is on.

    :param archive_relative: the archive's path relative to the ``.rehu``'s directory.
    :param folder: the member folder, as :func:`member_folder` spells it.
    :param flags: which boxes are on.
    :returns: the text.
    """
    match (flags.zip_names, flags.folder_names):
        case (True, True):
            return f"{archive_relative}:{folder}"
        case (True, False):
            return archive_relative
        case (False, True):
            return folder
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
    stripped = (
        redundant_top_folders(entries) if flags.zip_names and flags.folder_names and flags.strip_zip_folder else set()
    )
    previous: str | None = None
    for index, entry in enumerate(entries):
        folder = member_folder(entry.name)
        if entry.archive in stripped:
            folder = strip_top_folder(folder)
        text = banner_text(archive_relative_path(entry.archive, rehu_directory), folder, flags)
        if text is not None and text != previous:
            yield index, text
        previous = text


def group_of(
    entries: Sequence[ContentImageEntry], rehu_directory: Path, flags: ContentDisplayFlags
) -> list[str | None]:
    """Which banner group each entry belongs to -- the text of the banner above it, or ``None`` with
    both boxes off.

    :param entries: the content images, in browse order.
    :param rehu_directory: the ``.rehu`` file's directory.
    :param flags: which boxes are on.
    :returns: one group per entry, in order.
    """
    groups: list[str | None] = []
    current: str | None = None
    banners = dict(banner_rows(entries, rehu_directory, flags))
    for index in range(len(entries)):
        current = banners.get(index, current)
        groups.append(current)
    return groups
