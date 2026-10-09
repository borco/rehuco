"""MainWindow's own geometry and outer dock layout, persisted across restarts
(#21, #47).

Kept in ``main-window.json`` in the config folder, not the ``.ini`` (#404): the layout blobs were most of the group.
The old ``[main_window]`` group is neither read nor removed.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from . import state_file
from .persistent_settings import config_folder

WINDOW_FILENAME: Final = "main-window.json"
"""What the state is called, in the app's own config folder."""
WINDOW_VERSION: Final = 1
"""Schema version of the file. A file of another version reads as nothing saved."""
GEOMETRY_KEY: Final = "geometry"
OUTER_LAYOUT_KEY: Final = "outer_layout"
TOOLBARS_STATE_KEY: Final = "toolbars_state"


def main_window_state_path() -> Path:
    """Where the window's state lives: :func:`~.persistent_settings.config_folder`, beside ``task-queue.json``.

    :returns: the file's path, whether or not it exists.
    """
    return config_folder() / WINDOW_FILENAME


TOOLBARS_STATE_VERSION: Final = 2
"""Version passed to Qt's own ``QMainWindow.saveState``/``restoreState`` (the toolbar-area/floating
layout for ``action_bar`` -- distinct from :attr:`MainWindowSettings.outer_layout`,
which is QtAds' own, separate state). Qt rejects a mismatched version itself (``restoreState``
returns ``False`` and leaves the default layout), so this is passed straight through rather than
checked here. Bump whenever the toolbar set changes."""


@dataclass
class MainWindowSettings:
    """The main window's saved geometry (size/position), outer dock layout, and toolbar layout."""

    geometry: bytes = field(default=b"")
    """The window's ``saveGeometry()`` blob, or empty before any session has been saved."""

    outer_layout: dict[str, Any] | None = None
    """The outer manager's layout tree (`~borco_pyside.qtads.QtAdsLayout`, #102): the Documents dock and its
    siblings, with the Log dock's filters and the Tasks dock's nested layout folded into their entries. ``None``
    before any session has been saved."""

    toolbars_state: bytes = field(default=b"")
    """Qt's own ``QMainWindow.saveState()`` blob -- the ``action_bar`` toolbar's area/floating
    layout, distinct from :attr:`outer_layout` (QtAds' own docks). Empty before any session
    has been saved."""

    def load(self, path: Path | None = None) -> None:
        """Replace the current geometry, outer dock state, and toolbar state with what is in the state file.

        :param path: the state file; :func:`main_window_state_path` unless a test says otherwise. A missing or
            unreadable one leaves nothing saved.
        """
        values = state_file.read_state_file(path if path is not None else main_window_state_path(), WINDOW_VERSION)
        self.__read(values or {})

    def save(self, path: Path | None = None) -> None:
        """Save the geometry, outer dock state, and toolbar state to the state file.

        :param path: the state file; :func:`main_window_state_path` unless a test says otherwise.
        """
        path = path if path is not None else main_window_state_path()
        values = {
            GEOMETRY_KEY: state_file.encode_bytes(self.geometry),
            OUTER_LAYOUT_KEY: self.outer_layout,
            TOOLBARS_STATE_KEY: state_file.encode_bytes(self.toolbars_state),
        }
        state_file.write_state_file(path, WINDOW_VERSION, values)

    def __read(self, values: dict[str, object]) -> None:
        """Take the state from a file's values.

        :param values: what :func:`~.state_file.read_state_file` returned, or nothing.
        """
        self.geometry = state_file.decode_bytes(values.get(GEOMETRY_KEY))
        outer_layout = values.get(OUTER_LAYOUT_KEY)
        self.outer_layout = outer_layout if isinstance(outer_layout, dict) else None
        self.toolbars_state = state_file.decode_bytes(values.get(TOOLBARS_STATE_KEY))
