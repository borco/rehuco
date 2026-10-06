"""One open document's dock: it holds its view-model and owns its viewer/editor widget, and keeps its own
tab title and persisted identity in step with the model ([[nodes#single-instance]])."""

from pathlib import Path
from typing import Final

import PySide6QtAds as QtAds
from borco_pyside.qtads import tab_label
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget
from rehuco_core import TaskQueue

from ..resource_events import ResourceEvents
from .document_widget import DocumentWidget
from .rehu_document_model import RehuDocumentModel

DIRTY_DOCK_MARKER: Final = "⬤ "
"""Marker prepended to the title of dirty document tabs."""

LOCKED_DOCK_MARKER: Final = "⚿ "
"""Marker prepended to the title of locked document tabs ([[data-model#schema-version]]); takes
precedence over :data:`DIRTY_DOCK_MARKER` -- a locked document's editors are disabled, so it can never
actually be dirty too. A plain Unicode symbol (Miscellaneous Symbols, not an emoji-presentation
codepoint), same as :data:`DIRTY_DOCK_MARKER` -- renders in the tab's own text color with no font
wiring, unlike a Phosphor glyph, which would need the tab label's font swapped mid-string (unverified
whether ``CElidingLabel``'s own eliding logic tolerates that) and can't be a ``CDockWidget.setIcon()``
icon either, since that single shared property also backs the tabs-menu entry, which has no notion of
"is this the current tab" for a state-dependent color to key off (confirmed the hard way)."""


