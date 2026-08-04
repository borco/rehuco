"""The stop protocol, implemented once, so a job only has to write its work
([[appendices.task-queue#job-responsibility]]).

:class:`~rehuco_core.tasks.TaskJob` puts stopping in the job's hands, which is right -- only the job
knows where its work divides and whether a stop has gone too far to take back -- but it would be a
poor trade if every client had to reason about a lock to get a checkpoint. This is that reasoning,
done once.
"""

from pathlib import Path
from threading import RLock
from typing import Final

from .task_job import JobCancelled, JobControl, JobPaused, StopRequest


class TaskJobBase:
    """A job with the stop protocol already written: one request slot, one lock, one checkpoint.

    Subclasses implement :meth:`run` and a ``label``, and call :meth:`checkpoint` wherever their work
    divides. Everything :class:`~rehuco_core.tasks.TaskJob` asks for beyond that is here.

    **Why a base class at all**, when the appendix used to say a job is a plain object satisfying a
    `Protocol` structurally: because the protocol now includes three methods called from another
    thread while ``run`` is executing, and a correct implementation of them is the same eleven lines
    every time. Inheriting is not required -- a job with genuinely different stop semantics implements
    the protocol itself -- but writing those eleven lines again is not a design choice, it is a copy.

    **:meth:`checkpoint` is the job's own, not the engine's** ([[appendices.task-queue#jobs]]). It is
    absent from :class:`~rehuco_core.tasks.TaskJob` and unreachable from the queue, which is the whole
    point of the redesign -- where a job's work divides is nobody else's business. It survives as a
    method here because the alternative is every job hand-writing the same two-branch raise, and
    because it is the one path that acknowledges a request *truthfully*: it says "I have been told" and
    unwinds in the same breath, where a bare :attr:`stop_requested` read has to assume the worst.

    **The single request slot** ([[appendices.task-queue#pause-concept]]): a job is asked for at most
    one thing, and the latest instruction replaces the one before it. Asking a cancelling job to pause
    downgrades the request; asking a pausing job to cancel escalates it. Two independent flags could
    express *cancel and pause*, which is not something a checkpoint can act on.

    **A stale request cannot survive into the next run**, and it is :meth:`resume` that guarantees it:
    the engine calls it on every job it puts back in line, and it clears unconditionally. Clearing on
    entry to ``run`` instead was tried and is wrong -- it silently discards a request made before the
    job first started, which is a legal thing for a caller to do and a trap for anyone using this base
    outside the engine.
    """

    label: str
    """How this job is named to a reader. Annotated rather than given a value or made an abstract
    property: subclasses overwhelmingly set it in ``__init__``, and a ``property`` here would be a data
    descriptor that refuses exactly that assignment."""

    source: Path | None = None
    """What this job is about; overridden by a job that is about one resource."""

    safely_interruptible: bool = True
    """Whether stopping part-way leaves nothing behind; overridden by a job that changes things."""

    resumes_where_it_stopped: bool = False
    """Whether pausing keeps the work done; overridden by a job that keeps a cursor."""

    def __init__(self) -> None:
        self.__lock: Final = RLock()
        self.__stop: StopRequest | None = None
        self.__acted = False

    @property
    def stop_requested(self) -> StopRequest | None:
        """What this job has been asked to do, **and an acknowledgement that it has been told**.

        For a job that would rather tidy up than be raised out of -- a conversion writing its rollback
        record ([[acquisition-tooling#convert-mechanics]]). Reading it is how the job says *I know*,
        so a :meth:`resume` after this returns ``False``: once the job has been told, the engine can
        no longer promise that nothing has begun. Ordinary jobs call :meth:`checkpoint` and never read
        this.

        :returns: the pending request, or ``None``.
        """
        with self.__lock:
            if self.__stop is not None:
                self.__acted = True
            return self.__stop

    def checkpoint(self) -> None:
        """Yield: unwind if a stop has been asked for, otherwise return at once.

        Call it wherever the work divides -- once per file, once per resource -- and nowhere else: a
        job that never calls it runs to completion and cannot be interrupted, and a job that calls it
        between two halves of an atomic step can be stopped in the middle of one.

        :raises JobCancelled: when a cancel is pending.
        :raises JobPaused: when a pause is pending.
        """
        with self.__lock:
            if self.__stop is None:
                return
            self.__acted = True
            if self.__stop is StopRequest.CANCEL:
                raise JobCancelled(self.label)
            raise JobPaused(self.label)

    def pause(self) -> None:
        """Record a pause request, replacing whatever was asked before."""
        with self.__lock:
            self.__stop = StopRequest.PAUSE

    def cancel(self) -> None:
        """Record a cancel request, replacing whatever was asked before."""
        with self.__lock:
            self.__stop = StopRequest.CANCEL

    def resume(self) -> bool:
        """Drop the pending request, and say whether it had been acted on.

        Always clears, because this is also how a job that has stopped is made ready to run again --
        so the answer is about *what already happened*, not about whether the clearing worked.

        :returns: ``True`` when nothing had been acted on and this job can carry on as though it was
            never asked; ``False`` when it had, and the stop is genuinely under way.
        """
        with self.__lock:
            acted = self.__acted
            self.__stop = None
            self.__acted = False
            return not acted

    def reset(self) -> None:
        """Throw away what was kept, so the next run starts from the beginning.

        Clears the request slot too, since a retried job must not inherit a stop nobody asked of *it*.
        Subclasses that keep a cursor override this, and call up.
        """
        with self.__lock:
            self.__stop = None
            self.__acted = False

    def run(self, control: JobControl) -> None:
        """Do the work, on the worker thread.

        :param control: the engine's face to this job.
        :raises NotImplementedError: always; a job with no work is not a job.
        """
        raise NotImplementedError
