"""Downloads one image URL and hands the bytes to the GUI thread ([[acquisition-tooling#drag-drop-aids]],
#73).

The image-acquisition counterpart of `~.scrape_job.ScrapeJob`, and built the same way: not a `TaskJob`,
never enqueued on the app-wide `rehuco_core.TaskQueue`, but run on `~.scraper_executor.ScraperExecutor`'s
own pool so several downloads (a scrape's whole ``images`` list, or one dropped URL) run concurrently
without blocking the GUI thread or waiting behind whatever the queue is doing.
"""

import logging
from typing import Final

from PySide6.QtCore import QObject, Qt, Signal, SignalInstance

from .image_pipeline import acquire

LOG: Final = logging.getLogger(__name__)


class ImageDownloadJob:
    """Fetches one image URL and hands the result to the GUI thread.

    Constructed for one URL and one already-assigned slot -- a scrape result's own numbering, or
    ``None`` for a plain drop, which takes the next free slot at write time.

    :param url: the image's URL.
    :param referrer: the page to send as the download's ``Referer``, or ``None`` when the site does
        not need one.
    :param slot: the ``<stem>NN`` slot this image is destined for, or ``None`` for the next free one.
    :param relay: where the outcome goes, on the GUI thread -- the caller's one :class:`Relay`, for the reason
        `~.scrape_job.ScrapeJob` takes one (#529).
    """

    def __init__(
        self, url: str, referrer: str | None, slot: int | None = None, *, relay: ImageDownloadJob.Relay
    ) -> None:
        self.__url: Final = url
        self.__referrer: Final = referrer
        self.__slot: Final = slot
        self.__relay: Final = relay

    class Relay(QObject):
        """Carries finished downloads' outcomes across the thread boundary, for every job one caller runs (#529).

        One per caller, for the caller's lifetime, for the reason `~.scrape_job.ScrapeJob.Relay` is, and the
        same two-pairs-of-signals shape: :attr:`downloaded`/:attr:`failure` fire on the worker thread and
        are relayed to :attr:`result_ready`/:attr:`failed`, always on the GUI thread, over an explicit
        `Qt.ConnectionType.QueuedConnection` to a method of this object. Every signal carries the job first.

        :param parent: the caller.
        """

        downloaded = Signal(object, object)
        """Fires with the job and its `~.image_pipeline.AcquiredImage`, on the worker thread."""

        failure = Signal(object, object)
        """Fires with the job and its exception, on the worker thread."""

        result_ready = Signal(object, object)
        """Fires on the GUI thread with the job and its `~.image_pipeline.AcquiredImage`, exactly once per job,
        only on success."""

        failed = Signal(object, object)
        """Fires on the GUI thread with the job and its exception, exactly once per job, whenever
        :attr:`result_ready` does not."""

        def __init__(self, parent: QObject | None = None) -> None:
            super().__init__(parent)
            self.downloaded.connect(self.__relay_result, Qt.ConnectionType.QueuedConnection)
            self.failure.connect(self.__relay_failure, Qt.ConnectionType.QueuedConnection)

        def __relay_result(self, job: object, result: object) -> None:
            """Re-emit :attr:`result_ready`, on the GUI thread by construction of the connection above.

            :param job: the job that downloaded.
            :param result: the `~.image_pipeline.AcquiredImage` :attr:`downloaded` carried.
            """
            self.result_ready.emit(job, result)

        def __relay_failure(self, job: object, error: object) -> None:
            """Re-emit :attr:`failed`, on the GUI thread by construction of the connection above.

            :param job: the job that failed.
            :param error: the exception :attr:`failure` carried.
            """
            self.failed.emit(job, error)

    @property
    def slot(self) -> int | None:
        """The ``<stem>NN`` slot this download is destined for, or ``None`` for the next free one."""
        return self.__slot

    def run(self) -> None:
        """Do the work: fetch, emit -- the `~.scraper_executor.PoolJob` contract.

        Runs on whatever thread `~.scraper_executor.ScraperExecutor` hands it to. The blanket catch is
        the point, the same one `~.scrape_job.ScrapeJob.run` makes: an exception escaping a pool thread
        is printed by the pool and reaches no log dock, and the document's log is the one place a
        download failure can be diagnosed from.
        """
        try:
            result = acquire(self.__url, self.__referrer)
        except Exception as error:  # pylint: disable=broad-exception-caught
            LOG.warning("Could not download %s: %s", self.__url, error)
            self.__deliver(self.__relay.failure, error)
            return
        self.__deliver(self.__relay.downloaded, result)

    def __deliver(self, signal: SignalInstance, payload: object) -> None:
        """Send ``payload`` to the GUI thread through one of the relay's worker-side signals, with this job --
        nothing for a job whose relay went with its document while the download ran, whose outcome is nobody's.

        :param signal: which of the relay's signals to emit.
        :param payload: what the signal carries after the job.
        """
        try:
            signal.emit(self, payload)
        except RuntimeError:  # the relay was deleted with its document while the download ran
            pass
