"""Per-file session state: which `.rehu` files were open, LRU-capped on save ([[implementation-plan]] A2.1/#21)."""

from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, cast

from PySide6.QtCore import QByteArray, QSettings

MAXIMUM_REMEMBERED_FILES: Final = 10
"""LRU cap on remembered closed files. Configurable later in settings (A7); a constant for now."""

GROUP: Final = "documents"
FOCUSED_PATH_KEY: Final = "focused_path"
DOCKS_STATE_KEY: Final = "docks_state"
ITEMS_KEY: Final = "items"
ITEM_PATH_KEY: Final = "path"
ITEM_OPEN_KEY: Final = "open"
ITEM_STATE_KEY: Final = "state"


@dataclass
class DocumentSessionSettings:
    """Which `.rehu` files were open, which one was focused, and each one's dock-layout state."""

    @dataclass
    class Item:
        """One remembered file's session state."""

        open: bool = field(default=False)
        """True if the file was open when the session was last saved."""

        state: bytes = field(default=b"")
        """The file's cbor2-encoded dock-layout state (``DocumentWidget.save_state()``)."""

    items: Final[OrderedDict[Path, DocumentSessionSettings.Item]] = field(default_factory=OrderedDict)
    """Per-path session state, in most-recently-used order (oldest first)."""

    focused_path: Path | None = field(default=None)
    """Which open document was focused when the session was last saved, if any."""

    docks_state: bytes = field(default=b"")
    """``DocumentsDock.save_state()``'s own layout (splits/tabs between open documents), restored
    via ``DocumentsDock.restore_state()`` only after every document it references has reopened."""

    def items_to_save(self) -> OrderedDict[Path, DocumentSessionSettings.Item]:
        """The items to persist: every open item, plus the newest closed ones up to the LRU cap.

        The full open set is always kept, even past the cap, so the session always restores
        completely; only the *closed* tail is pruned to :data:`MAXIMUM_REMEMBERED_FILES`.

        :returns: the pruned items, in their original relative order.
        """
        opened = sum(1 for item in self.items.values() if item.open)
        closed_budget = max(0, MAXIMUM_REMEMBERED_FILES - opened)

        kept: list[tuple[Path, DocumentSessionSettings.Item]] = []
        for path, item in reversed(self.items.items()):
            if not item.open:
                if closed_budget <= 0:
                    continue
                closed_budget -= 1
            kept.append((path, item))

        pruned: OrderedDict[Path, DocumentSessionSettings.Item] = OrderedDict()
        for path, item in reversed(kept):
            pruned[path] = item
        return pruned

    def load(self, settings: QSettings) -> None:
        """Replace the current items (and focused path) with what's in persistent storage.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        focused = str(settings.value(FOCUSED_PATH_KEY, ""))
        self.focused_path = Path(focused).resolve() if focused else None
        docks_state = cast(QByteArray, settings.value(DOCKS_STATE_KEY, QByteArray(), type=QByteArray))
        self.docks_state = bytes(docks_state.data())
        self.items.clear()
        for index in range(settings.beginReadArray(ITEMS_KEY)):
            settings.setArrayIndex(index)
            path = Path(str(settings.value(ITEM_PATH_KEY, ""))).resolve()
            state = cast(QByteArray, settings.value(ITEM_STATE_KEY, QByteArray(), type=QByteArray))
            self.items[path] = DocumentSessionSettings.Item(  # pylint: disable=unsupported-assignment-operation
                open=bool(settings.value(ITEM_OPEN_KEY, False, type=bool)),
                state=bytes(state.data()),
            )
        settings.endArray()
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the focused path and the LRU-pruned items to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(FOCUSED_PATH_KEY, self.focused_path.as_posix() if self.focused_path else "")
        settings.setValue(DOCKS_STATE_KEY, QByteArray(self.docks_state))
        settings.beginWriteArray(ITEMS_KEY)
        for index, (path, item) in enumerate(self.items_to_save().items()):
            settings.setArrayIndex(index)
            settings.setValue(ITEM_PATH_KEY, path.as_posix())
            settings.setValue(ITEM_OPEN_KEY, item.open)
            settings.setValue(ITEM_STATE_KEY, QByteArray(item.state))
        settings.endArray()
        settings.endGroup()