class DocumentDock(QtAds.CDockWidget):
    """The dock for one open document: it **holds** the document's view-model and owns the widget over it.

    The :class:`RehuDocumentModel` belongs to the app's
    :class:`~rehuco_agent.documents.document_registry.DocumentRegistry`, which may hand the same one to
    other holders and frees it at the last release (#375); this dock only builds its
    :class:`DocumentWidget` over it, and that widget -- with everything it hangs on the model -- dies with
    the dock while the model may live on.

    Keeping the tab title and the persisted :meth:`objectName` in step with the model lives here too, as
    the dock's own concern: the connections are **bound methods of this dock**, so Qt severs them when the
    dock is destroyed, with no manual teardown and no way for a stale update to reach into the area's
    bookkeeping (the failure mode a lambda owned by the longer-lived area invited, #148).

    A **preview** dock (#39) outlives the documents it shows: :meth:`show_model` hands it the next one in
    place, cutting every connection to the last, until :meth:`promote` makes it an ordinary dock that shows one
    document for the rest of its life.

    :param dock_manager: the area's dock manager this dock registers with.
    :param model: the view-model to show, held for this dock by the area.
    :param stylesheet_host: passed straight through to this document's :class:`DocumentWidget` -- the
        widget carrying the dock styling for the whole nest (see
        :class:`~rehuco_agent.documents.documents_dock.DocumentsDock`).
    :param task_queue: the app-wide queue this document's slow work goes on (#204), passed straight
        through; ``None`` builds a document that offers no such work at all.
    :param resource_events: the app's file announcements (#376), passed straight through.
    :param preview_name: the object name of a preview dock (#39), kept until it is promoted -- unique per
        preview the area makes, since the manager's registry stays keyed by the name a dock was added under and
        a promoted preview keeps its entry. ``None`` builds an ordinary dock, named by its path.
    """

    path_moved: Signal = Signal(object, object)
    """Emitted ``(old_path, new_path)`` whenever this dock's document's :attr:`~RehuDocumentModel.path`
    moves -- a :meth:`~RehuDocumentModel.convert` swapping a ``.tc`` for its ``.rehu``, or a completed rename
    (#241). Tracked here because :attr:`~RehuDocumentModel.path_changed` carries only the *new* value, and
    ``Open recents`` needs the old one too (#295). ``old_path`` is the path this dock was built with or last
    reported, never ``None``: every document dock is built from a concrete path."""

    promotion_requested: Signal = Signal()
    """Emitted when a :attr:`is_preview` dock's title is double-clicked -- the reader asking to keep it (#39).
    The area promotes it (:meth:`promote`), since it is the area that knows which dock is its preview."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        dock_manager: QtAds.CDockManager,
        model: RehuDocumentModel,
        stylesheet_host: QWidget | None = None,
        task_queue: TaskQueue | None = None,
        resource_events: ResourceEvents | None = None,
        *,
        preview_name: str | None = None,
    ) -> None:
        super().__init__(dock_manager, "")
        self.__model = model
        self.__last_path = model.path
        self.__preview_name = preview_name
        self.__switching = False
        """True only while :meth:`load` moves the model to another record -- a path change that is no move."""
        self.__widget: Final = DocumentWidget(
            model, self, stylesheet_host=stylesheet_host, task_queue=task_queue, resource_events=resource_events
        )

        self.setObjectName(preview_name if preview_name is not None else self.__object_name(model.path))
        dock_features = QtAds.CDockWidget.DockWidgetFeature
        self.setFeatures(
            dock_features.CustomCloseHandling
            | dock_features.DockWidgetClosable
            | dock_features.DockWidgetDeleteOnClose
            | dock_features.DockWidgetFocusable
            | dock_features.DockWidgetForceCloseWithArea
            | dock_features.DockWidgetMovable
        )
        self.setWidget(self.__widget)

        self.__follow(model)
        tab_label(self).doubleClicked.connect(self.__on_tab_label_double_clicked)
        self.__update_title()
        self.__update_preview_mark()

    @property
    def is_preview(self) -> bool:
        """Whether this dock is the area's preview (#39): it shows whichever document it is handed next
        (:meth:`show_model`), keeps the fixed object name it was built with, and wears an italic title, until
        :meth:`promote` makes it an ordinary document dock."""
        return self.__preview_name is not None

    def show_model(self, model: RehuDocumentModel) -> None:
        """Show another document in this same dock (#39) -- a preview's switch in place.

        Every connection this dock made to the old model is cut before its widget tears down the old
        document's sub-docks and builds the new one's (:meth:`DocumentWidget.show_model`); the title, the
        path :attr:`path_moved` reports from, and every connection are then taken from ``model``. The caller
        holds ``model`` and lets go of the old one, and adopts a layout afterwards.

        :param model: the document to show.
        """
        self.__unfollow(self.__model)
        self.__widget.show_model(model)
        self.__model = model
        self.__last_path = model.path
        self.__follow(model)
        self.__update_title()

    def load(self, path: Path) -> None:
        """Show the record at ``path`` in this dock's own model (#381) -- a preview moving on to the next
        resource without building anything: :meth:`RehuDocumentModel.load` reseeds the widgets already here.

        Not a move: the model's path changes, but nothing was renamed, so :attr:`path_moved` -- which keeps
        ``Open recents`` pointed at a renamed file -- stays quiet, and the next move is reported from here.

        :param path: the record to show.
        """
        self.__switching = True
        try:
            self.__model.load(path)
        finally:
            self.__switching = False
        self.__last_path = self.__model.path

    def promote(self) -> None:
        """Make this preview an ordinary document dock, in place (#39): its object name becomes its path,
        as any document dock's is, and the italic goes. Nothing is rebuilt, so the document's widget state and
        the dock's position are kept. The manager's registry stays keyed by the preview name it was added
        under, which the area's removal already handles (#364)."""
        self.__preview_name = None
        self.__resync_object_name(self.__model.path)
        self.__update_preview_mark()

    def __follow(self, model: RehuDocumentModel) -> None:
        """Connect this dock's title and identity upkeep to ``model``.

        Bound methods of this dock, not lambdas: Qt drops them automatically when the dock is destroyed (the
        dock is their receiver), so closing the document needs no explicit disconnect, and each slot re-reads
        this dock's own model rather than looking a dock up in the area's map (#148). A switch in place cuts
        them explicitly (:meth:`__unfollow`).

        :param model: the model to follow.
        """
        model.dirty_changed.connect(self.__update_title)  # type: ignore[attr-defined]
        model.lock_reasons_changed.connect(self.__update_title)  # type: ignore[attr-defined]
        model.path_changed.connect(self.__resync_object_name)  # type: ignore[attr-defined]
        model.path_changed.connect(self.__update_title)  # type: ignore[attr-defined]
        model.path_changed.connect(self.__report_path_moved)  # type: ignore[attr-defined]

    def __unfollow(self, model: RehuDocumentModel) -> None:
        """Cut every connection :meth:`__follow` made to ``model``.

        :param model: the model this dock stops showing.
        """
        model.dirty_changed.disconnect(self.__update_title)  # type: ignore[attr-defined]
        model.lock_reasons_changed.disconnect(self.__update_title)  # type: ignore[attr-defined]
        model.path_changed.disconnect(self.__resync_object_name)  # type: ignore[attr-defined]
        model.path_changed.disconnect(self.__update_title)  # type: ignore[attr-defined]
        model.path_changed.disconnect(self.__report_path_moved)  # type: ignore[attr-defined]

    def __update_preview_mark(self) -> None:
        """Set the tab title in italic while this dock is a preview (#39), the way an editor marks a preview
        tab. On the label's font rather than in the title text, which carries the dirty and locked markers."""
        label = tab_label(self)
        font = label.font()
        font.setItalic(self.is_preview)
        label.setFont(font)

    @property
    def document_widget(self) -> DocumentWidget:
        """The viewer/editor widget this dock hosts; reach its model through ``document_widget.model``.

        Named apart from ``CDockWidget.widget()`` (the base class's own untyped content getter, which
        returns this same object as a bare ``QWidget``) so callers reach it with its real type.
        """
        return self.__widget

    def __update_title(self) -> None:
        """Set this dock's tab title/tooltip from its document's label, marking it locked or dirty.

        The tab title is the document's :attr:`~RehuDocumentModel.label`, with
        :data:`LOCKED_DOCK_MARKER` prepended while locked ([[data-model#schema-version]]) or
        :data:`DIRTY_DOCK_MARKER` while unsaved -- locked takes precedence, since a locked document's
        disabled editors mean it can never be dirty too. The tooltip always shows the full path.

        Takes no arguments and re-reads the model itself -- Qt lets a slot accept fewer arguments than
        the signal emits, and ``dirty_changed``, ``lock_reasons_changed`` and ``path_changed`` all drive
        it (a rename redraws it with the label and tooltip a fresh :meth:`RehuDocumentModel.path` gives).
        """
        name = self.__model.label
        if self.__model.locked:
            title = f"{LOCKED_DOCK_MARKER}{name}"
        elif self.__model.dirty:
            title = f"{DIRTY_DOCK_MARKER}{name}"
        else:
            title = name
        self.setWindowTitle(title)
        self.setTabToolTip(str(self.__model.path) if self.__model.path else "")

    def __resync_object_name(self, path: Path | None) -> None:
        """Resync the persisted dock identity when the document's path changes (a :meth:`convert`, a
        completed rename, or a path-less new document gaining one).

        A preview keeps the name it was built with (#39): it is what the manager's registry knows it by, and
        the next document it shows would only rename it again.

        :param path: the document's new path.
        """
        if not self.is_preview:
            self.setObjectName(self.__object_name(path))

    def __report_path_moved(self, path: Path | None) -> None:
        """Announce the document's move as :attr:`path_moved`, with the path it moved *from*.

        :param path: the document's new path.
        """
        if self.__switching:
            return
        old_path = self.__last_path
        if path is not None:
            self.__last_path = path
        self.path_moved.emit(old_path, path)

    @staticmethod
    def __object_name(path: Path | None) -> str:
        """A stable identifier for this dock, used only for
        :meth:`~rehuco_agent.documents.documents_dock.DocumentsDock.restore_state` to match a saved
        layout entry back up to the dock recreated for the same document on the next launch
        (``CDockManager`` matches docks up by ``objectName()``).

        Just the path itself, not the resource's UUID ([[data-model#stable-identity]]) -- a
        ``.tc``-backed document has no UUID until a live :meth:`~RehuDocumentModel.convert` mints
        one partway through an already-open dock's lifetime. Renaming an already-registered dock's
        ``objectName()`` propagates to what a layout capture records (confirmed empirically:
        ``CDockManager.saveState()`` reads ``objectName()`` fresh, not from a stale add-time cache),
        so this dock resyncs it on every :attr:`~RehuDocumentModel.path_changed`
        (:meth:`__resync_object_name`) instead of needing the identifier to be transition-immune by
        construction. The manager's own dock registry does **not** follow a rename -- it stays keyed by
        the name the dock was added under -- which is why the area takes the dock out through
        :func:`~borco_pyside.qtads.remove_dock_widget` rather than ``removeDockWidget`` (#364,
        [[appendices.qt-ads#dock-registry-keys]]).

        :param path: the document's current path.
        :returns: the path as a string, or a placeholder if it has no path yet.
        """
        return str(path) if path is not None else "untitled"

    def __on_tab_label_double_clicked(self) -> None:
        """Ask to keep a preview, on a double-click of its title (#39); an ordinary dock's title does nothing."""
        if self.is_preview:
            self.promotion_requested.emit()
