"""Removing a file or a folder that carries the read-only attribute (#711).

Windows refuses to unlink a file, or remove a folder, whose read-only attribute is set, with *Access is denied* -- a
``PermissionError`` -- and a folder still holding such a file then refuses as *not empty*. Archives carry the attribute
of what they stored, so whole downloaded folders arrive read-only. A caller entitled to remove the path asks here: a
refused removal of a path that is read-only clears the attribute and is tried once more. What still refuses -- a file
another program holds open, a folder that is not empty -- gets its attribute back, so a refusal leaves the path as it
was, and the second refusal is raised. A path found gone once refused -- removed meanwhile, or a delete-pending file
whose last handle is closing -- is gone, not refused: ``FileNotFoundError``, which a removal asked to accept a missing
path accepts.

POSIX decides an unlink by the parent folder's permissions, not the file's, so there clearing a file's write bit
changes nothing, and the second try raises as the first did, the mode restored.
"""

import stat
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path


def remove_clearing_read_only(path: Path, removal: Callable[[], None]) -> None:
    """Run ``removal`` of ``path``; when it is refused and ``path`` is read-only, make it writable and run it again.

    :param path: the file or folder ``removal`` removes.
    :param removal: the removal itself; its other exceptions pass straight through.
    :raises FileNotFoundError: ``path`` is gone, found so by the removal or once it was refused.
    :raises PermissionError: refused, and ``path`` was writable already, could not be read, or could not be made
        writable -- the refusal itself, chained to what made it final.
    :raises OSError: the second try failed; ``path`` has its old mode back.
    """
    try:
        removal()
        return
    except PermissionError as refusal:
        try:
            mode = path.stat().st_mode
        except FileNotFoundError:
            raise
        except OSError:
            raise refusal from None
        if mode & stat.S_IWRITE:
            raise
        try:
            path.chmod(mode | stat.S_IWRITE)
        except FileNotFoundError:
            raise
        except OSError as error:
            raise refusal from error
    try:
        removal()
    except OSError:
        with suppress(OSError):
            path.chmod(mode)
        raise


def remove_file(path: Path, *, missing_ok: bool = False) -> None:
    """Unlink a file, read-only or not.

    :param path: the file.
    :param missing_ok: whether a file already gone, or gone while it was being removed, is no failure.
    :raises FileNotFoundError: it is gone, and ``missing_ok`` is off.
    :raises OSError: it could not be removed (:func:`remove_clearing_read_only`).
    """
    try:
        remove_clearing_read_only(path, path.unlink)
    except FileNotFoundError:
        if not missing_ok:
            raise


def remove_folder(path: Path) -> None:
    """Remove an empty folder, read-only or not.

    :param path: the folder.
    :raises FileNotFoundError: it is gone.
    :raises OSError: it could not be removed -- it is not empty, among others (:func:`remove_clearing_read_only`).
    """
    remove_clearing_read_only(path, path.rmdir)
