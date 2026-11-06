"""What the agent remembers about one ``.rehuco`` between runs: its browsers and where their sub-docks sit (#396).

``rehuco-core`` knows nothing of browsers -- they are the Browsers dock's own state (#461), kept here under the
catalog's rehuco id so that moving or renaming the ``.rehuco`` keeps them, as it keeps the ``.rehudb``
([[data-model#local-file-trio]]). It is a file of its own, not the ``.ini``: a nested dock layout grows with use, and
those moved out of the ``.ini`` too (#404).
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from borco_core import atomic_write_text

from .persistent_settings import config_folder
from .state_file import UNREAD, decode_bytes, encode_bytes, read_json_file, set_aside_unread

LOG: Final = logging.getLogger(__name__)

CATALOG_STATE_FOLDER: Final = "catalogs"
"""The folder of the per-catalog files, in the app's own config folder."""

CATALOG_STATE_VERSION: Final = 2
"""Schema version of the file. A file of another version is read as empty -- it is view state, and the next close
writes a fresh one."""

TABLE_BROWSER_KIND: Final = "table"
"""The kind of a browser showing the cache's rows as a table; the image browser (#403) will be the second."""


def catalog_state_path(rehuco_id: UUID) -> Path:
    """Where ``rehuco_id``'s state lives, in :func:`~.persistent_settings.config_folder`.

    :param rehuco_id: the catalog's id.
    :returns: the file's path, whether or not it exists.
    """
    return config_folder() / CATALOG_STATE_FOLDER / f"{rehuco_id}.json"


@dataclass(frozen=True, slots=True)
class BrowserState:
    """One browser as it is remembered: what its sub-dock's entry in the layout carries (#102)."""

    browser_id: UUID
    """Stable for the browser's life; the object name of its dock, so a saved layout finds it."""

    kind: str
    """What the browser shows, e.g. :data:`TABLE_BROWSER_KIND`."""

    name: str
    """What its tab says."""

    filter: str = ""
    """The filter line's text (#398); empty until there is one."""

    columns: bytes = b""
    """The table header's saved state -- column widths, order, visibility and sort."""

    selection: tuple[tuple[UUID, str], ...] = ()
    """The selected rows' ``(root_id, relative)`` keys, re-selected once the rows load ([[plugins#session-restore]],
    #576)."""

    def to_bytes(self) -> bytes:
        """This browser as its layout entry stores it.

        :returns: UTF-8 JSON, readable by :meth:`from_bytes`.
        """
        values = {
            "id": str(self.browser_id),
            "kind": self.kind,
            "name": self.name,
            "filter": self.filter,
            "columns": encode_bytes(self.columns),
            "selection": [[str(root_id), relative] for root_id, relative in self.selection],
        }
        return json.dumps(values).encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> BrowserState | None:
        """Read a browser back from :meth:`to_bytes`.

        :param data: what its layout entry carried.
        :returns: the browser, or ``None`` if ``data`` is not one.
        """
        try:
            entry: Any = json.loads(data.decode("utf-8"))
        except ValueError:
            return None
        if not isinstance(entry, dict):
            return None
        try:
            browser_id = UUID(str(entry["id"]))
        except KeyError, ValueError:
            return None
        kind, name, filter_text = entry.get("kind"), entry.get("name"), entry.get("filter", "")
        if not isinstance(kind, str) or not isinstance(name, str) or not isinstance(filter_text, str):
            return None
        selection = cls.__read_selection(entry.get("selection"))
        return cls(browser_id, kind, name, filter_text, decode_bytes(entry.get("columns")), selection)

    @staticmethod
    def __read_selection(entries: object) -> tuple[tuple[UUID, str], ...]:
        """Read the selected rows' keys, skipping an entry that is not one.

        :param entries: what the file holds under ``selection``.
        :returns: the keys.
        """
        keys: list[tuple[UUID, str]] = []
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry, list) and len(entry) == 2 and isinstance(entry[1], str):
                try:
                    keys.append((UUID(str(entry[0])), entry[1]))
                except ValueError:
                    continue
        return tuple(keys)


