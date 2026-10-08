"""Per-file session state: which `.rehu` files were open, LRU-capped on save (#21).

Kept in ``document-session.json`` in the config folder, not the ``.ini`` (#404): every remembered document carries a
dock-layout blob, so the group was most of the ``.ini``. The old ``[documents]`` group is neither read nor removed.
"""

from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from . import state_file
from .persistent_settings import config_folder

MAXIMUM_REMEMBERED_FILES: Final = 10
"""LRU cap on remembered closed files. Configurable later in settings; a constant for now."""

SESSION_FILENAME: Final = "document-session.json"
"""What the session is called, in the app's own config folder."""
SESSION_VERSION: Final = 1
"""Schema version of the file. A file of another version reads as no session."""


def document_session_path() -> Path:
    """Where the session lives: :func:`~.persistent_settings.config_folder`, beside ``task-queue.json``.

    :returns: the file's path, whether or not it exists.
    """
    return config_folder() / SESSION_FILENAME


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

    def forget(self, path: Path) -> None:
        """Drop ``path`` for good (#464): its file is gone, and the device it was on answered to say so.

        Its remembered layout goes with it -- there is nothing left to lay out -- and so does the focus, which moves
        to the open document next in line (the one after it in the order the session lists them, else the one before),
        or to none.

        :param path: the remembered document; a no-op when it is not remembered.
        """
        if path not in self.items:
            return
        if self.focused_path == path:
            order = list(self.items)
            position = order.index(path)
            open_others = [other for other in order if other != path and self.items[other].open]
            after = [other for other in open_others if order.index(other) > position]
            self.focused_path = after[0] if after else open_others[-1] if open_others else None
        del self.items[path]

    def load(self, path: Path | None = None) -> None:
        """Replace the current items (and focused path) with what is in the session file.

        Paths are not resolved here (#464): each was when saved, and resolving one under an unreachable share blocks
        the start ([[appendices.code-conventions#worker-threads]], :mod:`borco_core.path_presence`).

        :param path: the session file; :func:`document_session_path` unless a test says otherwise. A missing or
            unreadable one leaves an empty session.
        """
        self.items.clear()
        self.focused_path = None
        self.docks_state = b""
        values = state_file.read_state_file(path if path is not None else document_session_path(), SESSION_VERSION)
        if values is not None:
            self.__read(values)

    def save(self, path: Path | None = None) -> None:
        """Save the focused path and the LRU-pruned items to the session file.

        :param path: the session file; :func:`document_session_path` unless a test says otherwise.
        """
        path = path if path is not None else document_session_path()
        values = {
            "focused_path": self.focused_path.as_posix() if self.focused_path else "",
            "docks_state": state_file.encode_bytes(self.docks_state),
            "items": [
                {"path": item_path.as_posix(), "open": item.open, "state": state_file.encode_bytes(item.state)}
                for item_path, item in self.items_to_save().items()
            ],
        }
        state_file.write_state_file(path, SESSION_VERSION, values)

    def __read(self, values: dict[str, Any]) -> None:
        """Take the session from a file's values, skipping an entry that is not one.

        :param values: what :func:`~.state_file.read_state_file` returned.
        """
        focused = values.get("focused_path")
        self.focused_path = Path(focused) if isinstance(focused, str) and focused else None
        self.docks_state = state_file.decode_bytes(values.get("docks_state"))
        entries = values.get("items")
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not entry["path"]:
                continue
            self.items[Path(entry["path"])] = DocumentSessionSettings.Item(
                open=entry.get("open") is True,
                state=state_file.decode_bytes(entry.get("state")),
            )
