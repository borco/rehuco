"""Reopening the documents the last session left open, in the documents area (#21, #66, #464, #576, #698) -- split
out of `DocumentsDock`, which hands it what it asks of the area (:class:`SessionRestoreHost`)."""

from collections.abc import Callable, Container
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, cast

import PySide6QtAds as QtAds
from rehuco_core.access import ResourceKey

from ..settings.document_session_settings import DocumentSessionSettings
from .document_dock import DocumentDock
from .document_widget import DocumentWidget
from .maximized_restore import MaximizedStack, is_wide
from .pending_docks import PendingDocks


class DockMaker(Protocol):  # pylint: disable=too-few-public-methods
    """How the documents area builds a dock for a record, the way a session's are built."""

    def __call__(
        self,
        key: ResourceKey,
        *,
        state: bytes | None = None,
        lazy: bool = False,
        preview: bool = False,
        preview_name: str | None = None,
    ) -> QtAds.CDockWidget:
        """Build ``key``'s dock.

        :param key: the record.
        :param state: its remembered layout.
        :param lazy: hold a placeholder, read when its tab is shown.
        :param preview: make it the preview.
        :param preview_name: the preview's object name.
        :returns: the dock.
        """
        ...  # pylint: disable=unnecessary-ellipsis


@dataclass(frozen=True, slots=True)
class SessionRestoreHost:  # pylint: disable=too-many-instance-attributes
    """What reopening a session asks of the documents area.

    :param find_dock: the dock showing a record, if the area shows one.
    :param make_dock: build a record's dock.
    :param activate: make a dock current, reading it if it is pending.
    :param widget_of: a dock's document widget.
    :param restore_state: lay the open docks out as a saved layout says, with the dock it says fills the area.
    :param hold: keep a dock just made from being read until its storage answers.
    :param preview: the preview dock, if there is one.
    :param pending: the docks not read yet.
    :param maximized_stack: the order maximized views are stacked in.
    """

    find_dock: Callable[[ResourceKey], QtAds.CDockWidget | None]
    make_dock: DockMaker
    activate: Callable[[QtAds.CDockWidget], object]
    widget_of: Callable[[QtAds.CDockWidget], DocumentWidget]
    restore_state: Callable[[object, str], bool]
    hold: Callable[[QtAds.CDockWidget], object]
    preview: Callable[[], DocumentDock | None]
    pending: PendingDocks
    maximized_stack: MaximizedStack


class DocumentSessionRestore:  # pylint: disable=too-few-public-methods  # one entry, over the host's parts
    """Reopens the documents the last session left open, in the documents area (#21).

    :param host: what it asks of the area.
    """

    def __init__(self, host: SessionRestoreHost) -> None:
        self.__host: Final = host

    def restore_session(
        self, session: DocumentSessionSettings, only: Container[Path] | None = None, held: Container[Path] = ()
    ) -> None:
        """Recreate every document the last session left open (#21), restoring its dock layout and
        focus -- touching **none of their files** up front (#66).

        Every remembered open path gets its dock/tab shell immediately, built around an empty
        placeholder model bound to its path (:meth:`RehuDocumentModel.create_pending` -- which is also
        what keeps the shell's own construction off the filesystem), read when its tab reaches the screen
        (:class:`~.pending_docks.PendingDocks`). The ones read *here* are the session's remembered focused one, through
        the area's own pending-load as it is made current, and any with a maximized view wider than its document, which
        shows whichever tab is in front. A legacy ``.tc`` is never made a placeholder.

        **A document whose storage has to be asked gets its dock here all the same** (#698), in its place in the
        layout, and is **held**: not read, however its tab is reached, until its storage has answered -- a read of a
        switched-off share holds a thread for as long as the share takes to time out. It shows locked meanwhile, and
        the reader closes it or leaves it. So the layout is applied once, with every dock in it, and the order, the
        splits and the focused document do not depend on how fast a share answers.

        **A path on a fixed local drive whose file is gone is not asked for here** (#464): ``MainWindow`` has already
        found out, with one ``stat``, and passes ``only``, so no empty locked
        ``missing`` dock is made for a delete between sessions. A path that is there but has become unparsable
        still reopens as an empty, **locked** dock materialized in its place ([[data-model#write-integrity]]) once
        its tab is actually shown, not skipped and not a dialog per file. Until then the tab shows no lock
        marker and does not count as missing -- knowing either would take the very read this defers. The outer layout
        (splits/tabs between documents) is restored only once every document it references has already been
        (re)created -- the area's ``restore_state`` matches saved entries up to currently-registered docks by name; it
        does not create any itself.

        :param session: the loaded session (#65) to restore.
        :param only: the paths to restore; ``None`` restores every open one. A path outside it is left as the
            session has it, neither restored nor forgotten.
        :param held: the paths among them whose storage has not answered yet.
        """
        host = self.__host
        host.maximized_stack.set_order(
            [*session.items, *([session.preview.path] if session.preview is not None else [])], session.focused_path
        )
        host.pending.restoring = True
        try:
            opened: dict[QtAds.CDockWidget, DocumentSessionSettings.Item] = {}
            for path, item in session.items.items():
                if not item.open or (only is not None and path not in only):
                    continue
                dock = self.__restore_dock(path, item)
                opened[dock] = item
                if path in held:
                    host.hold(dock)
            if session.preview is not None and (only is None or session.preview.path in only):
                dock = self.__restore_preview(session.preview)
                opened[dock] = session.preview.item
                if session.preview.path in held:
                    host.hold(dock)
            host.restore_state(session.docks_layout, session.maximized_dock)
        finally:
            host.pending.restoring = False

        focused_dock = next((dock for dock in opened if host.widget_of(dock).model.path == session.focused_path), None)
        if focused_dock is not None:
            host.activate(focused_dock)  # loads it now (#66) -- it is the first thing shown
        # a surface wider than its document shows whichever tab is in front, so it is read as it is shown
        for dock, item in opened.items():
            if item.maximized is not None and is_wide(item.maximized.mode):
                host.pending.load(dock)

    def __restore_dock(self, path: Path, item: DocumentSessionSettings.Item) -> QtAds.CDockWidget:
        """Make a document of the last session's dock, with its layout and its maximized view waiting for its read.

        :param path: the document's path.
        :param item: its session entry.
        :returns: its dock.
        """
        key = ResourceKey(path)
        found = self.__host.find_dock(key)
        if found is not None:
            # open already -- handed to the application as it started: what is shown is not the session's to cover
            return found
        # the remembered layout rides the open itself (#62): the dock applies exactly one layout per document -- this
        # one, or the saved default only where this one fails to restore -- not the default first, overwritten later
        dock = self.__host.make_dock(key, state=item.state, lazy=True)
        if item.maximized is not None:
            self.__host.widget_of(dock).restore_maximized(item.maximized)
        return dock

    def __restore_preview(self, preview: DocumentSessionSettings.Preview) -> QtAds.CDockWidget:
        """Make the last session's preview dock under the name its saved layout knows it by.

        A document already open in a dock of its own stays there and no preview is made, as showing it would not make
        one; nor is a preview of this run replaced.

        :param preview: its entry.
        :returns: the document's dock.
        """
        host = self.__host
        key = ResourceKey(preview.path)
        found = host.find_dock(key)
        current_preview = host.preview()
        if found is not None or current_preview is not None:
            return found if found is not None else cast(QtAds.CDockWidget, current_preview)
        dock = host.make_dock(key, state=preview.item.state, lazy=True, preview=True, preview_name=preview.name)
        if preview.item.maximized is not None:
            host.widget_of(dock).restore_maximized(preview.item.maximized)
        return dock
