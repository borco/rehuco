"""Per-document viewer/editor docks over a nested `CDockManager` ([[plugins#viewer-editor-both]])."""

from typing import Any, Final

import cbor2
import PySide6QtAds as QtAds
from borco_pyside.qtads import QtAdsFocusTracker
from borco_pyside.theming import ActionIconThemeHandler
from borco_pyside.widgets import MessageBanner, MessageBannerRow, MessageBannerSeverity
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import QMainWindow, QMessageBox, QVBoxLayout, QWidget

from rehuco_agent.documents.document_fields import build_document_form
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields import FieldsTab, StatefulWidget

STATE_VERSION_KEY: Final = "version"
STATE_VERSION: Final = 3
"""Schema version of :meth:`DocumentWidget.save_state`'s blob. The dock layout is keyed by dock
object name, so any change to the docks (names, count, which tabs exist) makes an older blob
incompatible: QtAds's ``restoreState`` would accept it and silently hide the current docks. Bump this
on any such change; :meth:`DocumentWidget.restore_state` ignores a blob whose version differs, keeping
the default (all-visible) layout instead."""

STATE_DOCK_MANAGER_KEY: Final = "dock_manager"
STATE_STASHED_SIZES_KEY: Final = "stashed_sizes"
STATE_CURRENT_DOCK_KEY: Final = "current_dock"
STATE_WIDGET_STATE_KEY: Final = "widget_state"

SAVE_ICON_RESOURCE: Final = ":/icons/document_save.svg"
REVERT_ICON_RESOURCE: Final = ":/icons/document_revert.svg"
CONVERT_KEEP_BACKUPS_ICON_RESOURCE: Final = ":/icons/tc_convert_with_backup.svg"
CONVERT_DISCARD_ICON_RESOURCE: Final = ":/icons/tc_convert.svg"
UPGRADE_ICON_RESOURCE: Final = ":/icons/rehu_upgrade.svg"

UPGRADE_MESSAGE: Final = "This document uses an older format — click the <i>Upgrade</i> button to bring it up to date."
"""The upgrade offer's inline banner message (#89, [[data-model#schema-version]]); names the toolbar
button by the label it actually carries, the same way the banner already names Revert/Convert as *the*
remedy for every lock reason. The specs' own user-facing word for this is "upgrade" -- "migration" stays
the internal name."""


