"""What a walk may enter, and what it may take as a record -- one answer for every walk (#498).

**A link is never entered, whatever kind.** A directory symlink pointing at an ancestor would loop a walk forever,
and one pointing sideways would reach the same files under a second name -- the same resources swept twice, the same
content counted twice, the same record cataloged twice. A Windows **junction** is the same hazard under another
name, but :meth:`os.DirEntry.is_dir` with ``follow_symlinks=False`` answers ``True`` for one, since only a reparse
point tagged as a symlink counts as a link there, so each walk asking that alone used to descend junctions. The four
walks (the catalog's, the content walk, the conversion plan, the file-kinds listing) ask here instead, so they cannot
drift apart again.

**A record is a plain file**: a symlink to a ``.rehu`` would catalog its target a second time whenever the target is
under a root too. Content files are another matter -- reading through a link is harmless -- and the content walk
keeps following them.
"""

import os


def is_walkable_directory(entry: os.DirEntry[str]) -> bool:
    """Whether a walk may descend into an entry: a real directory, neither a symlink nor a junction.

    :param entry: a listing's entry.
    :returns: whether it is a directory to enter.
    """
    return entry.is_dir(follow_symlinks=False) and not entry.is_junction()


def is_plain_file(entry: os.DirEntry[str]) -> bool:
    """Whether an entry is a regular file in its own right, not a link to one -- what a record must be.

    :param entry: a listing's entry.
    :returns: whether it is a file, not followed through a link.
    """
    return entry.is_file(follow_symlinks=False)
