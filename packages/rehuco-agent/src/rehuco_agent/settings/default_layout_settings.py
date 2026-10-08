"""The saved default document dock layouts, one per resource type, applied to newly opened documents
(#62, #320).

Each group's blobs live in ``layouts/<group>.json`` in the config folder, not the ``.ini`` (#404). The old ``.ini``
group is neither read nor removed.
"""

from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Final

from . import state_file
from .persistent_settings import config_folder

LAYOUTS_FOLDER: Final = "layouts"
"""The folder of the per-group files, in the app's own config folder."""
LAYOUTS_VERSION: Final = 1
"""Schema version of the files. A file of another version reads as no defaults saved."""

GROUP: Final = "default_layout"
"""The group of the Documents dock's defaults, and the name of their file (:func:`default_layouts_path`)."""
PREVIEW_LAYOUT_GROUP: Final = "preview_layout"
"""The group the Documents dock's preview keeps each type's last arrangement under (#39), beside :data:`GROUP`.
Implicit: captured whenever the preview stops showing a type's layout, never read or written from the UI -- the
Layout button in the preview acts on :data:`GROUP`, as in any document dock."""


def default_layouts_path(group: str) -> Path:
    """Where ``group``'s layouts live, in :func:`~.persistent_settings.config_folder`.

    :param group: the settings group (:attr:`DefaultLayoutSettings.group`).
    :returns: the file's path, whether or not it exists.
    """
    return config_folder() / LAYOUTS_FOLDER / f"{group}.json"


@dataclass
class DefaultLayoutSettings:
    """The default document dock layout of each resource type, or nothing for a type none has ever
    been saved for.

    A plain ``@dataclass`` rather than the reactive `QObject` shape `ImageViewerSettings` uses:
    nothing already on screen renders from this directly -- it is read only when a new document dock
    is built, or when the toolbar's "Apply default layout" action is triggered.
    """

    group: str = GROUP
    """The settings group the blobs sit under (#380): :data:`GROUP` for the Documents dock's defaults, and
    another for a host keeping a set of its own -- so neither one's saved default ever lands on the other's
    documents."""

    states: dict[str, bytes] = field(default_factory=dict)
    """A :meth:`~rehuco_agent.documents.document_sub_docks.DocumentSubDocks.save_layout_state` blob per
    resource type, keyed by the type's main key
    (:attr:`~rehuco_agent.documents.document_sub_docks.DocumentSubDocks.layout_type`). A type with no entry
    has no default: no inheritance across types, so a tutorial layout never lands on a reference pack
    (#320). A type-less document keys by ``""`` (#354)."""

    def state_for(self, layout_type: str) -> bytes:
        """The saved default of one type.

        :param layout_type: the type's main key.
        :returns: its blob, or empty when none has been saved for it.
        """
        return self.states.get(layout_type, b"")

    def load(self, path: Path | None = None) -> None:
        """Replace the current states with what is in the group's file.

        :param path: the group's file; :func:`default_layouts_path` unless a test says otherwise. A missing or
            unreadable one leaves no default saved.
        """
        self.states.clear()
        values = state_file.read_state_file(
            path if path is not None else default_layouts_path(self.group), LAYOUTS_VERSION
        )
        saved = values.get("states") if values is not None else None
        for layout_type, blob in (saved if isinstance(saved, dict) else {}).items():
            state = state_file.decode_bytes(blob)
            if state:
                self.states[layout_type] = state  # pylint: disable=unsupported-assignment-operation

    def save(self, path: Path | None = None) -> None:
        """Save the current states to the group's file, dropping every type no longer held.

        :param path: the group's file; :func:`default_layouts_path` unless a test says otherwise.
        """
        path = path if path is not None else default_layouts_path(self.group)
        values = {"states": {layout_type: state_file.encode_bytes(state) for layout_type, state in self.states.items()}}
        state_file.write_state_file(path, LAYOUTS_VERSION, values)


@cache
def shared_default_layout_settings_in(group: str) -> DefaultLayoutSettings:
    """The single, process-wide `DefaultLayoutSettings` instance of ``group``, loaded from persistent
    storage on
    first call -- the same shape, and for the same reason, as
    :func:`~rehuco_agent.settings.checksum_settings.shared_checksum_settings`: every open
    `~rehuco_agent.documents.document_sub_docks.DocumentSubDocks`' "Save current layout as default"
    in that group writes onto this one instance, and every newly opened document reads it back from the
    same place. One instance per group (#380), so ``cache_clear`` resets them all.

    :param group: the settings group (:attr:`DefaultLayoutSettings.group`).
    :returns: the shared instance.
    """
    settings = DefaultLayoutSettings(group=group)
    settings.load()
    return settings


def shared_default_layout_settings() -> DefaultLayoutSettings:
    """The Documents dock's own shared `DefaultLayoutSettings`, under :data:`GROUP` -- the instance
    :func:`shared_default_layout_settings_in` keeps for it, not a second one.

    :returns: the shared instance.
    """
    return shared_default_layout_settings_in(GROUP)
