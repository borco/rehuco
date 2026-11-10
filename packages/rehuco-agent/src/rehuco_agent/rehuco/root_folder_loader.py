"""The Roots view's folder reads, off the GUI thread (#378, [[plugins#rehuco-dock]]).

One :class:`~rehuco_core.RootFolderLister` read per request on the global thread pool, its answer handed back on the
GUI thread through the application's :class:`~rehuco_agent.pool_relay.PoolRelay` -- the seam
:class:`~.roots_folder_model.RootsFolderModel` lists through.
"""

from pathlib import Path
from uuid import UUID

from PySide6.QtCore import QObject, QThreadPool, Signal
from rehuco_core import DirectoryListing, RootFolderLister

from ..pool_relay import PoolRelay


class RootFolderLoader(QObject):
    """Runs a :class:`~rehuco_core.RootFolderLister` read on the global thread pool and hands the answer back on the
    GUI thread, through the application's relay: an owner destroyed while the read was out hears nothing.

    The mechanism is :class:`~rehuco_agent.documents.files_rows.FilesRowsLoader`'s, but **keyed**: it is
    single-generation and answers for one resource's ``.rehu``, where a column view has several folders out at once,
    each told apart by the serial its caller chose.

    :param parent: optional Qt parent.
    """

    listed = Signal(int, object)
    """``(serial, listing)``: one request's answer, a :class:`~rehuco_core.rehu_file_kinds.DirectoryListing`. Typed as
    plain ``object`` for the reason ``DocumentsDock.open_requested`` is. Emitted once for every :meth:`start`, an
    unreadable folder included."""

    def start(
        self,
        serial: int,
        lister: RootFolderLister,
        root_id: UUID,
        relative: tuple[str, ...],
        covering: tuple[str, ...] | None = None,
    ) -> None:
        """Read one folder on the pool.

        :param serial: what the answer is told apart by.
        :param lister: what lists it.
        :param root_id: the root the folder is under.
        :param relative: the folder's path under the root; empty for the root's own folder.
        :param covering: the directory-scoped record above whose ``info.checksum`` covers this folder, if any.
        """
        relay = PoolRelay.instance()
        QThreadPool.globalInstance().start(lambda: self.__run(relay, serial, lister, root_id, relative, covering))

    def __run(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        relay: PoolRelay,
        serial: int,
        lister: RootFolderLister,
        root_id: UUID,
        relative: tuple[str, ...],
        covering: tuple[str, ...] | None,
    ) -> None:
        """Read, on a pool thread, and answer through ``relay``.

        :param relay: the application's relay.
        :param serial: the request's serial.
        :param lister: what lists the folder.
        :param root_id: the root.
        :param relative: the folder under it.
        :param covering: see :meth:`start`.
        """
        try:
            listing = (
                lister.list(root_id, relative)
                if covering is None
                else lister.list(root_id, relative, covering=covering)
            )
        except OSError:
            listing = DirectoryListing(Path(), reachable=False)
        relay.post(self, self.__deliver, serial, listing)

    def __deliver(self, serial: int, listing: DirectoryListing) -> None:
        """Emit :attr:`listed` with a read's answer (GUI thread).

        :param serial: the request's serial.
        :param listing: what it listed.
        """
        self.listed.emit(serial, listing)
