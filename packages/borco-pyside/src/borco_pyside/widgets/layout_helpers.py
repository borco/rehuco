"""Generic Qt layout helpers, independent of any particular widget's purpose."""

from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget


def equal_width_row(parent: QWidget, *widgets: QWidget) -> QHBoxLayout:
    """Lay ``widgets`` out left to right, zero-margin, split evenly regardless of each widget's own
    ``sizeHint`` -- a stretch factor alone only governs space *above* each widget's own minimum, so a
    widget like ``QSpinBox`` (sized to fit its widest possible digit count) would otherwise starve its
    neighbor of most of the row's width (confirmed empirically).

    :param parent: the widget to install this layout on.
    :param widgets: the widgets to lay out, evenly split.
    :returns: the installed layout.
    """
    layout = QHBoxLayout(parent)
    layout.setContentsMargins(0, 0, 0, 0)
    for widget in widgets:
        policy = widget.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        widget.setSizePolicy(policy)
        layout.addWidget(widget, 1)
    return layout
