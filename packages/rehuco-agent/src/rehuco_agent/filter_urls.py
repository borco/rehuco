"""Click-to-filter links: the one wire format a linkified value and the Root Catalog dock share
([[plugins#filter-urls]], #398).

``filter://<field>?name=<percent-encoded value>`` -- the field is the host, the value always rides the ``name``
query parameter, so any character a name can contain survives and one parser serves every field.
"""

from typing import Final
from urllib.parse import parse_qs, quote, urlsplit

from rehuco_core import CatalogField

FILTER_SCHEME: Final = "filter"
"""The internal scheme a click-to-filter link carries; never handed to the OS."""

FILTER_URL_FIELDS: Final = frozenset({CatalogField.AUTHORS, CatalogField.TAGS, CatalogField.PUBLISHERS})
"""The fields a link can filter on -- the three values the viewers linkify."""

FILTER_URL_KEY: Final = "name"
"""The query parameter the value rides."""


def filter_url(field: CatalogField, value: str) -> str:
    """The link that filters on ``value`` in ``field``.

    :param field: one of :data:`FILTER_URL_FIELDS`.
    :param value: the value, as its resource spells it.
    :returns: the ``filter://`` URL, the value percent-encoded whole.
    """
    return f"{FILTER_SCHEME}://{field.value}?{FILTER_URL_KEY}={quote(value, safe='')}"


def filter_url_token(url: str) -> tuple[CatalogField, str] | None:
    """The filter token a click-to-filter link stands for.

    :param url: the clicked link.
    :returns: its field and decoded value; ``None`` for another scheme, a field no link filters on, or a missing or
        empty ``name``.
    """
    parts = urlsplit(url)
    if parts.scheme.lower() != FILTER_SCHEME:
        return None
    field = next((field for field in FILTER_URL_FIELDS if field.value == parts.netloc.lower()), None)
    values = parse_qs(parts.query).get(FILTER_URL_KEY, [])
    if field is None or not values or not values[0]:
        return None
    return field, values[0]
