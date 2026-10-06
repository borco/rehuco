"""One card of a card list: grip, framed content, and the buttons beside the frame."""

from collections.abc import Mapping
from dataclasses import replace
from typing import Final, override

from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QEnterEvent, QKeySequence, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from ...shortcuts import Command
from ..item_actions import (
    DeleteItemAction,
    InsertItemAction,
    MoveDownItemAction,
    MoveToBottomItemAction,
    MoveToTopItemAction,
    MoveUpItemAction,
    list_editor_command,
    set_command,
)
from .buddy_button_strip import BuddyButtonStrip
from .card_content import CardContent
from .card_grip import CardGrip
from .card_style import CardStateStyle, CardStyle

CARD_LIST_FOCUS_GROUP: Final = "card_list"
"""The focus group every card command shares: a card list routes their keys to its current card alone."""


def card_list_command(command_id: str, name: str, description: str, key: Qt.Key) -> Command:
    """One card command, on Ctrl+``key``: a list-editor command re-homed in the :data:`CARD_LIST_FOCUS_GROUP`.

    :param command_id: the command's id.
    :param name: its label.
    :param description: what it does -- also the action's tooltip.
    :param key: the key pressed with Ctrl.
    :returns: the command.
    """
    command = list_editor_command(command_id, name, description, Qt.KeyboardModifier.ControlModifier | key)
    return replace(command, focus_group=CARD_LIST_FOCUS_GROUP)


CARD_DELETE_COMMAND: Final = card_list_command(
    "card_list.delete", "Delete card", "Delete this entry", Qt.Key.Key_Delete
)
CARD_INSERT_COMMAND: Final = card_list_command(
    "card_list.insert", "Insert card", "Insert a new entry below this one", Qt.Key.Key_Insert
)
CARD_MOVE_TO_TOP_COMMAND: Final = card_list_command(
    "card_list.move_to_top", "Move card to top", "Move the current entry to the top", Qt.Key.Key_Home
)
CARD_MOVE_UP_COMMAND: Final = card_list_command(
    "card_list.move_up", "Move card up", "Move the current entry up one place", Qt.Key.Key_Up
)
CARD_MOVE_DOWN_COMMAND: Final = card_list_command(
    "card_list.move_down", "Move card down", "Move the current entry down one place", Qt.Key.Key_Down
)
CARD_MOVE_TO_BOTTOM_COMMAND: Final = card_list_command(
    "card_list.move_to_bottom", "Move card to bottom", "Move the current entry to the bottom", Qt.Key.Key_End
)

CARD_LIST_COMMANDS: Final = (
    CARD_DELETE_COMMAND,
    CARD_INSERT_COMMAND,
    CARD_MOVE_TO_TOP_COMMAND,
    CARD_MOVE_UP_COMMAND,
    CARD_MOVE_DOWN_COMMAND,
    CARD_MOVE_TO_BOTTOM_COMMAND,
)
"""Every card action's command, for a host to register in its own registry. Commands of their own rather
than the list editor's: a card list routes its keys differently (Ctrl+Del, so plain Del stays a text key),
and rebinding one kind of list must not rebind the other."""


