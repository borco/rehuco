"""How a table browser's numeric cells read (#379): the model holds the value, a delegate says it in words."""

from typing import Final, override

import humanize
from borco_pyside.widgets import RowBandDelegate
from PySide6.QtCore import QLocale

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


COLUMN_DELEGATES: Final = {
    CatalogColumn.SIZE: SizeDelegate,
    CatalogColumn.ADVERTISED_DURATION: DurationDelegate,
    CatalogColumn.ORIGINAL_DURATION: DurationDelegate,
    CatalogColumn.CURRENT_DURATION: DurationDelegate,
}
"""The columns whose values a delegate words; every other column reads as its value."""
