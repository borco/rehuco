"""The saved default document dock layouts, one per resource type, applied to newly opened documents
(#62, #320)."""

from dataclasses import dataclass, field
from functools import cache
from typing import Final, cast

from PySide6.QtCore import QByteArray, QSettings

from .persistent_settings import persistent_settings

GROUP: Final = "default_layout"
STATE_KEY: Final = "state"
"""Each type's blob sits at ``default_layout/<type>/state``. Before #320 one untyped blob sat at
``default_layout/state``; it was written against the pre-split dock set, so it is dropped rather than
migrated -- :meth:`DefaultLayoutSettings.load` ignores it and :meth:`DefaultLayoutSettings.save` removes it."""
UNTYPED_GROUP: Final = "_untyped"
"""The group the empty type's blob sits under (#354): ``default_layout//state`` is malformed, and the
pre-#320 ``default_layout/state`` is the blob :meth:`DefaultLayoutSettings.save` drops. Translated at
this storage boundary only -- in :attr:`DefaultLayoutSettings.states` the empty type keys by ``""``."""


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
    another for a host keeping a set of its own (the Root Catalog dock, #381) -- so neither one's saved
    default ever lands on the other's documents."""

    states: dict[str, bytes] = field(default_factory=dict)
    """A :meth:`~rehuco_agent.documents.document_sub_docks.DocumentSubDocks.save_layout_state` blob per
    resource type, keyed by the type's main key
    (:attr:`~rehuco_agent.documents.document_sub_docks.DocumentSubDocks.layout_type`). A type with no entry
    has no default: no inheritance across types, so a tutorial layout never lands on a reference pack
    (#320). A type-less document keys by ``""``, stored under :data:`UNTYPED_GROUP` (#354)."""

    def state_for(self, layout_type: str) -> bytes:
        """The saved default of one type.

        :param layout_type: the type's main key.
        :returns: its blob, or empty when none has been saved for it.
        """
        return self.states.get(layout_type, b"")

    def load(self, settings: QSettings) -> None:
        """Replace the current states with what's in persistent storage.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(self.group)
        self.states.clear()
        for group in settings.childGroups():
            settings.beginGroup(group)
            state = bytes(cast(QByteArray, settings.value(STATE_KEY, QByteArray(), type=QByteArray)).data())
            settings.endGroup()
            if state:
                layout_type = "" if group == UNTYPED_GROUP else group
                self.states[layout_type] = state  # pylint: disable=unsupported-assignment-operation
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the current states to persistent storage, dropping every type no longer held and the
        pre-#320 untyped blob.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(self.group)
        settings.remove(STATE_KEY)
        groups = {layout_type or UNTYPED_GROUP: state for layout_type, state in self.states.items()}
        for stale in settings.childGroups():
            if stale not in groups:
                settings.remove(stale)
        for group, state in groups.items():
            settings.beginGroup(group)
            settings.setValue(STATE_KEY, QByteArray(state))
            settings.endGroup()
        settings.endGroup()


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
    settings.load(persistent_settings())
    return settings


def shared_default_layout_settings() -> DefaultLayoutSettings:
    """The Documents dock's own shared `DefaultLayoutSettings`, under :data:`GROUP` -- the instance
    :func:`shared_default_layout_settings_in` keeps for it, not a second one.

    :returns: the shared instance.
    """
    return shared_default_layout_settings_in(GROUP)
