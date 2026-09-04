"""Ties a log record to the things it is about, so a log surface can show only that thing's records."""

from collections.abc import Generator, Hashable
from contextlib import contextmanager
from contextvars import ContextVar
from logging import LogRecord
from typing import Final

LOG_SCOPE_ATTRIBUTE: Final = "log_scope"
"""Attribute name a scope is stamped under on a `logging.LogRecord`.

Set it explicitly through ``logging``'s own ``extra=`` to scope a single call
(``LOG.info("...", extra={LOG_SCOPE_ATTRIBUTE: key})``); it wins over whatever :meth:`LogScope.open`
has open, because naming a scope at the call site is the more specific statement of the two: it does not
join the open stack, it **stands alone** as the whole of what the record is about."""


class LogScope:
    """What a log record is about -- opaque keys, carried ambiently rather than passed.

    A scope is any hashable the application finds meaningful (a file path, an id, an enum member);
    nothing here interprets it, and two scopes are the same scope when they compare equal. The point
    is that the **call sites do not change**: an operation wraps itself in :meth:`open` once, and every
    record its callees emit -- including a library's, several frames down -- is placed without ever
    having heard of the scope.

    Ambient state is normally worth avoiding, and is the right answer here for the same reason
    ``logging`` itself is ambient: the alternative is threading a scope argument through every layer
    between the operation and the log call, which is most of them, for the benefit of a surface that
    may not exist.

    **Scopes nest, and a record keeps every one that was open** -- the *stack*, outermost first, and a
    sink matches when its scope is anywhere in it rather than only at the end. One record is about more
    than one thing as soon as two of them are true at once: work on a document, run as a queued job, is
    about the document *and* the job. With a single key the inner one would displace the outer, so the
    document's surface would fall silent exactly while work was being done on it -- and the alternative,
    letting each surface filter the app-wide log for itself, is the same match written once per surface
    over every record instead of once here.

    The stack is a *set of labels* built by nesting rather than named per call, which is what makes it
    correct: a label's lifetime is a block, it is dropped when that block raises, and
    ``contextvars.copy_context()`` carries the whole set to a worker in one move. An ``add``/``remove``
    pair would put the second half on every path out of the operation.

    Never instantiated -- the scopes live in a class-level `contextvars.ContextVar`, which is *one*
    variable holding a per-context value, not shared state to be given out per object.
    """

    __CONTEXT: Final[ContextVar[tuple[Hashable, ...]]] = ContextVar("borco_core_log_scope", default=())
    """Every scope open in this context, outermost first; empty for unscoped.

    A tuple rather than a `set`, because it has to be immutable to be a `ContextVar` value that
    :meth:`open` can restore by token, and because the order is worth the nothing it costs:
    :meth:`current` is the last element. Nothing downstream reads it as an order -- routing is
    membership.

    A `ContextVar` rather than a thread-local so the value can be *carried* somewhere on purpose:
    ``contextvars.copy_context()`` captures it, and running work inside that copy puts a worker
    thread's records under the scopes of whoever submitted the work -- which is how a queued background
    job stays attributable to the document it was started for. A thread-local offers no such capture;
    it could only be re-set by hand, per thread, by code that had to remember to."""

    @classmethod
    @contextmanager
    def open(cls, scope: Hashable | None) -> Generator[None]:
        """Scope every record logged inside this block, from any module at any depth.

        Nests by **adding**: a record logged inside two open blocks is about both, and the inner block
        leaving restores the stack the outer one had. Passing ``None`` deliberately un-scopes a block
        inside a scoped one -- an empty stack for its duration, since work that is about nothing in
        particular is not about the enclosing thing either.

        Re-opening a scope already on the stack keeps the duplicate. Routing is membership, so
        ``(p, p)`` reaches exactly the sinks ``(p,)`` does, and checking would buy only a tidier tuple.

        :param scope: what the records inside belong to, or ``None`` to be about nothing here.
        """
        token = cls.__CONTEXT.set((*cls.__CONTEXT.get(), scope) if scope is not None else ())
        try:
            yield
        finally:
            cls.__CONTEXT.reset(token)

    @classmethod
    def current(cls) -> Hashable | None:
        """Say what scope is open right here.

        Answers with the innermost alone, which is what a caller asking *"what am I working on"* means.
        :meth:`stack` is the one to route by.

        :returns: the innermost open scope, or ``None`` when nothing is scoped.
        """
        stack = cls.__CONTEXT.get()
        return stack[-1] if stack else None

    @classmethod
    def stack(cls) -> tuple[Hashable, ...]:
        """Say everything the records logged right here are about.

        :returns: the open scopes, outermost first; empty when nothing is scoped.
        """
        return cls.__CONTEXT.get()

    @classmethod
    def of(cls, record: LogRecord) -> tuple[Hashable, ...]:
        """Say what ``record`` is about.

        Correct only when called on the thread that logged the record and before that thread moves on
        -- which is exactly where a `logging.Handler` runs: handlers are called synchronously from
        ``LOG.info(...)`` itself, on the calling thread, so the context read here is still the
        caller's. A handler that queued records and resolved their scope later would read whatever
        context it happened to be in instead, which is why :class:`~borco_pyside.logging.log_bridge.LogBridge` resolves
        this in ``emit`` and carries the answer rather than the record alone.

        :param record: the record to place.
        :returns: the record's own :data:`LOG_SCOPE_ATTRIBUTE` alone, as a one-element stack, if it
            carries one; else every scope open here, outermost first.
        """
        scope = getattr(record, LOG_SCOPE_ATTRIBUTE, None)
        return (scope,) if scope is not None else cls.__CONTEXT.get()
