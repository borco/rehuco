"""What the agent remembers about one ``.rehuco`` between runs: its browsers and where their sub-docks sit (#396).

``rehuco-core`` knows nothing of browsers -- they are the Browsers dock's own state (#461), kept here under the
catalog's rehuco id so that moving or renaming the ``.rehuco`` keeps them, as it keeps the ``.rehudb``
([[data-model#local-file-trio]]). It is a file of its own, not the ``.ini``: a nested dock layout is a binary blob
that grows with use, and those moved out of the ``.ini`` too (#404).
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from borco_core import atomic_write_text

from .persistent_settings import config_folder
from .state_file import decode_bytes, encode_bytes

LOG: Final = logging.getLogger(__name__)

CATALOG_STATE_FOLDER: Final = "catalogs"
"""The folder of the per-catalog files, in the app's own config folder."""

CATALOG_STATE_VERSION: Final = 2
"""Schema version of the file. A file of another version is read as empty -- it is view state, and the next close
writes a fresh one -- except :data:`ROOTS_IN_LAYOUT_VERSION`'s.

Bumped to 2 when the Roots view left the browsers' shell for a dock of its own (#461): the browsers are written
the same way, and only the layout means something else."""

ROOTS_IN_LAYOUT_VERSION: Final = 1
"""The version whose layout nests the Roots view among the browsers. Its browsers -- names, filters, columns -- are
read as they are; its layout is dropped, so the browsers open in the default arrangement rather than placed around
a Roots sub-dock that is no longer there (#461)."""

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
    """One browser as it is remembered."""

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


@dataclass
class CatalogState:
    """Everything remembered about one catalog."""

    browsers: list[BrowserState] = field(default_factory=list)
    """The browsers, in the order they were open."""

    layout: bytes = b""
    """The Browsers dock's nested dock manager's saved layout; empty to place every browser by default."""


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
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return CatalogState()
        except OSError:
            LOG.exception("The saved state of %s could not be read.", path)
            return CatalogState()
        try:
            values: Any = json.loads(text)
        except ValueError:
            LOG.error("The saved state %s is not readable JSON; it is ignored.", path)
            return CatalogState()
        version = values.get("version") if isinstance(values, dict) else None
        if version not in (CATALOG_STATE_VERSION, ROOTS_IN_LAYOUT_VERSION):
            LOG.warning("The saved state %s is not in a shape this build reads; it is ignored.", path)
            return CatalogState()
        return CatalogState(
            browsers=self.__read_browsers(values.get("browsers"), path),
            layout=decode_bytes(values.get("layout")) if version == CATALOG_STATE_VERSION else b"",
        )

    def save(self, rehuco_id: UUID, state: CatalogState) -> None:
        """Write ``rehuco_id``'s state.

        :param rehuco_id: the catalog's id.
        :param state: what to remember.
        """
        path = catalog_state_path(rehuco_id)
        payload = {
            "version": CATALOG_STATE_VERSION,
            "browsers": [
                {
                    "id": str(browser.browser_id),
                    "kind": browser.kind,
                    "name": browser.name,
                    "filter": browser.filter,
                    "columns": encode_bytes(browser.columns),
                }
                for browser in state.browsers
            ],
            "layout": encode_bytes(state.layout),
        }
        try:
            # the folder does not exist until something is first written to it
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(path, json.dumps(payload, indent=2) + "\n")
        except OSError:
            LOG.exception("The state of the catalog could not be saved to %s.", path)

    def __read_browsers(self, values: object, path: Path) -> list[BrowserState]:
        """Read the browser list, skipping an entry that is malformed or repeats an id.

        :param values: the file's ``browsers`` value.
        :param path: the file, for the log.
        :returns: the browsers that could be read, in order.
        """
        if not isinstance(values, list):
            return []
        browsers: list[BrowserState] = []
        seen: set[UUID] = set()
        for entry in values:
            browser = self.__read_browser(entry)
            if browser is None or browser.browser_id in seen:
                LOG.warning("A browser in %s is malformed or repeated; it is skipped.", path)
                continue
            seen.add(browser.browser_id)
            browsers.append(browser)
        return browsers

    def __read_browser(self, entry: object) -> BrowserState | None:
        """Read one browser entry.

        :param entry: what the file holds.
        :returns: the browser, or ``None`` if the entry is not one.
        """
        if not isinstance(entry, dict):
            return None
        try:
            browser_id = UUID(str(entry["id"]))
        except KeyError, ValueError:
            return None
        kind, name, filter_text = entry.get("kind"), entry.get("name"), entry.get("filter", "")
        if not isinstance(kind, str) or not isinstance(name, str) or not isinstance(filter_text, str):
            return None
        return BrowserState(browser_id, kind, name, filter_text, decode_bytes(entry.get("columns")))
