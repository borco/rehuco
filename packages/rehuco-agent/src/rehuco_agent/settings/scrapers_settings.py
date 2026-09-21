"""Where the Scrapers settings page keeps the scripts folder ([[acquisition-tooling#scraper-registry]]).

A plain `@dataclass`, like `ChecksumSettings` and `VideosSettings`: nothing already on screen renders
from this, it is read only when `rehuco_agent.scraping.registry.ScraperRegistry` reloads.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final, cast

from PySide6.QtCore import QSettings

from .persistent_settings import APPLICATION_NAME, persistent_settings

GROUP: Final = "scrapers"
SCRIPTS_FOLDER_KEY: Final = "scripts_folder"


def default_scripts_folder() -> Path:
    """Where the scripts folder lives when nothing has been configured.

    Derived from `persistent_settings`'s own `.ini` location rather than `QStandardPaths.AppConfigLocation`
    -- that call needs an organization/application name set on `QCoreApplication`, which nothing in this
    app does today, while the `.ini`'s path already carries both. Its *parent* alone is the
    **organization** directory (``…/borco/``, shared by every borco app), so the application name is
    appended here to land under this app's own config directory specifically.

    :returns: the default scripts folder. Not created by this call; a registry reading a folder that
        does not exist simply finds no scripts in it.
    """
    return Path(persistent_settings().fileName()).parent / APPLICATION_NAME / "scrapers"


@dataclass
class ScrapersSettings:
    """Where the user's own scraper scripts live.

    :attr:`scripts_folder` is stored as the page left it; what `ScraperRegistry` reads is
    :attr:`effective_scripts_folder`, the value it resolves to.
    """

    scripts_folder: str = ""
    """The configured scripts folder, or empty to use :func:`default_scripts_folder`."""

    @property
    def effective_scripts_folder(self) -> Path:
        """The folder `ScraperRegistry.reload` actually scans: :attr:`scripts_folder` when set, else
        :func:`default_scripts_folder`.
        """
        return Path(self.scripts_folder) if self.scripts_folder else default_scripts_folder()

    def load(self, settings: QSettings) -> None:
        """Replace the current value with what's in persistent storage.

        :param settings: the `QSettings` to read from.
        """
        settings.beginGroup(GROUP)
        self.scripts_folder = cast(str, settings.value(SCRIPTS_FOLDER_KEY, "", type=str))
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the current value to persistent storage.

        :param settings: the `QSettings` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(SCRIPTS_FOLDER_KEY, self.scripts_folder)
        settings.endGroup()


@lru_cache(maxsize=1)
def shared_scrapers_settings() -> ScrapersSettings:
    """The single, process-wide `ScrapersSettings` instance, loaded from persistent storage on first
    call -- the same shape, and for the same reason, as `shared_checksum_settings`: the settings page's
    Save must be what the next `ScraperRegistry.reload` reads.

    :returns: the shared instance.
    """
    settings = ScrapersSettings()
    settings.load(persistent_settings())
    return settings
