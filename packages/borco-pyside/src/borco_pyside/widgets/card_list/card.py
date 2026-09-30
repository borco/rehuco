"""One card of a card list: grip, framed content, and the buttons beside the frame."""

from collections.abc import Mapping
from typing import Final, override

from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QEnterEvent, QKeySequence, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from ..item_actions import (
    DeleteItemAction,
    InsertItemAction,
    MoveDownItemAction,
    MoveToBottomItemAction,
    MoveToTopItemAction,
    MoveUpItemAction,
    set_tooltip_and_shortcut,
)
from .buddy_button_strip import BuddyButtonStrip
from .card_content import CardContent
from .card_grip import CardGrip
from .card_style import CardStateStyle, CardStyle


class Card(QWidget):  # pylint: disable=too-many-instance-attributes
    """``grip | frame | buttons``: the frame wraps only the app's content, and the buttons sit outside it.

    The whole card -- grip, frame and buttons -- is painted in its :class:`CardStyle` look: the current
    card's selection colour, a state the app registered (``flagged``, say), or nothing. The delete and insert
    buttons show while the pointer is over the card or the card is current.

    The card's actions carry the keys a card list reacts to -- Ctrl+Del, Ctrl+Ins, Ctrl+Up/Down/Home/End --
    so their tooltips name them; the keys themselves are routed by the
    :class:`~.card_list_editor.CardListEditor`, which is what keeps plain Del a text key.

    :param content: the app's widget, satisfying :class:`CardContent`.
    :param style: how the card paints its states.
    :param parent: optional Qt parent.
    """

    drag_requested = Signal()
    """Fires when the grip is dragged."""

    RADIUS: Final = 4
    """The corner radius of the card's fill and outline."""

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
        frame_layout.addWidget(content)

        self.delete_action: Final = self.__keyed(DeleteItemAction(self), "Delete this entry", Qt.Key.Key_Delete)
        self.insert_action: Final = self.__keyed(
            InsertItemAction(self), "Insert a new entry below this one", Qt.Key.Key_Insert
        )
        self.move_to_top_action: Final = MoveToTopItemAction(self)
        self.move_up_action: Final = MoveUpItemAction(self)
        self.move_down_action: Final = MoveDownItemAction(self)
        self.move_to_bottom_action: Final = MoveToBottomItemAction(self)

        self.__strip: Final = BuddyButtonStrip(self, self.__frame)
        delete_buddy, insert_buddy = content.buddies()
        self.__strip.add_button(self.delete_action, delete_buddy)
        self.__strip.add_button(self.insert_action, insert_buddy)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2 + self.__strip.reserved_width(), 2)
        layout.addWidget(self.__grip)
        layout.addWidget(self.__frame, 1)

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
        return next((action for action in actions if action.shortcut() == key), None)

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

        :returns: the style for its current and state flags.
        """
        return self.__style.style_for(self.__current, self.__states)

    def __keyed(self, action: QAction, tooltip: str, key: Qt.Key) -> QAction:
        """Give ``action`` its Ctrl+``key`` shortcut, naming it in the tooltip.

        :param action: the action to rekey.
        :param tooltip: what it does, in words.
        :param key: the key pressed with Ctrl.
        :returns: ``action``.
        """
        set_tooltip_and_shortcut(action, tooltip, QKeySequence(Qt.KeyboardModifier.ControlModifier | key))
        return action

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
