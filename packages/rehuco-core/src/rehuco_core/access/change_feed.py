"""What changed under the resources the app reaches, announced without Qt (#413).

The Qt-free form of the agent's ``ResourceEvents`` ([[nodes#access-seam]]): :class:`~rehuco_core.access.Records`
publishes every write it makes here, and the agent adapts the feed to Qt signals. Each event says *what* changed, never
what to do about it -- every holder applies its own rule.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Final
from uuid import UUID

from .key_relocation import KeyRelocation
from .keys import ResourceKey

LOG: Final = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Moved:
    """A rename landed -- possibly an empty one, for a rename to the name the resource already had.

    :param relocation: the rename's executed plan.
    """

    relocation: KeyRelocation


@dataclass(frozen=True, slots=True)
class Changed:
    """Files were written or replaced: a saved record, a converted one and what it replaced, a rewritten checksum
    record.

    :param keys: the files' keys.
    """

    keys: tuple[ResourceKey, ...]


@dataclass(frozen=True, slots=True)
class FolderChanged:
    """A folder's listing changed without saying which files: screenshots renumbered, deleted, converted or written.

    :param key: the folder's key.
    """

    key: ResourceKey


@dataclass(frozen=True, slots=True)
class RootStale:
    """Nothing held about a root can be trusted any more -- its watch may have missed changes -- so every holder reads
    it again. The file notifier is its first publisher (#511).

    :param root_id: the root's ``.rehuco`` id.
    """

    root_id: UUID


type ChangeEvent = Moved | Changed | FolderChanged | RootStale
"""One announcement on a :class:`ChangeFeed`."""


class ChangeFeed:
    """Hands each published :data:`ChangeEvent` to every listener, in the order they were added.

    **Listeners run on the publisher's thread, with no lock held**, as :class:`~rehuco_core.RenameCoordinator`'s
    rename listeners do: a listener that needs another thread moves the event there itself, which is what the agent's
    adapter to Qt signals does. A listener may add or remove listeners -- itself included -- while it runs; that takes
    effect from the next event.
    """

    def __init__(self) -> None:
        self.__lock: Final = Lock()
        self.__listeners: list[Callable[[ChangeEvent], None]] = []

    def add_listener(self, listener: Callable[[ChangeEvent], None]) -> None:
        """Be told of every event published from now on.

        :param listener: called with each event.
        """
        with self.__lock:
            self.__listeners.append(listener)

    def remove_listener(self, listener: Callable[[ChangeEvent], None]) -> None:
        """Stop being told. A listener that was never added is ignored, as a teardown after a failed setup needs.

        :param listener: the callable to drop.
        """
        with self.__lock:
            if listener in self.__listeners:
                self.__listeners.remove(listener)

    def publish(self, event: ChangeEvent) -> None:
        """Hand ``event`` to every listener.

        **A listener's exception is logged, never propagated**: the change has already happened, and raising out of
        the announcement would tell the publisher an operation failed that in fact succeeded.

        :param event: what changed.
        """
        with self.__lock:
            listeners = tuple(self.__listeners)
        for listener in listeners:
            try:
                listener(event)
            except Exception:  # pylint: disable=broad-exception-caught
                LOG.exception("A change listener failed; detach it or fix it -- it was skipped.")
