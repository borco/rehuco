"""How a move's split moves what it moves (#680): each record and each folder through the rename barrier, on the
thread a rename runs on, so the cache, an open document and a playing video follow it as they follow any rename.

Split from :mod:`~rehuco_core.move_record_job`, whose split phase lends it to :class:`~rehuco_core.BucketSplitter`.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Final

from .prefix_buckets import records_beneath
from .record_move_host import RecordMoveHost
from .rename_coordination import RenameCoordinator


class RecordBucketMover:
    """A :class:`~rehuco_core.BucketMover` that renames through the barrier, on the host's thread.

    What a move raises leaves through here as the rename raised it: a lock held elsewhere
    (:class:`~rehuco_core.RecordLockedError`) or a reader that did not let go
    (:class:`~rehuco_core.RenameYieldTimeout`), for the job to wait on.

    :param coordinator: the rename barrier.
    :param host: what the app lends the move: the thread a rename runs on.
    :param checkpoint: called while a step waits to start; what it raises abandons the step.
    """

    def __init__(self, coordinator: RenameCoordinator, host: RecordMoveHost, checkpoint: Callable[[], None]) -> None:
        self.__coordinator: Final = coordinator
        self.__host: Final = host
        self.__checkpoint: Final = checkpoint

    def move_record(self, record: Path, into: Path) -> None:
        """Move a file record and its sidecars into a folder, keeping its name.

        :param record: its ``.rehu``.
        :param into: the folder, made when missing.
        """
        self.__host.run_step(lambda: self.__coordinator.rename(record, record.stem, into=into), self.__checkpoint)

    def move_folder(self, folder: Path, into: Path, name: str) -> None:
        """Move a folder whole, its records listed here, off the host's thread.

        :param folder: the folder.
        :param into: the folder it lands in, made when missing.
        :param name: its name there.
        """
        records = records_beneath(folder)
        self.__host.run_step(lambda: self.__coordinator.move_folder(folder, into, name, records), self.__checkpoint)
