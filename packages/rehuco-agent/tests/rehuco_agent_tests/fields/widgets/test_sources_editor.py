"""Tests for SourcesEditor and SourceCardContent: one card per source, flagged never refused (#391)."""

from typing import Any

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.field import HeaderPinned
from rehuco_agent.fields.widgets import SourceCardContent, SourcesEditor, UrlEditDropFilter
from rehuco_core import RehuDocument

from rehuco_agent_tests.fields.field_testers import SourcesFieldTester


# region helpers
def make_model(*sources: dict[str, Any]) -> RehuDocumentModel:
    """A model over a Tutorial holding ``sources``, the first one flagged primary as a file would.

    :param sources: the source records, top first.
    :returns: the model.
    """
    records = [{**source, "primary": True} if row == 0 else dict(source) for row, source in enumerate(sources)]
    return RehuDocumentModel(RehuDocument({"type": "Tutorial", "sources": records}))


def make_editor(qtbot: QtBot, model: RehuDocumentModel) -> SourcesEditor:
    """A sources editor bound to ``model`` the way the field binds it.

    :param qtbot: pytest-qt bot.
    :param model: the model to bind to.
    :returns: the editor.
    """
    field = SourcesFieldTester("sources")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, SourcesEditor)
    qtbot.addWidget(editor)
    editor.show()
    return editor


def content(editor: SourcesEditor, row: int) -> SourceCardContent:
    """The content of the card at ``row``.

    :param editor: the editor.
    :param row: the row.
    :returns: its content.
    """
    found = editor.cards[row].content
    assert isinstance(found, SourceCardContent)
    return found


def link_mime(url: str) -> QMimeData:
    """Mime data carrying one link.

    :param url: the link.
    :returns: the data.
    """
    mime = QMimeData()
    mime.setUrls([QUrl(url)])
    return mime


def drag_enter(mime: QMimeData) -> QDragEnterEvent:
    """A drag-enter event carrying ``mime``, over the top-left of whatever it is sent to.

    :param mime: the dragged data, which the caller keeps alive beside the event.
    :returns: the event.
    """
    return QDragEnterEvent(
        QPoint(3, 3), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    )


def drop(mime: QMimeData) -> QDropEvent:
    """A drop event carrying ``mime``, over the top-left of whatever it is sent to.

    :param mime: the dropped data, which the caller keeps alive beside the event.
    :returns: the event.
    """
    return QDropEvent(
        QPointF(3, 3), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    )


@fixture
def two_sources() -> RehuDocumentModel:
    """A model with two sources at different addresses.

    :returns: the model.
    """
    return make_model(
        {"title": "First", "publisher": "A", "url": "https://a.example/1"},
        {"title": "Second", "publisher": "B", "url": "https://b.example/2"},
    )


# endregion


def test_one_card_per_source_with_plain_captions(qtbot: QtBot, two_sources: RehuDocumentModel) -> None:
    """Each source is a card, captioned Title, URL and Publisher, none of them bold -- the primary is not
    marked on the card, so dragging never makes a different card look changed.

    **Test steps:**

    * build the editor over two sources
    * verify two cards, each with plain Title/URL/Publisher captions
    """
    editor = make_editor(qtbot, two_sources)

    assert len(editor.cards) == 2
    assert not any(caption.font().bold() for row in (0, 1) for caption in content(editor, row).captions)
    assert [caption.text() for caption in content(editor, 0).captions] == ["Title", "URL", "Publisher"]


def test_moving_a_card_to_the_top_makes_it_the_primary(qtbot: QtBot, two_sources: RehuDocumentModel) -> None:
    """The written value has the moved source first and flagged primary, and the model's title follows.

    **Test steps:**

    * move the second card to the top
    * verify the document's sources lead with it, flagged ``primary``, and it alone
    * verify the model's title moved with it, and the model is dirty
    """
    editor = make_editor(qtbot, two_sources)

    editor.model.move_to_top(1)

    assert two_sources.document.sources == [
        {"title": "Second", "publisher": "B", "url": "https://b.example/2", "primary": True},
        {"title": "First", "publisher": "A", "url": "https://a.example/1"},
    ]
    assert two_sources.title == "Second"
    assert two_sources.dirty is True


def test_the_pink_tint_follows_the_urls_live(qtbot: QtBot, two_sources: RehuDocumentModel) -> None:
    """A card repeating the address of one above is flagged, and the flag tracks edits, moves and deletes.

    **Test steps:**

    * type the first card's URL into the second card and verify only the second is flagged
    * edit it to a different address and verify the flag clears
    * make it a duplicate again and move it to the top: the card that is now second is the flagged one
    * delete the flagged card and verify no card is flagged
    """
    editor = make_editor(qtbot, two_sources)
    assert [card.states for card in editor.cards] == [{}, {}]

    content(editor, 1).url_edit.setText("https://a.example/1")
    assert [bool(card.states) for card in editor.cards] == [False, True]
    cards = editor.cards
    assert cards[1].painted_style().fill is not None

    content(editor, 1).url_edit.setText("https://b.example/2")
    assert [bool(card.states) for card in editor.cards] == [False, False]

    content(editor, 1).url_edit.setText("  https://a.example/1 ")
    editor.model.move_to_top(1)
    assert [bool(card.states) for card in editor.cards] == [False, True]
    assert content(editor, 1).title_edit.text() == "First"

    editor.model.delete(1)
    assert [bool(card.states) for card in editor.cards] == [False]


