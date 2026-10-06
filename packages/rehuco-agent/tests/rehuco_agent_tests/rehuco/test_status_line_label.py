"""Tests for :class:`~rehuco_agent.rehuco.status_line_label.StatusLineLabel`."""

from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.status_line_label import PARTS_SEPARATOR, StatusLineLabel

PRIMARY = "1,240 resources / 188 legacy .tc / 1.2T"
SECONDARY = "3 selected / 4.1G / 120 images"


def sized(qtbot: QtBot, width: int) -> StatusLineLabel:
    """A label with the two parts, ``width`` pixels wide."""
    label = StatusLineLabel()
    qtbot.addWidget(label)
    label.show()  # an unshown widget is not told it was resized
    label.resize(width, 20)
    label.set_parts(PRIMARY, SECONDARY)
    return label


def test_a_wide_label_shows_both_parts_in_full(qtbot: QtBot) -> None:
    """Nothing elides while the line fits.

    **Test steps:**

    * set both parts on a wide label
    * verify the text is the whole line and the tooltip says the same
    """
    label = sized(qtbot, 2000)

    assert label.text() == f"{PRIMARY}{PARTS_SEPARATOR}{SECONDARY}" == label.full_text
    assert label.toolTip() == label.full_text


def test_no_secondary_part_shows_no_separator(qtbot: QtBot) -> None:
    """The line is the primary part alone.

    **Test steps:**

    * set only a primary part
    * verify the text has no separator
    """
    label = sized(qtbot, 2000)
    label.set_parts(PRIMARY)

    assert label.text() == PRIMARY


def test_the_secondary_part_elides_before_the_primary_one(qtbot: QtBot) -> None:
    """A narrow label keeps the totals whole and shortens the selection, with the whole line as its tooltip.

    **Test steps:**

    * size a label to the primary part and some of the secondary one
    * verify the text starts with the whole primary part, ends in an ellipsis, and the tooltip is the full line
    """
    label = sized(qtbot, 2000)
    advance = label.fontMetrics().horizontalAdvance
    label.resize(advance(PRIMARY + PARTS_SEPARATOR) + advance(SECONDARY) // 2, 20)

    assert label.text().startswith(PRIMARY + PARTS_SEPARATOR)
    assert label.text().endswith("…")
    assert label.text() != label.full_text
    assert label.toolTip() == label.full_text


def test_the_primary_part_elides_only_once_the_secondary_one_has_gone(qtbot: QtBot) -> None:
    """A label narrower than the totals drops the selection and shortens the totals at their end.

    **Test steps:**

    * size a label to half the primary part
    * verify the text is an elided prefix of the primary part with no separator
    """
    label = sized(qtbot, 2000)
    label.resize(label.fontMetrics().horizontalAdvance(PRIMARY) // 2, 20)

    assert label.text().endswith("…")
    assert label.text()[:-1] == PRIMARY[: len(label.text()) - 1]
    assert PARTS_SEPARATOR not in label.text()
    assert label.toolTip() == label.full_text


def test_an_empty_label_has_no_tooltip(qtbot: QtBot) -> None:
    """Nothing to say, nothing to explain.

    **Test steps:**

    * set empty parts
    * verify empty text and tooltip
    """
    label = sized(qtbot, 200)
    label.set_parts("")

    assert (label.text(), label.toolTip()) == ("", "")


def test_a_bigger_font_elides_the_line_again(qtbot: QtBot) -> None:
    """The line is fitted to the font it is drawn in, so a font change re-elides it.

    **Test steps:**

    * size a label to just hold the whole line
    * enlarge its font until even the primary part is wider than the label, and verify the line is elided
    """
    label = sized(qtbot, 2000)
    label.resize(label.fontMetrics().horizontalAdvance(label.full_text) + 4, 20)
    assert label.text() == label.full_text

    # four times the size, not two: text does not scale linearly (hinting), and on macOS a doubled font leaves the
    # primary part alone still fitting, which is then shown whole -- correctly, and not what this test is about
    font = label.font()
    font.setPointSizeF(font.pointSizeF() * 4)
    label.setFont(font)
    assert label.fontMetrics().horizontalAdvance(PRIMARY) > label.width()

    assert label.text().endswith("…")
