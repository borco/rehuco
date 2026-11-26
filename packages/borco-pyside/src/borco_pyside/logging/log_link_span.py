"""A record's link, placed in the message a surface draws."""

from collections.abc import Hashable, Iterable
from dataclasses import dataclass

from borco_core.logging import LogLink


@dataclass(frozen=True, slots=True)
class LogLinkSpan:
    """Where one link sits in a :attr:`~.log_entry.LogEntry.message`, and what a click on it hands back.

    :param start: offset of its first character in the formatted message.
    :param end: offset just past its last character.
    :param target: what the host is handed back; see :attr:`borco_core.logging.LogLink.target`.
    """

    start: int
    end: int
    target: Hashable

    @staticmethod
    def placed(message: str, links: Iterable[LogLink]) -> tuple[LogLinkSpan, ...]:
        """Find each link's text in the formatted message, once, when the record arrives.

        Searched in order, each from where the one before ended, so a title and the address after it are found at
        their own places even when one repeats the other's text. Offsets are into the **formatted** message, which is
        what a surface draws, so whatever a formatter put in front of it cannot shift them.

        :param message: the formatted message.
        :param links: the record's links, in message order.
        :returns: the spans, in order; a link whose text is empty, or is not found after the one before, is left out.
        """
        spans: list[LogLinkSpan] = []
        cursor = 0
        for link in links:
            if not link.text:
                continue
            start = message.find(link.text, cursor)
            if start < 0:
                continue
            cursor = start + len(link.text)
            spans.append(LogLinkSpan(start, cursor, link.target))
        return tuple(spans)
