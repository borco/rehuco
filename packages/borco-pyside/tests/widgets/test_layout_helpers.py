"""Tests for layout_helpers: generic Qt layout helpers."""

from borco_pyside.widgets.layout_helpers import equal_height_column, equal_width_row
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget
from pytestqt.qtbot import QtBot


def test_equal_width_row_installs_a_zero_margin_layout(qtbot: QtBot) -> None:
    """The installed layout has no content margins.

    **Test steps:**

    * build two widgets and call ``equal_width_row``
    * verify the returned layout's margins are all zero
    """
    parent = QWidget()
    qtbot.addWidget(parent)
    first, second = QWidget(parent), QWidget(parent)

    layout = equal_width_row(parent, first, second)

    assert layout.contentsMargins().left() == 0
    assert layout.contentsMargins().right() == 0
    assert layout.contentsMargins().top() == 0
    assert layout.contentsMargins().bottom() == 0


def test_equal_width_row_adds_every_widget_with_equal_stretch(qtbot: QtBot) -> None:
    """Every widget is added to the layout with an equal (1) stretch factor.

    **Test steps:**

    * build three widgets and call ``equal_width_row``
    * verify the layout holds all three, each with stretch 1
    """
    parent = QWidget()
    qtbot.addWidget(parent)
    widgets = [QWidget(parent), QWidget(parent), QWidget(parent)]

    layout = equal_width_row(parent, *widgets)

    assert layout.count() == 3
    for index in range(3):
        assert layout.stretch(index) == 1


def test_equal_width_row_ignores_each_widgets_own_size_hint(qtbot: QtBot) -> None:
    """Every widget's horizontal size policy is set to ``Ignored``, so the layout's stretch factors
    alone govern the split rather than each widget's own (possibly oversized) ``sizeHint``.

    **Test steps:**

    * build two widgets and call ``equal_width_row``
    * verify both widgets' horizontal size policy is ``Ignored``
    """
    parent = QWidget()
    qtbot.addWidget(parent)
    first, second = QWidget(parent), QWidget(parent)

    equal_width_row(parent, first, second)

    assert first.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored
    assert second.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored


def test_equal_height_column_installs_a_zero_margin_zero_spacing_layout(qtbot: QtBot) -> None:
    """The installed layout has neither content margins nor spacing -- the bands it makes are what a
    second column beside it has to match, and a margin either side would not be in that second column.

    **Test steps:**

    * build two widgets and call ``equal_height_column``
    * verify the returned layout's margins and spacing are all zero
    """
    parent = QWidget()
    qtbot.addWidget(parent)
    first, second = QWidget(parent), QWidget(parent)

    layout = equal_height_column(parent, first, second)

    assert layout.contentsMargins().left() == 0
    assert layout.contentsMargins().right() == 0
    assert layout.contentsMargins().top() == 0
    assert layout.contentsMargins().bottom() == 0
    assert layout.spacing() == 0


def test_equal_height_column_adds_every_widget_with_equal_stretch(qtbot: QtBot) -> None:
    """Every widget is added with an equal (1) stretch factor -- which is what splits the column's height
    into equal bands.

    **Test steps:**

    * build three widgets and call ``equal_height_column``
    * verify the layout holds all three, each with stretch 1
    """
    parent = QWidget()
    qtbot.addWidget(parent)
    widgets = [QWidget(parent), QWidget(parent), QWidget(parent)]

    layout = equal_height_column(parent, *widgets)

    assert layout.count() == 3
    for index in range(3):
        assert layout.stretch(index) == 1


def test_equal_height_column_splits_the_height_into_equal_bands(qtbot: QtBot) -> None:
    """Given a height, the column hands each widget the same share of it -- the property the whole helper
    exists for, since two columns laid out this way then agree band for band.

    **Test steps:**

    * stack two labels in a column and give the parent a height neither would ask for
    * verify both ended up the same height, together filling it
    """
    parent = QWidget()
    qtbot.addWidget(parent)
    first, second = QLabel("first", parent), QLabel("second", parent)
    equal_height_column(parent, first, second)

    parent.resize(200, 120)
    parent.show()
    qtbot.waitExposed(parent)

    assert first.height() == second.height()
    assert first.height() + second.height() == parent.height()


def test_equal_height_column_keeps_each_widgets_own_height_hint(qtbot: QtBot) -> None:
    """The column still asks for the height its contents need, unlike its horizontal twin: zeroing the
    size hint vertically would let a form row holding nothing but this column collapse to nothing.

    **Test steps:**

    * stack two labels in a column
    * verify neither widget's vertical policy was set to ``Ignored``, and the column's own size hint is
      at least both labels together
    """
    parent = QWidget()
    qtbot.addWidget(parent)
    first, second = QLabel("first", parent), QLabel("second", parent)

    equal_height_column(parent, first, second)

    assert first.sizePolicy().verticalPolicy() != QSizePolicy.Policy.Ignored
    assert second.sizePolicy().verticalPolicy() != QSizePolicy.Policy.Ignored
    assert parent.sizeHint().height() >= first.sizeHint().height() + second.sizeHint().height()
