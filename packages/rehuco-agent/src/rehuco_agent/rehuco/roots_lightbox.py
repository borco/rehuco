"""The Roots view's lightbox: a reference pack's images, or a folder's, shown without a document in the way (#456).

A document's own lightbox lives inside its Documents dock and reads what that document's Content Images or Files
sub-dock holds. Here there is no document: a double-click on a zip lists its images from the central directory, a
double-click on an image takes the images beside it, and the same :class:`~..fields.widgets.ImageLightbox` shows them.

An image copied or dragged out of it (#395) is named as one taken out of a document is: by the record that manages it
-- its id, else its location -- and its path relative to that record; an image no record manages, by its folder.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QWidget
from rehuco_core import ContentImageEntry, RenameCoordinator, list_archive_images

from ..documents.content_images.archive_cache import ArchiveCache
from ..documents.content_images.content_images_model import ArchiveImageSource
from ..fields.widgets import (
    ImageExporter,
    ImageLightbox,
    ImageSource,
    ImageViewerMode,
    PathImageSource,
    ThumbnailLoader,
    viewer_mode_for,
)
from ..settings.image_viewer_settings import shared_image_viewer_settings
from ..settings.persistent_settings import staging_folder
from ..settings.reference_images_settings import shared_reference_images_settings

LOG: Final = logging.getLogger(__name__)

EMPTY_PACK_MESSAGE: Final = "{name} holds no images the lightbox can show."


@dataclass(frozen=True, slots=True)
class ImagesOwner:
    """Whose images the lightbox shows, as an image copied out of it is named (#395).

    :ivar origin: what the staged name says the images came from (:func:`rehuco_core.staging_origin`).
    :ivar folder: what an image's path is named relative to -- the record's folder, as in a document.
    """

    origin: str
    folder: Path

    @classmethod
    def folder_of(cls, file: Path) -> ImagesOwner:
        """The owner of a file no record manages: its folder, by name.

        :param file: the image or the archive.
        :returns: the owner.
        """
        return cls(file.parent.name, file.parent)


class ListingSignals(QObject):
    """The sender one listing job answers through, deleted on the GUI thread only -- the shape
    :class:`~rehuco_agent.documents.content_images.content_images_model.JobSignals` documents.

    :param pool: the pool the job runs on, which owns the sender.
    """

    listed = Signal(int, object, list)
    """``(generation, archive, entries)``: an archive's images, in pack order."""

    def __init__(self, pool: QThreadPool) -> None:
        super().__init__(pool)


class ListingJob(QRunnable):
    """Lists an archive's images off the GUI thread: the central directory is one read, but over a share it is a slow
    one.

    :param signals: the sender to answer through, already wired; released when the job is done.
    :param generation: which request this answers.
    :param archive: the archive file.
    :param extensions: the recognized image extensions.
    :param coordinator: the rename barrier the read is held under.
    """

    def __init__(
        self,
        signals: ListingSignals,
        generation: int,
        archive: Path,
        extensions: tuple[str, ...],
        coordinator: RenameCoordinator,
    ) -> None:
        super().__init__()
        self.__signals: Final = signals
        self.__generation: Final = generation
        self.__archive: Final = archive
        self.__extensions: Final = extensions
        self.__coordinator: Final = coordinator

    def run(self) -> None:
        try:
            try:
                entries = list_archive_images(self.__archive, self.__extensions, self.__coordinator)
            except Exception:  # pylint: disable=broad-exception-caught
                # the pool would swallow it and no answer would ever arrive: the owner is told there is nothing
                LOG.exception("Listing the images of %s failed", self.__archive)
                entries = []
            self.__signals.listed.emit(self.__generation, self.__archive, entries)
        finally:
            self.__signals.deleteLater()


class RootsLightbox(QObject):
    """Opens the lightbox for the Roots view: over a zip's images, or over the images of a folder.

    **One viewer at a time**: opening another closes the previous one and lets go of its archive handles. Nothing is
    written to disk -- an archive's open handles are the cache's, and the thumbnails are Qt's in-process pixmap
    cache, as in a document's lightbox -- so everything goes with the viewer.

    The surface it paints on follows the settings, and **Shift**, **Ctrl** and **Ctrl+Shift** held at the activation
    pick the dock, the app window or the whole screen
    (:func:`~rehuco_agent.fields.widgets.image_lightbox.viewer_mode_for`). Whether the thumbnail row is shown starts
    from the setting and is remembered here for the next viewer, not written back.

    :param host: the widget the viewer belongs to and covers -- the Roots panel.
    :param coordinator: what every archive read is held under, so it never blocks a rename.
    """

    nothing_to_show = Signal(str)
    """Emitted with a sentence when an archive holds no images, for the owner to say where the user will see it."""

    def __init__(self, host: QWidget, coordinator: RenameCoordinator) -> None:
        super().__init__(host)
        self.__host: Final = host
        self.__coordinator: Final = coordinator
        self.__loader: Final = ThumbnailLoader(self)
        self.__generation = 0
        self.__viewer: ImageLightbox | None = None
        self.__strip_visible: bool | None = None
        self.__pending = (ImageViewerMode.DOCUMENT_OVERLAY, ImagesOwner("", Path()))
        """The surface the archive whose listing is out was asked for, read from the keys at the activation, and
        whose images it holds."""

    @property
    def viewer(self) -> ImageLightbox | None:
        """The viewer on screen, or ``None`` while there is none."""
        return self.__viewer

    def open_archive(self, archive: Path, owner: ImagesOwner | None = None) -> None:
        """Show the images of a zip, in pack order, starting on the first.

        The listing is read on the pool; a request overtaken by a newer one is dropped when it lands.

        :param archive: the zip or cbz.
        :param owner: whose images they are; the zip's folder when ``None``.
        """
        self.__generation += 1
        # the keys are read now, at the activation: the listing lands later, when they are no longer held
        self.__pending = (self.__mode(), owner if owner is not None else ImagesOwner.folder_of(archive))
        pool = QThreadPool.globalInstance()
        signals = ListingSignals(pool)
        signals.listed.connect(self.__on_listed)
        extensions = shared_reference_images_settings().content_image_extensions
        job = ListingJob(signals, self.__generation, archive, extensions, self.__coordinator)
        job.setAutoDelete(True)
        pool.start(job)

    def open_images(self, images: Sequence[Path], start: int, owner: ImagesOwner | None = None) -> None:
        """Show loose image files, starting on one of them.

        :param images: the files, in the order to browse them; never empty, as the one asked for is among them.
        :param start: the position to open on.
        :param owner: whose images they are; their folder when ``None``.
        """
        self.__generation += 1
        owner = owner if owner is not None else ImagesOwner.folder_of(images[0])
        self.__show(PathImageSource(images, owner.folder), start, None, self.__mode(), owner)

    @Slot(int, object, list)
    def __on_listed(self, generation: int, archive: Path, entries: list[ContentImageEntry]) -> None:
        """Open the viewer on a listing, unless a newer request has gone out since.

        :param generation: which request this answers.
        :param archive: the archive listed.
        :param entries: its images.
        """
        if generation != self.__generation:
            return
        if not entries:
            self.nothing_to_show.emit(EMPTY_PACK_MESSAGE.format(name=archive.name))
            return
        mode, owner = self.__pending
        cache = ArchiveCache(self.__coordinator)
        self.__show(ArchiveImageSource(entries, cache, owner.folder), 0, cache, mode, owner)

    @staticmethod
    def __mode() -> ImageViewerMode:
        """The surface the keys held right now ask for: **Shift** the Roots dock, **Ctrl** the app window,
        **Ctrl+Shift** the whole screen, none the setting -- as in a document.

        :returns: the surface.
        """
        return viewer_mode_for(QApplication.keyboardModifiers(), shared_image_viewer_settings().mode)

    def __show(
        self, source: ImageSource, index: int, cache: ArchiveCache | None, mode: ImageViewerMode, owner: ImagesOwner
    ) -> None:
        """Build the viewer over a source, as the settings ask, replacing any open one.

        :param source: the images to navigate.
        :param index: where to start.
        :param cache: the archive handles the source reads through, closed with the viewer; ``None`` for files.
        :param mode: the surface to paint on, chosen when the viewer was asked for.
        :param owner: whose images they are, as one copied out is named.
        """
        self.__close_viewer()
        settings = shared_image_viewer_settings()
        strip_visible = settings.strip_visible if self.__strip_visible is None else self.__strip_visible
        viewer = ImageLightbox(
            source,
            index,
            mode,
            self.__host,
            loader=self.__loader,
            strip_visible=strip_visible,
            strip_height=settings.lightbox_image_height,
            info_visible=settings.lightbox_info_visible,
            backdrop=QColor(settings.lightbox_backdrop),
            double_click_closes=settings.lightbox_double_click_closes,
            exporter=ImageExporter(staging_folder(), lambda: owner.origin),
        )
        self.__viewer = viewer
        # the closure holds the cache itself: by the time `destroyed` fires the viewer's wrapper is gone, and the
        # next viewer must not close the handles of this one's successor
        viewer.destroyed.connect(lambda: self.__on_viewer_gone(viewer, cache))
        viewer.strip_visible_changed.connect(self.__remember_strip)
        viewer.reveal()

    def __remember_strip(self, visible: bool) -> None:
        """Remember whether the thumbnail row was shown, for the next viewer.

        :param visible: whether it is.
        """
        self.__strip_visible = visible

    def __on_viewer_gone(self, viewer: ImageLightbox, cache: ArchiveCache | None) -> None:
        """Let go of what a viewer read through, once it is destroyed.

        :param viewer: the viewer that went.
        :param cache: its archive handles, if it had any.
        """
        if cache is not None:
            cache.close()
        if self.__viewer is viewer:
            self.__viewer = None

    def __close_viewer(self) -> None:
        """Close the viewer on screen, if any; it deletes itself and lets go of its handles."""
        viewer = self.__viewer
        self.__viewer = None
        if viewer is not None:
            viewer.close()