def test_deleting_a_pink_card_dirties_the_document(qtbot: QtBot) -> None:
    """A file holding a duplicate opens clean and keeps it; deleting it is an ordinary edit.

    **Test steps:**

    * open a model with the same URL on two sources, and build the editor
    * verify it is clean, both cards show, and the second is flagged
    * delete the flagged card and verify one source remains and the model is dirty
    """
    url = "https://dup.example/x"
    model = make_model({"title": "T", "url": url}, {"title": "T", "url": url})
    editor = make_editor(qtbot, model)
    assert model.dirty is False
    assert [bool(card.states) for card in editor.cards] == [False, True]
    assert len(model.document.sources) == 2

    editor.model.delete(1)

    assert model.document.sources == [{"title": "T", "url": url, "primary": True}]
    assert model.dirty is True


def test_a_card_started_from_its_url_is_kept_and_flagged_for_its_title(
    qtbot: QtBot, two_sources: RehuDocumentModel
) -> None:
    """A card may begin with its URL: it is kept with no title, and says a title is missing.

    **Test steps:**

    * insert a card after the last one and verify the value is unchanged while it is blank
    * type only a URL into it
    * verify the source is in the model with just that URL, its title edit is flagged with the reason, and
      the URL edit is not
    """
    editor = make_editor(qtbot, two_sources)
    editor.model.insert(1)
    assert len(two_sources.document.sources) == 2

    content(editor, 2).url_edit.setText("https://c.example/3")

    assert two_sources.document.sources[2] == {"url": "https://c.example/3"}
    assert content(editor, 2).title_edit.property("warning") is True
    assert content(editor, 2).title_edit.toolTip() == SourceCardContent.MISSING_TITLE_REASON
    assert content(editor, 2).url_edit.property("warning") is False


def test_a_url_that_is_not_http_is_flagged_but_kept(qtbot: QtBot, two_sources: RehuDocumentModel) -> None:
    """A non-http(s) address is painted as a warning with a tooltip, and stored all the same.

    **Test steps:**

    * type an ``ftp`` address into the first card
    * verify the URL edit is flagged with a tooltip and the model holds the address
    """
    editor = make_editor(qtbot, two_sources)

    content(editor, 0).url_edit.setText("ftp://files.example/x")

    assert content(editor, 0).url_edit.property("warning") is True
    assert content(editor, 0).url_edit.toolTip() != ""
    assert two_sources.url == "ftp://files.example/x"


def test_an_edit_merges_into_the_source_and_an_emptied_field_loses_its_key(qtbot: QtBot) -> None:
    """Typing rewrites only what was touched: unknown keys stay, and an emptied edit deletes its key.

    **Test steps:**

    * open a source carrying a key the card has no edit for
    * change its title and verify the extra key survives
    * empty its publisher and verify the key is gone rather than ``""``
    """
    model = make_model({"title": "T", "publisher": "P", "url": "https://x.example", "note": {"keep": 1}})
    editor = make_editor(qtbot, model)

    content(editor, 0).title_edit.setText("Renamed")
    assert model.document.sources[0]["note"] == {"keep": 1}
    assert model.document.sources[0]["title"] == "Renamed"

    content(editor, 0).publisher_edit.setText("")
    assert "publisher" not in model.document.sources[0]


def test_a_blank_card_is_left_out_of_the_value_until_something_is_typed(
    qtbot: QtBot, two_sources: RehuDocumentModel
) -> None:
    """A card holding none of title, URL and publisher is not part of the value.

    **Test steps:**

    * insert a card and verify it is shown but the value has two sources
    * type a publisher and verify the value has three
    """
    editor = make_editor(qtbot, two_sources)

    editor.model.insert(1)
    assert len(editor.cards) == 3
    assert len(editor.value) == 2

    content(editor, 2).publisher_edit.setText("Someone")
    assert len(editor.value) == 3


def test_a_link_dropped_on_the_url_edit_replaces_its_text(qtbot: QtBot, two_sources: RehuDocumentModel) -> None:
    """A link dropped on a URL edit becomes its whole text, rather than being inserted into it.

    **Test steps:**

    * drag a link onto the first card's URL edit and drop it
    * verify both events were accepted and the edit reads the link alone, written through to the model
    """
    editor = make_editor(qtbot, two_sources)
    edit = content(editor, 0).url_edit
    mime = link_mime("https://dropped.example/page")

    enter = drag_enter(mime)
    QApplication.sendEvent(edit, enter)
    dropped = drop(mime)
    QApplication.sendEvent(edit, dropped)

    assert enter.isAccepted()
    assert dropped.isAccepted()
    assert edit.text() == "https://dropped.example/page"
    assert two_sources.url == "https://dropped.example/page"


