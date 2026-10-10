"""One open document's window: a nested `CDockManager` hosting its sub-docks ([[plugins#viewer-editor-both]])."""

from typing import Final

import PySide6QtAds as QtAds
from borco_pyside.logging import LogWidget
from borco_pyside.qtads import QtAdsAutoHideButtonSuppressor, QtAdsFocusTracker, QtAdsPinGuard
from borco_pyside.widgets import MessageBanner
from PySide6.QtCore import Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow, QVBoxLayout, QWidget
from rehuco_core import TaskQueue

from ..commands import MAXIMIZE_DOCK, shared_command_registry
from ..dock_maximize import attach_maximize_handler
from ..fields import FieldsTab
from ..glyphs import TAB_CLOSE_GLYPH
from ..resource_events import ResourceEvents
from .checksum_actions import ChecksumActions
from .conversion_backup_actions import ConversionBackupActions
from .document_sub_docks import DocumentSubDocks, SubDockHost
from .rehu_document_model import RehuDocumentModel


class DocumentWidget(QMainWindow):  # pylint: disable=too-many-instance-attributes
    """One open document's window in the Documents dock: an inline notice strip over a nested dock
    manager holding the document's `DocumentSubDocks`, whose toolbar it carries (#380).

    Everything about the document itself -- which sub-docks it has and how a type switch changes them,
    its toolbar, its banner rows, its layout and the default layouts of its type -- is
    :attr:`sub_docks`'; this widget is the host they are built into, and owns only what belongs to its
    manager rather than to a document: the manager, its focus tracker and maximize toggle, and the
    banner's place above it. Its members other than those delegate to :attr:`sub_docks`, so a holder --
    `DocumentsDock`, `MainWindow` -- addresses the document through this widget unchanged, even after a
    preview dock has handed it another document (:meth:`show_model`, #39).

    :param model: the reactive view-model this document's docks bind to.
    :param parent: optional Qt parent.
    :param stylesheet_host: the widget carrying the dock styling for the whole nest -- normally the
        window's outermost ``CDockManager``. Given one, this document's manager sets no stylesheet of
        its own at all, since the host's already cascades over it: one document per manager means one
        redundant copy of QtAds' ~10 KB default sheet per open document, re-evaluated on every tab
        switch ([[appendices.qt-ads#per-manager-stylesheet]], #234, and see
        :class:`~borco_pyside.qtads.QtAdsFocusTracker`).
    :param task_queue: the app-wide queue this document's slow work goes on; ``None`` offers no such work.
    :param resource_events: the app's file announcements (#376), which the Files sub-dock follows; ``None``
        leaves it following only this document's own.
    """

    status_message: Signal = Signal(str)
    """Re-emits a field's transient status message (the ``authors`` viewer's hovered-link URL, a
    `StatusReporter`) so the owner above can route it -- an empty string clears the bar. This widget is
    itself a `QMainWindow` embedded in a dock, so it can't safely drive a status bar of its own (the
    ``.window()`` trap, see :meth:`~rehuco_agent.main_window.MainWindow` -- calling ``statusBar()`` here
    would lazily create a stray bar that swallows the message); it bubbles up to ``DocumentsDock`` and on
    to the genuine top-level window instead."""

    filter_requested: Signal = Signal(str)
    """Re-emits a field's clicked ``filter://`` link (a `FilterRequester`) on up to ``DocumentsDock``, the hop
    :attr:`status_message` makes ([[plugins#filter-urls]])."""

    record_activated: Signal = Signal(object)
    """Relays another resource's record, double-clicked in this document's Files sub-dock (#266), up to
    the window that knows how to open one.

    The same ``DocumentWidget`` -> ``DocumentsDock`` -> ``MainWindow`` hop :attr:`status_message` makes,
    and for the same reason: opening a resource is the window's act -- it resolves the path, reveals the
    documents area and remembers the file in ``Open recents`` -- so a sub-dock three managers down
    reports rather than reaches. Typed as plain ``object`` (Python-object marshalling) for the reason
    ``DocumentsDock``'s own object-typed signals document."""

    def __init__(
        self,
        model: RehuDocumentModel,
        parent: QWidget | None = None,
        stylesheet_host: QWidget | None = None,
        task_queue: TaskQueue | None = None,
        resource_events: ResourceEvents | None = None,
    ) -> None:
        super().__init__(parent)
        self.__banner: Final = MessageBanner(self)
        # a plain container, not `self`, hosts the dock manager -- CDockManager auto-installs itself
        # as its parent's central widget when that parent is a QMainWindow (confirmed empirically),
        # which would leave no room for the banner strip above it; parenting to this container instead
        # and setting *it* as the central widget keeps that auto-install from firing at all
        central = QWidget(self)
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self.__banner)
        self.__dock_manager: Final = QtAds.CDockManager(central)
        central_layout.addWidget(self.__dock_manager)
        self.setCentralWidget(central)

        self.__tracker: Final = QtAdsFocusTracker(
            self.__dock_manager, close_glyph=TAB_CLOSE_GLYPH, stylesheet_host=stylesheet_host
        )
        # pinning stays the main window's affordance (#279): a viewer or editor collapsed into a
        # sidebar of its own would put a third sidebar behind the two the window already has. The pin
        # button comes from a process-wide flag, so it is suppressed per manager rather than cleared
        # per dock. Nothing holds onto it -- it parents itself to the manager it suppresses.
        QtAdsAutoHideButtonSuppressor(self.__dock_manager)
        # and a pin the button never offered is undone as it happens (#491); parents itself to the manager too
        QtAdsPinGuard(self.__dock_manager, pins=False)
        # the maximize toggle on each sub-dock's tab (#341), filling this document; handed to the
        # sub-docks so every layout capture reads them un-maximized, and so a dock toggle exits it first
        self.__maximize_handler: Final = attach_maximize_handler(self.__dock_manager)

        self.__host: Final = SubDockHost(
            self, self.__dock_manager, self.__tracker, self.__maximize_handler, self.__banner
        )
        self.__task_queue: Final = task_queue
        self.__resource_events: Final = resource_events
        self.__sub_docks = self.__build_sub_docks(model)

        # keyboard reach for the tab button's maximize (#341), on whichever dock is current
        self.__maximize_action: Final = QAction("Maximize Current Dock", self)
        shared_command_registry().bind(self.__maximize_action, MAXIMIZE_DOCK.id)
        self.__maximize_action.triggered.connect(self.toggle_maximized_dock)
        self.addAction(self.__maximize_action)

    def show_model(self, model: RehuDocumentModel) -> None:
        """Show another document in this same window (#39): the current document's sub-docks are torn down
        (:meth:`DocumentSubDocks.teardown`) and the new one's are built into the same manager, banner and
        toolbar area. Everything that belongs to the manager -- the manager itself, its focus tracker,
        maximize toggle and banner -- stays.

        Lays nothing out: the caller adopts a layout next, as it does after building a widget.

        :param model: the document to show; the caller holds it, and lets go of the old one itself.
        """
        old = self.__sub_docks
        old.status_message.disconnect(self.status_message)
        old.filter_requested.disconnect(self.filter_requested)
        old.record_activated.disconnect(self.record_activated)
        self.removeToolBar(old.toolbar)
        old.teardown()
        self.__sub_docks = self.__build_sub_docks(model)

    def __build_sub_docks(self, model: RehuDocumentModel) -> DocumentSubDocks:
        """Build ``model``'s sub-docks into this widget's host, relaying their signals and carrying their
        toolbar.

        :param model: the document to build them over.
        :returns: the new sub-docks.
        """
        sub_docks = DocumentSubDocks(
            model, self.__host, task_queue=self.__task_queue, resource_events=self.__resource_events, parent=self
        )
        sub_docks.status_message.connect(self.status_message)
        sub_docks.filter_requested.connect(self.filter_requested)
        sub_docks.record_activated.connect(self.record_activated)
        self.addToolBar(sub_docks.toolbar)
        return sub_docks

    @property
    def sub_docks(self) -> DocumentSubDocks:
        """This document's sub-docks, toolbar and layout (#380)."""
        return self.__sub_docks

    @property
    def model(self) -> RehuDocumentModel:
        """The reactive view-model wrapping this document."""
        return self.__sub_docks.model

    @property
    def save_action(self) -> QAction:
        """Saves the document ([[data-model#write-integrity]]); bound to the ``document.save`` command."""
        return self.__sub_docks.save_action

    @property
    def maximize_action(self) -> QAction:
        """Maximizes the current dock over this document's others, or restores them -- the tab button's
        toggle from the keyboard (``document.maximize``, #343)."""
        return self.__maximize_action

    @property
    def maximized_dock(self) -> QtAds.CDockWidget | None:
        """The dock filling this document, or ``None`` while none is (#341)."""
        return self.__maximize_handler.maximized_dock

    def toggle_maximized_dock(self) -> None:
        """Restore the maximized dock if there is one, else maximize the current one -- the dock the
        focus tracker last saw focused. Nothing to do when no dock is current."""
        if self.__maximize_handler.maximized_dock is not None:
            self.__maximize_handler.restore()
            return
        dock = self.__tracker.current_dock
        if dock is not None:
            self.__maximize_handler.maximize(dock)

    @property
    def revert_action(self) -> QAction:
        """See :attr:`DocumentSubDocks.revert_action`."""
        return self.__sub_docks.revert_action

    @property
    def upgrade_action(self) -> QAction:
        """See :attr:`DocumentSubDocks.upgrade_action`."""
        return self.__sub_docks.upgrade_action

    @property
    def checksum_actions(self) -> ChecksumActions | None:
        """See :attr:`DocumentSubDocks.checksum_actions`."""
        return self.__sub_docks.checksum_actions

    @property
    def conversion_backup_actions(self) -> ConversionBackupActions:
        """See :attr:`DocumentSubDocks.conversion_backup_actions`."""
        return self.__sub_docks.conversion_backup_actions

    @property
    def log_widget(self) -> LogWidget:
        """See :attr:`DocumentSubDocks.log_widget`."""
        return self.__sub_docks.log_widget

    def detach(self) -> None:
        """See :meth:`DocumentSubDocks.detach`; called by `DocumentsDock` as the document is closed."""
        self.__sub_docks.detach()

    def toggle_action(self, tab: FieldsTab) -> QAction:
        """See :meth:`DocumentSubDocks.toggle_action`.

        :param tab: the tab whose dock to toggle.
        :returns: that dock's checkable toggle action.
        """
        return self.__sub_docks.toggle_action(tab)

    def take_focus(self) -> None:
        """See :meth:`DocumentSubDocks.take_focus`; called by `DocumentsDock` as this document becomes
        the current one."""
        self.__sub_docks.take_focus()

    def save_state(self) -> bytes:
        """See :meth:`DocumentSubDocks.save_state`.

        :returns: cbor2-encoded state, suitable for :meth:`restore_state`.
        """
        return self.__sub_docks.save_state()

    def save_layout_state(self) -> bytes:
        """See :meth:`DocumentSubDocks.save_layout_state`.

        :returns: cbor2-encoded layout, suitable for :meth:`restore_state`.
        """
        return self.__sub_docks.save_layout_state()

    def restore_state(self, state: bytes) -> bool:
        """See :meth:`DocumentSubDocks.restore_state`.

        :param state: the cbor2-encoded state to restore.
        :returns: whether the dock manager's own state was restored.
        """
        return self.__sub_docks.restore_state(state)

    def adopt_layout(self, state: bytes | None) -> None:
        """See :meth:`DocumentSubDocks.adopt_layout`; called by `DocumentsDock` once this widget is
        parented into the hierarchy.

        :param state: the document's own stored layout, or ``None`` when it has none.
        """
        self.__sub_docks.adopt_layout(state)
