"""What turns a saved ``kind`` back into a job ([[appendices.task-queue#lifetime]]).

The indirection that lets a job class move, or be renamed, without invalidating the queue files users
already have: a saved item names a kind, and this is where a build says which class that is -- or that
it no longer ships one.
"""

import logging
from collections.abc import Callable
from typing import Any, Final

from .persistable_task_job import PersistableTaskJob
from .task_job import TaskJob

LOG: Final = logging.getLogger(__name__)


class TaskJobRegistry:
    """The kinds of job this build can reconstruct.

    **One call rather than two** ([[appendices.task-queue#lifetime]]): :meth:`create` builds the job
    *and* gives it its state, because a job that has been constructed but not restored is an invalid
    object and nothing outside should be able to hold one, let alone enqueue it.

    Registration is done by whoever owns the job -- a module registering its own kinds at import --
    rather than by a central list this package would have to keep in step with every client.
    """

    def __init__(self) -> None:
        self.__factories: dict[str, Callable[[], PersistableTaskJob]] = {}

    @property
    def kinds(self) -> tuple[str, ...]:
        """Every kind this build can reconstruct, in registration order.

        :returns: the registered kind names.
        """
        return tuple(self.__factories)

    def register(self, kind: str, factory: Callable[[], PersistableTaskJob]) -> None:
        """Say which class a saved ``kind`` names.

        :param kind: the stable name, matching the class's own
            :attr:`~rehuco_core.tasks.PersistableTaskJob.kind`.
        :param factory: builds an instance ready to be handed a state -- typically the class itself,
            when its constructor takes no arguments.
        :raises ValueError: if ``kind`` is already registered. Silently replacing it would make a saved
            item ambiguous, and two classes claiming one kind is a programming error rather than
            something a user can cause.
        """
        if kind in self.__factories:
            raise ValueError(f"Two job classes claim the task kind {kind!r}.")
        self.__factories[kind] = factory

    def create(self, kind: str, state: dict[str, Any]) -> TaskJob | None:
        """Rebuild the job a saved item describes.

        Returns ``None`` rather than raising for an unknown kind, matching
        :meth:`~rehuco_core.PluginRegistry.resolve`'s house style: a queue file from a newer build, or
        one naming a feature this build dropped, must not stop the app starting.

        A job whose :meth:`~rehuco_core.tasks.PersistableTaskJob.restore_state` raises is treated the
        same way and for the same reason -- the item is unusable, and a half-built job is worse than a
        missing one.

        :param kind: the saved kind name.
        :param state: the saved state, handed to the job verbatim.
        :returns: the restored job, or ``None`` when this build cannot make one.
        """
        factory = self.__factories.get(kind)
        if factory is None:
            return None
        try:
            job = factory()
            job.restore_state(state)
        except Exception:  # pylint: disable=broad-exception-caught
            LOG.exception("A saved task of kind %r could not be restored; it was dropped.", kind)
            return None
        return job


DEFAULT_TASK_JOB_REGISTRY: Final = TaskJobRegistry()
"""The registry the app restores from, and the one a job class registers itself into at import.

A module-level default rather than an instance passed everywhere, for the same reason
:data:`~rehuco_core.DEFAULT_PLUGIN_REGISTRY` is one: what a build can reconstruct is a property of the
build. Tests build their own instead of registering into this."""
