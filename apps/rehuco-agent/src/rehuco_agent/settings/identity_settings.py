"""The persisted identity: the username per-user state is filed under ([[field-schema#per-user-shared]], #99).

Read by the document-open and ``.tc``-conversion call sites (`DocumentsDock`), which thread it into
core's ``username=`` parameters -- a document keeps the username it was **opened** with for its whole
life (`RehuDocument`'s ``username`` is fixed at construction), so editing this setting affects only
documents opened or converted afterwards, never ones already open.
"""

import getpass
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Final, cast

from PySide6.QtCore import QSettings
from rehuco_core import DEFAULT_USERNAME

from .persistent_settings import persistent_settings

GROUP: Final = "identity"
USERNAME_KEY: Final = "username"


def default_username() -> str:
    """The OS login name, or core's :data:`~rehuco_core.DEFAULT_USERNAME` (``admin``) when the
    platform can't produce one ([[field-schema#per-user-shared]]'s seeding rule).

    :returns: the username a fresh install (nothing persisted yet) starts with.
    """
    try:
        return getpass.getuser()
    except OSError:
        return DEFAULT_USERNAME


@dataclass
class IdentitySettings:
    """The single persisted username."""

    username: str = field(default_factory=default_username)

    def load(self, settings: QSettings) -> None:
        """Replace the current username with what's in persistent storage.

        A value that was never saved, or saved blank (nothing but whitespace), falls back to
        :func:`default_username` rather than leaving the identity empty -- per-user state must
        always be filed under *some* name ([[field-schema#per-user-shared]]).

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        value = cast(str, settings.value(USERNAME_KEY, "", type=str))
        settings.endGroup()
        self.username = value.strip() or default_username()

    def save(self, settings: QSettings) -> None:
        """Save the current username to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(USERNAME_KEY, self.username)
        settings.endGroup()


@lru_cache(maxsize=1)
def shared_identity_settings() -> IdentitySettings:
    """The single, process-wide `IdentitySettings` instance, loaded from persistent storage on
    first call -- the same shape as
    :func:`~rehuco_agent.settings.markdown_rendering_settings.shared_markdown_rendering_settings`,
    and shared for the same reason: the settings page's Save must be what the next document open
    reads, not a disconnected per-reader copy.

    :returns: the shared instance.
    """
    settings = IdentitySettings()
    settings.load(persistent_settings())
    return settings
