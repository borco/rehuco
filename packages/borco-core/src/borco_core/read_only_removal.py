"""Removing a file or a folder that is read-only, or sits in a read-only folder (#711).

Windows refuses to unlink a file, or remove a folder, whose read-only attribute is set, with *Access is denied* -- a
``PermissionError`` -- and a folder still holding such a file then refuses as *not empty*. POSIX asks the **folder
holding** the path instead: a file in a folder without its write bit is refused, whatever the file's own mode, and so
is a folder there. Archives carry the modes and attributes of what they stored, so whole downloaded folders arrive
read-only either way.

A caller entitled to remove the path asks here. A removal refused is tried once more with the path made writable, and
the folder holding it too when the caller says that folder is its own -- one it removes as well. What still refuses (a
file another program holds open, a folder that is not empty) gets every mode back, so a refusal leaves everything as
it was, and the second refusal is raised. Once the path is gone its folder gets its mode back too: only the path
removed is changed. A path found gone once refused is gone, not refused: ``FileNotFoundError``, which a removal asked
to accept a missing path accepts.
"""

import stat
from collections.abc import Callable, Iterable
from contextlib import suppress
from pathlib import Path
from typing import Final


class LoosenedModes:
    """The paths a refused removal makes writable, with the modes they had, to give back.

    :param path: the path being removed.
    :param places: the paths that may need their write bit to remove it -- the path, and its folder when that is the
        caller's.
    :raises FileNotFoundError: one of them is gone.
    :raises OSError: one of them could not be read.
    """

    def __init__(self, path: Path, places: Iterable[Path]) -> None:
        self.__path: Final = path
        modes = {place: place.stat().st_mode for place in places}
        self.__locked: Final = {place: mode for place, mode in modes.items() if not mode & stat.S_IWRITE}
        self.__loosened: Final[list[Path]] = []

    def __bool__(self) -> bool:
        """Whether any of them lacks its write bit."""
        return bool(self.__locked)

    def loosen(self) -> None:
        """Make each writable; when one cannot be, give back those that were.

        :raises OSError: one could not be made writable.
        """
        try:
            for place, mode in self.__locked.items():
                place.chmod(mode | stat.S_IWRITE)
                self.__loosened.append(place)
        except BaseException:
            self.restore()
            raise

    def restore(self, *, removed: bool = False) -> None:
        """Give back each mode changed, as far as it can be.

        :param removed: whether the path itself is gone, so only its folder is given back.
        """
        for place in self.__loosened:
            if not (removed and place == self.__path):
                with suppress(OSError):
                    place.chmod(self.__locked[place])


def remove_clearing_read_only(path: Path, removal: Callable[[], None], *, parent_is_ours: bool = False) -> None:
    """Run ``removal`` of ``path``; when it is refused, make ``path`` writable -- and its folder, when that is the
    caller's -- and run it again.

    :param path: the file or folder ``removal`` removes.
    :param removal: the removal itself; its other exceptions pass straight through.
    :param parent_is_ours: whether the folder holding ``path`` is the caller's to make writable for the moment of the
        removal -- a folder it removes as well.
    :raises FileNotFoundError: ``path`` is gone, found so by the removal or once it was refused.
    :raises PermissionError: refused, and nothing was read-only or a mode could not be read -- the refusal as it came
        -- or one could not be made writable -- the refusal, chained to why.
    :raises OSError: the second try failed; every mode is given back, as it is for anything else that stops it.
    """
    try:
        removal()
        return
    except PermissionError as refusal:
        try:
            modes = LoosenedModes(path, [path, path.parent] if parent_is_ours else [path])
        except FileNotFoundError:
            raise
        except OSError:
            raise refusal from None
        if not modes:
            raise
        try:
            modes.loosen()
        except FileNotFoundError:
            raise
        except OSError as error:
            raise refusal from error
    try:
        removal()
    except BaseException:
        modes.restore()
        raise
    modes.restore(removed=True)


def remove_file(path: Path, *, missing_ok: bool = False, parent_is_ours: bool = False) -> None:
    """Unlink a file, read-only or not.

    :param path: the file.
    :param missing_ok: whether a file already gone, or gone while it was being removed, is no failure.
    :param parent_is_ours: whether the folder holding it may be made writable for the moment of the removal
        (:func:`remove_clearing_read_only`).
    :raises FileNotFoundError: it is gone, and ``missing_ok`` is off.
    :raises OSError: it could not be removed (:func:`remove_clearing_read_only`).
    """
    try:
        remove_clearing_read_only(path, path.unlink, parent_is_ours=parent_is_ours)
    except FileNotFoundError:
        if not missing_ok:
            raise


def remove_folder(path: Path, *, parent_is_ours: bool = False) -> None:
    """Remove an empty folder, read-only or not.

    :param path: the folder.
    :param parent_is_ours: whether the folder holding it may be made writable for the moment of the removal
        (:func:`remove_clearing_read_only`).
    :raises FileNotFoundError: it is gone.
    :raises OSError: it could not be removed -- it is not empty, among others (:func:`remove_clearing_read_only`).
    """
    remove_clearing_read_only(path, path.rmdir, parent_is_ours=parent_is_ours)
