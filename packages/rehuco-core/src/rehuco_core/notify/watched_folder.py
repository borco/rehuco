"""What a file notifier watches (#511)."""

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID


@dataclass(frozen=True, slots=True)
class WatchedFolder:
    """A folder, and what kind of watch it gets.

    :param path: the folder.
    :param root_id: the ``.rehuco`` root it is; ``None`` for the folder of an open document under no root, whose watch
        lets go for a rename (:class:`~rehuco_core.notify.NativeWatch`) and announces no reachability.
    :param recursive: whether everything beneath it is watched, or only its own entries.
    """

    path: Path
    root_id: UUID | None = None
    recursive: bool = True
