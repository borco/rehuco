"""Tests for the app-wide persistent settings storage helper."""

from PySide6.QtCore import QSettings
from rehuco_agent.settings.persistent_settings import APPLICATION_NAME, ORGANIZATION_NAME, persistent_settings


def test_persistent_settings_is_scoped_to_this_app() -> None:
    """The returned ``QSettings`` is an ini-format, per-user store identified as rehuco-agent's.

    **Test steps:**

    * call ``persistent_settings``
    * verify its format, scope, organization, and application name
    """
    settings = persistent_settings()

    assert settings.format() == QSettings.Format.IniFormat
    assert settings.scope() == QSettings.Scope.UserScope
    assert settings.organizationName() == ORGANIZATION_NAME
    assert settings.applicationName() == APPLICATION_NAME
