"""What the file browser says about one user's watching: a percentage on each video and each folder (#316,
[[field-schema#watch-progress]], [[plugins#files-subdock]]).

Pure: the sums are core's (:func:`~rehuco_core.watch_totals`), derived at the moment they are drawn and never stored,
and this module only turns them into the words a row ends with.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Final

from rehuco_core import ProgressEntry, VideoFacts, WatchTotals, watch_totals

UNOPENED_TOOLTIP: Final = "Not opened yet."
"""What a video never played says on hover: nothing is drawn after its name, and this says why."""

UNMEASURED_FILE_TOOLTIP: Final = (
    "This video's length is not known yet, so there is no percentage: playing it records it, and so does Compute in "
    "the main editor."
)
"""What a video that has a position but no length says on hover."""

UNMEASURED_FOLDER_TOOLTIP: Final = "Some videos here have no known length, so there is no percentage."
"""What a folder holding a video of unknown length says on hover (#316): a share of a total that is not known would be
a wrong number, so none is drawn."""

MISSING_TOOLTIP: Final = "This file is gone; its progress is kept until you forget it."
"""What a missing video's row says on hover ([[field-schema#watch-progress]])."""


@dataclass(frozen=True, slots=True)
class RowProgress:
    """What a row ends with.

    :param text: the percentage, ``""`` when there is nothing to say.
    :param tooltip: what hovering says about it, ``""`` for nothing more than the path.
    """

    text: str = ""
    tooltip: str = ""


@dataclass(frozen=True)
class FilesProgress:
    """One user's progress on a resource's videos, with the totals the folders show.

    :param root: the resource's own folder, which a folder's key is measured from.
    :param entries: the user's progress on each video, by content key.
    :param measured: the lengths a Measure wrote, by content key.
    :param video_keys: the content key of every video on disk now, or ``None`` when that is not known -- a document
        that is not a tutorial, or a folder that would not list. Without it no total is claimed: a folder's share of
        files nobody counted would be a wrong number.
    """

    root: Path
    entries: Mapping[str, ProgressEntry]
    measured: Mapping[str, VideoFacts]
    video_keys: tuple[str, ...] | None

    @cached_property
    def totals(self) -> dict[str, WatchTotals]:
        """The user's watching summed per folder, by folder key, once per snapshot; empty when the videos on disk are
        not known."""
        if self.video_keys is None:
            return {}
        return watch_totals(self.video_keys, self.measured, self.entries)

    def folder_key(self, folder: Path) -> str | None:
        """The key :func:`~rehuco_core.watch_totals` sums a folder under.

        :param folder: a folder under the resource's own.
        :returns: its POSIX path below the root, or ``None`` for a path that is not below it.
        """
        try:
            return folder.relative_to(self.root).as_posix()
        except ValueError:
            return None

    def for_video(self, key: str, *, missing: bool = False) -> RowProgress:
        """What a video's row ends with.

        :param key: the video's content key.
        :param missing: whether the file is gone and only its entry is left.
        :returns: ``100%`` once viewed, else the position over the length when both are known, and nothing for a video
            never opened.
        """
        entry = self.entries.get(key)
        facts = self.measured.get(key)
        length = facts.duration if facts is not None else (entry.duration if entry is not None else None)
        if entry is None:
            return RowProgress(tooltip=UNOPENED_TOOLTIP)
        tooltip = MISSING_TOOLTIP if missing else ""
        if entry.viewed:
            return RowProgress("100%", tooltip)
        if length is None or length <= 0:
            return RowProgress(tooltip=tooltip or UNMEASURED_FILE_TOOLTIP)
        return RowProgress(percent(entry.position, length), tooltip)

    def for_folder(self, folder: Path) -> RowProgress | None:
        """What a folder's row ends with: the duration-weighted share of every video beneath it.

        :param folder: the folder.
        :returns: the share, or nothing with the reason for a folder holding a video of unknown length; ``None`` when
            there is nothing to say -- no video beneath it, or the videos on disk are not known.
        """
        key = self.folder_key(folder)
        total = self.totals.get(key) if key is not None else None
        if total is None or not total.files:
            return None
        if total.unknown_length or total.length <= 0:
            return RowProgress(tooltip=UNMEASURED_FOLDER_TOOLTIP)
        return RowProgress(percent(total.watched, total.length))


def percent(done: float, whole: float) -> str:
    """A share as a whole percentage, never ``100%`` until it is: a video a second short of its end reads ``99%``.

    :param done: how much.
    :param whole: out of how much; positive.
    :returns: the percentage, from ``0%`` to ``100%``.
    """
    return f"{min(100, int(100 * done / whole))}%"
