"""Tests for layout_helpers: generic Qt layout helpers."""

from borco_pyside.widgets.layout_helpers import equal_width_row
from PySide6.QtWidgets import QSizePolicy, QWidget
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
