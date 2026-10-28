"""Tests for ElidedRadioButton: middle-eliding its caption to fit, and the full caption as a tooltip while shortened.

As for ``test_elided_label.py``, the tests that exercise *whether* the caption elides mock
``QFontMetrics.elidedText``: the offscreen platform's font metrics are unreliable, and measuring is Qt's job.
"""

from typing import Final

from borco_pyside.widgets import ElidedRadioButton
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QSizePolicy
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot

LONG_TEXT: Final = r"C:\Users\someone\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg\bin (9.0.2, usable)"
PATH: Final = r"C:\Users\someone\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg\bin"
SUFFIX: Final = " (9.0.2, usable)"


def test_a_wide_button_shows_the_full_caption(qtbot: QtBot) -> None:
    """Given ample width, the caption shows unchanged, with no tooltip.

    **Test steps:**

    * build a very wide button and set a long caption
    * verify the caption is whole and there is no tooltip
    """
    button = ElidedRadioButton()
    qtbot.addWidget(button)
    button.setFixedWidth(4000)

    button.set_text(LONG_TEXT)

    assert button.text() == LONG_TEXT
    assert button.full_text() == LONG_TEXT
    assert button.toolTip() == ""


def test_a_shortened_caption_keeps_the_full_one_as_its_tooltip(qtbot: QtBot, mocker: MockerFixture) -> None:
    """What the button shows is Qt's middle elision; the whole caption is a hover away.

    **Test steps:**

    * make the metrics elide, and set a long caption
    * verify the shown caption is the elided one, elided in the middle, and the tooltip is the full caption
    """
    elided = mocker.patch.object(QFontMetrics, "elidedText", return_value="C:\\Users…(9.0.2, usable)")
    button = ElidedRadioButton()
    qtbot.addWidget(button)

    button.set_text(LONG_TEXT)

    assert button.text() == "C:\\Users…(9.0.2, usable)"
    assert button.toolTip() == LONG_TEXT
    assert button.full_text() == LONG_TEXT
    assert elided.call_args.args[1] == Qt.TextElideMode.ElideMiddle


def test_resizing_elides_again(qtbot: QtBot, mocker: MockerFixture) -> None:
    """The caption follows the width the layout gives.

    **Test steps:**

    * set a caption, then make the metrics elide and resize the button
    * verify the shown caption is now the elided one
    """
    button = ElidedRadioButton()
    qtbot.addWidget(button)
    button.set_text(LONG_TEXT)
    mocker.patch.object(QFontMetrics, "elidedText", return_value="short…")

    button.resize(50, button.height())
    button.show()
    qtbot.waitExposed(button)

    assert button.text() == "short…"


def test_a_long_caption_never_makes_the_button_ask_for_width(qtbot: QtBot) -> None:
    """The layout decides the width, so a page of long paths does not scroll sideways.

    **Test steps:**

    * set a long caption
    * verify the horizontal size policy is ``Ignored`` and the minimum width is far below the caption's
    """
    button = ElidedRadioButton()
    qtbot.addWidget(button)

    button.set_text(LONG_TEXT)

    assert button.sizePolicy().horizontalPolicy() is QSizePolicy.Policy.Ignored
    assert button.minimumSizeHint().width() < 100


def test_the_suffix_is_never_elided(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A version after a path stays whole: only the text before it shortens.

    **Test steps:**

    * make the metrics elide, and set a path with a version suffix
    * verify only the path was handed to the eliding, the suffix follows it whole, and the tooltip is both
    """
    elided = mocker.patch.object(QFontMetrics, "elidedText", return_value="ELIDED")
    button = ElidedRadioButton()
    qtbot.addWidget(button)

    button.set_text(PATH, SUFFIX)

    assert elided.call_args.args[0] == PATH
    assert button.text() == "ELIDED" + SUFFIX
    assert button.full_text() == PATH + SUFFIX
    assert button.toolTip() == PATH + SUFFIX


def test_the_suffix_takes_its_width_before_the_text_is_fitted(qtbot: QtBot, mocker: MockerFixture) -> None:
    """The room left for the path is what the suffix leaves, so the two together fit.

    **Test steps:**

    * record the width the eliding is offered, and set a path with and without a suffix at one width
    * verify the width offered to the path shrank by the suffix's own
    """
    elided = mocker.patch.object(QFontMetrics, "elidedText", side_effect=lambda text, _mode, _width: text)
    button = ElidedRadioButton()
    qtbot.addWidget(button)
    button.setFixedWidth(400)

    button.set_text(PATH)
    without_suffix = elided.call_args.args[2]
    button.set_text(PATH, SUFFIX)
    with_suffix = elided.call_args.args[2]

    assert without_suffix - with_suffix == button.fontMetrics().horizontalAdvance(SUFFIX)
