"""Whether the local node runs beside the agent (#506, [[nodes#two-roles]])."""

from functools import lru_cache
from typing import Final, cast

from borco_pyside.core import SimpleProperty
from PySide6.QtCore import QObject, QSettings

from .persistent_settings import persistent_settings

GROUP: Final = "node"
ENABLED_KEY: Final = "enabled"


class NodeSettings(QObject):
    """Whether the agent starts the local node and keeps it running for as long as it runs itself.

    A reactive ``QObject`` (``SimpleProperty``), like `TraySettings`: turning this off on the settings page
    stops the node the agent already hosts, and turning it on starts it, rather than only changing what the
    next launch does. :func:`shared_node_settings` is the single, process-wide instance the System
    Integration pages' `NodeBlock` writes and `NodeHost` follows.

    :param parent: optional Qt parent.
    """

    enabled = SimpleProperty(True)
    """On by default: the node is what will serve the web pages and run the long jobs, and it costs the
    window nothing, since it starts a little after the window is up."""

    def load(self, settings: QSettings) -> None:
        """Replace the current value with what's in persistent storage.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        self.enabled = cast(bool, settings.value(ENABLED_KEY, True, type=bool))
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the current value to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(ENABLED_KEY, self.enabled)
        settings.endGroup()


@lru_cache(maxsize=1)
def shared_node_settings() -> NodeSettings:
    """The single, process-wide `NodeSettings` instance, loaded from persistent storage on first call.

    :returns: the shared instance.
    """
    settings = NodeSettings()
    settings.load(persistent_settings())
    return settings
