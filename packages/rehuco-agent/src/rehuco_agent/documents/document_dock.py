"""One open document's dock: it owns its view-model and viewer/editor widget, and keeps its own tab
title and persisted identity in step with the model ([[nodes#single-instance]])."""

import logging
from pathlib import Path
from typing import Final

import PySide6QtAds as QtAds
from borco_pyside.qtads import tab_label

from .document_widget import DocumentWidget
from .rehu_document_model import RehuDocumentModel

LOG: Final = logging.getLogger(__name__)

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


class DocumentDock(QtAds.CDockWidget):  # pylint: disable=too-few-public-methods
    """The dock for one open document -- it **owns** the document, not merely displays it.

    Holds the :class:`RehuDocumentModel` and the :class:`DocumentWidget` built over it, and parents the
    model to itself so the whole document (model, its `NameSuggestionModel`, the field bindings' data)
    is freed when the dock closes rather than leaking for the session (#148). The area
    (:class:`~rehuco_agent.documents.documents_dock.DocumentsDock`) creates the model -- it alone knows
    load-vs-new and the identity to file per-user writes under -- and hands it here parentless; this dock
    adopts it.

    Keeping the tab title and the persisted :meth:`objectName` in step with the model lives here too, as
    the dock's own concern: the connections are **bound methods of this dock**, so Qt severs them when the
    dock is destroyed, with no manual teardown and no way for a stale update to reach into the area's
    bookkeeping (the failure mode a lambda owned by the longer-lived area invited, #148).

    :param dock_manager: the area's dock manager this dock registers with.
    :param model: the view-model to wrap; created parentless by the area and adopted here.
    """

    def __init__(self, dock_manager: QtAds.CDockManager, model: RehuDocumentModel) -> None:
        super().__init__(dock_manager, "")
        model.setParent(self)
        self.__model: Final = model
        self.__widget: Final = DocumentWidget(model, self)

        self.setObjectName(self.__object_name(model.path))
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

        # bound methods of this dock, not lambdas: Qt drops them automatically when the dock is destroyed
        # (the dock is their receiver), so closing the document needs no explicit disconnect, and each
        # slot re-reads this dock's own model rather than looking a dock up in the area's map (#148)
        model.dirty_changed.connect(self.__update_title)  # type: ignore[attr-defined]
        model.lock_reasons_changed.connect(self.__update_title)  # type: ignore[attr-defined]
        model.path_changed.connect(self.__resync_object_name)  # type: ignore[attr-defined]
        tab_label(self).doubleClicked.connect(self.__on_tab_label_double_clicked)
        self.__update_title()

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
        the signal emits, and both ``dirty_changed`` and ``lock_reasons_changed`` drive it.
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

        :param path: the document's new path.
        """
        self.setObjectName(self.__object_name(path))

    @staticmethod
    def __object_name(path: Path | None) -> str:
        """A stable identifier for this dock, used only for
        :meth:`~rehuco_agent.documents.documents_dock.DocumentsDock.restore_state` to match a saved
        layout entry back up to the dock recreated for the same document on the next launch
        (``CDockManager`` matches docks up by ``objectName()``).

        Just the path itself, not the resource's UUID ([[data-model#stable-identity]]) -- a
        ``.tc``-backed document has no UUID until a live :meth:`~RehuDocumentModel.convert` mints
        one partway through an already-open dock's lifetime. Renaming an already-registered dock's
        ``objectName()`` is itself safe and propagates correctly (confirmed empirically:
        ``CDockManager.saveState()`` reads ``objectName()`` fresh, not from a stale add-time cache),
        so this dock resyncs it on every :attr:`~RehuDocumentModel.path_changed`
        (:meth:`__resync_object_name`) instead of needing the identifier to be transition-immune by
        construction.

        :param path: the document's current path.
        :returns: the path as a string, or a placeholder if it has no path yet.
        """
        return str(path) if path is not None else "untitled"

    def __on_tab_label_double_clicked(self) -> None:
        """Handle a double-click on this document's tab label."""
        # TODO: implement tab label double-clicked functionality -- convert a preview-mode tab
        # into a normal one, once tab preview mode (VSCode-explorer-style: opened-from-explorer
        # tabs start in preview and get replaced by the next preview open, until double-click or
        # an edit promotes them) exists.
        LOG.info("Tab label double-clicked; not implemented yet")
