"""The library wizard dialog's memory: the root last used for each scraper wizard
([[acquisition-tooling#library-wizard-protocol]], #685).
"""

import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Final, cast
from uuid import UUID

from PySide6.QtCore import QSettings

from .persistent_settings import persistent_settings

GROUP: Final = "library_wizard"
ROOTS_KEY: Final = "roots"


@dataclass
class LibraryWizardSettings:
    """The root each scraper wizard last started a scan into, preselected the next time that site is chosen."""

    roots: dict[str, UUID] = field(default_factory=dict)
    """The root last used, by the wizard's :attr:`~rehuco_agent.scraping.scraper_wizard.ScraperWizard.key`."""

    def load(self, settings: QSettings) -> None:
        """Replace the current roots with what's in persistent storage; a stored value that is not a map of ids reads
        as none.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        stored = cast(str, settings.value(ROOTS_KEY, "", type=str))
        settings.endGroup()
        self.roots = self.__parse(stored)

    def save(self, settings: QSettings) -> None:
        """Save the roots to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(ROOTS_KEY, json.dumps({key: str(root) for key, root in sorted(self.roots.items())}))
        settings.endGroup()

    @staticmethod
    def __parse(stored: str) -> dict[str, UUID]:
        """The roots a stored text holds.

        :param stored: what :meth:`save` wrote.
        :returns: the roots; empty when the text is not a map of wizard keys to ids.
        """
        try:
            loaded = json.loads(stored)
            return {key: UUID(root) for key, root in loaded.items()}
        except ValueError, AttributeError, TypeError:
            return {}


@lru_cache(maxsize=1)
def shared_library_wizard_settings() -> LibraryWizardSettings:
    """The single, process-wide `LibraryWizardSettings`, loaded from persistent storage on first call.

    :returns: the shared instance.
    """
    settings = LibraryWizardSettings()
    settings.load(persistent_settings())
    return settings
