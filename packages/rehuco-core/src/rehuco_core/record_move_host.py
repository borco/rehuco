"""What the app lends a record's move (#339): where this machine finds a root, whether a save of the record is still
on its way, and the thread a rename runs on.

The app installs its host at startup (:data:`DEFAULT_RECORD_MOVE_HOST`); without one a step runs where the job does.
Split from :mod:`~rehuco_core.move_record_job`, whose jobs ask it.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Final, Protocol
from uuid import UUID


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


DEFAULT_RECORD_MOVE_HOST: Final = RecordMoveHosting()
"""The host every move asks unless a test hands it another."""
