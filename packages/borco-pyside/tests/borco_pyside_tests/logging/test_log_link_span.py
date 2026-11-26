"""Tests for LogLinkSpan."""

from borco_core.logging import LogLink
from borco_pyside.logging.log_link_span import LogLinkSpan


def test_a_link_is_found_in_the_message() -> None:
    """A link's text is placed where it sits in the formatted message.

    **Test steps:**

    * Place one link in a message that has other text around it.
    * Assert the span covers exactly the link's text and carries its target.
    """
    message = "saved title now"

    spans = LogLinkSpan.placed(message, [LogLink("title", 7)])

    assert spans == (LogLinkSpan(6, 11, 7),)
    assert message[spans[0].start : spans[0].end] == "title"


def test_each_link_is_searched_after_the_one_before() -> None:
    """A link repeating an earlier one's text is found at its own place, not the earlier one's.

    **Test steps:**

    * Place a title and then an address that contains the title's text.
    * Assert the second span lies after the first.
    """
    message = "Pack - https://store/Pack: added"

    spans = LogLinkSpan.placed(message, [LogLink("Pack", "record"), LogLink("https://store/Pack", "page")])

    assert [(span.start, span.end, span.target) for span in spans] == [(0, 4, "record"), (7, 25, "page")]


def test_a_link_not_in_the_message_or_empty_is_left_out() -> None:
    """A link that cannot be placed does not stop the others being placed.

    **Test steps:**

    * Place an absent link, an empty one and a present one.
    * Assert only the present one has a span.
    """
    spans = LogLinkSpan.placed("hello world", [LogLink("absent", 1), LogLink("", 2), LogLink("world", 3)])

    assert spans == (LogLinkSpan(6, 11, 3),)


def test_a_link_out_of_message_order_is_left_out() -> None:
    """Links are in message order: one that sits before the one placed ahead of it is not found.

    **Test steps:**

    * Place the later text first, then the earlier.
    * Assert only the first has a span.
    """
    assert LogLinkSpan.placed("one two", [LogLink("two", 2), LogLink("one", 1)]) == (LogLinkSpan(4, 7, 2),)


def test_no_links_place_nothing() -> None:
    """A record without links has no spans.

    **Test steps:**

    * Place an empty list.
    * Assert the result is empty.
    """
    assert not LogLinkSpan.placed("message", [])
