"""**``.rehuco`` v1 -> v2**: a root's ``removable`` flag becomes a ``storage`` ([[data-model#local-file-trio]], #378).

A removable root becomes ``"removable"`` and every other ``"local"``; ``removable`` is dropped and every other key
on the root is left as it was. Self-contained: the spellings are frozen *here*, at v2, not imported from the live
vocabulary, so a later change to them never rewrites what this step did.
"""

from typing import Any

VERSION = 2
"""The version this step brings a ``.rehuco`` up to."""

# Frozen at v2 -- this migration's own copy, deliberately not imported from the live vocabulary.
ROOTS_KEY = "roots"
REMOVABLE_KEY = "removable"
STORAGE_KEY = "storage"
LOCAL = "local"
REMOVABLE = "removable"


def upgrade(data: dict[str, Any], _username: str) -> None:
    """Replace every root's ``removable`` flag with a ``storage``, in place.

    A root that is not an object, or a ``roots`` that is not a list, is left for the reader to refuse: a
    migration that raised would hide the file's own, better, error message.

    :param data: the parsed v1 ``.rehuco`` object; mutated in place.
    :param _username: unused -- the file is machine-local and holds nothing per user.
    """
    roots = data.get(ROOTS_KEY)
    if not isinstance(roots, list):
        return
    for root in roots:
        if not isinstance(root, dict):
            continue
        removable = root.pop(REMOVABLE_KEY, False)
        root.setdefault(STORAGE_KEY, REMOVABLE if removable is True else LOCAL)