def test_other_drops_are_left_to_the_dock_behind_the_editor(qtbot: QtBot, two_sources: RehuDocumentModel) -> None:
    """Only a link on the URL edit is taken; the other edits accept no drops, so the dock's scrape sees them.

    **Test steps:**

    * verify the title and publisher edits accept no drops
    * send the URL edit's filter a plain-text drag and verify it is left alone
    * send the editor a drag it did not start and verify it is not accepted
    """
    editor = make_editor(qtbot, two_sources)
    card = content(editor, 0)
    assert not card.title_edit.acceptDrops()
    assert not card.publisher_edit.acceptDrops()

    text = QMimeData()
    text.setText("just words")
    drop_filter = card.url_edit.findChild(UrlEditDropFilter)
    assert drop_filter is not None
    assert drop_filter.eventFilter(card.url_edit, drag_enter(text)) is False

    mime = link_mime("https://x.example")
    foreign = drag_enter(mime)
    QApplication.sendEvent(editor, foreign)
    assert not foreign.isAccepted()


def test_the_cards_actions_wear_the_apps_icons(qtbot: QtBot, two_sources: RehuDocumentModel) -> None:
    """Every card's delete and insert actions carry an icon, and its buttons stay square -- also for a card
    added later.

    **Test steps:**

    * insert a card, so there are cards built at construction and one built later
    * verify each card's delete and insert actions have icons and its buttons are square
    """
    editor = make_editor(qtbot, two_sources)
    editor.model.insert(1)

    for card in editor.cards:
        assert not card.delete_action.icon().isNull()
        assert not card.insert_action.icon().isNull()
        for button in card.strip.buttons:
            assert button.width() == button.height()


def test_the_glyphs_read_on_the_selected_fill(qtbot: QtBot, two_sources: RehuDocumentModel) -> None:
    """A current card's buttons wear the highlighted-text glyphs, and the plain ones again when it is not.

    **Test steps:**

    * note the delete icon of a card that is not current
    * make it current and verify the icon changed
    * make it not current and verify the original icon is back
    """
    editor = make_editor(qtbot, two_sources)
    cards = editor.cards
    card = cards[0]
    plain = card.delete_action.icon().cacheKey()

    card.set_current(True)
    assert card.delete_action.icon().cacheKey() != plain

    card.set_current(False)
    assert card.delete_action.icon().cacheKey() == plain


def test_the_drag_handle_shows_only_while_there_are_several_sources(qtbot: QtBot) -> None:
    """A single source has nothing to reorder, so its grip is hidden; a second source brings it back.

    **Test steps:**

    * build the editor over one source and verify the grip is hidden
    * insert a card and verify both grips show
    * delete it and verify the remaining grip is hidden again
    """
    model = make_model({"title": "Only"})
    editor = make_editor(qtbot, model)
    grips = [card.grip for card in editor.cards]
    assert [grip.isHidden() for grip in grips] == [True]

    editor.model.insert(0)
    grips = [card.grip for card in editor.cards]
    assert [grip.isHidden() for grip in grips] == [False, False]

    editor.model.delete(1)
    grips = [card.grip for card in editor.cards]
    assert [grip.isHidden() for grip in grips] == [True]


def test_insert_sits_above_delete(qtbot: QtBot, two_sources: RehuDocumentModel) -> None:
    """The card's ``[+]`` is on the Title row and its ``[x]`` on the Publisher row, like the item tables.

    **Test steps:**

    * verify the insert button is level with the Title edit and the delete button with the Publisher edit
    """
    editor = make_editor(qtbot, two_sources)
    cards = editor.cards
    card, body = cards[0], content(editor, 0)
    delete, insert = card.strip.buttons

    def middle(widget: Any) -> int:
        return widget.mapTo(card, QPoint(0, widget.height() // 2)).y()

    assert abs(insert.geometry().center().y() - middle(body.title_edit)) <= 1
    assert abs(delete.geometry().center().y() - middle(body.publisher_edit)) <= 1
    assert insert.geometry().center().y() < delete.geometry().center().y()


def test_every_source_is_always_shown_and_the_label_is_pinned_to_the_first_row(
    qtbot: QtBot, two_sources: RehuDocumentModel
) -> None:
    """There is no collapsing: every card shows. The editor is `HeaderPinned`, so the row's label sits fixed
    beside the first card's Title row, whatever the number of cards.

    **Test steps:**

    * verify both cards show, and that the editor offers no expand state
    * verify it is a `HeaderPinned` editor whose header covers the first row, and does not change with the count
    """
    editor = make_editor(qtbot, two_sources)
    assert [card.isHidden() for card in editor.cards] == [False, False]
    assert not hasattr(editor, "set_expanded")

    assert isinstance(editor, HeaderPinned)
    height = editor.header_height
    assert height > 0
    editor.model.insert(1)
    assert editor.header_height == height
