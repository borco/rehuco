"""How a table browser's numeric and date cells read (#379, #623): the model holds the value, a delegate words it."""

from datetime import datetime, tzinfo
from typing import Final, override

import humanize
from borco_pyside.widgets import RowBandDelegate
from PySide6.QtCore import QLocale, QObject

from ..fields.widgets.duration_edit import DurationEdit
from .catalog_table_model import CatalogColumn


class SizeDelegate(RowBandDelegate):
    """A size in bytes as a short human size, ``1.0K``; the exact bytes are the cell's tooltip, and its sort."""

    @override
    def displayText(self, value: object, locale: QLocale | QLocale.Language) -> str:  # noqa: N802  (Qt API name)
        if isinstance(value, int):
            return humanize.naturalsize(value, gnu=True)
        return super().displayText(value, locale)


class DurationDelegate(RowBandDelegate):
    """A duration in seconds as a field shows one, ``2h 15m`` ([[field-schema#duration-format]])."""

    @override
    def displayText(self, value: object, locale: QLocale | QLocale.Language) -> str:  # noqa: N802  (Qt API name)
        if isinstance(value, int):
            return DurationEdit.format(value)
        return super().displayText(value, locale)


LOCAL_TIME_FORMAT: Final = "%Y-%m-%d %H:%M:%S"
"""How :class:`LocalTimeDelegate` spells a moment, ``2026-11-08 17:32:54``."""


class LocalTimeDelegate(RowBandDelegate):
    """A UTC timestamp, ``2026-11-08T15:32:54Z``, in local time, ``2026-11-08 17:32:54`` (#623).

    A value with no time, an empty one or one that is not a timestamp reads as stored; the cell's sort stays on the
    stored value.

    :param parent: optional Qt parent.
    :param tz: the zone to show a moment in; the machine's local zone when omitted.
    """

    def __init__(self, parent: QObject | None = None, *, tz: tzinfo | None = None) -> None:
        super().__init__(parent)
        self.__tz: Final = tz

    @override
    def displayText(self, value: object, locale: QLocale | QLocale.Language) -> str:  # noqa: N802  (Qt API name)
        if isinstance(value, str):
            try:
                moment = datetime.fromisoformat(value)
            except ValueError:
                return super().displayText(value, locale)
            if moment.tzinfo is not None:
                return moment.astimezone(self.__tz).strftime(LOCAL_TIME_FORMAT)
        return super().displayText(value, locale)


COLUMN_DELEGATES: Final = {
    CatalogColumn.SIZE: SizeDelegate,
    CatalogColumn.ADVERTISED_DURATION: DurationDelegate,
    CatalogColumn.ORIGINAL_DURATION: DurationDelegate,
    CatalogColumn.CURRENT_DURATION: DurationDelegate,
    CatalogColumn.RELEASED: LocalTimeDelegate,
    CatalogColumn.UPDATED: LocalTimeDelegate,
}
"""The columns whose values a delegate words; every other column reads as its value."""
