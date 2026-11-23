"""What a store adds for the library wizard's one dialog ([[acquisition-tooling#library-wizard-protocol]], #683).

Three members and nothing else: how a scan is saved, pausing, resuming and asking the user are the job's own
([[acquisition-tooling#library-scan-stops]]). A plain structural `Protocol`, so a user's own script satisfies it
without importing this package, as a `~.protocols.SiteScraper` does.
"""

from typing import Protocol, runtime_checkable

from rehuco_core import PersistableTaskJob

from .library_scan_job import LibraryScanTarget


@runtime_checkable
class ScraperWizard(Protocol):
    """A store the library wizard can scan into a root.

    A wizard that is also a `~.library_site.LibrarySite` -- it has the site's ``name`` and ``session`` -- is the one
    the scan job reads its library through ([[acquisition-tooling#library-scan-job]]); the registry hands the job
    that same object by :attr:`key`.
    """

    @property
    def key(self) -> str:  # pyright: ignore[reportReturnType]
        """The stable name that identifies the wizard, in the settings and in a saved queue."""

    @property
    def label(self) -> str:  # pyright: ignore[reportReturnType]
        """What the user picks the wizard by."""

    def create_job(self, target: LibraryScanTarget) -> PersistableTaskJob:  # pyright: ignore[reportReturnType]
        """The scan of this store into a root, as a job for the task queue.

        :param target: the root to scan into, as the dialog chose it; its ``site_key`` is this wizard's :attr:`key`.
        :returns: the job, not yet enqueued.
        """
