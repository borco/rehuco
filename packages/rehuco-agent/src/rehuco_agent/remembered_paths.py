"""What the last run remembered, minus what is gone -- and the remote parts that arrive after the window is up (#464).

``MainWindow`` loads three lists of paths: the ``File`` menu's recents, the root catalogs' (recents and the one to
reopen), and the documents the session left open. This object judges every one of them
(:class:`~rehuco_agent.startup_presence.StartupPresence`) and keeps the three lists honest:

- **A file that is gone is forgotten from all of them**, at once for a fixed local drive and as soon as the scan hears
  for a share or a removable drive. "Gone" always means the device answered and does not hold the file.
- **A file whose device does not answer is kept, and not shown**: its recents entry stays but is disabled
  (:meth:`unavailable`), a session document is not opened and is **still remembered as open**
  (:attr:`still_open`) so it returns with its device, and a root catalog is not opened and stays the one to reopen.
- **A remote document or catalog that is there arrives late**, through :attr:`document_arrived` and
  :attr:`rehuco_arrived`, the moment its device answers -- the start never waits for it. The documents' saved
  split layout is re-applied once the last of them is in (:attr:`layout_due`), but only while the start is still
  settling (:data:`SETTLING_SECONDS`, counted from :meth:`window_shown`): after that the user may have rearranged
  things, and a layout restored over their work would be worse than documents left where they are. Each document is
  tabbed in at its saved place as it arrives whatever the time, so the order survives a slow share (#698).

Holds no thread and no Qt job of its own: the asking is :class:`~rehuco_agent.startup_presence.StartupPresence`'s, and
why that runs on daemon threads is documented once, with the measurements, in :mod:`borco_core.path_presence`.
"""

import logging
import time
from pathlib import Path
from typing import Final

from borco_core import Presence
from PySide6.QtCore import QObject, Signal

from .settings.document_session_settings import DocumentSessionSettings
from .settings.recent_files_settings import RecentFilesSettings
from .settings.rehuco_settings import RehucoSettings
from .settings.session_restore_settings import SessionRestoreSettings
from .startup_presence import StartupPresence

LOG: Final = logging.getLogger(__name__)

SETTLING_SECONDS: Final = 5.0
"""How long after the window is shown a late arrival may still bring the saved layout back whole, splits included, and
open a wide maximized view at once. Its place among the tabs and the focus do not depend on it. A scan answers a
live share in tens of milliseconds, so anything slower than this is a device the user has long since stopped
waiting for, and has probably started working past."""


