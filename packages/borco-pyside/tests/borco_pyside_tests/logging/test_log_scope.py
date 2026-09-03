"""Tests for LogScope."""

import logging
from collections.abc import Hashable

from borco_pyside.logging.log_scope import LOG_SCOPE_ATTRIBUTE, LogScope

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


# region placing a record


def test_a_record_logged_with_no_scope_open_is_about_nothing() -> None:
    """A record carries no scope when none was open.

    **Test steps:**

    * build a record with no scope open
    * verify LogScope.of reports None
    """
    assert LogScope.of(make_record()) is None


def test_a_record_is_placed_by_the_open_scope() -> None:
    """A record logged inside a scope belongs to it.

    **Test steps:**

    * build a record inside an open scope
    * verify LogScope.of reports that scope
    """
    with LogScope.open("resource"):
        assert LogScope.of(make_record()) == "resource"


def test_an_explicit_scope_on_the_record_wins() -> None:
    """A scope named at the call site beats the one the block opened.

    **Test steps:**

    * open a scope
    * build a record carrying a different explicit scope attribute
    * verify LogScope.of reports the explicit one
    """
    record = make_record(**{LOG_SCOPE_ATTRIBUTE: "explicit"})

    with LogScope.open("ambient"):
        assert LogScope.of(record) == "explicit"


def test_an_explicit_scope_is_used_with_no_scope_open() -> None:
    """A record's own scope attribute is enough on its own.

    **Test steps:**

    * build a record carrying an explicit scope, with no scope open
    * verify LogScope.of reports it
    """
    assert LogScope.of(make_record(**{LOG_SCOPE_ATTRIBUTE: "explicit"})) == "explicit"


# endregion
