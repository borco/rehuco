"""Tests for the card list's widgets: `BuddyButtonStrip` as a `Card` uses it, and `CardListEditor` -- in-place
updates, keys, focus, drag with a ghost, and the value contract."""

# the two widgets and their sample content share one set of helpers and fixtures; splitting the module would
# copy them, so the module-length cap is lifted here rather than fragmenting it.
# pylint: disable=too-many-lines

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from borco_pyside.widgets import Card, CardListEditor, CardListModel, CardStateStyle, CardStyle
from PySide6.QtCore import QByteArray, QEvent, QMimeData, QPoint, QPointF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QEnterEvent,
    QPalette,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout, QWidget
from pytest import fixture, mark, param, raises
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot

# region Sample classes


class SampleContent(QWidget):
    """Name, URL and a checkbox over a ``{"name", "url", "on"}`` dict -- a `CardContent`.

    :param parent: optional Qt parent.
    """

    value_changed = Signal()
    """Fires on every user edit."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.name = QLineEdit(self)
        self.url = QLineEdit(self)
        self.on = QCheckBox("On", self)
        self.primary: bool | None = None
        self.reasons: tuple[str, ...] = ()
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addRow("Name", self.name)
        layout.addRow("URL", self.url)
        layout.addRow(self.on)
        self.name.textEdited.connect(self.value_changed)
        self.url.textEdited.connect(self.value_changed)
        self.on.clicked.connect(self.value_changed)

    def set_item(self, item: Any) -> None:
        """Show ``item`` without emitting.

        :param item: the dict to show.
        """
        self.name.setText(item.get("name", ""))
        self.url.setText(item.get("url", ""))
        self.on.setChecked(bool(item.get("on", False)))

    def item_values(self) -> dict[str, Any]:
        """The dict the widgets now read.

        :returns: the item.
        """
        item: dict[str, Any] = {}
        if self.name.text():
            item["name"] = self.name.text()
        if self.url.text():
            item["url"] = self.url.text()
        if self.on.isChecked():
            item["on"] = True
        return item

    def buddies(self) -> tuple[QWidget, QWidget]:
        """Delete beside the name, insert beside the URL.

        :returns: the two buddies.
        """
        return self.name, self.url

    def set_primary(self, primary: bool) -> None:
        """Record whether the card is the top one.

        :param primary: whether it is.
        """
        self.primary = primary

    def set_reasons(self, reasons: tuple[str, ...]) -> None:
        """Record why the card is in its states.

        :param reasons: the reasons.
        """
        self.reasons = tuple(reasons)


@dataclass
class Page:
    """An editor on a shown, active window, beside a line edit outside it.

    :param editor: the card list.
    :param other: a focus target outside the editor.
    """

    editor: CardListEditor
    other: QLineEdit

    @property
    def model(self) -> CardListModel:
        """The editor's model."""
        return self.editor.model

    def card(self, row: int) -> Card:
        """The card at ``row``.

        :param row: the row.
        :returns: the card.
        """
        cards = self.editor.cards
        return cards[row]

    def content(self, row: int) -> SampleContent:
        """The content of the card at ``row``.

        :param row: the row.
        :returns: its content.
        """
        content = self.card(row).content
        assert isinstance(content, SampleContent)
        return content

    def names(self) -> list[str]:
        """What each card's name edit reads, in card order.

        :returns: the names.
        """
        return [self.content(row).name.text() for row in range(len(self.editor.cards))]


# endregion


def flag_duplicates(items: Sequence[Any]) -> list[dict[str, str]]:
    """Flag every row repeating an earlier row's name.

    :param items: the rows' items.
    :returns: per row, its states.
    """
    seen: set[str] = set()
    states: list[dict[str, str]] = []
    for item in items:
        name = item.get("name", "")
        states.append({"flagged": "Duplicate name"} if name and name in seen else {})
        seen.add(name)
    return states


@fixture
def page(qtbot: QtBot) -> Iterator[Page]:
    """Three cards, ``a``, ``b``, ``c``, on a shown and active window.

    :param qtbot: pytest-qt bot.
    :returns: the page.
    """
    window = QWidget()
    qtbot.addWidget(window)
    model = CardListModel(dict, lambda item: not item, flag_duplicates, parent=window)
    model.set_items([{"name": "a"}, {"name": "b"}, {"name": "c"}])
    editor = CardListEditor(model, SampleContent)
    other = QLineEdit()
    layout = QVBoxLayout(window)
    layout.addWidget(editor)
    layout.addWidget(other)
    with qtbot.waitExposed(window):
        window.show()
    window.activateWindow()
    yield Page(editor, other)


