"""Ties a log record to the parts of its message that are links, as data -- never as markup in the message."""

from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from logging import LogRecord
from typing import Final

LOG_LINKS_ATTRIBUTE: Final = "log_links"
"""Attribute name a record's links are stamped under on a `logging.LogRecord`: set through ``logging``'s own
``extra=`` (``LOG.info("%s", title, extra={LOG_LINKS_ATTRIBUTE: (LogLink(title, target),)})``).

Carried beside the message rather than inside it, so the run log file and a copied line read as the plain text they
always were."""


@dataclass(frozen=True, slots=True)
class LogLink:
    """A part of a record's message that a surface may draw as a link.

    :param text: the part of the formatted message to show as the link: its **first** occurrence after the link
        before it, so a text short enough to occur earlier in the message (a one-letter title after ``saved``)
        is linked there. Links are given in message order.
    :param target: what the host is handed back when the link is clicked. Opaque to the log stack, which never reads
        it; hashable so a surface can compare two of them.
    """

    text: str
    target: Hashable

    @staticmethod
    def of(record: LogRecord) -> tuple[LogLink, ...]:
        """Say which parts of ``record``'s message are links.

        :param record: the record to read.
        :returns: its links, in message order; empty when it carries none, or carries something that is not a
            sequence of :class:`LogLink` -- an ``extra`` is outside input, and a surface drawing a record must not
            fail on one.
        """
        links = getattr(record, LOG_LINKS_ATTRIBUTE, None)
        if not isinstance(links, Sequence) or isinstance(links, str):
            return ()
        if not all(isinstance(link, LogLink) for link in links):
            return ()
        return tuple(links)