class DocumentWidget(QMainWindow):  # pylint: disable=too-many-instance-attributes
    """One open document's **viewer** and **editor**, each in its own dock ([[plugins#viewer-editor-both]]).

    Both docks are built once, from the same :class:`RehuDocumentModel`, and stay live regardless of
    which are currently visible -- toggling a dock only hides/shows it, so an edit in the (possibly
    hidden) editor still reaches the (possibly hidden) viewer through the model's signals, making
    "both" work even when only one is on screen. Carries the closed-dock-size workaround
    ([[packaging-deployment#qml-regression]]): `CDockManager.splitterSizes` are stashed on
    ``viewToggled(False)`` -- confirmed, against this QtAds version, to still fire with the area at
    its pre-hide size, unlike ``closeRequested`` (never emitted by a toggle-hide; that signal is
    for the ``CustomCloseHandling`` close-button flow `DocumentsDock` uses instead) -- and
    re-applied on ``viewToggled(True)``, since QtAds does not otherwise restore a closed dock's size.
    Also carries the save action (the platform save shortcut, e.g. ``Ctrl+S``), since A1's per-file
    save button/shortcut ([[data-model#write-integrity]]) has no other home in the dock shell, and a
    revert action that re-reads the document from disk (#41). Save is enabled only while the model is
    :attr:`~RehuDocumentModel.dirty` -- there is nothing to save otherwise. Revert stays enabled
    unconditionally: it is also how a clean document picks up a change made outside this app, not
    just how a dirty one discards in-memory edits. The editor docks' content is disabled outright
    while the model is :attr:`~RehuDocumentModel.locked` (A3, [[data-model#schema-version]]) -- a file-wide
    or active-block ``format_version`` newer than this build understands ([[plugins#plugin-blocks]], #81),
    so editing isn't safe.

    While viewing a legacy ``.tc`` (:attr:`~RehuDocument.legacy_tc`, A3.1,
    [[acquisition-tooling#tc-to-rehu]]), Save and Revert are hidden -- there is nothing to save, and
    Revert would try to re-parse the ``.tc`` path as JSON and raise -- and two convert actions take
    their place instead, each running :meth:`~RehuDocumentModel.convert`'s safe-replace sequence. On
    success the model swaps in the converted, unlocked document in place: the same toolbar swap runs
    in reverse (Save/Revert reappear, the convert actions hide) and the dock's lock marker drops, with
    no new dock and no reload round-trip.

    A clean document whose file on disk predates :data:`~rehuco_core.CURRENT_FORMAT_VERSION`, its active
    plugin block's own version ([[plugins#plugin-blocks]], #81), or both
    (:attr:`~RehuDocumentModel.upgradable`, #89) gets the same treatment as a legacy ``.tc``: Save
    hides and :attr:`upgrade_action` takes its place, since the meaningful write action on a clean,
    older-format document is the upgrade, not a no-op Save. Saving is what upgrades a document
    (:meth:`RehuDocumentModel.save`'s own docstring), so the swap runs in reverse the moment the
    document is no longer clean-and-old, whether from this action, an ordinary Save once dirtied, or a
    successful Revert. The inline notice banner also gets a row for it, same as every lock reason --
    message-only, since the remedy already sits right above the strip.

    :param model: the reactive view-model this document's docks bind to.
    :param parent: optional Qt parent.
    """

    def __init__(self, model: RehuDocumentModel, parent: QWidget | None = None) -> None:  # pylint: disable=too-many-statements
        super().__init__(parent)
        self.__model: Final = model

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

        self.__tracker: Final = QtAdsFocusTracker(self.__dock_manager)
        self.__stashed_sizes: Final[dict[str, list[int]]] = {}
        self.__restoring_layout = False

        # the whole field composition (location + images + record fields + unknown fallbacks) is
        # authored in document_fields; this widget only hosts the resulting docks
        form = build_document_form(model)
        # one dock per FieldsTab: editor tabs stacked on the left, viewer tabs on the right
        self.__editor_docks: Final = self.__add_docks(form.make_editor(model), "editor", QtAds.LeftDockWidgetArea)
        self.__viewer_docks: Final = self.__add_docks(form.make_viewer(model), "viewer", QtAds.RightDockWidgetArea)

        self.__save_action: Final = QAction("&Save", self)
        self.__save_action.setShortcut(QKeySequence.StandardKey.Save)
        # WidgetWithChildrenShortcut, not the default WindowShortcut: this widget is a QMainWindow
        # embedded in a dock, not a genuine top-level window, so WindowShortcut resolves to the
        # single real top-level window shared by every open document -- with two dirty documents
        # open, Qt would see two enabled actions on the same key sequence in that shared scope and
        # call it ambiguous, firing neither (#41). Scoping to this widget's own subtree instead
        # means the shortcut only fires whichever document actually has focus.
        self.__save_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        ActionIconThemeHandler(self.__save_action, SAVE_ICON_RESOURCE)
        self.__save_action.triggered.connect(model.save)
        self.addAction(self.__save_action)

        self.__revert_action: Final = QAction("&Revert", self)
        ActionIconThemeHandler(self.__revert_action, REVERT_ICON_RESOURCE)
        self.__revert_action.triggered.connect(model.revert)
        self.addAction(self.__revert_action)

        self.__convert_keep_backups_action: Final = QAction("Convert, &Keep Backups", self)
        ActionIconThemeHandler(self.__convert_keep_backups_action, CONVERT_KEEP_BACKUPS_ICON_RESOURCE)
        self.__convert_keep_backups_action.triggered.connect(lambda: self.__on_convert_triggered(keep_backups=True))
        self.addAction(self.__convert_keep_backups_action)

        self.__convert_discard_originals_action: Final = QAction("Convert, &Discard Originals", self)
        self.__convert_discard_originals_action.setIcon(QIcon(CONVERT_DISCARD_ICON_RESOURCE))
        self.__convert_discard_originals_action.triggered.connect(
            lambda: self.__on_convert_triggered(keep_backups=False)
        )
        self.addAction(self.__convert_discard_originals_action)

        self.__upgrade_action: Final = QAction("&Upgrade", self)
        ActionIconThemeHandler(self.__upgrade_action, UPGRADE_ICON_RESOURCE)
        # save() upgrades a stale-on-disk document as a side effect of writing it -- there is no
        # separate migrate call (RehuDocumentModel.upgradable's own docstring)
        self.__upgrade_action.triggered.connect(model.save)
        self.addAction(self.__upgrade_action)

        self.__save_action.setEnabled(model.dirty)
        model.dirty_changed.connect(self.__on_dirty_changed)  # type: ignore[attr-defined]

        self.__set_editors_locked(model.locked)
        self.__update_write_action_visibility()
        self.__banner.set_rows(self.__banner_rows())
        model.lock_reasons_changed.connect(self.__on_lock_reasons_changed)  # type: ignore[attr-defined]
        model.upgradable_changed.connect(self.__on_upgradable_changed)  # type: ignore[attr-defined]

        toolbar = self.addToolBar("View")
        toolbar.addAction(self.__revert_action)
        toolbar.addAction(self.__save_action)
        toolbar.addAction(self.__upgrade_action)
        toolbar.addAction(self.__convert_keep_backups_action)
        toolbar.addAction(self.__convert_discard_originals_action)
        for dock in (*self.__viewer_docks.values(), *self.__editor_docks.values()):
            toolbar.addAction(dock.toggleViewAction())

    @property
    def model(self) -> RehuDocumentModel:
        """The reactive view-model wrapping this document."""
        return self.__model

    @property
    def save_action(self) -> QAction:
        """Saves the document ([[data-model#write-integrity]]); bound to the platform's save shortcut."""
        return self.__save_action

    @property
    def revert_action(self) -> QAction:
        """Discards in-memory edits and reloads the document from disk (#41)."""
        return self.__revert_action

    @property
    def upgrade_action(self) -> QAction:
        """Upgrades this document to the current format by saving it (#89,
        :attr:`~RehuDocumentModel.upgradable`). Visible on the toolbar exactly while the offer stands,
        same as the convert actions during ``legacy_tc``."""
        return self.__upgrade_action

    def toggle_action(self, tab: FieldsTab) -> QAction:
        """The visibility-toggle action for ``tab``'s dock -- whichever viewer or editor tab it is.

        :param tab: the tab whose dock to toggle.
        :returns: that dock's checkable toggle action.
        :raises KeyError: if no dock hosts ``tab``.
        """
        dock = self.__viewer_docks.get(tab) or self.__editor_docks.get(tab)
        if dock is None:
            raise KeyError(tab)
        return dock.toggleViewAction()

    def save_state(self) -> bytes:
        """Serialize this document's dock layout (visible docks, splitter sizes) and each persisting
        widget's own state for persistence.

        Widget state (e.g. the path field's expand state) rides along here -- persisted per ``.rehu``
        together with the tab layout, not in a separate global settings section (#25).

        :returns: cbor2-encoded state, suitable for :meth:`restore_state`
            (:class:`~rehuco_agent.settings.document_session_settings.DocumentSessionSettings.Item.state`).
        """
        return cbor2.dumps(
            {
                STATE_VERSION_KEY: STATE_VERSION,
                STATE_DOCK_MANAGER_KEY: bytes(self.__dock_manager.saveState().data()),
                STATE_STASHED_SIZES_KEY: self.__stashed_sizes,
                STATE_CURRENT_DOCK_KEY: self.__tracker.save_state(),
                STATE_WIDGET_STATE_KEY: {
                    name: widget.save_state() for name, widget in self.__stateful_widgets().items()
                },
            }
        )

    def restore_state(self, state: bytes) -> bool:
        """Restore a dock layout previously captured by :meth:`save_state`.

        :param state: the cbor2-encoded state to restore.
        :returns: ``True`` if the dock manager's own state was restored successfully; ``False`` if
            ``state`` was empty, malformed, not in the expected shape, or of an incompatible
            :data:`STATE_VERSION` (in which case the default layout is kept).
        """
        try:
            values: Any = cbor2.loads(state)
        except cbor2.CBORDecodeError:
            return False
        if not isinstance(values, dict):
            return False
        # An incompatible (e.g. pre-rename) blob would restore cleanly but hide the current docks,
        # leaving a blank window -- ignore it and keep the default all-visible layout instead.
        if values.get(STATE_VERSION_KEY) != STATE_VERSION:
            return False

        stashed_sizes = values.get(STATE_STASHED_SIZES_KEY)
        if isinstance(stashed_sizes, dict):
            self.__stashed_sizes.clear()
            self.__stashed_sizes.update(stashed_sizes)

        dock_manager_state = values.get(STATE_DOCK_MANAGER_KEY, b"")
        # restoreState() fires viewToggled(True) for every dock it reconstructs, even ones never
        # really hidden/shown in the user-facing sense -- without this guard, __on_view_toggled
        # would re-apply __stashed_sizes (last updated on some earlier, unrelated hide/show toggle,
        # not necessarily reflecting the sizes actually being restored here) right on top of the
        # correct sizes restoreState() itself just set, clobbering them with stale data
        self.__restoring_layout = True
        try:
            restored = bool(self.__dock_manager.restoreState(QByteArray(dock_manager_state)))
        finally:
            self.__restoring_layout = False
        if restored:
            # re-select the dock that was current -- restoreState above only recovers the current
            # tab within each area, not which of two split (viewer/editor) areas actually had focus
            current_dock_state = values.get(STATE_CURRENT_DOCK_KEY, b"")
            if isinstance(current_dock_state, bytes):
                self.__tracker.restore_state(current_dock_state)

        widget_state = values.get(STATE_WIDGET_STATE_KEY)
        if isinstance(widget_state, dict):
            widgets = self.__stateful_widgets()
            for name, saved in widget_state.items():
                widget = widgets.get(name)
                if widget is not None and isinstance(saved, bytes):
                    widget.restore_state(saved)
        return restored

    def __stateful_widgets(self) -> dict[str, StatefulWidget]:
        """The persisting widgets (`StatefulWidget`) across all docks, keyed by object name.

        Found by protocol rather than by holding references or knowing which field types persist, so
        persistence stays decoupled from the field toolkit's layout and its set of stateful widgets. A
        field names its stateful widget after itself (via ``setObjectName``), which is the key here.

        Enumerated through the manager's dock registry (not ``findChildren``): QtAds detaches the
        content of a dock hidden behind another tab from the widget tree, so ``findChildren`` would
        miss it once a second editor tab (e.g. the description) is present.

        :returns: the stateful widgets, keyed by their object name.
        """
        widgets: dict[str, StatefulWidget] = {}
        for dock in self.__dock_manager.dockWidgetsMap().values():
            content = dock.widget()
            for widget in (content, *content.findChildren(QWidget)):
                name = widget.objectName()
                if name and isinstance(widget, StatefulWidget):
                    widgets[name] = widget
        return widgets

    def __on_dirty_changed(self, dirty: bool) -> None:
        """Enable save only while the model holds unsaved edits -- there is nothing to save otherwise.

        Revert stays enabled regardless: it re-reads the document from disk (#41), which is useful
        even on a clean model, to pick up a change made outside this app.

        :param dirty: the model's new dirty state.
        """
        self.__save_action.setEnabled(dirty)

    def __on_lock_reasons_changed(self) -> None:
        """Disable/re-enable the editor docks and rebuild the inline notice strip as the model's lock
        reasons change (e.g. on revert or a successful :meth:`~RehuDocumentModel.convert`).

        Takes no arguments and re-reads ``self.__model.lock_reasons`` itself, rather than accepting the
        signal's payload -- Qt lets a slot accept fewer arguments than the signal emits, and the banner
        needs the same live list :meth:`__banner_rows` already reads off the model, not a stale copy
        the signal happened to carry.
        """
        self.__set_editors_locked(self.__model.locked)
        self.__update_write_action_visibility()
        self.__banner.set_rows(self.__banner_rows())

    def __on_upgradable_changed(self) -> None:
        """Swap the toolbar's write action and rebuild the inline notice strip as the model's upgrade
        offer appears or clears (#89) -- the same toolbar-plus-banner shape
        :meth:`__on_lock_reasons_changed` already drives for every lock reason.

        Takes no arguments and re-reads ``self.__model.upgradable`` itself, same as
        :meth:`__on_lock_reasons_changed` does for its own signal.
        """
        self.__update_write_action_visibility()
        self.__banner.set_rows(self.__banner_rows())

    def __banner_rows(self) -> list[MessageBannerRow]:
        """Build the inline notice strip's current rows: one per active lock reason (#94), plus the
        upgrade offer (#89) when the document has one.

        Message-only, with no remedy button -- every kind's remedy is already on this widget's own
        toolbar (Revert, always visible except during ``legacy_tc``; the convert actions, visible
        exactly during it; :attr:`upgrade_action`, visible exactly while
        :attr:`~RehuDocumentModel.upgradable`), so a button here would only duplicate a control already
        sitting right above the strip.

        :returns: one row per :attr:`~RehuDocumentModel.lock_reasons` entry, in the same order, plus a
            trailing upgrade row when :attr:`~RehuDocumentModel.upgradable` is set.
        """
        rows = [MessageBannerRow(MessageBannerSeverity.WARNING, reason.message) for reason in self.__model.lock_reasons]
        if self.__model.upgradable:
            rows.append(MessageBannerRow(MessageBannerSeverity.INFO, UPGRADE_MESSAGE))
        return rows

    def __set_editors_locked(self, locked: bool) -> None:
        """Disable every editor dock's content while ``locked`` -- the document's ``format_version`` is
        newer than this build understands ([[data-model#schema-version]]), so editing it isn't safe.

        Only the content widget is disabled, not the dock itself: the tab/toggle stay usable, so the
        editor is still viewable, just not editable.

        :param locked: whether to disable (``True``) or re-enable (``False``) the editor docks.
        """
        for dock in self.__editor_docks.values():
            dock.widget().setEnabled(not locked)

    def __update_write_action_visibility(self) -> None:
        """Swap the toolbar's write action for whichever one is actually meaningful right now,
        re-reading :attr:`~RehuDocument.legacy_tc` and :attr:`~RehuDocumentModel.upgradable` off the
        model directly rather than taking either as a parameter (both :meth:`__on_lock_reasons_changed`
        and :meth:`__on_upgradable_changed` call this on their own signal, and each needs the *other*
        condition's current value too).

        Two independent swaps, never both active at once (a legacy ``.tc`` has no ``.rehu`` on disk at
        any version yet, so it is never :attr:`~RehuDocumentModel.upgradable`):

        - **legacy_tc**: Save/Revert hide, the two convert actions take their place.
        - **upgradable**: Save hides, :attr:`upgrade_action` takes its place -- the meaningful write
          action on a clean, older-format document is the upgrade, not a no-op Save; once dirty (or
          once the upgrade lands), :attr:`~RehuDocumentModel.upgradable` drops and Save reappears.

        Revert is unaffected by ``upgradable`` -- re-reading a clean file from disk is still useful
        regardless of its format version, so it stays visible whenever it isn't ``legacy_tc``.
        """
        legacy_tc = self.__model.document.legacy_tc
        upgradable = self.__model.upgradable
        self.__save_action.setVisible(not legacy_tc and not upgradable)
        self.__revert_action.setVisible(not legacy_tc)
        self.__convert_keep_backups_action.setVisible(legacy_tc)
        self.__convert_discard_originals_action.setVisible(legacy_tc)
        self.__upgrade_action.setVisible(upgradable)

    def __on_convert_triggered(self, *, keep_backups: bool) -> None:
        """Convert this document, confirming first if it would overwrite an already-converted ``.rehu``.

        :param keep_backups: whether to keep ``.orig`` backups of the ``.tc`` and legacy screenshots.
        """
        path = self.__model.path
        target = path.with_suffix(".rehu") if path is not None else None
        overwrite = False
        if target is not None and target.exists():
            buttons = QMessageBox.StandardButton
            answer = QMessageBox.warning(
                self,
                "Overwrite Existing File",
                f'"{target.name}" already exists. Convert and overwrite it?',
                buttons.Yes | buttons.No,
                buttons.No,
            )
            if answer != buttons.Yes:
                return
            overwrite = True
        try:
            self.__model.convert(keep_backups=keep_backups, overwrite=overwrite)
        except OSError as exc:
            QMessageBox.critical(self, "Conversion Failed", f"Could not convert the document:\n\n{exc}")

    def __add_docks(
        self, grids: dict[FieldsTab, QWidget], kind: str, position: QtAds.DockWidgetArea
    ) -> dict[FieldsTab, QtAds.CDockWidget]:
        """Build one dock per tab, stacked together into a single area at ``position``, theming each
        dock's toggle action from the tab's SVG icon.

        :param grids: the ``{tab: grid widget}`` mapping (from `FieldsForm`).
        :param kind: ``"viewer"`` or ``"editor"`` -- namespaces the dock object names.
        :param position: the dock area the first tab opens into; later tabs stack into it.
        :returns: the built docks, keyed by tab.
        """
        docks: dict[FieldsTab, QtAds.CDockWidget] = {}
        area: QtAds.CDockAreaWidget | None = None
        for tab, widget in grids.items():
            dock = self.__make_dock(f"{kind}:{tab.text}", tab.text, widget)
            if area is None:
                area = self.__dock_manager.addDockWidget(position, dock)
            else:
                self.__dock_manager.addDockWidget(QtAds.CenterDockWidgetArea, dock, area)
            ActionIconThemeHandler(dock.toggleViewAction(), tab.icon)
            docks[tab] = dock
        if docks:
            # later tabs open as the current one; make the first (e.g. the main editor) current instead
            next(iter(docks.values())).setAsCurrentTab()
        return docks

    def __make_dock(self, name: str, title: str, widget: QWidget) -> QtAds.CDockWidget:
        dock = QtAds.CDockWidget(self.__dock_manager, title)
        dock.setObjectName(name)
        dock_features = QtAds.CDockWidget.DockWidgetFeature
        dock.setFeatures(
            dock_features.DockWidgetFocusable
            | dock_features.DockWidgetClosable
            | dock_features.DockWidgetForceCloseWithArea
            | dock_features.DockWidgetMovable
        )
        dock.setWidget(widget)
        dock.viewToggled.connect(lambda visible: self.__on_view_toggled(dock, visible))
        return dock

    def __on_view_toggled(self, dock: QtAds.CDockWidget, visible: bool) -> None:
        """Stash ``dock``'s splitter sizes as it hides, or restore them as it reappears.

        No-op while :meth:`restore_state` is actively running -- see the comment there.

        :param dock: the dock whose visibility changed.
        :param visible: the dock's new visibility.
        """
        if self.__restoring_layout:
            return
        if visible:
            self.__restore_size(dock)
        else:
            self.__stash_size(dock)

    def __stash_size(self, dock: QtAds.CDockWidget) -> None:
        """Record the containing splitter's size distribution before ``dock`` hides.

        :param dock: the dock about to hide.
        """
        area = dock.dockAreaWidget()
        if area is not None:
            self.__stashed_sizes[dock.objectName()] = (  # pylint: disable=unsupported-assignment-operation
                self.__dock_manager.splitterSizes(area)
            )

    def __restore_size(self, dock: QtAds.CDockWidget) -> None:
        """Re-apply ``dock``'s stashed splitter sizes now that it is visible again.

        :param dock: the dock that just became visible.
        """
        area = dock.dockAreaWidget()
        sizes = self.__stashed_sizes.get(dock.objectName())
        if sizes and area is not None and len(sizes) == len(self.__dock_manager.splitterSizes(area)):
            self.__dock_manager.setSplitterSizes(area, sizes)