def drop_event(
    editor: CardListEditor, kind: type, row: int, y: float, owner: int | None = None
) -> tuple[Any, QMimeData]:
    """A synthesized drag event carrying a drag of ``row``, and the mime data it must be kept alive with.

    :param editor: the editor dragged over.
    :param kind: the event class.
    :param row: the dragged row.
    :param y: the pointer's height, in the editor's coordinates.
    :param owner: the payload's owner identity; the editor's own by default.
    :returns: the event and its mime data.
    """
    mime = QMimeData()
    payload = f"{id(editor) if owner is None else owner}:{row}"
    mime.setData(CardListEditor.MIME_TYPE, QByteArray(payload.encode()))
    # QDropEvent takes a QPointF, its enter/move subclasses a QPoint
    event = kind(
        QPointF(10, y) if kind is QDropEvent else QPoint(10, int(y)),
        Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    return event, mime


def card_top(editor: CardListEditor, row: int) -> float:
    """A height just inside the top of the card at ``row``.

    :param editor: the editor.
    :param row: the row.
    :returns: the height, in the editor's coordinates.
    """
    return editor.cards[row].geometry().top() + 2


def card_bottom(editor: CardListEditor, row: int) -> float:
    """A height just inside the bottom of the card at ``row``.

    :param editor: the editor.
    :param row: the row.
    :returns: the height, in the editor's coordinates.
    """
    return editor.cards[row].geometry().bottom() - 2


# region BuddyButtonStrip tests


@fixture
def card(qtbot: QtBot) -> Card:
    """A shown card over a :class:`SampleContent`.

    :param qtbot: pytest-qt bot.
    :returns: the card.
    """
    card = Card(SampleContent(), CardStyle())
    qtbot.addWidget(card)
    card.resize(400, card.sizeHint().height())
    with qtbot.waitExposed(card):
        card.show()
    return card


def centre_in(card: Card, widget: QWidget) -> int:
    """The vertical middle of ``widget``, in ``card``'s coordinates.

    :param card: the card.
    :param widget: a widget inside it.
    :returns: the height of its middle.
    """
    return widget.mapTo(card, QPoint(0, widget.height() // 2)).y()


def buttons_on_buddies(card: Card) -> bool:
    """Whether every strip button is centred on its buddy, within a pixel.

    :param card: the card.
    :returns: whether they all are.
    """
    content = card.content
    assert isinstance(content, SampleContent)
    return all(
        abs(button.geometry().center().y() - centre_in(card, buddy)) <= 1
        for button, buddy in zip(card.strip.buttons, content.buddies(), strict=True)
    )


def test_buttons_are_square_at_their_natural_height(card: Card) -> None:
    """Each button is as wide as its own natural height -- never its buddy's.

    **Test steps:**

    * verify each button's width equals its height equals its size hint's height
    """
    for button in card.strip.buttons:
        assert button.width() == button.height() == button.sizeHint().height()


def test_buttons_are_centred_on_their_buddies_right_of_the_frame(card: Card) -> None:
    """Delete sits beside the first buddy, insert beside the second, both outside the frame.

    **Test steps:**

    * verify each button's middle matches its buddy's middle (within a pixel)
    * verify each button starts right of the frame
    """
    frame = card.content.parentWidget()
    assert frame is not None

    assert buttons_on_buddies(card)
    assert all(button.geometry().left() > frame.geometry().right() for button in card.strip.buttons)


def test_buttons_follow_a_buddy_that_moves(card: Card, qtbot: QtBot) -> None:
    """A layout change inside the content moves the buttons with their buddies.

    **Test steps:**

    * add a tall widget above the content's rows
    * wait for the buttons to settle back onto their buddies' new middles
    """
    content = card.content
    assert isinstance(content, SampleContent)
    spacer = QWidget()
    spacer.setFixedHeight(40)
    layout = content.layout()
    assert isinstance(layout, QFormLayout)

    layout.insertRow(0, spacer)

    qtbot.waitUntil(lambda: buttons_on_buddies(card))


def test_buttons_never_take_focus(card: Card) -> None:
    """Tab never lands on a button: the keyboard reaches their actions by shortcut.

    **Test steps:**

    * verify each button's focus policy
    """
    for button in card.strip.buttons:
        assert button.focusPolicy() == Qt.FocusPolicy.NoFocus


def test_buttons_show_on_hover_or_when_the_card_is_current(card: Card) -> None:
    """Hidden on a plain card, shown while hovered or current.

    **Test steps:**

    * send a leave event (the offscreen cursor may start over the card) and verify the buttons are hidden
    * send an enter event and verify they show; a leave event, and verify they hide
    * make the card current and verify they show
    """
    QApplication.sendEvent(card, QEvent(QEvent.Type.Leave))
    assert all(button.isHidden() for button in card.strip.buttons)

    QApplication.sendEvent(card, QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
    assert not any(button.isHidden() for button in card.strip.buttons)

    QApplication.sendEvent(card, QEvent(QEvent.Type.Leave))
    assert all(button.isHidden() for button in card.strip.buttons)

    card.set_current(True)
    assert not any(button.isHidden() for button in card.strip.buttons)


def test_the_buttons_carry_the_card_keys_in_their_tooltips(card: Card) -> None:
    """The tooltips name Ctrl+Del and Ctrl+Ins, since the keyboard is the only other way to them.

    **Test steps:**

    * verify each button's tooltip names its Ctrl key
    """
    delete, insert = card.strip.buttons

    assert "Ctrl+Del" in delete.toolTip()
    assert "Ctrl+Ins" in insert.toolTip()


# endregion

# region CardListEditor tests

# region in-place updates


def test_an_insert_adds_one_card_and_keeps_the_others(page: Page) -> None:
    """Inserting builds one card; the existing card widgets are the same objects.

    **Test steps:**

    * remember the cards, insert after the first
    * verify the old cards survive in place and a new card sits at row 1
    """
    before = page.editor.cards

    page.model.insert(0)

    after = page.editor.cards
    assert (after[0], after[2], after[3]) == before
    assert page.names() == ["a", "", "b", "c"]


def test_a_removal_drops_one_card_and_keeps_the_others(page: Page) -> None:
    """Deleting removes only that card.

    **Test steps:**

    * remember the cards, delete the middle one
    * verify the other two are the same objects
    """
    before = page.editor.cards

    page.model.delete(1)

    assert page.editor.cards == (before[0], before[2])


def test_a_move_moves_the_card_and_keeps_focus_in_it(page: Page, qtbot: QtBot) -> None:
    """Moving reorders the card widgets themselves; focus stays in the moved card.

    **Test steps:**

    * focus the last card's name and move it to the top
    * verify the same card is now first and still holds focus
    """
    last = page.editor.cards[2]
    page.content(2).name.setFocus()
    qtbot.waitUntil(lambda: page.editor.current_index == 2)

    page.model.move_to_top(2)

    assert page.editor.cards[0] is last
    assert page.names() == ["c", "a", "b"]
    assert QApplication.focusWidget() is page.content(0).name
    assert page.editor.current_index == 0


def test_the_top_card_is_told_it_is_primary(page: Page) -> None:
    """Only the first card's content hears it is the primary, and a move updates that.

    **Test steps:**

    * verify only the first card is primary
    * move the last card to the top and verify it became the primary
    """
    assert [page.content(row).primary for row in range(3)] == [True, False, False]

    page.model.move_to_top(2)

    assert [page.content(row).primary for row in range(3)] == [True, False, False]
    assert page.content(0).name.text() == "c"


def test_typing_updates_the_row_without_resetting_the_edit(page: Page) -> None:
    """Typing writes the item into its row, and the echo does not rewrite the edit under the cursor.

    **Test steps:**

    * type into the second card's name, watching the value signal
    * verify the model's row and the reported value, and that the cursor stayed at the end
    """
    edit = page.content(1).name
    edit.setFocus()
    received: list[Any] = []
    page.editor.value_changed.connect(received.append)

    QTest.keyClicks(edit, "x")

    assert page.model.item(1) == {"name": "bx"}
    assert received == [[{"name": "a"}, {"name": "bx"}, {"name": "c"}]]
    assert edit.cursorPosition() == 2


# endregion

# region keyboard


@mark.parametrize(
    ("key", "order"),
    [
        param(Qt.Key.Key_Up, ["b", "a", "c"], id="ctrl-up"),
        param(Qt.Key.Key_Down, ["a", "c", "b"], id="ctrl-down"),
        param(Qt.Key.Key_Home, ["b", "a", "c"], id="ctrl-home"),
        param(Qt.Key.Key_End, ["a", "c", "b"], id="ctrl-end"),
        param(Qt.Key.Key_Delete, ["a", "c"], id="ctrl-del"),
        param(Qt.Key.Key_Insert, ["a", "b", "", "c"], id="ctrl-ins"),
    ],
)
def test_a_ctrl_key_acts_on_the_focused_card(page: Page, key: Qt.Key, order: list[str]) -> None:
    """The card keys win over the line edit's own use of them, and act on the card holding focus.

    **Test steps:**

    * focus the middle card's name and press Ctrl plus the key
    * verify the cards' order
    """
    edit = page.content(1).name
    edit.setFocus()

    QTest.keyClick(edit, key, Qt.KeyboardModifier.ControlModifier)

    assert page.names() == order


def test_ctrl_ins_focuses_the_new_card(page: Page) -> None:
    """The inserted card takes focus, ready for typing.

    **Test steps:**

    * press Ctrl+Ins on the first card
    * verify focus is on the new second card's name
    """
    page.content(0).name.setFocus()

    QTest.keyClick(page.content(0).name, Qt.Key.Key_Insert, Qt.KeyboardModifier.ControlModifier)

    assert QApplication.focusWidget() is page.content(1).name


def test_ctrl_del_hands_focus_to_the_next_card(page: Page, qtbot: QtBot) -> None:
    """Deleting the focused card moves focus into the card that took its place.

    **Test steps:**

    * press Ctrl+Del on the first card
    * verify focus is on the new first card
    """
    page.content(0).name.setFocus()

    QTest.keyClick(page.content(0).name, Qt.Key.Key_Delete, Qt.KeyboardModifier.ControlModifier)

    qtbot.waitUntil(lambda: QApplication.focusWidget() is page.content(0).name)
    assert page.names() == ["b", "c"]


def test_plain_del_is_a_text_key(page: Page) -> None:
    """Del alone edits the text; it never deletes a card.

    **Test steps:**

    * put the cursor at the start of the first name and press Del
    * verify the character went and all three cards remain
    """
    edit = page.content(0).name
    edit.setFocus()
    edit.setCursorPosition(0)

    QTest.keyClick(edit, Qt.Key.Key_Delete)

    assert page.names() == ["", "b", "c"]


def test_tab_visits_only_the_edit_widgets_in_card_order(page: Page) -> None:
    """Tab walks each card's name, URL and checkbox, card after card, skipping grips and buttons -- in the
    order the cards stand after a move.

    **Test steps:**

    * move the last card to the top, focus its name
    * press Tab through the three cards' widgets
    * verify the focus sequence
    """
    page.model.move_to_top(2)
    page.content(0).name.setFocus()
    expected = [
        widget for row in range(3) for widget in (page.content(row).name, page.content(row).url, page.content(row).on)
    ]

    visited = [QApplication.focusWidget()]
    for _ in range(len(expected) - 1):
        focus = QApplication.focusWidget()
        assert focus is not None
        QTest.keyClick(focus, Qt.Key.Key_Tab)
        visited.append(QApplication.focusWidget())

    assert visited == expected


# endregion

# region current card and blanks


def test_the_current_card_follows_focus_and_clears_when_focus_leaves(page: Page, qtbot: QtBot) -> None:
    """The card holding focus is current; focus outside the editor leaves none current.

    **Test steps:**

    * focus the second card's URL and verify it is current
    * focus the line edit outside and verify no card is current
    """
    page.content(1).url.setFocus()
    qtbot.waitUntil(lambda: page.editor.current_index == 1)
    assert page.card(1).current

    page.other.setFocus()
    qtbot.waitUntil(lambda: page.editor.current_index == -1)
    assert not page.card(1).current


def test_a_blank_card_survives_focus_loss_and_stays_out_of_the_value(page: Page, qtbot: QtBot) -> None:
    """A blank card is removed only by the user, and is not part of the value.

    **Test steps:**

    * insert a card after the first, focus it, then focus outside the editor
    * verify the card is still there and the value has three items
    """
    received: list[Any] = []
    page.editor.value_changed.connect(received.append)
    QTest.keyClick(page.content(0).name, Qt.Key.Key_Insert, Qt.KeyboardModifier.ControlModifier)

    page.other.setFocus()
    qtbot.waitUntil(lambda: page.editor.current_index == -1)

    assert page.names() == ["a", "", "b", "c"]
    assert len(page.editor.value) == 3
    assert not received


def test_an_equal_set_value_keeps_blank_cards_and_emits_nothing(page: Page, qtbot: QtBot) -> None:
    """Setting the value the editor already holds changes nothing: the echo guard.

    **Test steps:**

    * insert a blank card, then set the unchanged value
    * verify the cards are the same objects and no value was reported
    """
    page.model.insert(-1)
    before = page.editor.cards

    with qtbot.assertNotEmitted(page.editor.value_changed):
        page.editor.set_value([{"name": "a"}, {"name": "b"}, {"name": "c"}])

    assert page.editor.cards == before


def test_a_new_set_value_rebuilds_without_reporting(page: Page, qtbot: QtBot) -> None:
    """A different value replaces the cards and is not echoed back.

    **Test steps:**

    * set a two-item value
    * verify the cards read it and no value was reported
    """
    with qtbot.assertNotEmitted(page.editor.value_changed):
        page.editor.set_value([{"name": "x"}, {"name": "y"}])

    assert page.names() == ["x", "y"]


def test_an_empty_list_shows_only_the_add_button(page: Page) -> None:
    """With no rows the add button stands in for the cards, and adds a focused one.

    **Test steps:**

    * set an empty value and verify the add button shows
    * click it and verify one focused card exists and the button hides
    """
    assert page.editor.add_button.isHidden()

    page.editor.set_value([])
    assert not page.editor.add_button.isHidden()

    page.editor.add_button.click()

    assert len(page.editor.cards) == 1
    assert page.editor.add_button.isHidden()
    assert QApplication.focusWidget() is page.content(0).name


def test_states_reach_the_cards_and_their_content(page: Page) -> None:
    """The model's states flag the card and hand its content the reasons.

    **Test steps:**

    * rename the last card to repeat the first
    * verify the last card is flagged and its content heard why
    """
    page.model.set_item(2, {"name": "a"})

    assert page.card(2).states == {"flagged": "Duplicate name"}
    assert page.content(2).reasons == ("Duplicate name",)
    assert page.card(0).states == {}


def test_a_current_flagged_card_keeps_the_flag_as_its_border(page: Page, qtbot: QtBot) -> None:
    """Current wins the fill; a registered state keeps its border.

    **Test steps:**

    * register a pink ``flagged`` state, flag the last card and focus it
    * verify the unfocused flagged card paints pink over pink
    * focus it and verify it paints the palette's selection colour, still bordered pink
    """
    pink = QColor("pink")
    page.editor.style_map.register("flagged", CardStateStyle(fill=pink, border=pink))
    page.model.set_item(2, {"name": "a"})
    card = page.card(2)
    palette = card.palette()

    style = card.painted_style()
    assert CardStateStyle.resolve(style.fill, palette) == pink
    assert CardStateStyle.resolve(style.border, palette) == pink

    page.content(2).url.setFocus()
    qtbot.waitUntil(lambda: page.editor.current_index == 2)

    style = card.painted_style()
    assert CardStateStyle.resolve(style.fill, palette) == palette.color(QPalette.ColorRole.Highlight)
    assert CardStateStyle.resolve(style.border, palette) == pink


def test_an_edit_the_content_adds_later_is_wired_like_the_others(page: Page, qtbot: QtBot) -> None:
    """A widget a content grows after its card was built makes the card current, answers the card keys, and
    takes its place in the tab order.

    **Test steps:**

    * add a line edit to the middle card's content, after its checkbox
    * focus it and verify the middle card becomes current
    * press Ctrl+Up on it and verify the card moved to the top
    * Tab from the checkbox before it and verify focus lands on it
    """
    content = page.content(1)
    later = QLineEdit()
    layout = content.layout()
    assert isinstance(layout, QFormLayout)
    layout.addRow("Later", later)
    later.show()
    qtbot.wait(1)  # the content is rewired on the next pass of the event loop

    later.setFocus()
    qtbot.waitUntil(lambda: page.editor.current_index == 1)

    QTest.keyClick(later, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
    assert page.names() == ["b", "a", "c"]

    content.on.setFocus()
    QTest.keyClick(content.on, Qt.Key.Key_Tab)
    assert QApplication.focusWidget() is later


# endregion

# region drag and drop


@mark.parametrize(
    ("row", "position", "slot"),
    [
        param(2, "top-of-first", 0, id="top"),
        param(0, "bottom-of-last", 2, id="bottom"),
        param(0, "bottom-of-second", 1, id="middle"),
    ],
)
def test_the_ghost_takes_the_dragged_cards_place_and_follows_the_pointer(
    page: Page, row: int, position: str, slot: int
) -> None:
    """While a card is dragged it leaves the list and the ghost stands where it would land -- at the top and
    bottom too -- so the list never shows more items than it has.

    **Test steps:**

    * send a drag enter and move for ``row`` at the given height
    * verify the ghost's slot is the row the card would end up at
    * verify the dragged card is hidden, and that the visible cards plus the ghost still make three
    """
    heights = {
        "top-of-first": card_top(page.editor, 0),
        "bottom-of-last": card_bottom(page.editor, 2),
        "bottom-of-second": card_bottom(page.editor, 1),
    }
    dragged = page.card(row)
    enter, enter_mime = drop_event(page.editor, QDragEnterEvent, row, heights[position])
    QApplication.sendEvent(page.editor, enter)
    move, move_mime = drop_event(page.editor, QDragMoveEvent, row, heights[position])
    QApplication.sendEvent(page.editor, move)

    assert page.editor.ghost_slot == slot
    assert dragged.isHidden()
    assert sum(not card.isHidden() for card in page.editor.cards) == 2
    assert enter_mime is not None and move_mime is not None


@mark.parametrize("position", [param("top", id="above-itself"), param("bottom", id="below-itself")])
def test_dragged_over_itself_the_ghost_stands_in_its_original_place(page: Page, position: str) -> None:
    """Over its own place the card is not shown twice: it is hidden and the ghost sits where it was.

    **Test steps:**

    * drag the middle card over its own top and bottom half
    * verify the ghost is at row 1, the card is hidden, and two cards plus the ghost are visible
    * drop it there and verify the order is unchanged and the card is back
    """
    y = card_top(page.editor, 1) if position == "top" else card_bottom(page.editor, 1)
    card = page.card(1)
    enter, mime = drop_event(page.editor, QDragEnterEvent, 1, y)
    QApplication.sendEvent(page.editor, enter)

    assert page.editor.ghost_slot == 1
    assert card.isHidden()
    assert sum(not c.isHidden() for c in page.editor.cards) == 2

    drop, drop_mime = drop_event(page.editor, QDropEvent, 1, y)
    QApplication.sendEvent(page.editor, drop)

    assert page.names() == ["a", "b", "c"]
    assert not card.isHidden()
    assert page.editor.ghost_slot == -1
    assert mime is not None and drop_mime is not None


def test_a_drag_that_leaves_puts_the_gap_back_where_the_card_came_from(page: Page) -> None:
    """When the pointer leaves the editor the ghost returns to the card's original place, and the card
    stays out of the list until the drag ends.

    **Test steps:**

    * drag the first card to the bottom, then leave the editor
    * verify the ghost is back at row 0 and the card is still hidden
    """
    dragged = page.card(0)
    enter, mime = drop_event(page.editor, QDragEnterEvent, 0, card_bottom(page.editor, 2))
    QApplication.sendEvent(page.editor, enter)
    assert page.editor.ghost_slot == 2

    QApplication.sendEvent(page.editor, QDragLeaveEvent())

    assert page.editor.ghost_slot == 0
    assert dragged.isHidden()
    assert mime is not None


def test_a_drop_moves_the_card_and_closes_the_gap(page: Page) -> None:
    """Dropping the first card below the last moves it there, and brings the card back into the list.

    **Test steps:**

    * drag the first card to below the last and drop it
    * verify the order, that the card is shown again, and that the ghost is gone
    """
    first = page.card(0)
    y = card_bottom(page.editor, 2)
    enter, enter_mime = drop_event(page.editor, QDragEnterEvent, 0, y)
    QApplication.sendEvent(page.editor, enter)
    drop, drop_mime = drop_event(page.editor, QDropEvent, 0, y)
    QApplication.sendEvent(page.editor, drop)

    assert page.names() == ["b", "c", "a"]
    assert page.card(2) is first
    assert not first.isHidden()
    assert page.editor.ghost_slot == -1
    assert enter_mime is not None and drop_mime is not None


def test_a_drag_from_elsewhere_is_not_accepted(page: Page) -> None:
    """A payload this editor did not create is left for the host.

    **Test steps:**

    * send a drag enter whose payload names another owner
    * verify the event was ignored and no ghost opened
    """
    enter, mime = drop_event(page.editor, QDragEnterEvent, 0, card_bottom(page.editor, 2), owner=1)
    QApplication.sendEvent(page.editor, enter)

    assert not enter.isAccepted()
    assert page.editor.ghost_slot == -1
    assert mime is not None


def test_the_grip_starts_a_drag_of_its_card(page: Page, mocker: MockerFixture) -> None:
    """Pressing and moving a grip past the drag distance drags that card's row.

    **Test steps:**

    * replace ``QDrag`` so the drag records its payload instead of blocking
    * press and move the second card's grip
    * verify one drag of row 1 was started
    """
    drag_class = mocker.patch("borco_pyside.widgets.card_list.card_list_editor.QDrag")
    grip = page.card(1).grip
    QTest.mousePress(grip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, grip.rect().center())
    QTest.mouseMove(grip, grip.rect().center() + grip.rect().bottomRight())

    drag = drag_class.return_value
    drag.exec.assert_called_once_with(Qt.DropAction.MoveAction)
    (mime,) = drag.setMimeData.call_args.args
    assert bytes(mime.data(CardListEditor.MIME_TYPE).data()) == f"{id(page.editor)}:1".encode()


# endregion

# endregion


# region coverage of the remaining paths


class BareContent(QWidget):
    """A `CardContent` with nothing to type into: a caption only.

    :param parent: optional Qt parent.
    """

    value_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item: Any = {}
        self.caption = QLabel("nothing to edit", self)
        QVBoxLayout(self).addWidget(self.caption)

    def set_item(self, item: Any) -> None:
        """Keep ``item``.

        :param item: the item.
        """
        self.item = item

    def item_values(self) -> Any:
        """The item as it was given.

        :returns: the item.
        """
        return self.item

    def buddies(self) -> tuple[QWidget, QWidget]:
        """Both buttons beside the caption.

        :returns: the two buddies.
        """
        return self.caption, self.caption


def make_page(qtbot: QtBot, factory: Any, *items: dict[str, Any]) -> tuple[QWidget, CardListEditor]:
    """A shown editor over ``items`` built from ``factory``.

    :param qtbot: pytest-qt bot, which holds the window only weakly -- the caller keeps it alive.
    :param factory: builds one card's content.
    :param items: the rows' items.
    :returns: the window holding the editor, and the editor.
    """
    window = QWidget()
    qtbot.addWidget(window)
    model = CardListModel(dict, lambda item: not item, parent=window)
    model.set_items(list(items))
    editor = CardListEditor(model, factory)
    QVBoxLayout(window).addWidget(editor)
    with qtbot.waitExposed(window):
        window.show()
    window.activateWindow()
    return window, editor


def test_a_card_needs_a_card_content(qapp: QApplication) -> None:  # pylint: disable=unused-argument
    """A widget that is not a `CardContent` is refused, naming its class.

    **Test steps:**

    * build a card over a plain widget
    * verify it raises ``TypeError``
    """
    with raises(TypeError, match="QWidget is not a CardContent"):
        Card(QWidget(), CardStyle())


def test_setting_the_same_current_state_again_announces_nothing(page: Page, qtbot: QtBot) -> None:
    """A card made current twice, or not current twice, announces once.

    **Test steps:**

    * make a card current twice and not current twice, watching for the announcement
    * verify each real change was announced once
    """
    card = page.card(1)
    card.set_current(False)
    with qtbot.waitSignal(card.current_changed):
        card.set_current(True)
    with qtbot.assertNotEmitted(card.current_changed):
        card.set_current(True)
    with qtbot.waitSignal(card.current_changed):
        card.set_current(False)
    with qtbot.assertNotEmitted(card.current_changed):
        card.set_current(False)


def test_the_editor_is_an_item_viewer(page: Page) -> None:
    """The current row can be read, set, cleared and edited through the `ItemViewer` contract.

    **Test steps:**

    * set the current row to 1 and verify focus and the reported row
    * ``edit_current`` and verify focus is in that card
    * set the current row to ``-1`` and verify none is current, and ``edit_current`` then does nothing
    """
    page.editor.set_current_index(1)
    assert page.editor.current_index == 1
    assert QApplication.focusWidget() is page.content(1).name

    page.other.setFocus()
    page.editor.edit_current()
    assert QApplication.focusWidget() is page.content(1).name

    page.editor.set_current_index(-1)
    assert page.editor.current_index == -1
    page.other.setFocus()
    page.editor.edit_current()
    assert QApplication.focusWidget() is page.other


def test_deleting_the_only_focused_card_hands_focus_to_the_add_button(qtbot: QtBot) -> None:
    """Removing the last card while it holds focus leaves focus on the add button, not nowhere.

    **Test steps:**

    * focus the only card's edit and delete its row
    * verify the add button shows and holds focus
    """
    _window, editor = make_page(qtbot, SampleContent, {"name": "solo"})
    cards = editor.cards
    first = cards[0].content
    assert isinstance(first, SampleContent)
    first.name.setFocus()

    editor.model.delete(0)

    assert not editor.add_button.isHidden()
    assert QApplication.focusWidget() is editor.add_button


def test_a_card_with_nothing_to_type_into_can_still_be_current(qtbot: QtBot) -> None:
    """A content with no edit widget is a card all the same; focusing it just has nowhere to land.

    **Test steps:**

    * build an editor over contents that hold only a caption
    * set the current row and verify it is reported
    """
    _window, editor = make_page(qtbot, BareContent, {"a": 1})

    editor.set_current_index(0)

    assert editor.current_index == 0


def test_events_for_a_card_that_is_gone_are_ignored(page: Page, qtbot: QtBot) -> None:
    """A late edit or a late widget from a removed card touches nothing.

    **Test steps:**

    * remember a card's content, add a widget to it, and delete its row before the event loop runs
    * emit its edit signal and let the loop run
    * verify the remaining cards and the model are untouched
    """
    content = page.content(2)
    layout = content.layout()
    assert isinstance(layout, QFormLayout)
    layout.addRow("Late", QLineEdit())
    page.model.delete(2)

    content.value_changed.emit()
    qtbot.wait(5)

    assert page.names() == ["a", "b"]
    assert page.model.value == [{"name": "a"}, {"name": "b"}]


def test_a_single_card_can_be_dragged_and_a_drag_can_end_two_ways(
    page: Page, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """The ghost of a lone card stands alone, and a drag that ends after a drop or after its card was
    removed finishes cleanly.

    **Test steps:**

    * drag over an editor holding one card and verify its ghost is at row 0
    * start a drag whose ``exec`` drops the card, and one whose ``exec`` deletes its row
    * verify the cards are shown again where they still exist and no ghost is left
    """
    _window, single = make_page(qtbot, SampleContent, {"name": "solo"})
    enter, mime = drop_event(single, QDragEnterEvent, 0, 3)
    QApplication.sendEvent(single, enter)
    assert single.ghost_slot == 0
    QApplication.sendEvent(single, QDragLeaveEvent())
    assert mime is not None

    drag_class = mocker.patch("borco_pyside.widgets.card_list.card_list_editor.QDrag")
    y = card_bottom(page.editor, 2)
    kept: list[QMimeData] = []

    def dropping(*_args: Any) -> Qt.DropAction:
        enter, enter_data = drop_event(page.editor, QDragEnterEvent, 0, y)
        drop, data = drop_event(page.editor, QDropEvent, 0, y)
        kept.extend((enter_data, data))
        QApplication.sendEvent(page.editor, enter)
        QApplication.sendEvent(page.editor, drop)
        return Qt.DropAction.MoveAction

    drag_class.return_value.exec.side_effect = dropping
    page.card(0).drag_requested.emit()
    assert page.names() == ["b", "c", "a"]
    assert page.editor.ghost_slot == -1

    drag_class.return_value.exec.side_effect = lambda *_args: page.model.delete(0)
    page.card(0).drag_requested.emit()
    assert page.names() == ["c", "a"]
    assert page.editor.ghost_slot == -1


def test_a_foreign_move_leave_or_drop_is_ignored(page: Page) -> None:
    """Only this editor's own drag is handled: a foreign move and drop are ignored, and a leave with no drag
    in progress is harmless.

    **Test steps:**

    * send a move and a drop carrying another owner's payload, and a drag leave
    * verify neither event was accepted and no ghost opened
    """
    # straight to the handlers: Qt does not deliver a move or a drop after an enter that was ignored
    move, move_mime = drop_event(page.editor, QDragMoveEvent, 0, 5, owner=1)
    page.editor.dragMoveEvent(move)
    drop, drop_mime = drop_event(page.editor, QDropEvent, 0, 5, owner=1)
    page.editor.dropEvent(drop)
    QApplication.sendEvent(page.editor, QDragLeaveEvent())

    assert not move.isAccepted()
    assert not drop.isAccepted()
    assert page.editor.ghost_slot == -1
    assert move_mime is not None and drop_mime is not None


def test_the_grip_asks_for_a_drag_only_after_a_left_press_and_a_real_move(page: Page, qtbot: QtBot) -> None:
    """A right press, a short move, or a move after the button was released never asks for a drag.

    **Test steps:**

    * press with the right button and move far; press left and move a pixel; press, release, move far
    * verify no drag was requested, then press left and move far and verify one was
    """
    grip = page.card(0).grip
    centre = grip.rect().center()
    far = centre + QPoint(40, 40)
    with qtbot.assertNotEmitted(grip.drag_requested):
        QTest.mousePress(grip, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, centre)
        QTest.mouseMove(grip, far)
        QTest.mouseRelease(grip, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, centre)
        QTest.mousePress(grip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre)
        QTest.mouseMove(grip, centre + QPoint(1, 0))
        QTest.mouseRelease(grip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre)
        QTest.mouseMove(grip, far)
    with qtbot.waitSignal(grip.drag_requested):
        QTest.mousePress(grip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre)
        QTest.mouseMove(grip, far)


def test_a_style_colour_may_be_a_function_of_the_palette() -> None:
    """A colour given as a callable is called with the palette at paint time.

    **Test steps:**

    * resolve a fixed colour, a palette role, a function of the palette, and ``None``
    * verify each resolves as it should
    """
    palette = QPalette()

    def dimmed(given: QPalette) -> QColor:
        return given.color(QPalette.ColorRole.Window).darker()

    assert CardStateStyle.resolve(QColor("red"), palette) == QColor("red")
    assert CardStateStyle.resolve(QPalette.ColorRole.Highlight, palette) == palette.color(QPalette.ColorRole.Highlight)
    assert CardStateStyle.resolve(dimmed, palette) == dimmed(palette)
    assert CardStateStyle.resolve(None, palette) is None


# endregion
