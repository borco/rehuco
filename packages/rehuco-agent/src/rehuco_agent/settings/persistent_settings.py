"""App-wide persistent settings storage, shared by every settings section (e.g. `DocumentSessionSettings`)."""

from typing import Final

from PySide6.QtCore import QSettings

ORGANIZATION_NAME: Final = "borco"
APPLICATION_NAME: Final = "rehuco-agent"


def persistent_settings() -> QSettings:
    """A ``QSettings`` pointed at rehuco-agent's persistent per-user storage."""
    return QSettings(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, ORGANIZATION_NAME, application=APPLICATION_NAME
    )
