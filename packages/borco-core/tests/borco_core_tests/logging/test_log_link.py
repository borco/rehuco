"""Tests for LogLink."""

import logging

from borco_core.logging.log_link import LOG_LINKS_ATTRIBUTE, LogLink


def make_record(**extra: object) -> logging.LogRecord:
    """Build a record the way ``logging`` does, optionally carrying extras.

    :param extra: attributes to stamp on the record, as ``logging``'s own ``extra=`` would.
    :returns: the record.
    """
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "message", None, None)
    for name, value in extra.items():
        setattr(record, name, value)
    return record


def test_a_record_without_links_has_none() -> None:
    """**Test steps:**

    * read the links of a record that names none
    * verify there are none
    """
    assert not LogLink.of(make_record())


def test_a_record_carries_its_links_in_order() -> None:
    """**Test steps:**

    * stamp a record with two links
    * verify they are read back, in order
    """
    links = (LogLink("title", 1), LogLink("https://example.com", "https://example.com"))

    assert LogLink.of(make_record(**{LOG_LINKS_ATTRIBUTE: links})) == links


def test_a_list_of_links_is_read_too() -> None:
    """**Test steps:**

    * stamp a record with a list of one link
    * verify it is read back as a tuple
    """
    link = LogLink("title", 1)

    assert LogLink.of(make_record(**{LOG_LINKS_ATTRIBUTE: [link]})) == (link,)


def test_anything_that_is_not_a_sequence_of_links_is_none() -> None:
    """**Test steps:**

    * stamp a record with a string, a number, a sequence holding a non-link and a bare object
    * verify each reads as no links
    """
    for value in ("a string", 7, (LogLink("title", 1), "not a link"), object()):
        assert not LogLink.of(make_record(**{LOG_LINKS_ATTRIBUTE: value}))


def test_a_link_is_comparable_and_hashable() -> None:
    """**Test steps:**

    * build two equal links
    * verify they compare equal and collapse in a set
    """
    assert LogLink("title", 1) == LogLink("title", 1)
    assert len({LogLink("title", 1), LogLink("title", 1)}) == 1
