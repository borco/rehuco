"""How a record moves and where a move is (#339): kept by the move, so a stopped one comes back to its phase.

Split from :mod:`~rehuco_core.move_record_job`, which runs the phases.
"""

from enum import StrEnum
from typing import Final


class MoveMode(StrEnum):
    """How a record gets to its new place."""

    RENAME = "rename"
    """One volume: renamed, verified before and after when the setting for the volume says so."""

    COPY = "copy"
    """Another volume: copied, the copy verified, the original removed only then."""


class MovePhase(StrEnum):
    """Where a move is; kept, so a stopped move comes back to it."""

    SOURCE = "source"
    """The record is checked, and verified when it must be."""

    MOVE = "move"
    """The files are copied, or the record renamed."""

    TARGET = "target"
    """The record is checked where it now is."""

    FINISH = "finish"
    """A copy's original is brought level with it, then stops being a record."""

    CLEANUP = "cleanup"
    """What is left of a copy's original is removed."""

    SPLIT = "split"
    """The buckets a bucketed place went into are settled (#680)."""

    DONE = "done"
    """Nothing is left to do."""


COPYING_PHASES: Final = frozenset({MovePhase.SOURCE, MovePhase.MOVE, MovePhase.TARGET, MovePhase.FINISH})
"""The phases a copy's files can be at the destination while the original is whole: what a cancel takes back. The
source check is one of them for a retried move, which starts over from it with its copy kept."""