@dataclass
class CatalogState:
    """Everything remembered about one catalog."""

    layout: dict[str, Any] | None = None
    """The Browsers dock's nested layout (`~borco_pyside.qtads.QtAdsLayout`), each browser's
    :class:`BrowserState` in its sub-dock's entry; ``None`` to open one default browser."""

    maximized_dock: str = ""
    """The object name of the browser's sub-dock filling the dock, kept beside :attr:`layout` because a layout is always
    captured unmaximized ([[appendices.qt-ads#area-maximize]], #576); empty for none."""

    roots_current: tuple[UUID, tuple[str, ...]] | None = None
    """The Root Catalog's current row: its root and the names down from it, walked again as the listings arrive
    ([[plugins#session-restore]], #576)."""


class CatalogStateStore:
    """Reads and writes :class:`CatalogState` files, one per catalog.

    **Lenient on read, silent on write**: this is view state, so a file that is missing, unreadable, of another
    version or hand-damaged costs the catalog its remembered browsers and nothing else -- it is logged and read as
    empty -- and a write that fails is logged, never raised, because losing a layout must not block closing.
    """

    def load(self, rehuco_id: UUID) -> CatalogState:
        """Read ``rehuco_id``'s state.

        :param rehuco_id: the catalog's id.
        :returns: its state; empty when there is none, or none that can be read.
        """
        path = catalog_state_path(rehuco_id)
        values = read_json_file(path)
        if values is None:
            return CatalogState()
        if not isinstance(values, dict) or values.get("version") != CATALOG_STATE_VERSION:
            LOG.warning("The saved state %s is not in a shape this build reads; it is ignored.", path)
            UNREAD.add(path)
            return CatalogState()
        layout, maximized_dock = values.get("layout"), values.get("maximized_dock")
        return CatalogState(
            layout if isinstance(layout, dict) else None,
            maximized_dock if isinstance(maximized_dock, str) else "",
            self.__read_roots_current(values.get("roots_current")),
        )

    def save_browsers(self, rehuco_id: UUID, layout: dict[str, Any] | None, maximized_dock: str) -> None:
        """Write the Browsers dock's half of ``rehuco_id``'s state, keeping the Root Catalog's.

        :param rehuco_id: the catalog's id.
        :param layout: the dock's nested layout.
        :param maximized_dock: the object name of the sub-dock filling it, or empty.
        """
        state = self.load(rehuco_id)
        state.layout, state.maximized_dock = layout, maximized_dock
        self.save(rehuco_id, state)

    def save_roots_current(self, rehuco_id: UUID, current: tuple[UUID, tuple[str, ...]] | None) -> None:
        """Write the Root Catalog's half of ``rehuco_id``'s state, keeping the Browsers dock's.

        :param rehuco_id: the catalog's id.
        :param current: its current row's root and the names down from it, or ``None``.
        """
        state = self.load(rehuco_id)
        state.roots_current = current
        self.save(rehuco_id, state)

    @staticmethod
    def __read_roots_current(entry: object) -> tuple[UUID, tuple[str, ...]] | None:
        """Read the Root Catalog's current row, if ``entry`` is one.

        :param entry: what the file holds under ``roots_current``.
        :returns: its root and the names down from it, or ``None``.
        """
        if not isinstance(entry, dict):
            return None
        names = entry.get("path")
        if not isinstance(names, list) or not all(isinstance(name, str) and name for name in names):
            return None
        try:
            return UUID(str(entry.get("root"))), tuple(names)
        except ValueError:
            return None

    def save(self, rehuco_id: UUID, state: CatalogState) -> None:
        """Write ``rehuco_id``'s state.

        :param rehuco_id: the catalog's id.
        :param state: what to remember.
        """
        path = catalog_state_path(rehuco_id)
        current = state.roots_current
        payload = {
            "version": CATALOG_STATE_VERSION,
            "layout": state.layout,
            "maximized_dock": state.maximized_dock,
            "roots_current": None if current is None else {"root": str(current[0]), "path": list(current[1])},
        }
        try:
            # the folder does not exist until something is first written to it
            path.parent.mkdir(parents=True, exist_ok=True)
            set_aside_unread(path)
            atomic_write_text(path, json.dumps(payload, indent=2) + "\n")
        except OSError:
            LOG.exception("The state of the catalog could not be saved to %s.", path)
