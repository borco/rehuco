"""Tests for FlowLayout: item bookkeeping, size hints, and row-wrapping geometry."""

from borco_pyside.widgets import FlowLayout
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy, QSpacerItem, QWidget
from pytestqt.qtbot import QtBot


def test_flow_layout_tracks_added_items(qtbot: QtBot) -> None:
    """`addWidget` (routed through `QLayout` to `addItem`) is reflected by `count`/`itemAt`.

    **Test steps:**

    * build a container with a `FlowLayout` and add three widgets
    * verify `count` and `itemAt` reflect all three, in order
    """
    container = QWidget()
    qtbot.addWidget(container)
    layout = FlowLayout(container)
    widgets = [QWidget(container), QWidget(container), QWidget(container)]
    for widget in widgets:
        layout.addWidget(widget)

    assert layout.count() == 3
    for index, widget in enumerate(widgets):
        item = layout.itemAt(index)
        assert item is not None
        assert item.widget() is widget
    assert layout.itemAt(3) is None


def test_flow_layout_take_at_removes_and_returns_the_item(qtbot: QtBot) -> None:
    """`takeAt` removes an item from the layout and returns it; an out-of-range index returns `None`.

    **Test steps:**

    * build a `FlowLayout` with two widgets
    * take the first item and verify it holds the first widget and `count` drops to one
    * verify a further out-of-range `takeAt` returns `None`
    """
    container = QWidget()
    qtbot.addWidget(container)
    layout = FlowLayout(container)
    first, second = QWidget(container), QWidget(container)
    layout.addWidget(first)
    layout.addWidget(second)

    taken = layout.takeAt(0)

    assert taken is not None
    assert taken.widget() is first
    assert layout.count() == 1
    remaining = layout.itemAt(0)
    assert remaining is not None
    assert remaining.widget() is second
    assert layout.takeAt(5) is None


def test_flow_layout_expands_horizontally_and_has_height_for_width() -> None:
    """The layout only expands horizontally and opts into height-for-width geometry.

    **Test steps:**

    * build a bare `FlowLayout`
    * verify `expandingDirections` is horizontal-only and `hasHeightForWidth` is true
    """
    layout = FlowLayout()

    assert layout.expandingDirections() == Qt.Orientation.Horizontal
    assert layout.hasHeightForWidth() is True


def test_flow_layout_wraps_widgets_to_a_new_row_when_width_is_exceeded(qtbot: QtBot) -> None:
    """A widget that would overflow the available width starts a new row below the first.

    **Test steps:**

    * build a container narrow enough to fit only one fixed-size widget per row
    * add two such widgets and force the layout to run
    * verify the second widget's geometry sits on a lower row than the first
    """
    container = QWidget()
    qtbot.addWidget(container)
    layout = FlowLayout(container)
    first, second = QWidget(container), QWidget(container)
    for widget in (first, second):
        widget.setFixedSize(80, 20)
        policy = widget.sizePolicy()
        policy.setControlType(QSizePolicy.ControlType.PushButton)
        widget.setSizePolicy(policy)
        layout.addWidget(widget)

    container.resize(100, 200)
    container.show()
    qtbot.waitExposed(container)

    assert first.geometry().y() < second.geometry().y()
    assert first.geometry().x() == second.geometry().x()


def test_flow_layout_minimum_size_covers_its_widest_item_plus_margins(qtbot: QtBot) -> None:
    """`minimumSize` expands to the widest/tallest item's own minimum size, plus content margins.

    **Test steps:**

    * build a `FlowLayout` on a parent (so it gets zero margins) with one fixed-size widget
    * verify `minimumSize` matches that widget's size exactly (zero margins add nothing)
    """
    container = QWidget()
    qtbot.addWidget(container)
    layout = FlowLayout(container)
    widget = QWidget(container)
    widget.setMinimumSize(42, 24)
    layout.addWidget(widget)

    size = layout.minimumSize()

    assert size.width() == 42
    assert size.height() == 24


def test_flow_layout_size_hint_and_height_for_width_match_minimum_size(qtbot: QtBot) -> None:
    """`sizeHint`/`heightForWidth` are computed the same way as `minimumSize`, since a `FlowLayout`
    always wraps down to its widest single item at any width.

    **Test steps:**

    * build a `FlowLayout` with one fixed-size widget
    * verify `sizeHint` matches `minimumSize`, and `heightForWidth` matches its height
    """
    container = QWidget()
    qtbot.addWidget(container)
    layout = FlowLayout(container)
    widget = QWidget(container)
    widget.setFixedSize(42, 24)
    layout.addWidget(widget)

    assert layout.sizeHint() == layout.minimumSize()
    assert layout.heightForWidth(200) == layout.minimumSize().height()


def test_flow_layout_tolerates_a_non_widget_item(qtbot: QtBot) -> None:
    """A non-widget item (e.g. a spacer added via `addItem` directly) doesn't crash layout geometry.

    **Test steps:**

    * build a `FlowLayout` with a widget and a spacer item
    * force the layout to run
    * verify it completes without error and still reports a positive height
    """
    container = QWidget()
    qtbot.addWidget(container)
    layout = FlowLayout(container)
    widget = QWidget(container)
    widget.setFixedSize(80, 20)
    layout.addWidget(widget)
    layout.addItem(QSpacerItem(20, 20))

    container.resize(200, 100)
    container.show()
    qtbot.waitExposed(container)

    assert layout.count() == 2
    assert layout.heightForWidth(200) > 0
