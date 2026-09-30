"""A vertical stack of cards over a :class:`~.card_list_model.CardListModel`, edited in place."""

from collections.abc import Callable
from functools import partial
from itertools import pairwise
from typing import Any, Final, cast, override

from PySide6.QtCore import QByteArray, QEvent, QMimeData, QModelIndex, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import (
    QDrag,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QFocusEvent,
    QKeyEvent,
    QKeySequence,
)
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

from .card import Card
from .card_ghost import CardGhost
from .card_list_model import CardListModel
from .card_style import CardStyle


# pylint: disable-next=too-many-instance-attributes  # the cards, their layout, the ghost and the add button
class CardListEditor(QWidget):
    """One card per row of ``model``, each holding a content widget ``content_factory`` builds.

    **In place.** Inserting, deleting and moving a row adds, removes or moves only that row's card -- never
    a rebuild, which would move focus under the user. Only :meth:`set_value` with a value this editor does
    not already hold rebuilds the cards.

    **Keyboard.** Tab and Shift+Tab visit the content's own edit widgets, card after card; the grip and the
    buttons never take focus. On a focused card, Ctrl+Ins inserts after it, Ctrl+Del deletes it, and
    Ctrl+Up/Down/Home/End move it -- claimed ahead of the edit widget's own use of those keys. Del alone is
    left to the edit widget: it never deletes a card.

    **Current card.** The card holding focus is current: painted in the selection colour, its buttons shown.
    It stops being current when focus leaves the editor, but not when the window merely loses activation.

    **Drag.** A card's grip drags it; a ghost as tall as the card opens a gap where it would land, except at
    the two slots that would leave the order unchanged. A drag this editor did not start is not accepted, so
    it goes on to whatever holds the editor.

    **Value.** :attr:`value` is the model's value -- every row but the blank ones just inserted -- and
    :attr:`value_changed` fires whenever it changes through an edit here. :meth:`set_value` never fires it,
    and a value equal to the current one changes nothing, blank cards included: the echo guard a two-way
    binding needs.

    :param model: the rows the cards edit.
    :param content_factory: builds one card's content, a widget satisfying
        :class:`~.card_content.CardContent`.
    :param style: how the cards paint their states; a fresh :class:`CardStyle` when omitted.
    :param parent: optional Qt parent.
    """

    value_changed = Signal(object)
    """Fires with the new :attr:`value` after an edit changed it."""

    current_index_changed = Signal(int)
    """Fires with the new :attr:`current_index` -- the `ItemViewer` contract."""

    card_added = Signal(object)
    """Fires with each :class:`~.card.Card` built after construction, so an app can dress it -- the icons on its
    actions, say. The cards that already exist when a subclass finishes its own construction are :attr:`cards`."""

    MIME_TYPE: Final = "application/x-borco-card-list"
    """The drag payload format: this editor's identity and the dragged row."""

    def __init__(
        self,
        model: CardListModel,
        content_factory: Callable[[], QWidget],
        style: CardStyle | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.__content_factory: Final = content_factory
        self.__style: Final = style or CardStyle()
        self.__cards: list[Card] = []
        self.__current: Card | None = None
        self.__last_value: list[Any] = model.value
        self.__ghost_slot = -1

        self.__layout: Final = QVBoxLayout(self)
        self.__layout.setContentsMargins(0, 0, 0, 0)
        self.__ghost: Final = CardGhost(self)
        self.__ghost.hide()
        self.__add_button: Final = QPushButton("+ Add", self)
        self.__add_button.setToolTip("Add an entry")
        self.__add_button.clicked.connect(self.__on_add)
        self.__layout.addWidget(self.__add_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.__layout.addStretch(1)
        self.setAcceptDrops(True)

        model.rowsInserted.connect(self.__on_rows_inserted)
        model.rowsRemoved.connect(self.__on_rows_removed)
        model.rowsMoved.connect(self.__on_rows_moved)
        model.dataChanged.connect(self.__on_data_changed)
        model.modelReset.connect(self.__rebuild)
        model.states_changed.connect(self.__apply_states)
        self.__rebuild()

    @property
    def model(self) -> CardListModel:
        """The rows the cards edit."""
        return self.__model

    @property
    def style_map(self) -> CardStyle:
        """How the cards paint their states -- where an app registers its own."""
        return self.__style

    @property
    def cards(self) -> tuple[Card, ...]:
        """The cards, in row order."""
        return tuple(self.__cards)

    @property
    def add_button(self) -> QPushButton:
        """The button an empty list shows instead of cards."""
        return self.__add_button

    @property
    def ghost_slot(self) -> int:
        """Where a drag would land -- the number of cards above the gap -- or ``-1`` with no gap shown."""
        return self.__ghost_slot

    @property
    def value(self) -> list[Any]:
        """Every row's item but the blank ones just inserted, in order."""
        return self.__model.value

    def set_value(self, value: list[Any]) -> None:
        """Show ``value`` without emitting :attr:`value_changed`; a no-op when it is already the value.

        :param value: the items to show, in order.
        """
        self.__last_value = list(value)
        self.__model.set_items(value)

    # region ItemViewer

    @property
    def current_index(self) -> int:
        """The row of the card holding focus, or ``-1`` -- the `ItemViewer` contract."""
        return self.__cards.index(self.__current) if self.__current is not None else -1

    def set_current_index(self, row: int) -> None:
        """Focus the card at ``row`` -- the `ItemViewer` contract.

        :param row: the row, or a negative row for none.
        """
        if 0 <= row < len(self.__cards):
            self.__focus_card(row)
        else:
            self.__set_current(None)

    def edit_current(self) -> None:
        """Focus the current card's first edit widget -- the `ItemViewer` contract."""
        if self.__current is not None:
            self.__focus_card(self.__cards.index(self.__current))

    # endregion

    # region model changes

    def __on_rows_inserted(self, _parent: QModelIndex, first: int, last: int) -> None:
        """Build a card for each inserted row, leaving every other card as it is.

        :param _parent: unused -- the model is flat.
        :param first: the first inserted row.
        :param last: the last inserted row.
        """
        self.__hide_ghost()
        for row in range(first, last + 1):
            card = self.__build_card(row)
            self.__cards.insert(row, card)
            self.__layout.insertWidget(row, card)
            card.show()
        self.__after_structure_change()

    def __on_rows_removed(self, _parent: QModelIndex, first: int, last: int) -> None:
        """Drop the removed rows' cards, handing focus to a neighbour first when one of them held it.

        :param _parent: unused -- the model is flat.
        :param first: the first removed row.
        :param last: the last removed row.
        """
        self.__hide_ghost()
        removed = self.__cards[first : last + 1]
        self.__cards = self.__cards[:first] + self.__cards[last + 1 :]
        focus = QApplication.focusWidget()
        held_focus = focus is not None and any(card.isAncestorOf(focus) for card in removed)
        if self.__current in removed:
            self.__set_current(None)
        if held_focus:
            if self.__cards:
                self.__focus_card(min(first, len(self.__cards) - 1))
            else:
                self.__add_button.show()
                self.__add_button.setFocus(Qt.FocusReason.OtherFocusReason)
        for card in removed:
            self.__layout.removeWidget(card)
            card.hide()
            card.deleteLater()
        self.__after_structure_change()

    def __on_rows_moved(self, _parent: QModelIndex, start: int, end: int, _destination: QModelIndex, row: int) -> None:
        """Move the moved rows' cards to their new places, keeping focus where it is.

        :param _parent: unused -- the model is flat.
        :param start: the first moved row, before the move.
        :param end: the last moved row, before the move.
        :param _destination: unused -- the model is flat.
        :param row: the row the block was moved before, in the pre-move row space.
        """
        self.__hide_ghost()
        block = self.__cards[start : end + 1]
        rest = self.__cards[:start] + self.__cards[end + 1 :]
        at = row if row < start else row - len(block)
        self.__cards = rest[:at] + block + rest[at:]
        for index, card in enumerate(self.__cards):
            if self.__layout.indexOf(card) != index:
                self.__layout.removeWidget(card)
                self.__layout.insertWidget(index, card)
        self.__after_structure_change()

    def __on_data_changed(self, top_left: QModelIndex, bottom_right: QModelIndex) -> None:
        """Show changed items on their cards, unless the card already reads that way.

        :param top_left: the first changed row's index.
        :param bottom_right: the last changed row's index.
        """
        for row in range(top_left.row(), bottom_right.row() + 1):
            content = self.__cards[row].content
            item = self.__model.item(row)
            if content.item_values() != item:  # type: ignore[attr-defined]
                content.set_item(item)  # type: ignore[attr-defined]
        self.__report_value()

    def __rebuild(self) -> None:
        """Replace every card -- the one full rebuild, for a value set from outside."""
        self.__hide_ghost()
        self.__set_current(None)
        for card in self.__cards:
            self.__layout.removeWidget(card)
            card.hide()
            card.deleteLater()
        self.__cards = []
        for row in range(self.__model.count):
            card = self.__build_card(row)
            self.__cards.append(card)
            self.__layout.insertWidget(row, card)
            card.show()
        self.__after_structure_change()

    def __apply_states(self) -> None:
        """Put each card in its row's states."""
        for row, card in enumerate(self.__cards):
            card.set_states(self.__model.states(row))

    def __after_structure_change(self) -> None:
        """What every insert, removal, move and rebuild ends with: the add button, the top card, the states,
        the tab order and the value."""
        self.__add_button.setVisible(not self.__cards)
        for row, card in enumerate(self.__cards):
            card.set_primary(row == 0)
        self.__apply_states()
        self.__restitch_tab_order()
        self.__report_value()

    def __report_value(self) -> None:
        """Emit :attr:`value_changed` when the value differs from the one last reported or set."""
        value = self.__model.value
        if value != self.__last_value:
            self.__last_value = value
            self.value_changed.emit(value)

    # endregion

    # region cards

    def __build_card(self, row: int) -> Card:
        """Build the card for ``row``, wired to this editor.

        :param row: the row.
        :returns: the card, not yet in the layout.
        """
        content = self.__content_factory()
        content.set_item(self.__model.item(row))  # type: ignore[attr-defined]
        card = Card(content, self.__style, self)
        content.value_changed.connect(lambda *_: self.__on_content_edited(card))  # type: ignore[attr-defined]
        card.delete_action.triggered.connect(lambda: self.__model.delete(self.__cards.index(card)))
        card.insert_action.triggered.connect(lambda: self.__focus_card(self.__model.insert(self.__cards.index(card))))
        card.move_to_top_action.triggered.connect(lambda: self.__model.move_to_top(self.__cards.index(card)))
        card.move_up_action.triggered.connect(lambda: self.__model.move_up(self.__cards.index(card)))
        card.move_down_action.triggered.connect(lambda: self.__model.move_down(self.__cards.index(card)))
        card.move_to_bottom_action.triggered.connect(lambda: self.__model.move_to_bottom(self.__cards.index(card)))
        card.drag_requested.connect(lambda: self.__start_drag(card))
        self.__wire(content)
        card.set_states(self.__model.states(row))
        self.card_added.emit(card)
        return card

    def __wire(self, content: QWidget) -> None:
        """Watch every widget of ``content`` -- for the card keys, for focus, and for widgets added later.

        Every widget rather than only the focusable ones, because a container is where a widget added later
        announces itself (`QEvent.Type.ChildAdded`). Installing a filter twice keeps one, so rewiring a grown
        content is safe.

        :param content: a card's content.
        """
        for widget in (content, *content.findChildren(QWidget)):
            widget.installEventFilter(self)

    def __on_content_grew(self, card: Card) -> None:
        """Wire the widgets a card's content added after it was built, and give them their place in the tab order.

        :param card: the card whose content grew.
        """
        if card in self.__cards:
            self.__wire(card.content)
            self.__restitch_tab_order()

    def __on_content_edited(self, card: Card) -> None:
        """Write what ``card``'s content now reads into its row.

        :param card: the edited card.
        """
        if card in self.__cards:
            self.__model.set_item(self.__cards.index(card), card.content.item_values())  # type: ignore[attr-defined]

    def __on_add(self) -> None:
        """Insert the first card of an empty list and focus it."""
        self.__focus_card(self.__model.insert(-1))

    def __focus_card(self, row: int) -> None:
        """Focus the first edit widget of the card at ``row``.

        :param row: the row.
        """
        widgets = self.__focus_chain(self.__cards[row])
        if widgets:
            widgets[0].setFocus(Qt.FocusReason.OtherFocusReason)
        self.__set_current(self.__cards[row])

    def __set_current(self, card: Card | None) -> None:
        """Make ``card`` the current one.

        :param card: the card holding focus, or ``None``.
        """
        if card is self.__current:
            return
        if self.__current is not None and self.__current in self.__cards:
            self.__current.set_current(False)
        self.__current = card
        if card is not None:
            card.set_current(True)
        self.current_index_changed.emit(self.current_index)

    def __card_of(self, widget: QWidget | None) -> Card | None:
        """The card of this editor holding ``widget``.

        :param widget: a widget inside a card, or not.
        :returns: its card, or ``None``.
        """
        while widget is not None:
            if isinstance(widget, Card) and widget in self.__cards:
                return widget
            widget = widget.parentWidget()
        return None

    @staticmethod
    def __takes_tab_focus(widget: QWidget) -> bool:
        """Whether Tab can land on ``widget``.

        :param widget: the widget.
        :returns: whether its focus policy includes tab focus.
        """
        return bool(widget.focusPolicy().value & Qt.FocusPolicy.TabFocus.value)

    def __focus_chain(self, card: Card) -> list[QWidget]:
        """The widgets Tab visits inside ``card``, in the content's own focus order.

        :param card: the card.
        :returns: its focusable widgets.
        """
        content = card.content
        widgets = [content] if self.__takes_tab_focus(content) else []
        widget = content.nextInFocusChain()
        while widget is not None and widget is not content:
            if content.isAncestorOf(widget) and self.__takes_tab_focus(widget):
                widgets.append(widget)
            widget = widget.nextInFocusChain()
        return widgets

    def __restitch_tab_order(self) -> None:
        """Chain every card's edit widgets in row order, so Tab follows the cards as they now stand."""
        chain = [widget for card in self.__cards for widget in self.__focus_chain(card)]
        for before, after in pairwise(chain):
            QWidget.setTabOrder(before, after)

    def __check_focus_left(self) -> None:
        """Clear the current card once focus has settled outside this editor."""
        focus = QApplication.focusWidget()
        if focus is None or not self.isAncestorOf(focus):
            self.__set_current(None)

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802  (Qt override)
        card = self.__card_of(watched) if isinstance(watched, QWidget) else None
        if card is None:
            return super().eventFilter(watched, event)
        match event.type():
            case QEvent.Type.ShortcutOverride | QEvent.Type.KeyPress:
                action = card.action_for(QKeySequence(cast(QKeyEvent, event).keyCombination()))
                if action is not None:
                    if event.type() == QEvent.Type.KeyPress:
                        action.trigger()
                    event.accept()
                    return True
            case QEvent.Type.ChildAdded:
                # the child is announced from its base constructor, before it is a finished widget
                QTimer.singleShot(0, self, partial(self.__on_content_grew, card))
            case QEvent.Type.FocusIn:
                self.__set_current(card)
            case QEvent.Type.FocusOut:
                if cast(QFocusEvent, event).reason() not in (
                    Qt.FocusReason.ActiveWindowFocusReason,
                    Qt.FocusReason.PopupFocusReason,
                ):
                    QTimer.singleShot(0, self, self.__check_focus_left)
            case _:
                pass
        return super().eventFilter(watched, event)

    # endregion

    # region drag and drop

    def __start_drag(self, card: Card) -> None:
        """Drag ``card`` by its grip.

        :param card: the card being dragged.
        """
        mime = QMimeData()
        mime.setData(self.MIME_TYPE, QByteArray(f"{id(self)}:{self.__cards.index(card)}".encode()))
        drag = QDrag(card.grip)
        drag.setMimeData(mime)
        drag.setPixmap(card.grab())
        drag.setHotSpot(card.grip.mapTo(card, QPoint(card.grip.width() // 2, card.grip.height() // 2)))
        drag.exec(Qt.DropAction.MoveAction)
        self.__hide_ghost()

    def __dragged_row(self, event: QDropEvent) -> int | None:
        """The row a drag of this editor carries.

        :param event: the drag event.
        :returns: the dragged row, or ``None`` for a drag this editor did not start.
        """
        mime = event.mimeData()
        if mime is None or not mime.hasFormat(self.MIME_TYPE):
            return None
        owner, _, row = bytes(mime.data(self.MIME_TYPE).data()).decode().partition(":")
        if owner != str(id(self)) or not row.isdigit() or int(row) >= len(self.__cards):
            return None
        return int(row)

    def __slot_at(self, y: float) -> int:
        """The slot a drop at ``y`` lands in: how many cards have their middle above it.

        :param y: the pointer's height, in this editor's coordinates.
        :returns: the slot, from ``0`` (above every card) to the card count (below every card).
        """
        return sum(1 for card in self.__cards if card.geometry().center().y() < y)

    def __place_ghost(self, row: int, y: float) -> None:
        """Open the gap where ``row`` would land, or close it where the drop would change nothing.

        :param row: the dragged row.
        :param y: the pointer's height, in this editor's coordinates.
        """
        slot = self.__slot_at(y)
        if slot in (row, row + 1):
            self.__hide_ghost()
            return
        if slot == self.__ghost_slot:
            return
        self.__hide_ghost()
        self.__ghost.setFixedHeight(self.__cards[row].height())
        self.__layout.insertWidget(slot, self.__ghost)
        self.__ghost.show()
        self.__ghost_slot = slot

    def __hide_ghost(self) -> None:
        """Close the gap, if one is open."""
        if self.__ghost_slot < 0:
            return
        self.__layout.removeWidget(self.__ghost)
        self.__ghost.hide()
        self.__ghost_slot = -1

    @override
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802  (Qt override)
        row = self.__dragged_row(event)
        if row is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self.__place_ghost(row, event.position().y())

    @override
    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802  (Qt override)
        row = self.__dragged_row(event)
        if row is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self.__place_ghost(row, event.position().y())

    @override
    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802  (Qt override)
        self.__hide_ghost()
        super().dragLeaveEvent(event)

    @override
    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802  (Qt override)
        row = self.__dragged_row(event)
        if row is None:
            event.ignore()
            return
        slot = self.__slot_at(event.position().y()) if self.__ghost_slot < 0 else self.__ghost_slot
        self.__hide_ghost()
        event.acceptProposedAction()
        if slot not in (row, row + 1):
            self.__model.move(row, slot if slot < row else slot - 1)

    # endregion
