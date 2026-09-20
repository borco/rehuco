"""The Content Images dock's model: the entries, their dimensions on demand, and the archive-backed
image source the lightbox and the thumbnail loader decode through (#221).

Nothing here is persisted: dimensions are read off each member's header the first time a row needs
them and held in memory, keyed by the tier-0 key ([[reference-images#image-identity]]) -- the shape
the scan sidecar ([[reference-images#scan-sidecar]]) can later sit in front of without a change.
"""

import threading
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Final, cast, override

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    Signal,
    Slot,
)
from PySide6.QtGui import QImage
from rehuco_core import ContentImageEntry, enumerate_content_images

from ...fields.widgets.image_source import ImageDescription, decode_image, image_size
from .archive_cache import ArchiveCache
from .banners import archive_relative_path

type ModelIndex = QModelIndex | QPersistentModelIndex
type TierZeroKey = tuple[str, str, int, int]


class ArchiveImageSource:
    """An `ImageSource` over archive members, read through an `ArchiveCache` (#221).

    :param entries: the members, in browse order.
    :param cache: the open-handle cache to read them through.
    :param rehu_directory: the ``.rehu`` file's directory, which the description names archives
        relative to.
    """

    def __init__(self, entries: Sequence[ContentImageEntry], cache: ArchiveCache, rehu_directory: Path) -> None:
        self.__entries: Final = list(entries)
        self.__cache: Final = cache
        self.__rehu_directory: Final = rehu_directory

    def __len__(self) -> int:
        return len(self.__entries)

    def key(self, index: int) -> TierZeroKey:
        """The member's tier-0 key ([[reference-images#image-identity]])."""
        return self.__entries[index].key

    def name(self, index: int) -> str:
        """The member's file name, without its folder."""
        return PurePosixPath(self.__entries[index].name).name

    def describe(self, index: int) -> ImageDescription:
        """``<archive relative to the .rehu>:/<member path>`` and the member's stored size."""
        entry = self.__entries[index]
        archive = archive_relative_path(entry.archive, self.__rehu_directory)
        return ImageDescription(f"{archive}:/{entry.name}", entry.size)

    def load(self, index: int, max_height: int | None) -> QImage:
        """Decode the member through the cache; null when the archive or member cannot be read."""
        data = self.__cache.read(self.__entries[index])
        return decode_image(data, max_height) if data is not None else QImage()


class JobSignals(QObject):
    """The sender one job emits through -- never the model itself (#221).

    A job never touches the model's ``QObject`` from the pool thread. Emitting on the model races its
    destruction: the document can close while a worker is inside ``emit``, and a stop flag checked a
    moment earlier guards nothing -- the worker crashes, or deadlocks against the GUI thread over the
    GIL and Qt's connection locks. And a job holding the model as its last reference would delete the
    ``QObject`` on the pool thread when the runnable is released, posted events and all.

    So each job gets a sender of its own, wired signal-to-signal into the model's landing signal on
    the GUI thread. When the model goes, Qt severs that connection under its own locks and a report
    emitted afterward reaches nobody. **The sender is deleted on the GUI thread only**: it is parented
    to the pool, whose destructor waits for its runnables, and the job ``deleteLater``-s it when done
    -- a ``QObject`` deleted on a pool thread would tear its connections down under the model's own
    destructor, with the same crashes. The same shape
    :func:`~rehuco_agent.fields.background_measurement.measure_in_background` documents.

    :param pool: the pool the job runs on, which owns the sender.
    """

    enumerated = Signal(int, list)
    """An `EnumerateJob`'s generation and entries."""

    header_read = Signal(object, QSize)
    """A `HeaderJob`'s tier-0 key and pixel size (invalid when unreadable)."""

    def __init__(self, pool: QThreadPool) -> None:
        super().__init__(pool)


class EnumerateJob(QRunnable):
    """Enumerates a resource's content images off the GUI thread -- it opens every archive.

    :param signals: the sender to report through, already wired; released when the job is done.
    :param generation: which request this answers; a stale answer is dropped.
    :param path: the ``.rehu`` file.
    :param extensions: the recognized image extensions.
    """

    def __init__(self, signals: JobSignals, generation: int, path: Path, extensions: tuple[str, ...]) -> None:
        super().__init__()
        self.__signals: Final = signals
        self.__generation: Final = generation
        self.__path: Final = path
        self.__extensions: Final = extensions

    def run(self) -> None:
        try:
            entries = enumerate_content_images(self.__path, self.__extensions)
            self.__signals.enumerated.emit(self.__generation, entries)
        finally:
            self.__signals.deleteLater()


