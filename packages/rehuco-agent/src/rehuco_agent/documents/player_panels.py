"""The tree and the notes beside the player's picture ([[plugins#player-maximized]], #575)."""

from collections.abc import Callable, Iterable
from typing import Final

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QToolBar, QVBoxLayout, QWidget

from .notes_panel import NotesPanel
from .player_panel_keys import PlayerPanelKeys
from .player_view_ui import Ui_PlayerView
from .video_tree_view import VideoTreeView


class PlayerPanels(QObject):
    """The player's ``T`` tree, on the left of the picture, and ``N`` notes, under the ``I`` info on its right.

    They are built by the document, which owns what they show, and put in the stage by :meth:`attach`. Each toggles on
    its own and any may show at once; none takes the keyboard as it is shown, and one hidden while it holds the
    keyboard hands it back to the player. The column on the right shows while the info or the notes do. Which are shown
    is session state ([[plugins#player-maximized]]).

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
        self.__keys: Final = PlayerPanelKeys(actions, focus_player, self)
        self.__tree: VideoTreeView | None = None
        self.__notes: NotesPanel | None = None
        self.__notes_box: QWidget | None = None
        ui.tree_action.toggled.connect(self.__on_tree_toggled)
        ui.notes_action.toggled.connect(self.__on_notes_toggled)

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
        box = QWidget(self.__ui.side_splitter)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        toolbar = QToolBar(box)
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        toolbar.addActions(notes.title_bar_actions)
        layout.addWidget(toolbar)
        layout.addWidget(notes)
        self.__notes_box = box
        stage, side = self.__ui.stage_splitter, self.__ui.side_splitter
        stage.insertWidget(0, tree)
        side.addWidget(box)
        tree.hide()
        box.hide()
        stage.setStretchFactor(0, 0)
        stage.setStretchFactor(1, 1)
        stage.setStretchFactor(2, 0)
        self.__keys.watch(tree)
        self.__keys.watch(notes)

    def detach(self) -> None:
        """Write what is waiting in the notes and let the panels go, before the document lets go of what they show."""
        if self.__notes is not None:
            self.__notes.detach()
        if self.__tree is not None:
            self.__tree.detach()
        self.__tree = self.__notes = self.__notes_box = None

    def update_side(self) -> None:
        """Show the column on the right while the info or the notes do."""
        self.__ui.side_splitter.setVisible(self.__ui.info_action.isChecked() or self.__ui.notes_action.isChecked())

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
        box, notes = self.__notes_box, self.__notes
        if box is None or notes is None:
            return
        if not shown:
            notes.flush()
        held = self.__holds_keyboard(box)
        box.setVisible(shown)
        self.update_side()
        if not shown and held:
            self.__focus_player()

    @staticmethod
    def __holds_keyboard(panel: QWidget) -> bool:
        """Whether the keyboard is in a panel; asked before it is hidden, since hiding moves the focus on.

        :param panel: the panel.
        :returns: whether the focused widget is it or inside it.
        """
        focused = QApplication.focusWidget()
        return focused is not None and (focused is panel or panel.isAncestorOf(focused))
