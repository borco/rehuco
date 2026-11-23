"""Fab as the first store whose library a scan reads ([[acquisition-tooling#library-wizard-protocol]], #684).

One class is every role Fab plays: the *scraper* a dropped listing is read by (`~.fab.Fab`, which it extends), the
*wizard* the dialog offers and the *site* a scan reads its library through. The Scrapers page shows a class once, so
Fab is one row there; a saved scan finds the site again by its key in
`~rehuco_agent.scraping.scraper_wizard_registry.ScraperWizardRegistry`.
"""

from contextlib import AbstractContextManager
from typing import Final

from rehuco_core import PersistableTaskJob

from ..browser_fetcher import PersonaLease
from ..library_scan_job import LibraryScanJob, LibraryScanTarget
from .fab import Fab
from .fab_library_session import FabLibrarySession

KEY: Final = "fab"
"""What a scan of Fab is saved under, in the settings and in a saved queue."""


class FabLibrary(Fab):
    """Fab as a scraper and as a wizard in one class, so the Scrapers page shows one row for it: what a dropped
    listing is read by, and the scan of an account's library into a root."""

    key = KEY
    name = Fab.publisher

    def session(self, lease: PersonaLease) -> AbstractContextManager[FabLibrarySession]:
        """Open the library for one run.

        :param lease: the persona browser, held for the run.
        :returns: the session.
        """
        return FabLibrarySession(lease)

    def create_job(self, target: LibraryScanTarget) -> PersistableTaskJob:
        """The scan of Fab into a root, as a job for the task queue.

        The job reads its library through this wizard; once saved and restored it finds the site again by key in the
        wizard registry (`~rehuco_agent.scraping.scraper_wizard_registry.register_library_scan_kind`).

        :param target: the root to scan into, as the dialog chose it.
        :returns: the job, not yet enqueued.
        """
        return LibraryScanJob(lambda key: self if key == self.key else None, target)
