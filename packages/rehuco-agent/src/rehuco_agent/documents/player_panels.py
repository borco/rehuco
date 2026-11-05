"""The tree and the notes beside the player's picture ([[plugins#player-maximized]], #575)."""

from collections.abc import Callable, Iterable
from typing import Final, override

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QWidget

from .notes_panel import NotesPanel
from .player_panel_keys import PlayerPanelKeys
from .player_view_ui import Ui_PlayerView
from .video_tree_view import VideoTreeView

QWIDGETSIZE_MAX: Final = 16777215
"""Qt's largest widget size, which PySide does not export: what a widget's maximum is when it has none."""


class PlayerPanels(QObject):
    """The player's ``T`` tree, on the left of the picture, and ``N`` notes, under the ``I`` info on its right.

    They are built by the document, which owns what they show, and put in the stage by :meth:`attach`. Each toggles on
    its own and any may show at once; none takes the keyboard as it is shown, and one hidden while it holds the
    keyboard hands it back to the player. The column on the right shows while the info or the notes do. Which are shown
    is session state ([[plugins#player-maximized]]).

    **Above the notes the info is as tall as its text**, behind a divider that shows and does not drag (owner). Its
    height is fixed only while both show: a splitter takes its maximum height from its children, so a fixed height on
    the info alone caps the column and then the whole stage (measured: the stage fell to the info's 84 px).

    :param ui: the player's generated UI.
    :param actions: the player's actions, whose keys a notes editor claims for typing (`PlayerPanelKeys`).
    :param focus_player: puts the keyboard on the player, or on the overlay it is maximized in.
    :param parent: the Qt parent, which owns this.
    """

    def __init__(
        self,
        ui: Ui_PlayerView,
        actions: Callable[[], Iterable[QAction]],
        focus_player: Callable[[], None],
        parent: QObject,
    ) -> None:
        super().__init__(parent)
        self.__ui: Final = ui
        self.__focus_player: Final = focus_player
        self.__keys: Final = PlayerPanelKeys(actions, self.__leave_editor, ui.edit_notes_action, self)
        self.__tree: VideoTreeView | None = None
        self.__notes: NotesPanel | None = None
        ui.tree_action.toggled.connect(self.__on_tree_toggled)
        ui.notes_action.toggled.connect(self.__on_notes_toggled)
        ui.edit_notes_action.triggered.connect(self.__on_edit_triggered)

    @property
    def attached(self) -> bool:
        """Whether the panels are in the stage."""
        return self.__tree is not None

    def attach(self, tree: VideoTreeView, notes: NotesPanel) -> None:
        """Put the panels in the stage, hidden: the tree before the picture, the notes in the column on its right.

        :param tree: a view of the tutorial's videos.
        :param notes: a view of the notes.
        """
        self.__tree, self.__notes = tree, notes
        stage, side = self.__ui.stage_splitter, self.__ui.side_splitter
        stage.insertWidget(0, tree)
        side.addWidget(notes)
        tree.hide()
        notes.hide()
        stage.setStretchFactor(0, 0)
        stage.setStretchFactor(1, 1)
        stage.setStretchFactor(2, 0)
        side.setStretchFactor(0, 0)
        side.setStretchFactor(1, 1)
        divider = side.handle(1)
        divider.setEnabled(False)
        divider.setCursor(Qt.CursorShape.ArrowCursor)
        self.__ui.info_panel.installEventFilter(self)
        self.__keys.watch(tree)
        self.__keys.watch(notes)

    def detach(self) -> None:
        """Write what is waiting in the notes and let the panels go, before the document lets go of what they show."""
        if self.__notes is not None and self.__tree is not None:
            self.__notes.detach()
            self.__tree.detach()
        self.__tree = self.__notes = None

    def update_side(self) -> None:
        """Show the column on the right while the info or the notes do."""
        self.__ui.side_splitter.setVisible(self.__ui.info_action.isChecked() or self.__ui.notes_action.isChecked())
        self.fit_info()

    def fit_info(self) -> None:
        """Make the info as tall as its text at its width while the notes show under it; else let it fill the column."""
        info = self.__ui.info_panel
        # released first: a label's height for its width follows the height it is fixed at, so a height fixed too tall
        # would be measured as the height wanted and never shrink (seen at 125 % scaling: 160 px for 96 px of text)
        info.setMinimumHeight(0)
        info.setMaximumHeight(QWIDGETSIZE_MAX)
        if self.__notes is not None and self.__ui.info_action.isChecked() and self.__ui.notes_action.isChecked():
            # a label with no text has no height for its width
            wanted = info.heightForWidth(info.width())
            info.setFixedHeight(wanted if wanted >= 0 else info.sizeHint().height())

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802  (Qt API name)
        """Fit the info again as the column's width changes, which wraps its text differently.

        :param watched: the info panel.
        :param event: what happened to it.
        :returns: whether the event is consumed -- never.
        """
        if event.type() == QEvent.Type.Resize:
            self.fit_info()
        return super().eventFilter(watched, event)

    def __on_tree_toggled(self, shown: bool) -> None:
        """Show or hide the tree beside the picture, which shrinks or grows to fit.

        :param shown: whether it is shown.
        """
        if self.__tree is None:
            return
        held = self.__holds_keyboard(self.__tree)
        self.__tree.setVisible(shown)
        if shown:
            self.__tree.scroll_to_current()
        elif held:
            self.__focus_player()

    def __on_notes_toggled(self, shown: bool) -> None:
        """Show or hide the notes under the info, writing what was typed in them as they go.

        :param shown: whether they are shown.
        """
        notes = self.__notes
        if notes is None:
            return
        if not shown:
            # hidden notes are not being edited: the next F2 starts, never ends out of sight
            notes.set_editing(False)
        held = self.__holds_keyboard(notes)
        notes.setVisible(shown)
        self.update_side()
        if not shown and held:
            self.__focus_player()

    def __on_edit_triggered(self) -> None:
        """Start editing the notes -- shown first when they are hidden -- or end it, as the key for it asks.

        Whatever video the notes show, a missing one included, or none: a note outlives its file, and the tutorial's
        notes are there without one (owner).
        """
        notes = self.__notes
        if notes is None:
            return
        if notes.editing:
            self.__leave_editor()
            return
        self.__ui.notes_action.setChecked(True)
        notes.set_editing(True)
        notes.focus_editor()

    def __leave_editor(self) -> None:
        """End the editing, writing what was typed, and put the keyboard on the player: F2 again, or Esc."""
        assert self.__notes is not None  # nosec B101  (only its editing, or an editor of it, asks for this)
        self.__notes.set_editing(False)
        self.__focus_player()

    @staticmethod
    def __holds_keyboard(panel: QWidget) -> bool:
        """Whether the keyboard is in a panel; asked before it is hidden, since hiding moves the focus on.

        :param panel: the panel.
        :returns: whether the focused widget is it or inside it.
        """
        focused = QApplication.focusWidget()
        return focused is not None and (focused is panel or panel.isAncestorOf(focused))
