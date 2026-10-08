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
  settling (:data:`SETTLING_SECONDS`): after that the user may have rearranged things, and a layout restored over
  their work would be worse than documents that tab in where they land.

Holds no thread and no Qt job of its own: the asking is :class:`~rehuco_agent.startup_presence.StartupPresence`'s, and
why that runs on daemon threads is documented once, with the measurements, in :mod:`borco_core.path_presence`.
"""

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

SETTLING_SECONDS: Final = 5.0
"""How long after the start a late arrival may still take the session's focus and its saved layout. A scan answers a
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
    ``take_focus`` is whether it was the focused one and the start is still settling."""

    rehuco_arrived: Signal = Signal(object)
    """The remote ``.rehuco`` to reopen is there; open it, unless the user has opened another meanwhile."""

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
        self.__rehuco: Final = rehuco
        self.__session: Final = session
        self.__kept_open: Final[set[Path]] = set()
        self.__awaiting: Final[set[Path]] = set()
        self.__deferred_rehuco: Path | None = None
        self.__late_added = False
        self.__born: Final = time.monotonic()
        remembered = [
            *recent_files.paths,
            *rehuco.recent.paths,
            *([rehuco.current_path] if rehuco.current_path is not None else []),
            *(path for path, item in session.items.items() if item.open),
        ]
        self.__presence: Final = StartupPresence(remembered, self)
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
        :returns: the paths to hand to :meth:`DocumentsDock.restore_session`.
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
                elif self.__presence.local_presence(path) is Presence.OFFLINE:
                    self.__kept_open.add(path)
        return now

    @property
    def still_open(self) -> frozenset[Path]:
        """The documents that were open and are not now -- their device has not answered, or has not yet -- which
        the session must go on recording as open so they come back."""
        return frozenset(self.__kept_open)

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

    def __settling(self) -> bool:
        """Whether the start is recent enough for a late arrival to take focus and layout."""
        return time.monotonic() - self.__born < SETTLING_SECONDS

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
                self.document_arrived.emit(
                    path, self.__session.items[path], path == self.__session.focused_path and self.__settling()
                )
        self.__awaiting.discard(path)
        if not self.__awaiting and self.__late_added:
            self.__late_added = False
            if self.__settling():
                self.layout_due.emit()
