"""Per-file session state: which `.rehu` files were open, LRU-capped on save (#21).

Kept in ``document-session.json`` in the config folder, not the ``.ini`` (#404): every remembered document carries a
dock-layout blob, so the group was most of the ``.ini``. The old ``[documents]`` group is neither read nor removed.
"""

from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from . import state_file
from .maximized_view import MaximizedView
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

        maximized: MaximizedView | None = field(default=None)
        """The screenshot or video it had maximized ([[plugins#session-restore]], #576), reopened once it has loaded."""

    @dataclass
    class Preview:
        """The preview dock's entry ([[plugins#session-restore]], #576): an open document kept apart from
        :attr:`items`, so it stays out of ``Open recents`` and has no LRU place to outlive."""

        path: Path
        """The document the preview showed."""

        name: str
        """The dock's object name, which :attr:`docks_layout` knows it by."""

        item: DocumentSessionSettings.Item
        """Its layout and maximized view; always open."""

    items: Final[OrderedDict[Path, DocumentSessionSettings.Item]] = field(default_factory=OrderedDict)
    """Per-path session state, in most-recently-used order (oldest first)."""

    focused_path: Path | None = field(default=None)
    """Which open document was focused when the session was last saved, if any."""

    docks_layout: dict[str, Any] | None = field(default=None)
    """``DocumentsDock.save_state()``'s own layout tree (splits/tabs between open documents,
    `~borco_pyside.qtads.QtAdsLayout`), restored via ``DocumentsDock.restore_state()`` once the documents it
    references have reopened. ``None`` before any session has been saved."""

    maximized_dock: str = field(default="")
    """The object name of the document dock filling the Documents dock, kept beside :attr:`docks_layout` because a
    layout is always captured unmaximized ([[appendices.qt-ads#area-maximize]]); empty for none."""

    preview: DocumentSessionSettings.Preview | None = field(default=None)
    """The preview dock's entry, or ``None`` when no preview was shown."""

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

    def forget_preview(self, path: Path) -> None:
        """Drop the preview's entry when it names ``path``: its file is gone.

        :param path: the document that is gone; a no-op when the preview names another.
        """
        if self.preview is not None and self.preview.path == path:
            self.preview = None

    def load(self, path: Path | None = None) -> None:
        """Replace the current items (and focused path) with what is in the session file.

        Paths are not resolved here (#464): each was when saved, and resolving one under an unreachable share blocks
        the start ([[appendices.code-conventions#worker-threads]], :mod:`borco_core.path_presence`).

        :param path: the session file; :func:`document_session_path` unless a test says otherwise. A missing or
            unreadable one leaves an empty session.
        """
        self.items.clear()
        self.focused_path = None
        self.docks_layout = None
        self.maximized_dock = ""
        self.preview = None
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
            "docks_layout": self.docks_layout,
            "maximized_dock": self.maximized_dock,
            "preview": self.__preview_values(),
            "items": [self.__item_values(item_path, item) for item_path, item in self.items_to_save().items()],
        }
        state_file.write_state_file(path, SESSION_VERSION, values)

    @staticmethod
    def __item_values(path: Path, item: DocumentSessionSettings.Item) -> dict[str, Any]:
        """One remembered file as the session file stores it.

        :param path: the file.
        :param item: its session state.
        :returns: its JSON object.
        """
        return {
            "path": path.as_posix(),
            "open": item.open,
            "state": state_file.encode_bytes(item.state),
            "maximized": item.maximized.to_json() if item.maximized is not None else None,
        }

    def __preview_values(self) -> dict[str, Any] | None:
        """The preview's entry as the session file stores it: an item's shape and the dock's name.

        :returns: its JSON object, or ``None`` when there is no preview.
        """
        preview = self.preview
        if preview is None:
            return None
        return {**self.__item_values(preview.path, preview.item), "name": preview.name}

    @staticmethod
    def __read_path(entry: dict[str, Any]) -> Path | None:
        """The path an entry names, when it names one: absolute, and with no way out of where it says.

        :param entry: an entry of the session file.
        :returns: the path, or ``None``.
        """
        value = entry.get("path")
        if not isinstance(value, str) or not value:
            return None
        path = Path(value)
        return None if not path.is_absolute() or ".." in path.parts else path

    @staticmethod
    def __read_item(entry: dict[str, Any]) -> DocumentSessionSettings.Item:
        """An entry's session state, each field costing only itself when it is malformed.

        :param entry: an entry of the session file.
        :returns: the item.
        """
        return DocumentSessionSettings.Item(
            open=entry.get("open") is True,
            state=state_file.decode_bytes(entry.get("state")),
            maximized=MaximizedView.from_json(entry.get("maximized")),
        )

    def __read_preview(self, entry: object) -> None:
        """Take the preview's entry from a file's value, if it is one.

        :param entry: what the file holds under ``preview``.
        """
        if not isinstance(entry, dict):
            return
        path, name = self.__read_path(entry), entry.get("name")
        if path is None or not isinstance(name, str) or not name:
            return
        item = self.__read_item(entry)
        item.open = True
        self.preview = DocumentSessionSettings.Preview(path, name, item)

    def __read(self, values: dict[str, Any]) -> None:
        """Take the session from a file's values, skipping an entry that is not one -- a document named by anything but
        an absolute path included, since every saved one was, and a key cannot name another ([[nodes#access-seam]]).

        :param values: what :func:`~.state_file.read_state_file` returned.
        """
        focused = values.get("focused_path")
        self.focused_path = Path(focused) if isinstance(focused, str) and focused else None
        docks_layout = values.get("docks_layout")
        self.docks_layout = docks_layout if isinstance(docks_layout, dict) else None
        maximized_dock = values.get("maximized_dock")
        self.maximized_dock = maximized_dock if isinstance(maximized_dock, str) else ""
        self.__read_preview(values.get("preview"))
        entries = values.get("items")
        for entry in entries if isinstance(entries, list) else []:
            path = self.__read_path(entry) if isinstance(entry, dict) else None
            if path is not None:
                self.items[path] = self.__read_item(entry)
