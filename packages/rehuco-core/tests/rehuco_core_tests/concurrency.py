"""Waiting on another thread, for the tests that have one (#241).

Two modules test the same protocol from opposite ends -- ``test_rename_coordination`` from the barrier's
side, ``test_content_reading`` from the reader's -- and both need the same two things: run something on
a worker for the length of a block, and wait for a state to arrive without hanging if it never does.
Written once here rather than twice there, so the two cannot drift on what a timeout means.

Not ``conftest.py``: these are plain callables a test *calls*, not state pytest should be injecting, and
a fixture that exists only to hand back a function is indirection for its own sake. Importable by bare
name because ``packages/rehuco-core/tests/`` carries no ``__init__.py``, so pytest puts it on
``sys.path`` for every module it collects there.
"""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from threading import Thread
from time import monotonic, sleep
from typing import Final

SETTLE: Final = 5.0
"""How long a test waits for another thread to reach the state it is checking, in seconds.

Far above anything the barrier needs (~7 ms measured) and far below a suite that looks hung: a wait that
runs out is a genuine failure, never a slow runner."""

BRIEF: Final = 0.05
"""A timeout a test *expects* to run out, in seconds.

For the assertions of the form *this has not happened yet*. Short, because waiting to be told nothing
happened is dead time in every run."""

POLL: Final = 0.001
"""How often :func:`wait_until` re-asks, in seconds. Fine enough that a test's timing reads as
immediate, coarse enough not to spin a core while it waits."""


@contextmanager
def running(target: Callable[[], object]) -> Generator[None]:
    """Run ``target`` on a daemon thread for the length of the block.

    Daemon, and joined with a bounded wait on the way out, so a test that fails its assertions still
    lets the suite exit rather than hanging on a worker stuck behind a barrier that never lifted.

    :param target: what to run; whatever it returns is dropped, so a bare ``coordinator.rename(...)``
        can be handed over without a wrapper that discards the new path.
    :yields: nothing; the block does the asserting.
    """
    thread = Thread(target=target, daemon=True)
    thread.start()
    try:
        yield
    finally:
        thread.join(SETTLE)


def wait_until(predicate: Callable[[], bool]) -> bool:
    """Poll ``predicate`` until it holds, or :data:`SETTLE` runs out.

    Returns rather than raises, so the caller asserts on it: a barrier that never lifts then fails the
    test at a named line instead of hanging the run.

    :param predicate: what to wait for.
    :returns: whether it came true in time.
    """
    deadline = monotonic() + SETTLE
    while monotonic() < deadline:
        if predicate():
            return True
        sleep(POLL)
    return predicate()
