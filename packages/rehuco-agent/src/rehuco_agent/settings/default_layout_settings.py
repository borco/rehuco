"""The saved default document dock layout, applied to newly opened documents (#62)."""

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Final, cast

from PySide6.QtCore import QByteArray, QSettings

from .persistent_settings import persistent_settings

GROUP: Final = "default_layout"
STATE_KEY: Final = "state"


@dataclass
class DefaultLayoutSettings:
    """The default document dock layout, or empty before one has ever been saved.

    A plain ``@dataclass`` rather than the reactive `QObject` shape `ImageViewerSettings` uses:
    nothing already on screen renders from this directly -- it is read only when a new document dock
    is built, or when the toolbar's "Apply default layout" action is triggered.
    """

    state: bytes = field(default=b"")
    """A :meth:`~rehuco_agent.documents.document_widget.DocumentWidget.save_state` blob, or empty
    before one has ever been saved as the default."""

    def load(self, settings: QSettings) -> None:
        """Replace the current state with what's in persistent storage.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        state = cast(QByteArray, settings.value(STATE_KEY, QByteArray(), type=QByteArray))
        self.state = bytes(state.data())
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the current state to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(STATE_KEY, QByteArray(self.state))
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
