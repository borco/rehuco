"""Tests for MessageBanner: a strip of state notices, one row per still-active condition.

Rows carry no dismiss affordance (state, not a one-shot notification) and rebuild wholesale on every
``set_rows`` call, so what these tests exercise is: a row renders its severity's marker and its
message, a severity's style is overridable (icon or fallback glyph, accent color), an empty row list
shows nothing, multiple rows stack, and long text wraps rather than widening the strip.
"""

from collections.abc import Iterator

from borco_pyside.widgets import MessageBanner, MessageBannerRow, MessageBannerSeverity, MessageBannerSeverityStyle
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QLabel
from pytest import fixture
from pytestqt.qtbot import QtBot


def real_icon() -> QIcon:
    """A real, non-null ``QIcon`` -- a solid-colored pixmap, not backed by any file on disk."""
    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor("blue"))
    return QIcon(pixmap)


@fixture(autouse=True)
def restore_severity_styles() -> Iterator[None]:
    """Snapshot and restore ``MessageBanner.SEVERITY_STYLES`` around every test.

    It is a class-level (app-wide) override seam by design (:attr:`MessageBanner.SEVERITY_STYLES`'s
    own docstring) -- a test that reassigns an entry must not leak that style into every other test.
    """
    original = dict(MessageBanner.SEVERITY_STYLES)
    yield
    MessageBanner.SEVERITY_STYLES.clear()
    MessageBanner.SEVERITY_STYLES.update(original)


def row(text: str = "Something needs attention") -> MessageBannerRow:
    """A sample warning row, seeded with a sensible default message.

    :param text: the row's message.
    :returns: the built row.
    """
    return MessageBannerRow(MessageBannerSeverity.WARNING, text)


# region rendering a row
def test_a_row_renders_its_message(qtbot: QtBot) -> None:
    """A row shows its message text.

    **Test steps:**

    * build a banner with one row
    * verify a label shows the message
    """
    banner = MessageBanner()
    qtbot.addWidget(banner)

    banner.set_rows([row(text="Invalid field: title")])

    texts = {label.text() for label in banner.findChildren(QLabel)}
    assert "Invalid field: title" in texts


def test_an_unconfigured_severity_shows_the_default_style(qtbot: QtBot) -> None:
    """A severity with no ``SEVERITY_STYLES`` entry (the default, empty table) renders with the
    fallback style -- its margin color, and its fallback glyph since it carries no icon -- instead of
    crashing.

    **Test steps:**

    * build a banner with one row, without registering any ``SEVERITY_STYLES`` entry
    * verify a label shows the fallback glyph, colored in the default style's margin color
    """
    banner = MessageBanner()
    qtbot.addWidget(banner)

    banner.set_rows([row()])

    default_style = MessageBanner._MessageBanner__DEFAULT_STYLE  # type: ignore[attr-defined]  # pylint: disable=protected-access
    styled = [label for label in banner.findChildren(QLabel) if default_style.margin_color in label.styleSheet()]
    assert len(styled) == 1
    assert styled[0].text() != ""


def test_a_severitys_configured_icon_is_used_as_the_marker(qtbot: QtBot) -> None:
    """A severity style carrying an ``icon`` renders it as the row's marker (a pixmap), not the
    fallback glyph.

    **Test steps:**

    * override the warning severity's style with a real icon
    * build a banner with one row
    * verify the marker label carries a non-null pixmap and shows no fallback glyph text
    """
    MessageBanner.SEVERITY_STYLES[MessageBannerSeverity.WARNING] = MessageBannerSeverityStyle(  # pylint: disable=unsupported-assignment-operation
        margin_color="#123456", icon=real_icon()
    )
    banner = MessageBanner()
    qtbot.addWidget(banner)

    banner.set_rows([row()])

    message_label = next(label for label in banner.findChildren(QLabel) if label.text() == "Something needs attention")
    marker_label = next(label for label in banner.findChildren(QLabel) if label is not message_label)
    assert marker_label.text() == ""
    assert not marker_label.pixmap().isNull()


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
