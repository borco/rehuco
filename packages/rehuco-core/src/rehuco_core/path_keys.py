"""How two spellings of a path compare when a name is chosen or a root or catalog file is matched (#629).

**Case folds on every platform**, not only where :func:`os.path.normcase` folds it (Windows): a root file, a root
folder or a renamed resource can land on NTFS, APFS or an SMB share, and each of those calls ``Blender`` and
``blender`` one name. Comparing as the platform does let a Mac plan both as separate root files, the second save
overwriting the first. A case-sensitive Linux disk pays for that with an extra ``(2)`` now and then, never with a
file overwritten.

The fold is :meth:`str.lower`, not :meth:`str.casefold`: it is what ``normcase`` does on Windows for ordinary
letters, so a key there is the one it always was, and ``ß`` stays apart from ``ss``, as those filesystems keep them.

Only what is compared folds. A key is never stored or shown, and a name written keeps the spelling it was given.
Resource keys, relocation and the cache's path keys keep the platform's rule (:class:`~rehuco_core.ResourceKey`):
they compare what the disk reports, not a name about to be written.
"""

from os import path as os_path
from pathlib import Path


def path_key(path: Path | str) -> str:
    """A path as a name is compared: normalized, separators as the platform spells them, case folded everywhere.

    :param path: the path or name, as spelled.
    :returns: the key; two spellings of one name that differ only lexically or in case share it.
    """
    return os_path.normcase(os_path.normpath(str(path))).lower()
