"""Thumbnails decoded off the GUI thread into a capped pixmap cache (#221).

The one loader behind every lazy thumbnail surface -- the lightbox's row and the Content Images grid.
A view asks for what it can see; the loader decodes it on the global `QThreadPool` and puts the pixmap
in `QPixmapCache`, and the view repaints on :attr:`ThumbnailLoader.ready`. Two rules keep a fast scroll
from decoding rows already gone: requests are served **newest first**, and a request a view has since
withdrawn is dropped before a worker ever picks it up. The cache's own limit is the expunge -- nothing
here holds a pixmap of its own.
"""

import threading
from collections import deque
from collections.abc import Hashable, Iterable
from typing import Final, NamedTuple

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtGui import QImage, QPixmap, QPixmapCache

from .image_source import ImageSource


class PendingDecode(NamedTuple):
    """One queued request: who asked, what to decode, and the cache key it lands under."""

    owner: int
    source: ImageSource
    position: int
    height: int
    cache_key: str


CACHE_LIMIT_KIB: Final = 256 * 1024
"""The pixmap cache's size floor in KiB once a loader exists -- Qt's own default (10 MiB) holds a
few dozen thumbnails, which a single wide grid row exceeds. Raised, never lowered: another owner may
have asked for more."""

WORKER_LIMIT: Final = 4
"""How many decodes run at once. Thumbnail decode is CPU-bound and archive reads serialize per handle,
so more workers only queue on the same locks."""


def thumbnail_cache_key(key: Hashable, height: int) -> str:
    """The `QPixmapCache` key of ``key``'s thumbnail at ``height``.

    :param key: the image's own key (:meth:`ImageSource.key`).
    :param height: the thumbnail height.
    :returns: the cache key.
    """
    return f"{key!r}@{height}"


class DecodeJob(QRunnable):
    """One worker draining the loader's queue until it is empty.

    Started when work arrives and a slot is free; exits when there is nothing left, so an idle loader
    holds no thread. Reports each decode back through the loader's own signal, which crosses to the
    GUI thread as a queued connection.

    :param loader: the loader whose queue this drains.
    """

    def __init__(self, loader: ThumbnailLoader) -> None:
        super().__init__()
        self.__loader: Final = loader
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            while (job := self.__loader.take_next()) is not None:
                source, index, height, cache_key = job
                image = source.load(index, height)
                try:
                    self.__loader.decoded.emit(cache_key, image)
                except RuntimeError:
                    # the loader's C++ side went while this decoded -- its document closed; the
                    # stop flag drains the rest, so nothing else is decoded for nobody
                    return
        finally:
            self.__loader.worker_done()


