"""Tests for MessageBanner: a strip of state notices, one row per still-active condition.

Rows carry no dismiss affordance (state, not a one-shot notification) and rebuild wholesale on every
``set_rows`` call, so what these tests exercise is: a row renders its icon/text, an empty row list
shows nothing, multiple rows stack, and long text wraps rather than widening the strip.
"""

from borco_pyside.widgets import MessageBanner, MessageBannerRow, MessageBannerSeverity
from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot


def row(text: str = "Something needs attention", *, glyph: str = "!", family: str = "") -> MessageBannerRow:
    """A sample warning row, seeded with sensible defaults for whichever field a test doesn't care about.

    :param text: the row's message.
    :param glyph: the row's icon glyph.
    :param family: the row's icon font family.
    :returns: the built row.
    """
    return MessageBannerRow(MessageBannerSeverity.WARNING, glyph, text, family=family)


# region rendering a row
def test_a_row_renders_its_icon_and_text(qtbot: QtBot) -> None:
    """A row shows both its icon glyph and its message text.

    **Test steps:**

    * build a banner with one row
    * verify a label shows the glyph and another shows the message
    """
    banner = MessageBanner()
    qtbot.addWidget(banner)

    banner.set_rows([row(glyph="!", text="Invalid field: title")])

    texts = {label.text() for label in banner.findChildren(QLabel)}
    assert "!" in texts
    assert "Invalid field: title" in texts


def test_a_rows_icon_uses_the_given_font_family(qtbot: QtBot) -> None:
    """A row given a ``family`` styles its icon glyph in that font -- an icon-font codepoint, not a
    plain Unicode symbol.

    **Test steps:**

    * build a banner with one row carrying an icon-font family
    * find the icon label (the one showing the glyph) and verify its stylesheet names that family
    """
    banner = MessageBanner()
    qtbot.addWidget(banner)

    banner.set_rows([row(glyph="!", family="SomeIconFont")])

    styled = [label for label in banner.findChildren(QLabel) if "SomeIconFont" in label.styleSheet()]
    assert len(styled) == 1
    assert styled[0].text() == "!"


# endregion


# region multiple rows and rebuilding
def test_multiple_rows_stack(qtbot: QtBot) -> None:
    """Several rows all render, each with its own message.

    **Test steps:**

    * build a banner with two rows
    * verify both messages are shown
    """
    banner = MessageBanner()
    qtbot.addWidget(banner)

    banner.set_rows([row(text="First notice"), row(text="Second notice")])

    texts = {label.text() for label in banner.findChildren(QLabel)}
    assert {"First notice", "Second notice"} <= texts


def test_set_rows_replaces_the_previous_rows(qtbot: QtBot) -> None:
    """A later ``set_rows`` call discards the rows from an earlier one -- the rebuild-wholesale
    behavior a cleared lock reason (or a successful convert) relies on.

    **Test steps:**

    * seed the banner with one row, then replace it with a different one
    * verify only the new row's text remains
    """
    banner = MessageBanner()
    qtbot.addWidget(banner)
    banner.set_rows([row(text="Stale notice")])

    banner.set_rows([row(text="Fresh notice")])

    texts = {label.text() for label in banner.findChildren(QLabel)}
    assert "Stale notice" not in texts
    assert "Fresh notice" in texts


def test_an_empty_row_list_shows_nothing(qtbot: QtBot) -> None:
    """With no rows, the strip renders no content and hides itself, taking no layout space.

    **Test steps:**

    * show a banner, then seed it with a row and verify it becomes visible
    * clear it with an empty row list and verify it reports not visible, with no labels left
    """
    banner = MessageBanner()
    qtbot.addWidget(banner)
    banner.show()
    qtbot.waitExposed(banner)
    banner.set_rows([row()])
    assert banner.isVisible() is True

    banner.set_rows([])

    assert banner.isVisible() is False
    assert banner.findChildren(QLabel) == []


# endregion


# region word-wrapping
def test_a_rows_message_word_wraps(qtbot: QtBot) -> None:
    """The message label word-wraps rather than forcing the strip wider.

    **Test steps:**

    * build a banner with one row
    * find its message label (the one showing the row's text) and verify word wrap is enabled
    """
    banner = MessageBanner()
    qtbot.addWidget(banner)

    banner.set_rows([row(text="A rather long notice that should wrap instead of widening the window")])

    labels = [label for label in banner.findChildren(QLabel) if label.text().startswith("A rather long")]
    assert len(labels) == 1
    assert labels[0].wordWrap() is True


# endregion
