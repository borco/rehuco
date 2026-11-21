"""What the last run remembered, minus what is gone -- and what the remote parts turn out to be once the window is up
(#464).

``MainWindow`` loads three lists of paths: the ``File`` menu's recents, the root catalogs' (recents and the one to
reopen), and the documents the session left open. This object judges every one of them
(:class:`~rehuco_agent.startup_presence.StartupPresence`) and keeps the three lists honest:

- **A file that is gone is forgotten from all of them**, at once for a fixed local drive and as soon as the scan hears
  for a share or a removable drive. "Gone" always means the device answered and does not hold the file. The one
  exception is a session document on a device that has to be asked: it has its dock by then, so the recents forget
  it and the session does not -- its dock says the file is missing, and the reader closes it.
- **A file whose device does not answer is kept**: its recents entry stays but is disabled (:meth:`unavailable`), and
  a root catalog is not opened and stays the one to reopen.
- **A session document on a device that has to be asked is restored with the window all the same** (#698), in its
  place, locked and unread (:meth:`documents_to_restore`); what its device says, at start or when it is asked again
  (:meth:`ask_again`), goes out through :attr:`storage_answered`. The start never waits for it.
- **A remote catalog that is there arrives late**, through :attr:`rehuco_arrived`, the moment its device answers.

Holds no thread and no Qt job of its own: the asking is :class:`~rehuco_agent.startup_presence.StartupPresence`'s, and
why that runs on daemon threads is documented once, with the measurements, in :mod:`borco_core.path_presence`.
"""

import logging
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


class RememberedPaths(QObject):
    """Judges the remembered paths and keeps the three lists in line with the verdicts.

    :param recent_files: the ``File`` menu's recents.
    :param rehuco: the root catalogs' recents and the one to reopen.
    :param session: the documents the last session left open.
    :param parent: optional Qt parent.
    """

    storage_answered: Signal = Signal(object, object)
    """``(path, presence)``: the device of a session document restored before it answered has said whether the file
    is there, is gone, or has not answered (#698)."""

    rehuco_arrived: Signal = Signal(object)
    """The remote ``.rehuco`` to reopen is there; open it, unless the user has opened another meanwhile."""

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
        self.__held: Final[set[Path]] = set()
        """The session documents restored before their device answered, whose answers go out."""
        self.__deferred_rehuco: Path | None = None
        """The ``.rehuco`` to open once its device answers, if it is on one that must be asked."""
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

    def documents_to_restore(self, restore: SessionRestoreSettings) -> tuple[set[Path], set[Path]]:
        """The session's open documents to restore with the window, and which of them are to be held unread.

        A document on a fixed local drive is restored when the local toggle is on: one that is there, and one the
        operating system gave no verdict on (a permission error), whose dock then says what its read ran into. A gone
        one was forgotten at construction. A document on a device that has to be asked is restored when the remote
        toggle is on, and **held**: its dock is made in its place and not read until the device has answered
        (:attr:`storage_answered`).

        :param restore: the Session page's choices.
        :returns: the paths to hand to :meth:`DocumentsDock.restore_session`, the preview's among them when it is one,
            and those of them to hold.
        """
        paths = [path for path, item in self.__session.items.items() if item.open]
        if self.__session.preview is not None:
            paths.append(self.__session.preview.path)
        now: set[Path] = set()
        for path in paths:
            if self.__presence.is_remote(path):
                if restore.restore_remote_documents:
                    now.add(path)
                    self.__held.add(path)
            elif restore.restore_local_documents:
                now.add(path)
        return now, set(self.__held)

    def ask_again(self, path: Path) -> bool:
        """Ask the device of a held session document once more (:meth:`StartupPresence.ask_again`).

        :param path: the document's path.
        :returns: whether it is being asked.
        """
        return self.__presence.ask_again(path)

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
        self.__held.discard(path)
        if self.__deferred_rehuco == path:
            self.__deferred_rehuco = None
        self.__presence.forget(path)

    def start(self) -> None:
        """Begin asking about the remote paths."""
        self.__presence.start()

    def stop(self) -> None:
        """Deliver no more answers. See :meth:`StartupPresence.stop`."""
        self.__presence.stop()

    def __on_answered(self, path: Path, presence: Presence) -> None:
        """A remote path was judged, on the GUI thread."""
        if path in self.__held:
            LOG.info("Session: the storage of %s answered: %s", path, presence.value)
            if presence is Presence.GONE:
                # its dock is there and says so; only the lists that would offer it again forget it
                self.__recent_files.forget(path)
            if presence is not Presence.OFFLINE:
                self.__held.discard(path)
            self.storage_answered.emit(path, presence)
        elif presence is Presence.GONE:
            self.forget(path)
        if presence is Presence.PRESENT and path == self.__deferred_rehuco:
            self.__deferred_rehuco = None
            self.rehuco_arrived.emit(path)
