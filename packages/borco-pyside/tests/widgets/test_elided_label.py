"""Tests for ElidedLabel: middle-eliding to fit width, optional hyperlink, tooltip-when-elided.

The offscreen test platform's font metrics are unreliable (a prior test loading application fonts
can leave the default font with zero-width metrics), so the tests that exercise *whether* text
elides mock ``QFontMetrics.elidedText`` -- Qt's measuring is Qt's job; what ElidedLabel adds is using
that result and surfacing the full text in a tooltip while shortened.
"""

from typing import Final

from borco_pyside.widgets import ElidedLabel
from PySide6.QtGui import QFontMetrics
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot

ELLIPSIS: Final = "…"
"""The Unicode horizontal ellipsis Qt inserts when it elides text."""

LONG_TEXT: Final = "a-really-quite-long-value-that-will-not-fit-in-a-narrow-label"


# region real-metric behavior (font-independent: a wide label never elides regardless of metrics)
def test_wide_label_shows_the_full_text(qtbot: QtBot) -> None:
    """Given ample width, the full text renders unchanged, with no tooltip.

    **Test steps:**

    * build a very wide label and set the value
    * verify the text is the full value and no ellipsis or tooltip is shown
    """
    label = ElidedLabel()
    qtbot.addWidget(label)
    label.setFixedWidth(4000)

    label.set_text(LONG_TEXT)

    assert label.text() == LONG_TEXT
    assert ELLIPSIS not in label.text()
    assert label.toolTip() == ""


def test_empty_text_clears_the_label_and_tooltip(qtbot: QtBot, mocker: MockerFixture) -> None:
    """An empty value renders nothing and no tooltip, even after a prior elided value.

    **Test steps:**

    * set a value that elides (leaving a tooltip), then set it empty
    * verify both the text and the tooltip are cleared
    """
    label = ElidedLabel()
    qtbot.addWidget(label)
    mocker.patch.object(QFontMetrics, "elidedText", return_value="a…z")
    label.set_text(LONG_TEXT)
    assert label.toolTip() == LONG_TEXT

    label.set_text("")

    assert label.text() == ""
    assert label.toolTip() == ""


def test_href_wraps_the_visible_text_in_a_link_to_the_full_target(qtbot: QtBot) -> None:
    """With a href, the visible text links to the full target.

    **Test steps:**

    * build a wide label and set a value with a href
    * verify the rendered markup is an anchor to the full href around the value
    """
    label = ElidedLabel()
    qtbot.addWidget(label)
    label.setFixedWidth(4000)

    label.set_text(LONG_TEXT, href="https://example.com/full/target")

    assert label.text() == f'<a href="https://example.com/full/target">{LONG_TEXT}</a>'


def test_href_escapes_html_special_characters(qtbot: QtBot) -> None:
    """HTML-special characters in the text/href are escaped, not injected as markup.

    **Test steps:**

    * build a wide label and set a value and href carrying ``<`` and ``"``
    * verify the special characters are escaped in the rendered markup
    """
    label = ElidedLabel()
    qtbot.addWidget(label)
    label.setFixedWidth(4000)

    label.set_text('a<b"c', href='https://example.com/?x="y"<z>')

    assert "&lt;" in label.text()
    assert "&quot;" in label.text()
    assert '<b"c' not in label.text()


def test_minimum_width_is_zero_so_it_never_forces_its_layout_wider(qtbot: QtBot) -> None:
    """The label reports a zero minimum width, so a long value can't impose a width floor.

    **Test steps:**

    * build a label with a long value
    * verify ``minimumSizeHint().width()`` is zero (height is left to the base ``QLabel``)
    """
    label = ElidedLabel()
    qtbot.addWidget(label)
    label.set_text(LONG_TEXT)

    assert label.minimumSizeHint().width() == 0


# endregion


# region elide/tooltip logic (mocked metrics)
def test_elided_result_is_shown_and_full_text_goes_to_the_tooltip(qtbot: QtBot, mocker: MockerFixture) -> None:
    """When Qt elides the text, the elided form is shown and the full text moves into the tooltip.

    **Test steps:**

    * mock ``elidedText`` to return a shortened form
    * set a value and verify the label shows the shortened form and tooltips the full value
    """
    label = ElidedLabel()
    qtbot.addWidget(label)
    mocker.patch.object(QFontMetrics, "elidedText", return_value="a…z")

    label.set_text("abcdef")

    assert label.text() == "a…z"
    assert label.toolTip() == "abcdef"


def test_no_tooltip_when_the_text_fits(qtbot: QtBot, mocker: MockerFixture) -> None:
    """When Qt returns the text unchanged (it fits), no tooltip is set.

    **Test steps:**

    * mock ``elidedText`` to return the text unchanged
    * set a value and verify the label shows it and has no tooltip
    """
    label = ElidedLabel()
    qtbot.addWidget(label)
    mocker.patch.object(QFontMetrics, "elidedText", return_value="abcdef")

    label.set_text("abcdef")

    assert label.text() == "abcdef"
    assert label.toolTip() == ""


def test_elides_against_the_current_width(qtbot: QtBot, mocker: MockerFixture) -> None:
    """``__render`` elides against the label's *current* width, re-rendering when it changes.

    **Test steps:**

    * mock ``elidedText`` to elide only below a threshold width
    * set the value while wide (full) then shrink and re-set, verifying it now elides
    """
    label = ElidedLabel()
    qtbot.addWidget(label)
    mocker.patch.object(QFontMetrics, "elidedText", side_effect=lambda *args: args[0] if args[2] >= 100 else "X…Y")

    label.setFixedWidth(200)
    label.set_text("hello")
    assert label.text() == "hello"

    label.setFixedWidth(50)
    label.set_text("hello")
    assert label.text() == "X…Y"


def test_resize_event_re_elides(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Shrinking a shown label re-elides on its resize event, without a fresh ``set_text``.

    **Test steps:**

    * mock ``elidedText`` to elide only below a threshold width
    * show a wide label with a value (full), then shrink it and wait for the resize to re-elide
    """
    label = ElidedLabel()
    qtbot.addWidget(label)
    mocker.patch.object(QFontMetrics, "elidedText", side_effect=lambda *args: args[0] if args[2] >= 100 else "X…Y")
    label.resize(200, 30)
    label.show()
    qtbot.waitExposed(label)
    label.set_text("hello")
    assert label.text() == "hello"

    label.setFixedWidth(50)

    qtbot.waitUntil(lambda: label.text() == "X…Y")


# endregion
