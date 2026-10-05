"""Tests for :class:`~rehuco_agent.rehuco.scaled_image.ScaledImage` (#378)."""

from PySide6.QtGui import QImage
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.scaled_image import ScaledImage


def picture(width: int, height: int) -> QImage:
    """A blank picture.

    :param width: its width.
    :param height: its height.
    :returns: the image.
    """
    return QImage(width, height, QImage.Format.Format_RGB32)


def test_with_no_image_it_takes_no_height_and_no_width(qtbot: QtBot) -> None:
    """Nothing shown costs nothing: the layout around it gives it no room.

    **Test steps:**

    * ask an empty widget for its sizes, and give it a null image
    * verify no height at any width, and no minimum
    """
    widget = ScaledImage()
    qtbot.addWidget(widget)

    widget.set_image(QImage())

    assert widget.image is None
    assert widget.heightForWidth(300) == 0
    assert widget.minimumSizeHint().width() == 0
    assert widget.drawn_size().isEmpty()


def test_the_height_keeps_the_proportions_at_the_width_given(qtbot: QtBot) -> None:
    """A picture is drawn at the width the layout gives, as long as that is not more than the picture has.

    **Test steps:**

    * show a 600 by 400 picture and ask for the height at narrower and wider widths
    * verify the proportions are kept, and a width past the picture's own adds nothing
    """
    widget = ScaledImage()
    qtbot.addWidget(widget)
    widget.set_image(picture(600, 400))

    assert widget.heightForWidth(300) == 200
    assert widget.heightForWidth(150) == 100
    assert widget.heightForWidth(2000) == 400


def test_it_never_asks_for_width(qtbot: QtBot) -> None:
    """The width comes from the layout, however large the picture: the hint and the minimum are zero wide.

    **Test steps:**

    * show a very wide picture
    * verify the size hint and minimum size hint ask for no width
    """
    widget = ScaledImage()
    qtbot.addWidget(widget)

    widget.set_image(picture(5000, 100))

    assert widget.sizeHint().width() == 0
    assert widget.minimumSizeHint().width() == 0


def test_it_draws_no_wider_than_itself_or_than_the_picture(qtbot: QtBot) -> None:
    """Narrow, it shrinks the picture; wide, it does not stretch it.

    **Test steps:**

    * show a 120 by 80 picture at 60 and at 400 pixels wide
    * verify the drawn width and height each time
    """
    widget = ScaledImage()
    qtbot.addWidget(widget)
    widget.set_image(picture(120, 80))

    widget.resize(60, 200)
    assert (widget.drawn_size().width(), widget.drawn_size().height()) == (60, 40)
    widget.resize(400, 200)
    assert (widget.drawn_size().width(), widget.drawn_size().height()) == (120, 80)


def test_painting_draws_the_picture_and_nothing_when_empty(qtbot: QtBot) -> None:
    """The paint path runs for both states without error.

    **Test steps:**

    * grab the widget with a picture, then without
    * verify the first has pixels of the picture's colour and the second does not
    """
    widget = ScaledImage()
    qtbot.addWidget(widget)
    image = picture(40, 40)
    image.fill(0xFF112233)
    widget.set_image(image)
    widget.resize(40, 40)

    painted = widget.grab().toImage()
    assert painted.pixel(20, 20) & 0xFFFFFF == 0x112233

    widget.set_image(None)
    assert widget.grab().toImage().pixel(20, 20) & 0xFFFFFF != 0x112233
