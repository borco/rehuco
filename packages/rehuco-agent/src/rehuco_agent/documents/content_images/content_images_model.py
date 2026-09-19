"""The Content Images dock's model: the entries, their dimensions on demand, and the archive-backed
image source the lightbox and the thumbnail loader decode through (#221).

Nothing here is persisted: dimensions are read off each member's header the first time a row needs
them and held in memory, keyed by the tier-0 key ([[reference-images#image-identity]]) -- the shape
the scan sidecar ([[reference-images#scan-sidecar]]) can later sit in front of without a change.
"""

import threading
from collections.abc import Callable, Sequence
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


class EnumerateJob(QRunnable):
    """Enumerates a resource's content images off the GUI thread -- it opens every archive.

    :param model: the model to report to.
    :param generation: which request this answers; a stale answer is dropped.
    :param path: the ``.rehu`` file.
    :param extensions: the recognized image extensions.
    """

    def __init__(self, model: ContentImagesModel, generation: int, path: Path, extensions: tuple[str, ...]) -> None:
        super().__init__()
        self.__model: Final = model
        self.__generation: Final = generation
        self.__path: Final = path
        self.__extensions: Final = extensions

    def run(self) -> None:
        entries = enumerate_content_images(self.__path, self.__extensions)
        self.__model.report(lambda: self.__model.enumerated.emit(self.__generation, entries))


class HeaderJob(QRunnable):
    """Reads one member's pixel size off its header, off the GUI thread.

    A partial inflate first; the whole member only when the header is not in the first slice.

    :param model: the model to report to.
    :param entry: the member.
    """

    def __init__(self, model: ContentImagesModel, entry: ContentImageEntry) -> None:
        super().__init__()
        self.__model: Final = model
        self.__entry: Final = entry

    def run(self) -> None:
        if self.__model.stopped:
            return
        cache = self.__model.archive_cache
        head = cache.read_head(self.__entry)
        size = image_size(head) if head is not None else QSize()
        if head is not None and not size.isValid():
            whole = cache.read(self.__entry)
            size = image_size(whole) if whole is not None else QSize()
        self.__model.report(lambda: self.__model.header_read.emit(self.__entry.key, size))


class ContentImagesModel(QAbstractListModel):  # pylint: disable=too-many-instance-attributes
    """The content images of one resource, with each one's pixel size read on demand (#221).

    :param parent: optional Qt parent.
    """

    enumerated = Signal(int, list)
    """Worker-to-GUI hop: an `EnumerateJob`'s generation and entries. Internal."""

    header_read = Signal(object, QSize)
    """Worker-to-GUI hop: a member's tier-0 key and pixel size (invalid when unreadable). Internal."""

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
        # a job that outlives this object's C++ side (the document closed mid-read) must report into
        # nothing rather than emit into a dead signal, and the archives it held open must close.
        # Not bound methods of self: Qt drops a connection whose receiver is being destroyed
        self.destroyed.connect(self.__stopped.set)
        self.destroyed.connect(self.__cache.close)
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

    def report(self, emit: Callable[[], None]) -> None:
        """Run ``emit`` -- a job's signal emission -- unless this model is gone (worker thread).

        :param emit: the emission.
        """
        if self.__stopped.is_set():
            return
        try:
            emit()
        except RuntimeError:
            # the C++ side went between the check and the emit; the job's result is for nobody
            return

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
        job = EnumerateJob(self, self.__generation, path, extensions)
        job.setAutoDelete(True)
        self.__pool().start(job)

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
        jobs: list[HeaderJob] = []
        with self.__lock:
            for index in indices:
                entry = self.__entries[index]
                if entry.key in self.__dimensions or entry.key in self.__pending:
                    continue
                self.__pending.add(entry.key)
                jobs.append(HeaderJob(self, entry))
        pool = self.__pool()
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
