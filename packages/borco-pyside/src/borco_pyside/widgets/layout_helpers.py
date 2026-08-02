"""Generic Qt layout helpers, independent of any particular widget's purpose."""

from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget


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


def equal_height_column(parent: QWidget, *widgets: QWidget) -> QVBoxLayout:
    """Stack ``widgets`` top to bottom, zero-margin and zero-spacing, each taking the same share of
    whatever height the column is given -- so a column stacked this way lines up, band for band, with a
    second one laid out the same way beside it.

    That is the whole point: a stacked label column beside a multi-row editor grid cannot be aligned by
    matching heights (a 20 px label against a 28 px editor row), but it does not have to be. Both
    containers sit in the same cell row of an outer grid, so both are handed the *same* height; an equal
    stretch on homogeneous items splits that height into equal bands regardless of what each item's own
    ``sizeHint`` is, so band *i* on one side is band *i* on the other. Homogeneous is the condition --
    within a column, not across the two.

    Unlike its horizontal twin :func:`equal_width_row`, this does **not** set
    ``QSizePolicy.Policy.Ignored`` on the items. That trick zeroes the item's ``sizeHint`` in the
    governed direction, which is harmless across a row whose width the parent dictates anyway; done
    vertically it would leave the column with no height to ask for, and a form row holding nothing but
    this column would collapse to nothing.

    :param parent: the widget to install this layout on.
    :param widgets: the widgets to stack, each taking an equal band.
    :returns: the installed layout.
    """
    layout = QVBoxLayout(parent)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    for widget in widgets:
        layout.addWidget(widget, 1)
    return layout
