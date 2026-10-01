"""Shortcuts settings: the user's keymap -- the commands whose keys or scope they changed (#343).

Overrides only: a command never touched has no entry, so a changed default in a later version reaches
everyone who kept it. The commands themselves are the app's catalog (:mod:`rehuco_agent.commands`); this
section only stores what differs from it.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Final

from borco_pyside.shortcuts import Keymap
from PySide6.QtCore import QSettings

from .persistent_settings import persistent_settings

GROUP: Final = "shortcuts"


@dataclass
class ShortcutsSettings:
    """The keymap, stored under :data:`GROUP` as ``keys/<command id>`` and ``scope/<command id>``.

    :ivar keymap: the user's overrides.
    """

    keymap: Keymap = field(default_factory=Keymap)

    def load(self, settings: QSettings) -> None:
        """Read the keymap from ``settings``.

        :param settings: where to read from.
        """
        settings.beginGroup(GROUP)
        self.keymap.load(settings)
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Write the keymap to ``settings``, replacing what was stored.

        :param settings: where to write to.
        """
        settings.beginGroup(GROUP)
        self.keymap.save(settings)
        settings.endGroup()


@lru_cache(maxsize=1)
def shared_shortcuts_settings() -> ShortcutsSettings:
    """The app's one `ShortcutsSettings`, loaded from persistent storage on first use.

    :returns: the shared settings.
    """
    settings = ShortcutsSettings()
    settings.load(persistent_settings())
    return settings