class ThumbnailLoader(QObject):
    """Decodes thumbnails on a thread pool into `QPixmapCache`, newest request first (#221).

    :param parent: optional Qt parent.
    :param pool: the thread pool to run on; the global one by default.
    """

    ready = Signal(str)
    """Fires with the cache key of a thumbnail that just landed in `QPixmapCache`."""

    decoded = Signal(str, QImage)
    """Worker-to-GUI hop: a decoded image and its cache key. Internal, connected to
    :meth:`__on_decoded` on this object's own thread."""

    def __init__(self, parent: QObject | None = None, pool: QThreadPool | None = None) -> None:
        super().__init__(parent)
        self.__pool: Final = pool if pool is not None else QThreadPool.globalInstance()
        self.__lock: Final = threading.Lock()
        self.__pending: Final[deque[PendingDecode]] = deque()
        self.__queued: Final[set[str]] = set()
        self.__failed: Final[set[str]] = set()
        self.__workers = 0
        self.__stopped: Final = threading.Event()
        # a worker that outlives this object's C++ side (the document closed mid-decode) must find
        # the queue empty rather than emit into a dead signal. Not a bound method: Qt drops a
        # connection whose receiver is the object being destroyed, so it would never run
        self.destroyed.connect(self.__stopped.set)
        QPixmapCache.setCacheLimit(max(QPixmapCache.cacheLimit(), CACHE_LIMIT_KIB))
        self.decoded.connect(self.__on_decoded)

    @staticmethod
    def cached(key: Hashable, height: int) -> QPixmap | None:
        """The thumbnail already in the cache, if any.

        :param key: the image's key.
        :param height: the thumbnail height.
        :returns: the pixmap, or ``None`` when it is not (or no longer) cached.
        """
        # the out-parameter form: the one-argument overload is mis-typed in PySide's stubs
        pixmap = QPixmap()
        return pixmap if QPixmapCache.find(thumbnail_cache_key(key, height), pixmap) and not pixmap.isNull() else None

    def failed(self, key: Hashable, height: int) -> bool:
        """Whether ``key``'s thumbnail was asked for and could not be decoded.

        What lets a view paint a broken placeholder rather than a pending one, and stop asking.

        :param key: the image's key.
        :param height: the thumbnail height.
        :returns: whether the decode failed.
        """
        with self.__lock:
            return thumbnail_cache_key(key, height) in self.__failed

    def request(self, requester: object, source: ImageSource, index: int, height: int) -> QPixmap | None:
        """Ask for ``source[index]``'s thumbnail at ``height``, on ``requester``'s behalf.

        :param requester: the surface asking -- what :meth:`retain` later prunes by, so two surfaces
            sharing one loader (the grid and the lightbox row it opens) never withdraw each other's.
        :param source: the image source.
        :param index: the position in it.
        :param height: the thumbnail height.
        :returns: the pixmap straight from the cache when it is there -- nothing is queued then -- or
            ``None`` with a decode queued, to be announced through :attr:`ready`.
        """
        key = source.key(index)
        cached = self.cached(key, height)
        if cached is not None:
            return cached
        cache_key = thumbnail_cache_key(key, height)
        with self.__lock:
            if cache_key in self.__queued or cache_key in self.__failed:
                return None
            self.__queued.add(cache_key)
            self.__pending.append(PendingDecode(id(requester), source, index, height, cache_key))
            start_worker = self.__workers < WORKER_LIMIT
            if start_worker:
                self.__workers += 1
        if start_worker:
            self.__pool.start(DecodeJob(self))
        return None

    def retain(self, requester: object, cache_keys: Iterable[str]) -> None:
        """Withdraw every request ``requester`` made but those in ``cache_keys`` -- what it still shows.

        Another requester's pending decodes are left alone.

        :param requester: the surface whose requests to prune.
        :param cache_keys: the cache keys it still wants.
        """
        wanted = set(cache_keys)
        owner = id(requester)
        with self.__lock:
            dropped = [job for job in self.__pending if job.owner == owner and job.cache_key not in wanted]
            kept = [job for job in self.__pending if job.owner != owner or job.cache_key in wanted]
            self.__pending.clear()
            self.__pending.extend(kept)
            self.__queued.difference_update(job.cache_key for job in dropped)

    def take_next(self) -> tuple[ImageSource, int, int, str] | None:
        """Pop the newest pending request, for a worker.

        :returns: the ``(source, index, height, cache_key)`` to decode, or ``None`` when the queue is
            empty -- or once the loader is being destroyed, whatever is still queued.
        """
        with self.__lock:
            if self.__stopped.is_set() or not self.__pending:
                return None
            job = self.__pending.pop()
            return job.source, job.position, job.height, job.cache_key

    def worker_done(self) -> None:
        """Release a worker slot, for a worker that found the queue empty."""
        with self.__lock:
            self.__workers -= 1

    @Slot(str, QImage)
    def __on_decoded(self, cache_key: str, image: QImage) -> None:
        """Put a decoded thumbnail in the cache and announce it (GUI thread).

        A null image -- undecodable bytes, an offline archive -- is announced too, so the view stops
        waiting and paints its broken placeholder instead of asking again on every repaint.

        :param cache_key: the thumbnail's cache key.
        :param image: the decoded image, possibly null.
        """
        with self.__lock:
            self.__queued.discard(cache_key)
            if image.isNull():
                self.__failed.add(cache_key)
        if not image.isNull():
            QPixmapCache.insert(cache_key, QPixmap.fromImage(image))
        self.ready.emit(cache_key)
