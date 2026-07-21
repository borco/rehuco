"""The persisted identities per-user state is filed under ([[field-schema#per-user-shared]], #109).

Two distinct usernames, so per-user state carries honest provenance:

- The **current** user -- who *this install's* own UI edits are filed under. Defaults to the OS login name,
  falling back to core's :data:`~rehuco_core.DEFAULT_CURRENT_USERNAME` (``admin``) when the platform can't
  produce one.
- The **unknown** user -- who **imported** per-user state is filed under, because a favorite/rating carried
  in from a ``.tc`` file was **not** set by this identity here; its real owner is unknown. Defaults to core's
  :data:`~rehuco_core.DEFAULT_UNKNOWN_USERNAME` (``unknown``).

Read by the document-open and ``.tc``-conversion call sites (`DocumentsDock`), which thread the **current**
name into core's ``username=`` where UI edits land and the **unknown** name where imports land -- a document
keeps the username it was **opened** with for its whole life (`RehuDocument`'s ``username`` is fixed at
construction), so editing these settings affects only documents opened or converted afterwards, never ones
already open. Setting both to the same value is a supported configuration -- there is no uniqueness constraint.
"""

import getpass
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Final, cast

from PySide6.QtCore import QSettings
from rehuco_core import DEFAULT_CURRENT_USERNAME, DEFAULT_UNKNOWN_USERNAME

from .persistent_settings import persistent_settings

GROUP: Final = "identity"
CURRENT_USERNAME_KEY: Final = "username"
UNKNOWN_USERNAME_KEY: Final = "unknown_username"


def default_username() -> str:
    """The default **current** username: the OS login name, or core's
    :data:`~rehuco_core.DEFAULT_CURRENT_USERNAME` (``admin``) when the platform can't produce one
    ([[field-schema#per-user-shared]]'s seeding rule).

    :returns: the current username a fresh install (nothing persisted yet) starts with.
    """
    try:
        return getpass.getuser()
    except OSError:
        return DEFAULT_CURRENT_USERNAME


@dataclass
class IdentitySettings:
    """The two persisted identities: the current user (UI edits) and the unknown user (``.tc`` imports)."""

    current_username: str = field(default_factory=default_username)
    unknown_username: str = DEFAULT_UNKNOWN_USERNAME

    def load(self, settings: QSettings) -> None:
        """Replace both usernames with what's in persistent storage.

        A value that was never saved, or saved blank (nothing but whitespace), falls back to its own
        default rather than leaving the identity empty -- per-user state must always be filed under
        *some* name ([[field-schema#per-user-shared]]). The current username falls back to
        :func:`default_username` (the OS login), the unknown one to
        :data:`~rehuco_core.DEFAULT_UNKNOWN_USERNAME`.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        current = cast(str, settings.value(CURRENT_USERNAME_KEY, "", type=str))
        unknown = cast(str, settings.value(UNKNOWN_USERNAME_KEY, "", type=str))
        settings.endGroup()
        self.current_username = current.strip() or default_username()
        self.unknown_username = unknown.strip() or DEFAULT_UNKNOWN_USERNAME

    def save(self, settings: QSettings) -> None:
        """Save both usernames to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(CURRENT_USERNAME_KEY, self.current_username)
        settings.setValue(UNKNOWN_USERNAME_KEY, self.unknown_username)
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
