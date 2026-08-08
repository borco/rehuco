"""What a record describes: the directory it sits in, or the files beside it named after it
([[data-model#resource-scoping]], #250).

One rule, asked in one voice. It used to be spelled -- as ``path.name == INFO_REHU_FILENAME`` -- at every
place that needed it: the content walk, the content-image walk, the rename plan, three job labels and the
agent's tab title. Eight copies agreed on ``info.rehu`` and every one of them was blind to ``info.tc``,
which tc4 wrote per resource *directory* and which is therefore directory-scoped in exactly the same
sense. A catalog opened before conversion got the file-scoped answer everywhere: five tabs all titled
``info.tc``, and a verify that hashed the ``.tc`` file instead of the resource it describes.

**A legacy record is a record.** :data:`RECORD_SUFFIXES` is what makes a file one, so a ``.tc`` found in a
tree is its directory's bookkeeping rather than content, and the ``info.sfv``/``info.checksum``/``infoNN``
siblings it claims are recognized as its -- exactly as they would be after the conversion renames it. A
resource's content set is then the same set before and after it is converted, which is the property that
lets a claim seeded from the old ``.sfv`` (#243) still describe the resource once the ``.rehu`` is there.

Matched exactly rather than case-insensitively, which is what the eight call sites did and what
:mod:`rehuco_core.rehu_rename` needs to keep meaning: a case-folded rule would make ``Info.rehu`` and
``info.rehu`` two spellings of one resource on a share that hands back either.
"""

import os
from pathlib import Path
from typing import Final

from .constants import INFO_REHU_FILENAME, INFO_TC_FILENAME, LEGACY_SUFFIX, REHU_SUFFIX

RECORD_SUFFIXES: Final = (REHU_SUFFIX, LEGACY_SUFFIX)
"""Every extension that makes a file a resource record: the live ``.rehu`` and the legacy ``.tc``.

Not a list of formats this build can *open* -- :mod:`rehuco_core.tc_document` reads a ``.tc`` and only
:mod:`rehuco_core.rehu_document` writes one -- but of names that mean *this file describes a resource*,
which is the question a walk asks when it decides what is content ([[data-model#resource-scoping]])."""

DIRECTORY_SCOPED_FILENAMES: Final = (INFO_REHU_FILENAME, INFO_TC_FILENAME)
"""The record filenames that mean *this record describes its directory* -- the whole of the rule
:func:`is_directory_scoped` applies, in the order the formats arrived."""


def is_directory_scoped(record_path: Path) -> bool:
    """Whether ``record_path`` describes the directory it sits in rather than its same-stem siblings.

    The one predicate every scope-dependent answer reads -- what a walk collects, what a rename moves,
    what a label names -- so none of them can disagree with another about the same file (#250).

    :param record_path: a resource record's path, ``.rehu`` or ``.tc``.
    :returns: whether it is directory-scoped; a named ``foo.rehu``/``foo.tc`` is not.
    """
    return record_path.name in DIRECTORY_SCOPED_FILENAMES


def is_record_name(filename: str) -> bool:
    """Whether ``filename`` names a resource record, of either format.

    Asked of names a listing handed back, so it takes a name rather than a path. Case-insensitive on the
    *suffix* alone, where :func:`is_directory_scoped` is exact throughout: a suffix is a format, and a
    ``.TC`` an old tool wrote describes a resource whatever its casing, while a filename is an identity
    the rename plan has to be able to reproduce.

    :param filename: a file's name, not its path.
    :returns: whether it is a record.
    """
    return os.path.splitext(filename)[1].lower() in RECORD_SUFFIXES


def is_legacy_record_name(filename: str) -> bool:
    """Whether ``filename`` names a legacy tc4 record specifically.

    The narrower half of :func:`is_record_name`, asked where the *format* is what matters rather than
    the fact of a record: a directory holding one still carries tc4's screenshot names, which the
    conversion will rename and the content walk therefore skips (#250).

    :param filename: a file's name, not its path.
    :returns: whether it is a ``.tc``.
    """
    return os.path.splitext(filename)[1].lower() == LEGACY_SUFFIX


def resource_name(record_path: Path) -> str:
    """How a resource is named to a reader -- the directory for a directory-scoped record, else the
    filename.

    The scoping rule applied to a label, shared by every job that carries one
    (:mod:`rehuco_core.checksum_jobs`, :mod:`rehuco_core.tc_import_job`,
    :mod:`rehuco_core.tc_backups_jobs`): every directory-scoped record is called ``info.rehu`` or
    ``info.tc``, so naming the file would give a queue of fifty jobs fifty identical rows.

    :param record_path: the resource's record, ``.rehu`` or ``.tc``.
    :returns: the display name.
    """
    return record_path.parent.name if is_directory_scoped(record_path) else record_path.name
