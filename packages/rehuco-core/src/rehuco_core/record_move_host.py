"""What the app lends a record's move (#339): where this machine finds a root, whether a save of the record is still
on its way, and the thread a rename runs on -- and what it lends a rebalance of a root's buckets besides (#681).

The app installs its host at startup (:data:`DEFAULT_RECORD_MOVE_HOST`); without one a step runs where the job does.
Split from :mod:`~rehuco_core.move_record_job`, whose jobs ask it.
"""

import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final, Protocol
from uuid import UUID

from .prefix_buckets import DEFAULT_SPLIT_LIMIT
from .replacement_rule import ReplacementRule

BUCKETS_GUARD: Final = threading.Lock()
"""Held by a move while it reads its buckets and says which it read, and by a rebalance while it asks for such a move
and takes one step (#681): neither can come between the other's two halves, so no record lands in a bucket a join is
removing. Never taken on the host's thread, which a step waits for with it held."""


class RecordMoveHost(Protocol):
    """What the app lends a move: this machine's roots, its saves, and the thread a rename runs on."""

    def root_folder(self, root_id: UUID) -> Path | None:
        """Where this machine finds a root.

        :param root_id: the root.
        :returns: its folder, or ``None`` when this machine does not map it.
        """

    def save_pending(self, rehu_path: Path) -> bool:  # pyright: ignore[reportReturnType]
        """Whether a save of a record has not landed yet -- a move removing the original waits for it. Asked inside a
        step :meth:`run_step` runs, on the host's thread.

        :param rehu_path: the record's ``.rehu`` file.
        :returns: whether one is queued or running.
        """

    def run_step(self, step: Callable[[], object], checkpoint: Callable[[], None]) -> None:
        """Run ``step`` where a rename runs, and return once it has.

        :param step: what to run; what it raises leaves through here.
        :param checkpoint: called while waiting for ``step`` to start; what it raises abandons ``step``, which then
            never runs.
        """

    def split_limit(self) -> int:  # pyright: ignore[reportReturnType]
        """How many entries a folder of a bucketed layout holds before it splits, as the settings say now (#680) --
        asked when a move settles its buckets, never captured, since it may change while the move waits.

        :returns: the limit.
        """

    def location_rules(self) -> Sequence[ReplacementRule]:  # pyright: ignore[reportReturnType]
        """The Location Replacements, as the settings say now: what a layout's place is rendered with (#681).

        :returns: the rules, in table order.
        """

    def blocking_move(self, root_id: UUID) -> str | None:
        """The move whose files a rebalance of a root would take from under it (#681): one into a bucketed place of the
        root that has read its buckets and not ended, running, waiting or paused, or that stopped with part of its copy
        there; and one out of the root about to remove what is left of the original. Asked with :data:`BUCKETS_GUARD`
        held.

        :param root_id: the root.
        :returns: how its row names it; ``None`` when there is none.
        """


class RecordMoveHosting:
    """The process-wide :class:`RecordMoveHost`: the one the app installed, or a stand-in answering from this thread.

    Process-wide for the reason :data:`~rehuco_core.DEFAULT_RENAME_COORDINATOR` is: a move restored from a saved queue
    is built with no window to be handed anything.
    """

    def __init__(self) -> None:
        self.__host: RecordMoveHost | None = None

    def install(self, host: RecordMoveHost | None) -> None:
        """Lend moves the app's host, or take it back.

        :param host: the host; ``None`` to go back to the stand-in.
        """
        self.__host = host

    def root_folder(self, root_id: UUID) -> Path | None:
        """See :meth:`RecordMoveHost.root_folder`; with no host installed, no root is mapped.

        :param root_id: the root.
        :returns: its folder, or ``None``.
        """
        return None if self.__host is None else self.__host.root_folder(root_id)

    def save_pending(self, rehu_path: Path) -> bool:
        """See :meth:`RecordMoveHost.save_pending`; with no host installed, none is.

        :param rehu_path: the record's ``.rehu`` file.
        :returns: whether one is queued or running.
        """
        return self.__host is not None and self.__host.save_pending(rehu_path)

    def run_step(self, step: Callable[[], object], checkpoint: Callable[[], None]) -> None:
        """See :meth:`RecordMoveHost.run_step`; with no host installed, ``step`` runs here.

        :param step: what to run.
        :param checkpoint: called first.
        """
        if self.__host is None:
            checkpoint()
            step()
            return
        self.__host.run_step(step, checkpoint)

    def split_limit(self) -> int:
        """See :meth:`RecordMoveHost.split_limit`; with no host installed, the default.

        :returns: the limit.
        """
        return DEFAULT_SPLIT_LIMIT if self.__host is None else self.__host.split_limit()

    def location_rules(self) -> Sequence[ReplacementRule]:
        """See :meth:`RecordMoveHost.location_rules`; with no host installed, none.

        :returns: the rules.
        """
        return () if self.__host is None else self.__host.location_rules()

    def blocking_move(self, root_id: UUID) -> str | None:
        """See :meth:`RecordMoveHost.blocking_move`; with no host installed, none.

        :param root_id: the root.
        :returns: how its row names it; ``None`` when there is none.
        """
        return None if self.__host is None else self.__host.blocking_move(root_id)


DEFAULT_RECORD_MOVE_HOST: Final = RecordMoveHosting()
"""The host every move asks unless a test hands it another."""
