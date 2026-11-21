"""What is left of a moved record's original once it stopped being a record (#339): kept by the move, so a quit
before it is all removed still removes it.

Split from :mod:`~rehuco_core.move_record_job`, whose *cleanup* phase removes it.
"""

from dataclasses import dataclass
from typing import Any, Final

CLEANUP_FILES_KEY: Final = "files"
CLEANUP_FOLDERS_KEY: Final = "folders"
CLEANUP_LEFT_KEY: Final = "left"
CLEANUP_ROOT_KEY: Final = "root"
"""The keys a :class:`MoveCleanup` writes itself down under."""


@dataclass(frozen=True, slots=True)
class MoveCleanup:
    """What is left of an original once it stopped being a record, kept so a quit before it is all removed still
    removes it.

    :param files: the original's files.
    :param folders: its folders, a parent before its children.
    :param left: the folder its own entry was in.
    :param root: the folder of the root it was under, or ``None`` for none.
    """

    files: tuple[str, ...]
    folders: tuple[str, ...]
    left: str
    root: str | None

    def to_state(self) -> dict[str, Any]:
        """This cleanup as JSON primitives.

        :returns: the state.
        """
        return {
            CLEANUP_FILES_KEY: list(self.files),
            CLEANUP_FOLDERS_KEY: list(self.folders),
            CLEANUP_LEFT_KEY: self.left,
            CLEANUP_ROOT_KEY: self.root,
        }

    @classmethod
    def from_state(cls, state: Any) -> MoveCleanup | None:
        """A cleanup from what :meth:`to_state` wrote.

        :param state: the saved value; ``None`` for a move with nothing to clean up.
        :returns: the cleanup, or ``None``.
        :raises ValueError: the value is not the shape written.
        """
        if state is None:
            return None
        if not isinstance(state, dict):
            raise ValueError("A saved move's cleanup is not an object.")
        files, folders = state.get(CLEANUP_FILES_KEY), state.get(CLEANUP_FOLDERS_KEY)
        left, root = state.get(CLEANUP_LEFT_KEY), state.get(CLEANUP_ROOT_KEY)
        if not (isinstance(files, list) and isinstance(folders, list) and isinstance(left, str)):
            raise ValueError("A saved move's cleanup names no files, folders or folder left.")
        if not all(isinstance(path, str) for path in [*files, *folders]) or not isinstance(root, str | None):
            raise ValueError("A saved move's cleanup names something that is not a path.")
        return cls(tuple(files), tuple(folders), left, root)