class Card(QWidget):  # pylint: disable=too-many-instance-attributes
    """``grip | frame | buttons``: the frame wraps only the app's content, and the buttons sit outside it.

    The whole card -- grip, frame and buttons -- is painted in its :class:`CardStyle` look: a state the app
    registered (``flagged``, say), or nothing. The current card is painted like any other: the delete and insert
    buttons, shown while the pointer is over the card **or** the card is current, are its only mark.

    The card's actions carry the keys a card list reacts to -- Ctrl+Del, Ctrl+Ins, Ctrl+Up/Down/Home/End --
    so their tooltips name them; the keys themselves are routed by the
    :class:`~.card_list_editor.CardListEditor`, which is what keeps plain Del a text key.

    :param content: the app's widget, satisfying :class:`CardContent`.
    :param style: how the card paints its states.
    :param parent: optional Qt parent.
    """

    drag_requested = Signal()
    """Fires when the grip is dragged."""

    current_changed = Signal(bool)
    """Fires with the new :attr:`current`."""

    RADIUS: Final = 4
    """The corner radius of the card's fill and outline."""

    MARGIN: Final = 2
    """The gap, in pixels, between the card's edge and its grip, frame and buttons."""

    FRAME_MARGIN: Final = 6
    """The gap, in pixels, between the frame's edge and the content inside it."""

    @classmethod
    def content_offset(cls) -> int:
        """How far below the card's top edge its content starts: the card's own margin, the frame's line, and
        the gap inside it. What a host pins something to the content's first row against.

        :returns: the offset, in pixels.
        """
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        return cls.MARGIN + frame.frameWidth() + cls.FRAME_MARGIN

    def __init__(self, content: QWidget, style: CardStyle, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if not isinstance(content, CardContent):
            raise TypeError(f"{type(content).__qualname__} is not a CardContent")
        self.__content: Final = content
        self.__style: Final = style
        self.__current = False
        self.__hovered = False
        self.__states: Mapping[str, str] = {}
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.__grip: Final = CardGrip(self)
        self.__grip.drag_requested.connect(self.drag_requested)
        self.__frame: Final = QFrame(self)
        self.__frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame_layout = QVBoxLayout(self.__frame)
        frame_layout.setContentsMargins(self.FRAME_MARGIN, self.FRAME_MARGIN, self.FRAME_MARGIN, self.FRAME_MARGIN)
        frame_layout.addWidget(content)

        self.delete_action: Final = self.__keyed(DeleteItemAction(self), CARD_DELETE_COMMAND)
        self.insert_action: Final = self.__keyed(InsertItemAction(self), CARD_INSERT_COMMAND)
        self.move_to_top_action: Final = self.__keyed(MoveToTopItemAction(self), CARD_MOVE_TO_TOP_COMMAND)
        self.move_up_action: Final = self.__keyed(MoveUpItemAction(self), CARD_MOVE_UP_COMMAND)
        self.move_down_action: Final = self.__keyed(MoveDownItemAction(self), CARD_MOVE_DOWN_COMMAND)
        self.move_to_bottom_action: Final = self.__keyed(MoveToBottomItemAction(self), CARD_MOVE_TO_BOTTOM_COMMAND)

        self.__strip: Final = BuddyButtonStrip(self, self.__frame)
        delete_buddy, insert_buddy = content.buddies()
        self.__strip.add_button(self.delete_action, delete_buddy)
        self.__strip.add_button(self.insert_action, insert_buddy)

        self.__layout: Final = QHBoxLayout(self)
        self.__layout.addWidget(self.__grip)
        self.__layout.addWidget(self.__frame, 1)
        self.__reserve_strip()
        self.__strip.size_changed.connect(self.__reserve_strip)

    @property
    def content(self) -> QWidget:
        """The app's widget inside the frame."""
        return self.__content

    @property
    def strip(self) -> BuddyButtonStrip:
        """The buttons beside the frame."""
        return self.__strip

    @property
    def grip(self) -> CardGrip:
        """The drag handle."""
        return self.__grip

    def action_for(self, key: QKeySequence) -> QAction | None:
        """The action this card fires for ``key``.

        :param key: the key pressed.
        :returns: its action, or ``None`` when the card has none for it.
        """
        actions = (
            self.delete_action,
            self.insert_action,
            self.move_to_top_action,
            self.move_up_action,
            self.move_down_action,
            self.move_to_bottom_action,
        )
        return next((action for action in actions if key in action.shortcuts()), None)

    @property
    def current(self) -> bool:
        """Whether this card holds focus."""
        return self.__current

    def set_current(self, current: bool) -> None:
        """Mark this card as holding focus, or not.

        :param current: whether it holds focus.
        """
        if current == self.__current:
            return
        self.__current = current
        self.__update_strip()
        self.update()
        self.current_changed.emit(current)

    @property
    def states(self) -> Mapping[str, str]:
        """The states this card is in, each name mapped to its reason."""
        return self.__states

    def set_states(self, states: Mapping[str, str]) -> None:
        """Put this card in ``states``, telling the content why when it listens.

        :param states: each state name mapped to its reason.
        """
        if states == self.__states:
            return
        self.__states = dict(states)
        if (set_reasons := getattr(self.__content, "set_reasons", None)) is not None:
            set_reasons(tuple(self.__states.values()))
        self.update()

    def set_primary(self, primary: bool) -> None:
        """Tell the content whether this is the top card, when it listens.

        :param primary: whether the card is the first one.
        """
        if (set_primary := getattr(self.__content, "set_primary", None)) is not None:
            set_primary(primary)

    def painted_style(self) -> CardStateStyle:
        """The look this card paints with now.

        :returns: the style for its states; being current changes nothing about it.
        """
        return self.__style.style_for(self.__states)

    @staticmethod
    def __keyed(action: QAction, command: Command) -> QAction:
        """Re-key a list-editor ``action`` as the card ``command``'s, naming its keys in the tooltip.

        :param action: the action to rekey.
        :param command: one of the :data:`CARD_LIST_COMMANDS`.
        :returns: ``action``.
        """
        set_command(action, command)
        return action

    def __reserve_strip(self) -> None:
        """Keep the room right of the frame the buttons' width, so revealing them never moves the frame."""
        self.__layout.setContentsMargins(
            self.MARGIN, self.MARGIN, self.MARGIN + self.__strip.reserved_width(), self.MARGIN
        )

    def __update_strip(self) -> None:
        """Reveal the buttons while the card is hovered or current."""
        self.__strip.set_revealed(self.__hovered or self.__current)

    @override
    def enterEvent(self, event: QEnterEvent) -> None:  # noqa: N802  (Qt override)
        self.__hovered = True
        self.__update_strip()
        super().enterEvent(event)

    @override
    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802  (Qt override)
        self.__hovered = False
        self.__update_strip()
        super().leaveEvent(event)

    @override
    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802  (Qt override)
        super().paintEvent(event)
        style = self.painted_style()
        fill = CardStateStyle.resolve(style.fill, self.palette())
        border = CardStateStyle.resolve(style.border, self.palette())
        if fill is None and border is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(border, 1) if border is not None else Qt.PenStyle.NoPen)
        painter.setBrush(fill if fill is not None else Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), self.RADIUS, self.RADIUS)
