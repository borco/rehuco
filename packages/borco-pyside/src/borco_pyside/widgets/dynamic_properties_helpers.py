"""A generic helper for toggling a QSS-selector-driving dynamic property on any widget."""

from PySide6.QtWidgets import QWidget


def toggle_dynamic_property(widget: QWidget, name: str, value: bool) -> None:
    """Set a boolean dynamic property on ``widget`` and re-polish it, so a stylesheet selector like
    ``QLineEdit[name="true"]`` picks up the change -- a bare ``setProperty`` alone doesn't repaint.

    A no-op when ``value`` already matches the current property, avoiding a redundant repolish.

    :param widget: the widget to flag.
    :param name: the dynamic property's name.
    :param value: the property's new value.
    """
    if widget.property(name) != value:
        widget.setProperty(name, value)
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