class HeaderJob(QRunnable):
    """Reads one member's pixel size off its header, off the GUI thread.

    A partial inflate first; the whole member only when the header is not in the first slice.

    :param signals: the sender to report through, already wired; released when the job is done.
    :param cache: the open-handle cache to read through.
    :param stopped: set once the model is being destroyed, so a job that has not read yet reads nothing.
    :param entry: the member.
    """

    def __init__(
        self, signals: JobSignals, cache: ArchiveCache, stopped: threading.Event, entry: ContentImageEntry
    ) -> None:
        super().__init__()
        self.__signals: Final = signals
        self.__cache: Final = cache
        self.__stopped: Final = stopped
        self.__entry: Final = entry

    def run(self) -> None:
        try:
            if self.__stopped.is_set():
                return
            head = self.__cache.read_head(self.__entry)
            size = image_size(head) if head is not None else QSize()
            if head is not None and not size.isValid():
                whole = self.__cache.read(self.__entry)
                size = image_size(whole) if whole is not None else QSize()
            self.__signals.header_read.emit(self.__entry.key, size)
        finally:
            self.__signals.deleteLater()


class ContentImagesModel(QAbstractListModel):  # pylint: disable=too-many-instance-attributes
    """The content images of one resource, with each one's pixel size read on demand (#221).

    :param parent: optional Qt parent.
    """

    enumerated = Signal(int, list)
    """Where an `EnumerateJob`'s generation and entries land on the GUI thread, relayed from
    `JobSignals`. Internal."""

    header_read = Signal(object, QSize)
    """Where a member's tier-0 key and pixel size (invalid when unreadable) land on the GUI thread,
    relayed from `JobSignals`. Internal."""

    dimensions_changed = Signal()
    """Fires after a header read lands, so a view can re-pack -- coalesced by the view, not here."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__cache: Final = ArchiveCache()
        self.__entries: list[ContentImageEntry] = []
        self.__rehu_directory: Path | None = None
        self.__dimensions: Final[dict[TierZeroKey, QSize]] = {}
        self.__pending: Final[set[TierZeroKey]] = set()
        self.__generation = 0
        self.__lock: Final = threading.Lock()
        self.__stopped: Final = threading.Event()
        stopped = self.__stopped
        cache = self.__cache

        def on_destroyed() -> None:
            stopped.set()
            cache.close()

        # a job that outlives this object's C++ side (the document closed mid-read) must read nothing
        # further, and the archives it held open must close. A closure, not a bound method: Qt drops
        # a connection whose receiver is the object being destroyed, and PySide holds a bound method's
        # receiver weakly, so on a plain `del` that receiver is torn down before -- or while -- the slot
        # runs. The connection holds a closure strongly, so this runs with intact state on every path
        self.destroyed.connect(on_destroyed)
        self.enumerated.connect(self.__on_enumerated)
        self.header_read.connect(self.__on_header_read)

    @property
    def archive_cache(self) -> ArchiveCache:
        """The open-handle cache every read of this resource's archives goes through."""
        return self.__cache

    @property
    def stopped(self) -> bool:
        """Whether this model is being destroyed, so a job on the pool should do nothing further."""
        return self.__stopped.is_set()

    @property
    def entries(self) -> list[ContentImageEntry]:
        """The content images, in browse order."""
        return list(self.__entries)

    @property
    def rehu_directory(self) -> Path | None:
        """The ``.rehu`` file's directory, or ``None`` while no resource is loaded."""
        return self.__rehu_directory

    @property
    def source(self) -> ArchiveImageSource:
        """The `ImageSource` over the current entries."""
        return ArchiveImageSource(self.__entries, self.__cache, self.__rehu_directory or Path())

    def refresh(self, path: Path | None, extensions: tuple[str, ...]) -> None:
        """Re-enumerate ``path``'s content images on the pool, replacing the entries when it lands.

        :param path: the ``.rehu`` file, or ``None`` for a document with no path yet -- empties the
            model.
        :param extensions: the recognized image extensions.
        """
        self.__generation += 1
        if path is None:
            self.set_entries([], None)
            return
        self.__rehu_directory = path.parent
        pool = self.__pool()
        job = EnumerateJob(self.__job_signals(pool), self.__generation, path, extensions)
        job.setAutoDelete(True)
        pool.start(job)

    def set_entries(self, entries: Sequence[ContentImageEntry], rehu_directory: Path | None) -> None:
        """Replace the entries wholesale.

        :param entries: the content images, in browse order.
        :param rehu_directory: the ``.rehu`` file's directory.
        """
        self.beginResetModel()
        self.__entries = list(entries)
        self.__rehu_directory = rehu_directory
        self.endResetModel()

    def aspect(self, index: int) -> float | None:
        """The width/height of the image at ``index``, or ``None`` while its header is unread or
        proved unreadable.

        :param index: the position.
        :returns: the aspect, or ``None``.
        """
        size = self.__dimensions.get(self.__entries[index].key)
        if size is None or not size.isValid() or size.height() <= 0:
            return None
        return size.width() / size.height()

    def dimensions(self, index: int) -> QSize | None:
        """The pixel size of the image at ``index``, or ``None`` while unread; invalid once it proved
        unreadable.

        :param index: the position.
        :returns: the size, or ``None``.
        """
        return self.__dimensions.get(self.__entries[index].key)

    def request_dimensions(self, indices: Sequence[int]) -> None:
        """Read the headers of ``indices`` that have none yet, off the GUI thread.

        :param indices: the positions a view is about to lay out.
        """
        pool = self.__pool()
        jobs: list[HeaderJob] = []
        with self.__lock:
            for index in indices:
                entry = self.__entries[index]
                if entry.key in self.__dimensions or entry.key in self.__pending:
                    continue
                self.__pending.add(entry.key)
                jobs.append(HeaderJob(self.__job_signals(pool), self.__cache, self.__stopped, entry))
        for job in jobs:
            job.setAutoDelete(True)
            pool.start(job)

    @override
    def rowCount(self, parent: ModelIndex = QModelIndex()) -> int:
        """See ``QAbstractListModel``: a flat list has rows only at the root."""
        return 0 if parent.isValid() else len(self.__entries)

    @override
    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """The member's file name as display text, its full member path as tooltip."""
        if not index.isValid():
            return None
        entry = self.__entries[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return PurePosixPath(entry.name).name
        if role == Qt.ItemDataRole.ToolTipRole:
            return entry.name
        return None

    @staticmethod
    def __pool() -> QThreadPool:
        """The pool every read runs on -- the global one, shared with the thumbnail loader."""
        return QThreadPool.globalInstance()

    def __job_signals(self, pool: QThreadPool) -> JobSignals:
        """A job's sender, wired into this model's landing signals (GUI thread).

        The pool-thread emits arrive queued; these connections are what the model's destruction
        severs, so a late report reaches nobody.

        :param pool: the pool the job runs on.
        :returns: the sender.
        """
        signals = JobSignals(pool)
        signals.enumerated.connect(self.enumerated)
        signals.header_read.connect(self.header_read)
        return signals

    @Slot(int, list)
    def __on_enumerated(self, generation: int, entries: list) -> None:
        """Adopt an enumeration's result, unless a newer request has since gone out.

        :param generation: which request this answers.
        :param entries: the entries found.
        """
        if generation != self.__generation:
            return
        self.set_entries(entries, self.__rehu_directory)

    @Slot(object, QSize)
    def __on_header_read(self, key: object, size: QSize) -> None:
        """Record a header read and tell the rows it may have moved.

        :param key: the member's tier-0 key.
        :param size: its pixel size, invalid when the member could not be read.
        """
        # ``object`` on the signal (a tuple would not marshal across the thread hop as its own type);
        # what arrives is the tuple the job put in
        tier_zero = cast(TierZeroKey, key)
        with self.__lock:
            self.__pending.discard(tier_zero)
            self.__dimensions[tier_zero] = size  # pylint: disable=unsupported-assignment-operation
        self.dimensions_changed.emit()
