"""What counts as an author-page URL ([[field-schema#authors]]) -- asked by both sides of the field."""

from typing import Final
from urllib.parse import urlsplit

HTTP_SCHEMES: Final = ("http", "https")
"""The only schemes an author URL is ever followed or written with."""


def is_http_author_url(value: str) -> bool:
    """Whether ``value`` parses strictly as an absolute http/https URL.

    One predicate for a rule that "splits by side" ([[field-schema#authors]]): the **editor** enforces
    it on what it writes (a row whose URL fails it is flagged invalid), and the **viewer** applies it as
    the safety boundary on what it reads (anything failing renders as if the entry carried no URL at
    all, [[data-model#write-integrity]]). Split in two, the two sides could disagree about a single
    value -- and the disagreement's shape is an editor happily writing a link the viewer then refuses
    to show.

    :param value: the candidate URL string.
    :returns: ``True`` iff the scheme is ``http``/``https`` and a host is present.
    """
    parsed = urlsplit(value)
    return parsed.scheme in HTTP_SCHEMES and bool(parsed.netloc)
