"""What a selected resource becomes in the Documents preview: one key, resolved in one place, shown at once
(#381)."""

from collections.abc import Callable
from pathlib import Path
from typing import Final, cast

from PySide6.QtCore import QObject, QTimer

from .catalog_table_model import RowKey
from .root_catalog import RootCatalog

SELECTION_SETTLE_MS: Final = 0
"""How long a selection stands before it is shown: no time at all. A preview switch reloads the widgets already
built, in milliseconds, so there is nothing to wait out. It still runs as a zero-length timer rather than inside
the selection's own handler: that turns the event loop once first, so the key presses an auto-repeating arrow
key has queued move the cursor through every row, and only the row it lands on is loaded."""


class SelectionPreview(QObject):
    """Turns a view's selection into one call to show a document in the preview, as soon as the input queued
    behind it has been handled.

    A selection is a ``(root_id, relative)`` key -- what a browser row and the Roots view both name a resource by --
    and :meth:`RootCatalog.resource_path` is the one place it becomes a path, read when the selection **settles**
    rather than when it is made, so a root removed in between shows nothing. Selecting nothing -- no row, several, a
    node with no record, a table a scan has just reset -- shows nothing and calls off a selection still waiting: the
    preview stays as it is.

    :param catalog: the open catalog, which resolves a key.
    :param show: shows the document at a path in the preview; what happens when the preview is already showing it is
        its own to decide.
    :param parent: optional Qt parent.
    """

    def __init__(self, catalog: RootCatalog, show: Callable[[Path], None], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__catalog: Final = catalog
        self.__show: Final = show
        self.__pending: RowKey | None = None
        self.__timer: Final = QTimer(self)
        self.__timer.setSingleShot(True)
        self.__timer.setInterval(SELECTION_SETTLE_MS)
        self.__timer.timeout.connect(self.__settle)

    def select(self, key: RowKey | None) -> None:
        """Take a selection: show it once it stands for :data:`SELECTION_SETTLE_MS`, or call off the one waiting.

        :param key: the one selected resource's ``(root_id, relative)``, or ``None`` when the selection is not one
            resource.
        """
        self.__pending = key
        if key is None:
            self.__timer.stop()
        else:
            self.__timer.start()

    def __settle(self) -> None:
        """Show the selection that has stood long enough."""
        # the timer only runs while a key is waiting: select(None) stops it
        key = cast(RowKey, self.__pending)
        self.__pending = None
        path = self.__catalog.resource_path(*key)
        if path is not None:
            self.__show(path)
