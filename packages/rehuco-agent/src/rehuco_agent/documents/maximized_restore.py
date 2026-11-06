"""What restoring maximized views takes beyond a document ([[plugins#session-restore]], #576)."""

from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from PySide6.QtWidgets import QWidget
from rehuco_core import IMAGE_EXTENSIONS

from ..fields.widgets.overlay_surface import OverlayMode, OverlaySurface


def is_wide(mode: str) -> bool:
    """Whether a remembered surface covers more than its own document, so it shows whichever tab is in front.

    :param mode: an ``OverlayMode`` value.
    :returns: whether it does.
    """
    return OverlayMode.stored(mode, OverlayMode.DOCUMENT_OVERLAY) is not OverlayMode.DOCUMENT_OVERLAY


def relative_key(path: Path, folder: Path | None) -> str | None:
    """What a session remembers an image file by.

    :param path: the image.
    :param folder: the record's folder.
    :returns: the path relative to the folder, ``None`` for a file outside it.
    """
    if folder is None:
        return None
    try:
        return path.relative_to(folder).as_posix()
    except ValueError:
        return None


def resolve_key(key: str, folder: Path | None) -> Path | None:
    """The image file a session remembers, confined to the record's folder.

    :param key: what :func:`relative_key` gave.
    :param folder: the record's folder.
    :returns: its path; ``None`` for a key that would leave the folder.
    """
    # a backslash is a separator to a Windows join whatever the posix parts say, so none is let through
    if folder is None or "\\" in key or ":" in key:
        return None
    relative = PurePosixPath(key)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    return folder / relative


def folder_images(folder: Path) -> list[Path]:
    """Every image in a folder, as the Files sub-dock lists them by default. Runs off the GUI thread: on a share it can
    block for the share's timeout.

    :param folder: the folder.
    :returns: the images, by name.
    """
    images = (path for path in folder.iterdir() if path.suffix.lower() in IMAGE_EXTENSIONS and path.is_file())
    return sorted(images, key=lambda path: path.name.casefold())


class MaximizedStack:
    """Keeps the wide views a session restored in session order, the focused document's on top.

    They open as their documents' reads answer, in any order, so each one opening raises every other in its place, and
    the one on top ends up with the keyboard. Focus staying inside overlays is `OverlaySurface`'s own rule, so two views
    over one surface do not fight for it.
    """

    def __init__(self) -> None:
        self.__ranks: dict[Path, int] = {}
        self.__views: list[tuple[int, OverlaySurface]] = []

    def set_order(self, paths: Sequence[Path], focused: Path | None) -> None:
        """Say what order the views stack in.

        :param paths: the session's documents, bottom first.
        :param focused: the session's focused document, which goes on top.
        """
        ordered = [path for path in paths if path != focused] + ([focused] if focused is not None else [])
        self.__ranks = {path: rank for rank, path in enumerate(ordered)}

    @property
    def holds_any(self) -> bool:
        """Whether a wide view is open, which then has the keyboard."""
        return bool(self.__views)

    def add(self, path: Path | None, view: QWidget) -> None:
        """Take a view just opened, and put every view back in its place.

        :param path: its document, ranked as :meth:`set_order` said; one it did not name goes on top.
        :param view: the view.
        """
        if not isinstance(view, OverlaySurface) or view.mode is OverlayMode.DOCUMENT_OVERLAY:
            return
        rank = self.__ranks.get(path, len(self.__ranks)) if path is not None else len(self.__ranks)
        self.__views = sorted([*self.__views, (rank, view)], key=lambda entry: entry[0])
        view.closed.connect(lambda: self.__forget(view))
        for _, shown in self.__views:
            shown.raise_()
        self.__give_keyboard(self.__views[-1][1])

    @staticmethod
    def __give_keyboard(view: OverlaySurface) -> None:
        """Give the view on top the keyboard, its window first when it is one of its own.

        :param view: the view.
        """
        view.activateWindow()
        view.setFocus()

    def __forget(self, view: OverlaySurface) -> None:
        """Stop stacking a view that has closed.

        :param view: the view.
        """
        self.__views = [entry for entry in self.__views if entry[1] is not view]
