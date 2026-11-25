"""The balance dialog's memory: its geometry, and the roots last balanced from the menu (#681)."""

import json
from dataclasses import dataclass, field
from typing import Final, cast
from uuid import UUID

from PySide6.QtCore import QByteArray, QSettings

GROUP: Final = "balance_buckets_dialog"
GEOMETRY_KEY: Final = "geometry"
ROOTS_KEY: Final = "roots"


# Mirrors MapRootsDialogSettings's geometry load/save, as each dialog's settings do.
# pylint: disable=duplicate-code
@dataclass
class BalanceBucketsDialogSettings:
    """The balance dialog's saved geometry and the roots checked on its last accepted run from the menu."""

    geometry: bytes = field(default=b"")
    """The dialog's ``saveGeometry()`` blob, or empty before any session has been saved."""

    roots: frozenset[UUID] = field(default=frozenset())
    """The roots checked, of every catalog balanced so far."""

    def load(self, settings: QSettings) -> None:
        """Replace the current values with what's in persistent storage; stored roots that are no list of ids read as
        none.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        state = cast(QByteArray, settings.value(GEOMETRY_KEY, QByteArray(), type=QByteArray))
        self.geometry = bytes(state.data())
        self.roots = self.__parse(cast(str, settings.value(ROOTS_KEY, "", type=str)))
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the values to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(GEOMETRY_KEY, QByteArray(self.geometry))
        settings.setValue(ROOTS_KEY, json.dumps(sorted(map(str, self.roots))))
        settings.endGroup()

    @staticmethod
    def __parse(stored: str) -> frozenset[UUID]:
        """The roots a stored text holds.

        :param stored: what :meth:`save` wrote.
        :returns: the roots; none when the text is not a list of ids.
        """
        try:
            return frozenset(map(UUID, json.loads(stored)))
        except ValueError, AttributeError, TypeError:
            return frozenset()


# pylint: enable=duplicate-code
