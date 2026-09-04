"""Tests for LogScope."""

import logging
from collections.abc import Hashable
from contextvars import copy_context
from threading import Thread

from borco_core.logging.log_scope import LOG_SCOPE_ATTRIBUTE, LogScope

# region helpers


def make_record(**extra: Hashable) -> logging.LogRecord:
    """Build a record the way ``logging`` does, optionally carrying an explicit scope.

    :param extra: attributes to stamp on the record, as ``logging``'s own ``extra=`` would.
    :returns: the record.
    """
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "message", None, None)
    for name, value in extra.items():
        setattr(record, name, value)
    return record


def scope_several_frames_down() -> Hashable | None:
    """Read the open scope from a function that was never told about it.

    :returns: whatever scope is open at the call site's caller, and its caller.
    """
    return LogScope.current()


# endregion


# region the open scope


def test_nothing_is_scoped_by_default() -> None:
    """The scope is None until a block opens one.

    **Test steps:**

    * read the current scope without opening any
    * verify it is None
    """
    assert LogScope.current() is None


def test_a_block_scopes_what_is_logged_inside_it() -> None:
    """Opening a scope makes it the current one for the block, and only for the block.

    **Test steps:**

    * open a scope and read it inside the block
    * verify it is the opened scope
    * verify the scope is None again after the block
    """
    with LogScope.open("resource"):
        assert LogScope.current() == "resource"

    assert LogScope.current() is None


def test_the_scope_reaches_code_that_was_never_told_about_it() -> None:
    """A callee several frames down sees the scope without it being passed.

    **Test steps:**

    * open a scope
    * call a helper that takes no arguments and reads the current scope
    * verify the helper saw the opened scope
    """
    with LogScope.open("resource"):
        assert scope_several_frames_down() == "resource"


def test_scopes_nest_and_the_outer_one_is_restored() -> None:
    """An inner scope holds for its block, then the outer one comes back.

    **Test steps:**

    * open an outer scope, then an inner one inside it
    * verify the inner scope is current inside the inner block
    * verify the outer scope is current again after it
    """
    with LogScope.open("outer"):
        with LogScope.open("inner"):
            assert LogScope.current() == "inner"

        assert LogScope.current() == "outer"


def test_a_none_scope_unscopes_a_block_inside_a_scoped_one() -> None:
    """Opening None inside a scope deliberately un-scopes that block.

    **Test steps:**

    * open a scope, then open None inside it
    * verify the current scope is None inside the inner block
    * verify the outer scope is restored after it
    """
    with LogScope.open("resource"):
        with LogScope.open(None):
            assert LogScope.current() is None

        assert LogScope.current() == "resource"


def test_the_scope_is_restored_when_the_block_raises() -> None:
    """A scope opened by a block that raises is still closed.

    **Test steps:**

    * open a scope and raise inside the block
    * swallow the exception
    * verify the scope is None again
    """
    try:
        with LogScope.open("resource"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert LogScope.current() is None


# endregion


# region the open stack


def test_nothing_is_on_the_stack_by_default() -> None:
    """A record written with no block open is about nothing at all.

    **Test steps:**

    * read the stack without opening any scope
    * verify it is empty
    """
    assert LogScope.stack() == ()


def test_nested_scopes_stack_outermost_first() -> None:
    """A record inside two blocks is about both, in the order they were opened.

    **Test steps:**

    * open an outer scope, then an inner one inside it
    * verify the stack inside the inner block holds both, outermost first
    * verify the outer block's stack is restored after it
    """
    with LogScope.open("outer"):
        with LogScope.open("inner"):
            assert LogScope.stack() == ("outer", "inner")

        assert LogScope.stack() == ("outer",)


def test_a_none_scope_empties_the_stack_for_its_block() -> None:
    """Un-scoping a block drops every open scope, not only the innermost.

    Work that is about nothing in particular is not about the enclosing thing either, so ``None``
    cannot mean "one fewer label".

    **Test steps:**

    * open two scopes, then open None inside them
    * verify the stack is empty inside the innermost block
    * verify both outer scopes are back after it
    """
    with LogScope.open("outer"):
        with LogScope.open("inner"):
            with LogScope.open(None):
                assert LogScope.stack() == ()

            assert LogScope.stack() == ("outer", "inner")


def test_a_scope_reopened_while_already_open_keeps_its_duplicate() -> None:
    """The same key opened twice is on the stack twice, which routes identically.

    Membership is what a sink matches on, so ``(p, p)`` reaches exactly the sinks ``(p,)`` does and
    collapsing would buy only a tidier tuple.

    **Test steps:**

    * open one scope, then open the same key again inside it
    * verify the stack holds it twice
    * verify one is left after the inner block
    """
    with LogScope.open("resource"):
        with LogScope.open("resource"):
            assert LogScope.stack() == ("resource", "resource")

        assert LogScope.stack() == ("resource",)


def test_the_stack_is_restored_when_the_block_raises() -> None:
    """A stack pushed by a block that raises is still popped.

    **Test steps:**

    * open two nested scopes and raise inside the inner block
    * swallow the exception
    * verify the stack is empty again
    """
    try:
        with LogScope.open("outer"):
            with LogScope.open("inner"):
                raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert LogScope.stack() == ()


def test_the_whole_stack_travels_to_a_worker_thread() -> None:
    """A context copied at submission carries every open scope, not only the innermost.

    This is the capture a task queue owes its jobs ([[appendices.logging#scopes]]): a thread inherits
    no context of its own, so a job enqueued under a document and run under a job scope keeps both only
    because the copy took the stack whole.

    **Test steps:**

    * copy the context from inside two nested scopes
    * run a helper inside that copy, on another thread
    * verify it saw both scopes, and that the thread sees nothing without the copy
    """
    seen: list[tuple[Hashable, ...]] = []

    with LogScope.open("outer"):
        with LogScope.open("inner"):
            context = copy_context()

    carried = Thread(target=lambda: seen.append(context.run(LogScope.stack)))
    carried.start()
    carried.join()
    bare = Thread(target=lambda: seen.append(LogScope.stack()))
    bare.start()
    bare.join()

    assert seen == [("outer", "inner"), ()]


# endregion


# region placing a record


def test_a_record_logged_with_no_scope_open_is_about_nothing() -> None:
    """A record carries no scope when none was open.

    **Test steps:**

    * build a record with no scope open
    * verify LogScope.of reports an empty stack
    """
    assert LogScope.of(make_record()) == ()


def test_a_record_is_placed_by_the_open_scope() -> None:
    """A record logged inside a scope belongs to it.

    **Test steps:**

    * build a record inside an open scope
    * verify LogScope.of reports that scope
    """
    with LogScope.open("resource"):
        assert LogScope.of(make_record()) == ("resource",)


def test_an_explicit_scope_on_the_record_wins() -> None:
    """A scope named at the call site replaces the open stack rather than joining it.

    **Test steps:**

    * open two nested scopes
    * build a record carrying a different explicit scope attribute
    * verify LogScope.of reports the explicit one alone, with no trace of either open one
    """
    record = make_record(**{LOG_SCOPE_ATTRIBUTE: "explicit"})

    with LogScope.open("ambient"):
        with LogScope.open("nested"):
            assert LogScope.of(record) == ("explicit",)


def test_an_explicit_scope_is_used_with_no_scope_open() -> None:
    """A record's own scope attribute is enough on its own.

    **Test steps:**

    * build a record carrying an explicit scope, with no scope open
    * verify LogScope.of reports it
    """
    assert LogScope.of(make_record(**{LOG_SCOPE_ATTRIBUTE: "explicit"})) == ("explicit",)


# endregion
