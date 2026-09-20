"""The saved default document dock layouts, one per resource type, applied to newly opened documents
(#62, #320)."""

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Final, cast

from PySide6.QtCore import QByteArray, QSettings

from .persistent_settings import persistent_settings

GROUP: Final = "default_layout"
STATE_KEY: Final = "state"
"""Each type's blob sits at ``default_layout/<type>/state``. Before #320 one untyped blob sat at
``default_layout/state``; it was written against the pre-split dock set, so it is dropped rather than
migrated -- :meth:`DefaultLayoutSettings.load` ignores it and :meth:`DefaultLayoutSettings.save` removes it."""


@dataclass
class DefaultLayoutSettings:
    """The default document dock layout of each resource type, or nothing for a type none has ever
    been saved for.

    A plain ``@dataclass`` rather than the reactive `QObject` shape `ImageViewerSettings` uses:
    nothing already on screen renders from this directly -- it is read only when a new document dock
    is built, or when the toolbar's "Apply default layout" action is triggered.
    """

    states: dict[str, bytes] = field(default_factory=dict)
    """A :meth:`~rehuco_agent.documents.document_widget.DocumentWidget.save_layout_state` blob per
    resource type, keyed by the type's main key
    (:attr:`~rehuco_agent.documents.document_widget.DocumentWidget.layout_type`). A type with no entry
    has no default: no inheritance across types, so a tutorial layout never lands on a reference pack
    (#320)."""

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
        settings.beginGroup(GROUP)
        self.states.clear()
        for layout_type in settings.childGroups():
            settings.beginGroup(layout_type)
            state = bytes(cast(QByteArray, settings.value(STATE_KEY, QByteArray(), type=QByteArray)).data())
            settings.endGroup()
            if state:
                self.states[layout_type] = state  # pylint: disable=unsupported-assignment-operation
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the current states to persistent storage, dropping every type no longer held and the
        pre-#320 untyped blob.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.remove(STATE_KEY)
        for stale in settings.childGroups():
            if stale not in self.states:
                settings.remove(stale)
        for layout_type, state in self.states.items():
            settings.beginGroup(layout_type)
            settings.setValue(STATE_KEY, QByteArray(state))
            settings.endGroup()
        settings.endGroup()


@lru_cache(maxsize=1)
def shared_default_layout_settings() -> DefaultLayoutSettings:
    """The single, process-wide `DefaultLayoutSettings` instance, loaded from persistent storage on
    first call -- the same shape, and for the same reason, as
    :func:`~rehuco_agent.settings.checksum_settings.shared_checksum_settings`: every open
    `~rehuco_agent.documents.document_widget.DocumentWidget`'s "Save current layout as default"
    writes onto this one instance, and every newly opened document reads it back from the same place.

    :returns: the shared instance.
    """
    settings = DefaultLayoutSettings()
    settings.load(persistent_settings())
    return settings
