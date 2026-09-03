"""Tests for WrappingLabel: wrapped-height size hints, and the resize that re-advertises them.

The offscreen platform wraps text for real, so these assert on relative growth (a narrower label is
taller) rather than exact pixel counts, which depend on the platform font.
"""

from borco_pyside.widgets import WrappingLabel
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot

PARAGRAPH = (
    "Matched against the file name only, so a pattern can never exclude a whole folder. An empty "
    "list falls back to the shipped patterns, and sizes already computed are not recalculated."
)
"""Long enough to wrap several times at any reasonable label width."""


def test_word_wrap_is_on_without_being_asked_for(qtbot: QtBot) -> None:
    """The widget exists to wrap, so it turns wrapping on itself.

    **Test steps:**

    * build a label
    * verify word wrap is enabled and it advertises height-for-width
    """
    label = WrappingLabel()
    qtbot.addWidget(label)

    assert label.wordWrap() is True
    assert label.hasHeightForWidth() is True


def test_size_hint_reports_the_wrapped_height_not_the_one_line_one(qtbot: QtBot) -> None:
    """The hint answers with the height the text needs at the label's width (#229).

    Guards the defect this widget was written for: a plain wrapping `QLabel` hints as though its text
    were one wide line, and a frame sized from that hint is a line tall while the text is a paragraph.

    **Test steps:**

    * set a paragraph on a label narrow enough to wrap it several times
    * verify its size-hint height is the wrapped height, past the one-line height it would have at a
      width nothing wraps at
    """
    label = WrappingLabel()
    qtbot.addWidget(label)
    label.setText(PARAGRAPH)
    label.resize(200, 10)

    assert label.sizeHint().height() == label.heightForWidth(200)
    assert label.sizeHint().height() > label.heightForWidth(100_000)


def test_narrowing_the_label_makes_it_report_a_taller_height(qtbot: QtBot) -> None:
    """The reported height folds on width, and is re-advertised as the width changes.

    **Test steps:**

    * show a wide label over a paragraph and read its size-hint height
    * narrow it and read the height again
    * verify the narrower label reports the taller height
    """
    label = WrappingLabel()
    qtbot.addWidget(label)
    label.setText(PARAGRAPH)
    label.resize(600, 10)
    label.show()
    qtbot.waitExposed(label)
    wide = label.sizeHint().height()

    label.resize(200, 10)

    assert label.sizeHint().height() > wide


def test_a_height_only_resize_does_not_re_advertise_the_geometry(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A resize leaving the width alone cannot have changed the wrapping, so it re-advertises nothing.

    Guards against a runaway relayout: the height a resize hands out is this label's own hint being
    applied, so answering it with another ``updateGeometry()`` would ask to be resized again forever.

    **Test steps:**

    * show a label over a paragraph, then resize it with the same width but a different height
    * verify it did not re-advertise its geometry
    """
    label = WrappingLabel()
    qtbot.addWidget(label)
    label.setText(PARAGRAPH)
    label.resize(300, 40)
    label.show()
    qtbot.waitExposed(label)
    update_geometry = mocker.spy(label, "updateGeometry")

    label.resize(300, 200)

    update_geometry.assert_not_called()


def test_a_widthless_label_falls_back_to_the_plain_hint(qtbot: QtBot) -> None:
    """A label with no width to wrap to is measured before it is laid out, and must not answer with
    the one-word-per-line height that wrapping at zero produces.

    **Test steps:**

    * set a paragraph on a label pinned to zero width
    * verify its hints match `QLabel`'s own, rather than growing without bound
    """
    label = WrappingLabel()
    qtbot.addWidget(label)
    label.setText(PARAGRAPH)

    label.resize(0, 0)

    assert label.sizeHint().height() == QLabel.sizeHint(label).height()
    assert label.sizeHint().height() < label.heightForWidth(1)


def test_minimum_size_hint_width_is_zero_so_long_words_wrap(qtbot: QtBot) -> None:
    """The minimum width is zero, so a long word can never force the label (or its layout) wider.

    **Test steps:**

    * set a single unbreakable word on a label
    * verify its minimum size-hint width is zero
    """
    label = WrappingLabel()
    qtbot.addWidget(label)
    label.setText("a" * 200)

    assert label.minimumSizeHint().width() == 0


def test_an_enclosing_frame_is_tall_enough_for_the_wrapped_text(qtbot: QtBot) -> None:
    """The corrected hint reaches the frame around the label, which is the point of correcting it.

    Guards what a size policy alone did not do: a frame allocates from its layout's ``sizeHint``
    before it consults ``heightForWidth``, so a label hinting one line left the paragraph painting
    past the frame's border.

    **Test steps:**

    * put a paragraph label inside a framed column and show it at a range of widths
    * verify at every width that the label is at least as tall as its text needs
    """
    host = QWidget()
    qtbot.addWidget(host)
    host_layout = QVBoxLayout(host)
    host_layout.setContentsMargins(0, 0, 0, 0)
    frame = QFrame(host)
    frame.setFrameShape(QFrame.Shape.StyledPanel)
    label = WrappingLabel(frame)
    label.setText(PARAGRAPH)
    QVBoxLayout(frame).addWidget(label)
    host_layout.addWidget(frame)
    host_layout.addStretch(1)
    host.show()
    qtbot.waitExposed(host)

    for width in (320, 900, 420, 640, 320):
        host.setGeometry(0, 0, width, 700)
        host_layout.activate()
        assert label.height() >= label.heightForWidth(label.width()), f"clipped at host width {width}"
