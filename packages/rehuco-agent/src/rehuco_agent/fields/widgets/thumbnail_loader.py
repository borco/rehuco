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
    ratio: float
    cache_key: str


CACHE_LIMIT_KIB: Final = 256 * 1024
"""The pixmap cache's size floor in KiB once a loader exists -- Qt's own default (10 MiB) holds a
few dozen thumbnails, which a single wide grid row exceeds. Raised, never lowered: another owner may
have asked for more."""

WORKER_LIMIT: Final = 4
"""How many decodes run at once. Thumbnail decode is CPU-bound and archive reads serialize per handle,
so more workers only queue on the same locks."""


def thumbnail_cache_key(key: Hashable, height: int, ratio: float = 1.0) -> str:
    """The `QPixmapCache` key of ``key``'s thumbnail at ``height`` logical pixels on a ``ratio`` screen.

    :param key: the image's own key (:meth:`ImageSource.key`).
    :param height: the thumbnail height, in logical pixels.
    :param ratio: the device pixel ratio it is decoded for.
    :returns: the cache key.
    """
    return f"{key!r}@{height}x{ratio:g}"


class DecodeSignals(QObject):
    """The sender one worker emits through -- never the loader itself (#221).

    Emitting on the loader from a pool thread races its destruction: the document can close while a
    worker is inside ``emit``, and no flag checked a moment earlier guards that -- the worker crashes,
    or deadlocks against the GUI thread over the GIL and Qt's connection locks. A worker holding the
    loader as its last reference would be worse still: the ``QObject`` deleted on the pool thread when
    the runnable is released, posted events and all.

    So each worker gets a sender of its own, wired signal-to-signal into the loader's landing signal
    on the GUI thread, and holds the loader's plain-Python queue rather than the loader; when the
    loader goes, Qt severs that connection under its own locks and a decode landing afterward reaches
    nobody. **The sender is deleted on the GUI thread only**: it is parented to the pool, whose
    destructor waits for its runnables, and the worker ``deleteLater``-s it when done -- a ``QObject``
    deleted on a pool thread would tear its connections down under the loader's own destructor, with
    the same crashes. The same shape
    :func:`~rehuco_agent.fields.background_measurement.measure_in_background` documents.

    :param pool: the pool the worker runs on, which owns the sender.
    """

    decoded = Signal(str, QImage)
    """A decoded image and its cache key."""

    def __init__(self, pool: QThreadPool) -> None:
        super().__init__(pool)


class DecodeQueue:
    """The loader's pending requests and worker count, shared with its workers under one lock (#221).

    Plain Python, no ``QObject``: this is the whole of what a worker touches, so a worker outliving
    its loader finds a stopped queue rather than a dead object.
    """

    def __init__(self) -> None:
        self.__lock: Final = threading.Lock()
        self.__pending: Final[deque[PendingDecode]] = deque()
        self.__queued: Final[set[str]] = set()
        self.__workers = 0
        self.__stopped: Final = threading.Event()

    def stop(self) -> None:
        """Drain the queue for good: every worker finds nothing more to take."""
        self.__stopped.set()

    def enqueue(self, job: PendingDecode) -> bool | None:
        """Queue ``job`` unless its cache key already is.

        :param job: the request.
        :returns: ``None`` when it was already queued; otherwise whether a worker slot was taken for
            it, in which case the caller starts one.
        """
        with self.__lock:
            if job.cache_key in self.__queued:
                return None
            self.__queued.add(job.cache_key)
            self.__pending.append(job)
            if self.__workers >= WORKER_LIMIT:
                return False
            self.__workers += 1
            return True

    def retain(self, owner: int, wanted: set[str]) -> None:
        """Withdraw every request of ``owner`` but those in ``wanted``.

        :param owner: the requester's identity.
        :param wanted: the cache keys it still wants.
        """
        with self.__lock:
            dropped = [job for job in self.__pending if job.owner == owner and job.cache_key not in wanted]
            kept = [job for job in self.__pending if job.owner != owner or job.cache_key in wanted]
            self.__pending.clear()
            self.__pending.extend(kept)
            self.__queued.difference_update(job.cache_key for job in dropped)

    def settle(self, cache_key: str) -> None:
        """Forget ``cache_key`` as queued: its decode landed, so a later request may queue it again.

        :param cache_key: the request's cache key.
        """
        with self.__lock:
            self.__queued.discard(cache_key)

    def take_next(self) -> tuple[ImageSource, int, int, float, str] | None:
        """Pop the newest pending request, for a worker.

        :returns: the ``(source, index, height, ratio, cache_key)`` to decode, or ``None`` when the
            queue is empty -- or once the loader is being destroyed, whatever is still queued.
        """
        with self.__lock:
            if self.__stopped.is_set() or not self.__pending:
                return None
            job = self.__pending.pop()
            return job.source, job.position, job.height, job.ratio, job.cache_key

    def worker_done(self) -> None:
        """Release a worker slot, for a worker that found the queue empty."""
        with self.__lock:
            self.__workers -= 1


class DecodeJob(QRunnable):
    """One worker draining the loader's queue until it is empty.

    Started when work arrives and a slot is free; exits when there is nothing left, so an idle loader
    holds no thread. Reports each decode through its own sender, which crosses to the GUI thread as
    a queued connection.

    :param queue: the queue this drains.
    :param signals: the sender to report through, already wired; released when the worker is done.
    """

    def __init__(self, queue: DecodeQueue, signals: DecodeSignals) -> None:
        super().__init__()
        self.__queue: Final = queue
        self.__signals: Final = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            while (job := self.__queue.take_next()) is not None:
                source, index, height, ratio, cache_key = job
                # decoded at the screen's own pixels, so a thumbnail on a scaled desktop is never a
                # logical-size image stretched up to device pixels
                image = source.load(index, round(height * ratio))
                image.setDevicePixelRatio(ratio)
                self.__signals.decoded.emit(cache_key, image)
        finally:
            self.__queue.worker_done()
            self.__signals.deleteLater()