class RememberedPaths(QObject):  # pylint: disable=too-many-instance-attributes
    """Judges the remembered paths and keeps the three lists in line with the verdicts.

    :param recent_files: the ``File`` menu's recents.
    :param rehuco: the root catalogs' recents and the one to reopen.
    :param session: the documents the last session left open.
    :param parent: optional Qt parent.
    """

    document_arrived: Signal = Signal(object, object, bool)
    """``(path, session item, take_focus)``: a remote document that was open last session is there; restore it.
    ``take_focus`` is whether it was the focused one: it takes the focus if the reader has not moved it."""

    rehuco_arrived: Signal = Signal(object)
    """The remote ``.rehuco`` to reopen is there; open it, unless the user has opened another meanwhile."""

    preview_arrived: Signal = Signal(object)
    """The last session's preview is there, with its entry: restore it as a document that arrived late is."""

    layout_due: Signal = Signal()
    """Every remote document that was awaited has answered and at least one arrived: re-apply the documents' saved
    layout, once."""

    def __init__(
        self,
        recent_files: RecentFilesSettings,
        rehuco: RehucoSettings,
        session: DocumentSessionSettings,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.__recent_files: Final = recent_files
        """The ``File`` menu's recents, kept in line with the verdicts."""
        self.__rehuco: Final = rehuco
        """The root catalogs' recents and the one to reopen."""
        self.__session: Final = session
        """The documents the last session left open, and the layout they were left in."""
        self.__kept_open: Final[set[Path]] = set()
        """The documents that were open and are not shown now, which the session goes on recording as open."""
        self.__awaiting: Final[set[Path]] = set()
        """The remote paths asked about whose answer has not come yet."""
        self.__deferred_rehuco: Path | None = None
        """The ``.rehuco`` to open once its device answers, if it is on one that must be asked."""
        self.__late_added = False
        """Whether a remote document has arrived since the last :attr:`layout_due`."""
        self.__settling_since: float | None = None
        """When the window was first shown (:meth:`window_shown`), on the monotonic clock; ``None`` before that."""
        remembered = [
            *recent_files.paths,
            *rehuco.recent.paths,
            *([rehuco.current_path] if rehuco.current_path is not None else []),
            *(path for path, item in session.items.items() if item.open),
            *([session.preview.path] if session.preview is not None else []),
        ]
        self.__presence: Final = StartupPresence(remembered, self)
        """Asks about every remote remembered path, and judges the fixed local ones at once."""
        self.__presence.answered.connect(self.__on_answered)
        for path, presence in self.__presence.local_paths.items():
            if presence is Presence.GONE:
                self.forget(path)

    def documents_to_restore_now(self, restore: SessionRestoreSettings) -> set[Path]:
        """The session's open documents on fixed local drives that are there and are to be restored with the window.

        As a side effect, notes which other open documents are to come back later or stay remembered: a remote one
        when the remote toggle is on is awaited; so is a local one that could not be judged (a permission error), which
        is kept open for the next run rather than lost.

        :param restore: the Session page's choices.
        :returns: the paths to hand to :meth:`DocumentsDock.restore_session`, the preview's among them when it is one.
        """
        now: set[Path] = set()
        for path, item in self.__session.items.items():
            if not item.open:
                continue
            if self.__presence.is_remote(path):
                if restore.restore_remote_documents:
                    self.__kept_open.add(path)
                    self.__awaiting.add(path)
            elif restore.restore_local_documents:
                if self.__presence.local_presence(path) is Presence.PRESENT:
                    now.add(path)
                else:
                    # a gone one was forgotten at construction, so what is left is one the operating system gave no
                    # verdict on (a permission error): not restored, not lost
                    self.__kept_open.add(path)
        preview = self.__session.preview
        if preview is not None and self.__note_preview(preview.path, restore):
            now.add(preview.path)
        return now

    def __note_preview(self, path: Path, restore: SessionRestoreSettings) -> bool:
        """Say whether the session's preview is restored with the window, and note it as awaited or kept otherwise, as
        :meth:`documents_to_restore_now` does a document.

        :param path: the document the preview showed.
        :param restore: the Session page's choices.
        :returns: whether it is to be restored now.
        """
        if self.__presence.is_remote(path):
            if restore.restore_remote_documents:
                self.__kept_open.add(path)
                self.__awaiting.add(path)
            return False
        if not restore.restore_local_documents:
            return False
        if self.__presence.local_presence(path) is Presence.PRESENT:
            return True
        self.__kept_open.add(path)
        return False

    @property
    def settling(self) -> bool:
        """Whether the start is recent enough for a late arrival to take the saved layout and cover."""
        return self.__settling()

    @property
    def still_open(self) -> frozenset[Path]:
        """The documents that were open and are not now -- their device has not answered, or has not yet -- which
        the session must go on recording as open so they come back."""
        return frozenset(self.__kept_open)

    def reached(self, path: Path | None) -> None:
        """The user opened ``path`` themselves, so from now on its dock -- open or closed -- is what the session
        records, not :attr:`still_open`.

        Without this, a document whose share was off at start, came back, and was then opened and **closed** by
        hand would be re-marked open at the next save and come back against the user's choice.

        :param path: the record just shown in a dock (``widget.model.path``, never the folder or archive opened);
            ``None`` -- a document with no file yet -- reaches nothing the session could hold.
        """
        if path is not None:
            self.__kept_open.discard(path)

    def defer_rehuco(self, path: Path) -> bool:
        """Leave the ``.rehuco`` at ``path`` to be opened when its device answers, if it is on one that must be asked.

        :param path: the catalog to reopen.
        :returns: whether it was deferred; ``False`` for one on a fixed local drive, which the caller opens now.
        """
        if not self.__presence.is_remote(path):
            return False
        self.__deferred_rehuco = path
        return True

    @property
    def deferred_rehuco(self) -> Path | None:
        """The ``.rehuco`` still waiting for its device, which the next save must go on remembering."""
        return self.__deferred_rehuco

    def clear_deferred_rehuco(self) -> None:
        """Stop waiting for the deferred ``.rehuco`` -- the user opened or closed a catalog themselves."""
        self.__deferred_rehuco = None

    def unavailable(self, path: Path) -> bool:
        """Whether ``path`` is remote and not known to be there -- its recents entry is shown disabled."""
        return self.__presence.unavailable(path)

    def forget(self, path: Path) -> None:
        """Drop ``path`` from every list: it is gone.

        :param path: a remembered path.
        """
        self.__recent_files.forget(path)
        self.__rehuco.forget(path)
        self.__session.forget(path)
        self.__session.forget_preview(path)
        self.__kept_open.discard(path)
        self.__awaiting.discard(path)
        if self.__deferred_rehuco == path:
            self.__deferred_rehuco = None
        self.__presence.forget(path)

    def start(self) -> None:
        """Begin asking about the remote paths."""
        self.__presence.start()

    def stop(self) -> None:
        """Deliver no more answers. See :meth:`StartupPresence.stop`."""
        self.__presence.stop()

    def window_shown(self) -> None:
        """Start the settling clock: the window is up, so an answer can reach the GUI thread from now on.

        Counted from here and not from construction, which comes before the whole window is built -- seconds in which
        no answer can be delivered, and which a slow share would otherwise spend out of the clock (#698). Only the
        first call counts.
        """
        if self.__settling_since is None:
            self.__settling_since = time.monotonic()

    def __settling(self) -> bool:
        """Whether the start is recent enough for a late arrival to take the saved layout and cover.

        :returns: ``True`` until :data:`SETTLING_SECONDS` have passed since :meth:`window_shown`.
        """
        return self.__settling_since is None or time.monotonic() - self.__settling_since < SETTLING_SECONDS

    def __on_answered(self, path: Path, presence: Presence) -> None:
        """A remote path was judged, on the GUI thread."""
        if presence is Presence.GONE:
            self.forget(path)
        elif presence is Presence.PRESENT:
            if path == self.__deferred_rehuco:
                self.__deferred_rehuco = None
                self.rehuco_arrived.emit(path)
            if path in self.__awaiting and path in self.__kept_open:
                self.__kept_open.discard(path)
                self.__late_added = True
                preview = self.__session.preview
                if preview is not None and preview.path == path:
                    self.preview_arrived.emit(preview)
                item = self.__session.items.get(path)
                if item is not None and item.open:
                    self.document_arrived.emit(path, item, path == self.__session.focused_path)
        self.__awaiting.discard(path)
        if not self.__awaiting and self.__late_added:
            self.__late_added = False
            if self.__settling():
                self.layout_due.emit()
            else:
                LOG.info("Session: the late layout is not applied, the start is past its settling time")
