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
    """

    def __init__(self, url: str, referrer: str | None, slot: int | None = None) -> None:
        self.__url: Final = url
        self.__referrer: Final = referrer
        self.__slot: Final = slot
        self.__marshaller: Final = ImageDownloadJob.Marshaller()

    class Marshaller(QObject):
        """Carries a finished download's result across the thread boundary, and nothing else.

        The same two-pairs-of-signals shape `~.scrape_job.ScrapeJob.Marshaller` uses, for the same
        reason: :attr:`downloaded`/:attr:`failure` fire on the worker thread and are relayed to
        :attr:`result_ready`/:attr:`failed`, always on the GUI thread, over an explicit
        `Qt.ConnectionType.QueuedConnection`.
        """

        downloaded = Signal(object)
        """Fires with the `~.image_pipeline.AcquiredImage`, on the worker thread."""

        failure = Signal(object)
        """Fires with the exception, on the worker thread."""

        result_ready = Signal(object)
        """Fires with the `~.image_pipeline.AcquiredImage`, always on the GUI thread."""

        failed = Signal(object)
        """Fires with the exception, always on the GUI thread."""

        def __init__(self) -> None:
            super().__init__()
            self.downloaded.connect(self.result_ready.emit, Qt.ConnectionType.QueuedConnection)
            self.failure.connect(self.failed.emit, Qt.ConnectionType.QueuedConnection)

    @property
    def slot(self) -> int | None:
        """The ``<stem>NN`` slot this download is destined for, or ``None`` for the next free one."""
        return self.__slot

    @property
    def result_ready(self) -> SignalInstance:
        """Fires on the GUI thread with the `~.image_pipeline.AcquiredImage`, exactly once, only on
        success."""
        return self.__marshaller.result_ready

    @property
    def failed(self) -> SignalInstance:
        """Fires on the GUI thread with the exception, exactly once, whenever :attr:`result_ready`
        does not."""
        return self.__marshaller.failed

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
            self.__marshaller.failure.emit(error)
            return
        self.__marshaller.downloaded.emit(result)