class ThumbnailLoader(QObject):
    """Decodes thumbnails on a thread pool into `QPixmapCache`, newest request first (#221).

    :param parent: optional Qt parent.
    :param pool: the thread pool to run on; the global one by default.
    """

    ready = Signal(str)
    """Fires with the cache key of a thumbnail that just landed in `QPixmapCache`."""

    decoded = Signal(str, QImage)
    """Where a decoded image and its cache key land on the GUI thread, relayed from `DecodeSignals`.
    Internal, connected to :meth:`__on_decoded` on this object's own thread."""

    def __init__(self, parent: QObject | None = None, pool: QThreadPool | None = None) -> None:
        super().__init__(parent)
        self.__pool: Final = pool if pool is not None else QThreadPool.globalInstance()
        self.__queue: Final = DecodeQueue()
        self.__failed: Final[set[str]] = set()
        queue = self.__queue

        def on_destroyed() -> None:
            queue.stop()

        # a worker that outlives this object's C++ side (the document closed mid-decode) must find
        # the queue empty. A closure, not a bound method: Qt drops a connection whose receiver is the
        # object being destroyed, and PySide holds a bound method's receiver weakly, so on a plain
        # `del` that receiver is torn down before -- or while -- the slot runs. The connection holds
        # a closure strongly, so this runs with intact state on every path
        self.destroyed.connect(on_destroyed)
        QPixmapCache.setCacheLimit(max(QPixmapCache.cacheLimit(), CACHE_LIMIT_KIB))
        self.decoded.connect(self.__on_decoded)

    @staticmethod
    def cached(key: Hashable, height: int, ratio: float = 1.0) -> QPixmap | None:
        """The thumbnail already in the cache, if any.

        :param key: the image's key.
        :param height: the thumbnail height, in logical pixels.
        :param ratio: the device pixel ratio it was decoded for.
        :returns: the pixmap, or ``None`` when it is not (or no longer) cached.
        """
        # the out-parameter form: the one-argument overload is mis-typed in PySide's stubs
        pixmap = QPixmap()
        found = QPixmapCache.find(thumbnail_cache_key(key, height, ratio), pixmap)
        return pixmap if found and not pixmap.isNull() else None

    def failed(self, key: Hashable, height: int, ratio: float = 1.0) -> bool:
        """Whether ``key``'s thumbnail was asked for and could not be decoded.

        What lets a view paint a broken placeholder rather than a pending one, and stop asking.

        :param key: the image's key.
        :param height: the thumbnail height, in logical pixels.
        :param ratio: the device pixel ratio it was asked for.
        :returns: whether the decode failed.
        """
        return thumbnail_cache_key(key, height, ratio) in self.__failed

    def request(
        self, requester: object, source: ImageSource, index: int, height: int, ratio: float = 1.0
    ) -> QPixmap | None:
        """Ask for ``source[index]``'s thumbnail at ``height``, on ``requester``'s behalf.

        :param requester: the surface asking -- what :meth:`retain` later prunes by, so two surfaces
            sharing one loader (the grid and the lightbox row it opens) never withdraw each other's.
        :param source: the image source.
        :param index: the position in it.
        :param height: the thumbnail height, in logical pixels.
        :param ratio: the surface's device pixel ratio -- the thumbnail is decoded at ``height`` times
            this many pixels and tagged with it, so it paints one device pixel per pixel.
        :returns: the pixmap straight from the cache when it is there -- nothing is queued then -- or
            ``None`` with a decode queued, to be announced through :attr:`ready`.
        """
        key = source.key(index)
        cached = self.cached(key, height, ratio)
        if cached is not None:
            return cached
        cache_key = thumbnail_cache_key(key, height, ratio)
        if cache_key in self.__failed:
            return None
        if self.__queue.enqueue(PendingDecode(id(requester), source, index, height, ratio, cache_key)):
            # the pool-thread emits arrive here queued; this connection is what the loader's
            # destruction severs, so a late decode reaches nobody
            signals = DecodeSignals(self.__pool)
            signals.decoded.connect(self.decoded)
            self.__pool.start(DecodeJob(self.__queue, signals))
        return None

    def retain(self, requester: object, cache_keys: Iterable[str]) -> None:
        """Withdraw every request ``requester`` made but those in ``cache_keys`` -- what it still shows.

        Another requester's pending decodes are left alone.

        :param requester: the surface whose requests to prune.
        :param cache_keys: the cache keys it still wants.
        """
        self.__queue.retain(id(requester), set(cache_keys))

    @Slot(str, QImage)
    def __on_decoded(self, cache_key: str, image: QImage) -> None:
        """Put a decoded thumbnail in the cache and announce it (GUI thread).

        A null image -- undecodable bytes, an offline archive -- is announced too, so the view stops
        waiting and paints its broken placeholder instead of asking again on every repaint.

        :param cache_key: the thumbnail's cache key.
        :param image: the decoded image, possibly null.
        """
        self.__queue.settle(cache_key)
        if image.isNull():
            self.__failed.add(cache_key)
        else:
            QPixmapCache.insert(cache_key, QPixmap.fromImage(image))
        self.ready.emit(cache_key)
