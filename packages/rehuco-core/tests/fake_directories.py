"""Stand-ins for what :func:`os.scandir` returns, shared by the two walks' tests.

The content walk (#226) and the catalog walk (#242) descend the same way and are mocked at the same
seam, so the fake listing entries live here rather than in one of the two test modules -- a helper
module beside the tests, the shape `qt_waits` already sets in the agent's suite.

The filesystem is never touched: both walks are tested against declared trees, so a test says what a
directory holds rather than arranging for one to hold it.
"""

from collections.abc import Iterator
from typing import Final


class FakeDirEntry:
    """A stand-in for :class:`os.DirEntry`, which cannot be constructed outside a real directory read.

    Only the three members the scanners touch: the entry's name, and whether it is a directory or a
    regular file -- answered from how the test declared it, exactly as a real ``DirEntry`` answers from
    what reading the directory returned.
    """

    def __init__(self, name: str, *, directory: bool = False, regular: bool = True, link: bool = False) -> None:
        self.name: Final = name
        self.__directory: Final = directory
        self.__regular: Final = regular
        self.__link: Final = link

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        """Whether the test declared this entry a directory -- through the link only when asked to.

        Mirrors :meth:`os.DirEntry.is_dir`'s contract: a symlink *to* a directory answers ``True`` when
        ``follow_symlinks`` (the default), ``False`` when not -- the distinction the scanners'
        loop guard turns on.
        """
        return self.__directory and (follow_symlinks or not self.__link)

    def is_file(self, *, follow_symlinks: bool = True) -> bool:
        """Whether the test declared this entry a regular file (through the link, per the default)."""
        del follow_symlinks
        return self.__regular


class FakeScandir:
    """What :func:`os.scandir` returns: an iterator that is also a context manager."""

    def __init__(self, entries: list[FakeDirEntry]) -> None:
        self.__entries: Final = entries

    def __enter__(self) -> Iterator[FakeDirEntry]:
        return iter(self.__entries)

    def __exit__(self, *_exception: object) -> None:
        return None
