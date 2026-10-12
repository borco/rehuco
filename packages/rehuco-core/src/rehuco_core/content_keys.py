"""How a record names one of its own content files ([[field-schema#watch-progress]], #410).

The per-file maps a record keeps -- the shared ``videos`` lengths and each user's ``progress`` -- are
keyed by **paths relative to the record**, POSIX-separated, so that moving the resource as a whole keeps
every key. For a directory-scoped ``info.rehu`` the key is the path under its directory. A standalone
``<stem>.rehu`` describes **one** media file -- a resource of several files is a folder with its own
``info.rehu`` -- and keys it by its name **with the stem removed** (``foo.mp4`` → ``.mp4``), so renaming the
stem ([[plugins#tutorial-plugin]]'s path row) keeps the key too.

Which files are content at all is :mod:`rehuco_core.rehu_content_files`'s question; this module only names
them.
"""

import os
from pathlib import Path

from .resource_scoping import is_directory_scoped


def content_key(rehu_path: Path, file_path: Path) -> str:
    """Name ``file_path`` the way ``rehu_path``'s per-file maps key it.

    :param rehu_path: the resource's record.
    :param file_path: one of its content files, as :func:`~rehuco_core.rehu_content_files.enumerate_content_files`
        lists them -- under the record's directory, and for a standalone record a sibling sharing its
        stem (matched case-insensitively, as the walk matches it).
    :returns: the key: the POSIX path under the record's directory, or for a standalone record the file
        name with the stem removed, its remainder spelled as on disk.
    :raises ValueError: ``file_path`` is not content of ``rehu_path`` by that rule.
    """
    relative = file_path.relative_to(rehu_path.parent).as_posix()
    if is_directory_scoped(rehu_path):
        return relative
    # the walk's own test (`ContentFileScanner.__scan_siblings`): the name up to its last dot is the stem, whole
    stem = rehu_path.stem
    if "/" in relative or os.path.splitext(relative)[0].lower() != stem.lower() or len(relative) == len(stem):
        raise ValueError(f"{file_path} is not content of {rehu_path}.")
    return relative[len(stem) :]


def content_path(rehu_path: Path, key: str) -> Path:
    """The file a per-file key names: :func:`content_key`'s inverse.

    A key comes off disk, written by another build, another node or a hand edit, so it is validated
    before it is resolved -- the same rule a checksum entry's name is held to
    (:func:`~rehuco_core.checksum_record.checksum_entry_name`): a key that could reach outside the
    resource is refused, never resolved.

    :param rehu_path: the resource's record.
    :param key: a key from ``videos`` or ``progress``.
    :returns: the file's path. For a standalone record, the record's own stem as spelled now plus the key.
    :raises ValueError: ``key`` is not a valid key -- empty, absolute, escaping (``..``), not POSIX-plain
        (``\\`` or a drive colon), or, for a standalone record, holding a directory.
    """
    if not is_valid_content_key(rehu_path, key):
        raise ValueError(f"Not a content key of {rehu_path}: {key!r}")
    if is_directory_scoped(rehu_path):
        return rehu_path.parent.joinpath(*key.split("/"))
    return rehu_path.parent / f"{rehu_path.stem}{key}"


def is_valid_content_key(rehu_path: Path, key: object) -> bool:
    """Whether ``key`` can name a content file of ``rehu_path`` (:func:`content_path`'s rule).

    :param rehu_path: the resource's record; its scope decides whether a key may hold a directory.
    :param key: a candidate key, of any shape.
    :returns: whether it is a non-empty string naming a file inside the resource; for a standalone record, an
        extension (``.mp4``), the only remainder its one same-stem file can leave.
    """
    if not isinstance(key, str) or not key:
        return False
    if not is_directory_scoped(rehu_path):
        return key.startswith(".") and key.count(".") == 1 and not any(char in key for char in "/\\:")
    return not any(part in ("", ".", "..") or "\\" in part or ":" in part for part in key.split("/"))
