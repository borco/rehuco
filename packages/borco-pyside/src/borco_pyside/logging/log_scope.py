"""Ties a log record to the thing it is about, so a log surface can show only that thing's records."""

from collections.abc import Generator, Hashable
from contextlib import contextmanager
from contextvars import ContextVar
from logging import LogRecord
from typing import Final

LOG_SCOPE_ATTRIBUTE: Final = "log_scope"
"""Attribute name a scope is stamped under on a `logging.LogRecord`.

Set it explicitly through ``logging``'s own ``extra=`` to scope a single call
(``LOG.info("...", extra={LOG_SCOPE_ATTRIBUTE: key})``); it wins over whatever :meth:`LogScope.open`
has open, because naming a scope at the call site is the more specific statement of the two."""


class LogScope:
    """What a log record is about -- an opaque key, carried ambiently rather than passed.

    A scope is any hashable the application finds meaningful (a file path, an id, an enum member);
    nothing here interprets it, and two scopes are the same scope when they compare equal. The point
    is that the **call sites do not change**: an operation wraps itself in :meth:`open` once, and every
    record its callees emit -- including a library's, several frames down -- is placed without ever
    having heard of the scope.

    Ambient state is normally worth avoiding, and is the right answer here for the same reason
    ``logging`` itself is ambient: the alternative is threading a scope argument through every layer
    between the operation and the log call, which is most of them, for the benefit of a surface that
    may not exist.

    Never instantiated -- the scope lives in a class-level `contextvars.ContextVar`, which is *one*
    variable holding a per-context value, not shared state to be given out per object.
    """

    __CONTEXT: Final[ContextVar[Hashable | None]] = ContextVar("borco_pyside_log_scope", default=None)
    """The scope every record logged in this context belongs to, or ``None`` for unscoped.

    A `ContextVar` rather than a thread-local so the value can be *carried* somewhere on purpose:
    ``contextvars.copy_context()`` captures it, and running work inside that copy puts a worker
    thread's records under the scope of whoever submitted the work -- which is how a queued background
    job stays attributable to the document it was started for. A thread-local offers no such capture;
    it could only be re-set by hand, per thread, by code that had to remember to."""

    @classmethod
    @contextmanager
    def open(cls, scope: Hashable | None) -> Generator[None]:
        """Scope every record logged inside this block, from any module at any depth.

        Nests: the inner scope holds for its block, then the outer one is restored. Passing ``None``
        deliberately un-scopes a block inside a scoped one, for work that is genuinely about nothing
        in particular.

        :param scope: what the records inside belong to, or ``None`` for none.
        """
        token = cls.__CONTEXT.set(scope)
        try:
            yield
        finally:
            cls.__CONTEXT.reset(token)

    @classmethod
    def current(cls) -> Hashable | None:
        """Say what scope is open right here.

        :returns: the innermost open scope, or ``None`` when nothing is scoped.
        """
        return cls.__CONTEXT.get()

    @classmethod
    def of(cls, record: LogRecord) -> Hashable | None:
        """Say what ``record`` is about.

        Correct only when called on the thread that logged the record and before that thread moves on
        -- which is exactly where a `logging.Handler` runs: handlers are called synchronously from
        ``LOG.info(...)`` itself, on the calling thread, so the context read here is still the
        caller's. A handler that queued records and resolved their scope later would read whatever
        context it happened to be in instead, which is why :class:`~.log_bridge.LogBridge` resolves
        this in ``emit`` and carries the answer rather than the record alone.

        :param record: the record to place.
        :returns: the record's own :data:`LOG_SCOPE_ATTRIBUTE` if it carries one, else the open scope.
        """
        scope = getattr(record, LOG_SCOPE_ATTRIBUTE, None)
        return scope if scope is not None else cls.__CONTEXT.get()
