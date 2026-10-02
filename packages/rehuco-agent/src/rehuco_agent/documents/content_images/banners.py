"""Which boundaries in a content-image sequence get a banner row, and what it says (#221, #392).

A banner is a full-width row and a forced row break, emitted wherever an image's **group** differs from
the previous image's. With *Show banners* off there are none -- one continuous grid. With it on, every
image belongs to the folder it sits in, named the same way whether that folder is on disk or inside an
archive: its path relative to the ``.rehu``'s directory, ``/``-separated on every platform, with a
trailing ``/`` -- the root alone being ``/``:

=====================================  ====================
an image in                            banner
=====================================  ====================
the ``.rehu``'s own folder             ``/``
the loose folder ``foo``               ``foo/``
the root of ``foo.zip``                ``foo.zip/``
the folder ``bar`` inside ``foo.zip``  ``foo.zip/bar/``
``bar`` inside ``baz/foo.zip``         ``baz/foo.zip/bar/``
=====================================  ====================

An archive reads as one more folder level, so the name alone says where an image is, and no two groups
can share one: a folder and an archive in the same directory differ by the archive's extension, and two
siblings cannot share a name on disk. The text is the group's **key** -- what a collapse folds by -- and the
view decorates it with its collapse mark and count as it paints. A pure function over the entries and two
flags, testable without a widget.

**A top folder named like its archive is dropped** (#367), under *Hide a top folder named like its zip*:
``foo.zip`` holding ``foo/bar/*.jpg`` banners as ``foo.zip/bar/``, not ``foo.zip/foo/bar/``. The folder must
match the archive's stem case-insensitively -- the way the scanner pairs a ``.rehu`` with its archive -- and
hold every content image of that archive, so none sits at the archive's root or under a sibling folder:

===========  =================================  =========================
archive      content images                     banner
===========  =================================  =========================
``foo.zip``  ``foo/*.jpg``                      ``foo.zip/``
``foo.zip``  ``foo/bar/*.jpg``                  ``foo.zip/bar/``
``baz.zip``  ``baz/*.jpg`` + ``baz.jpg``        ``baz.zip/baz/`` (kept)
``baz.zip``  ``baz/*.jpg`` + ``other/*.jpg``    ``baz.zip/baz/`` (kept)
``qux.zip``  ``quux/*.jpg``                     ``qux.zip/quux/`` (kept)
===========  =================================  =========================

Since the folder must be the archive's only root item, the stripped ``foo.zip/`` never merges with a real
root group, and banner texts stay unique collapse keys.

The enumeration orders the images so each group is contiguous (:func:`~rehuco_core.enumerate_content_images`:
at every level, a folder's own images before its subfolders and archives); this only names the groups.
"""

from collections.abc import Collection, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from rehuco_core import ContentImageEntry


@dataclass(frozen=True, slots=True)
class ContentDisplayFlags:
    """The two banner boxes on the Images / Display settings page (#221, #392).

    :ivar banners: whether each group starts with a banner naming it.
    :ivar strip_zip_folder: whether a top folder named like its archive is dropped from the banners, with
        banners on (#367).
    """

    banners: bool = True
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


def redundant_top_folders(entries: Sequence[ContentImageEntry]) -> set[Path]:
    """The archives whose content images all sit under one top folder named like the archive (#367).

    :param entries: the content images; loose ones have no archive to strip and are skipped.
    :returns: the archives whose top folder only repeats their name.
    """
    tops: dict[Path, set[str | None]] = {}
    for entry in entries:
        if entry.archive is None:
            continue
        parts = PurePosixPath(entry.name).parts
        tops.setdefault(entry.archive, set()).add(parts[0].lower() if len(parts) > 1 else None)
    return {archive for archive, names in tops.items() if names == {archive.stem.lower()}}


def group_name(entry: ContentImageEntry, rehu_directory: Path, stripped: Collection[Path] = ()) -> str:
    """The folder one content image is grouped under, as its banner spells it (#392).

    :param entry: the image.
    :param rehu_directory: the ``.rehu`` file's directory.
    :param stripped: the archives whose top folder is dropped, from :func:`redundant_top_folders`.
    :returns: ``/`` for the ``.rehu``'s own folder, otherwise the folder's path relative to it -- an
        archive counting as one more level -- with a trailing ``/``.
    """
    folder = PurePosixPath(entry.name).parent.parts
    if entry.archive is None:
        prefix: tuple[str, ...] = ()
    else:
        prefix = PurePosixPath(archive_relative_path(entry.archive, rehu_directory)).parts
        if entry.archive in stripped:
            folder = folder[1:]
    parts = (*prefix, *folder)
    return "/".join(parts) + "/" if parts else "/"


def banner_rows(
    entries: Sequence[ContentImageEntry], rehu_directory: Path, flags: ContentDisplayFlags
) -> Iterator[tuple[int, str]]:
    """Where the banners go: one at each position whose group differs from the previous one's.

    :param entries: the content images, in browse order.
    :param rehu_directory: the ``.rehu`` file's directory.
    :param flags: which boxes are on.
    :returns: ``(index, text)`` pairs -- the banner precedes the entry at ``index``; none with banners off.
    """
    if not flags.banners:
        return
    stripped = redundant_top_folders(entries) if flags.strip_zip_folder else set()
    previous: str | None = None
    for index, entry in enumerate(entries):
        text = group_name(entry, rehu_directory, stripped)
        if text != previous:
            yield index, text
        previous = text


def group_of(
    entries: Sequence[ContentImageEntry], rehu_directory: Path, flags: ContentDisplayFlags
) -> list[str | None]:
    """Which banner group each entry belongs to -- the text of the banner above it, or ``None`` with
    banners off.

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
