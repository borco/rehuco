"""The dedicated pool a scrape actually runs on, instead of the app-wide task queue
([[acquisition-tooling#scrape-job]]).
"""

from contextvars import Context, copy_context
from functools import lru_cache
from typing import Final, Protocol, runtime_checkable

from PySide6.QtCore import QRunnable, QThreadPool

MAX_CONCURRENT_SCRAPES: Final = 4
"""How many scrapes run at once. Generous for a handful of interactive fetches dropped in quick
succession, bounded so a burst of drops cannot open dozens of sockets at once."""


@runtime_checkable
# one method is the design, not an omission -- see ScrapeJob.run/ImageDownloadJob.run
# pylint: disable-next=too-few-public-methods
class PoolJob(Protocol):
    """What this pool runs: something with a synchronous ``run``, called on the worker thread.

    Structural rather than a shared base class, the same reason `~.protocols.SiteScraper` is: `ScrapeJob`
    and `~.image_download_job.ImageDownloadJob` share nothing but this one method and their own
    ``Marshaller`` idiom for getting a result back to the GUI thread -- there is no shared state or
    behaviour a base class would actually be for.
    """

    def run(self) -> None:
        """Do the work, on whatever thread the pool hands this to."""


class ScraperExecutor:
    """Runs each `PoolJob` (a `ScrapeJob`, or an `~.image_download_job.ImageDownloadJob`) on its own
    worker, independent of every other one and of the app-wide `rehuco_core.TaskQueue`'s single worker.

    **Its own `QThreadPool`, not `QThreadPool.globalInstance()`**: scraping's concurrency must never be
    contended by Qt-internal or unrelated pooled work, and the whole point is a cap that is scraping's
    alone.

    **Carries the caller's `borco_core.logging.LogScope` onto the worker.** A pool thread inherits
    nothing from the thread that submitted work to it, so without capturing `contextvars.copy_context`
    at :meth:`submit` time, every record a job's `logging.getLogger` calls make would land unscoped --
    on the app-wide log dock only, never the document's. This is the one piece of
    `rehuco_core.TaskQueue`'s machinery a caller here still needs: submit from inside
    ``with LogScope.open(path):``, the same way `rehuco_agent.documents.checksum_actions` enqueues a
    checksum run.
    """

    class Runnable(QRunnable):
        """Runs one `PoolJob` inside the log context captured at submission.

        Nested rather than a module-level helper, the same reason `rehuco_agent.tasks.TaskQueueModel.Marshaller`
        is: nothing outside `ScraperExecutor` has a reason to build one. A plain object rather than a
        lambda handed to `QThreadPool.start`, so it keeps a reference to ``job`` for as long as it runs.
        """

        def __init__(self, job: PoolJob, context: Context) -> None:
            super().__init__()
            self.__job: Final = job
            self.__context: Final = context

        def run(self) -> None:
            """Run the job inside the captured context -- the `QRunnable` contract."""
            self.__context.run(self.__job.run)

    def __init__(self) -> None:
        self.__pool: Final = QThreadPool()
        self.__pool.setMaxThreadCount(MAX_CONCURRENT_SCRAPES)

    def submit(self, job: PoolJob) -> None:
        """Run ``job`` on the pool, carrying the caller's log scope onto the worker thread.

        :param job: the work to run. Nothing about one submission blocks another -- each runs as an
            independent `QRunnable`, and nothing on the app-wide `rehuco_core.TaskQueue` shares this
            pool at all. The runnable is auto-deleted the moment ``run`` returns; the job reaches the
            GUI thread with its outcome, as the first argument of its relay's queued signal, so nothing
            here needs to hold it past that point.
        """
        context = copy_context()
        self.__pool.start(ScraperExecutor.Runnable(job, context))

    def shutdown(self) -> None:
        """Wait for every job still running, then delete the pool -- for whoever drops this executor (#529).

        Only a test does: the app keeps the shared executor for the session. Dropped without this, the pool would
        be left to the cyclic collector, which may run on one of the pool's own threads, and a pool destroyed
        there waits for that very thread.
        """
        self.__pool.waitForDone()
        self.__pool.deleteLater()


@lru_cache(maxsize=1)
def shared_scraper_executor() -> ScraperExecutor:
    """The single, process-wide `ScraperExecutor` every scrape submits to.

    :returns: the shared instance.
    """
    return ScraperExecutor()
