"""A single-line text value widget owning the echo/cursor guard ([[plugins#field-toolkit]])."""

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import QLineEdit, QWidget


class LineEdit(QLineEdit):
    """A ``QLineEdit`` exposing the value-widget contract ([[plugins#field-toolkit]]): a ``value``
    property, a ``value_changed`` signal, and a ``set_value`` slot -- so the ``text`` field's editor
    binds through :meth:`~rehuco_agent.fields.field.Field.bind_value_widget` like every other content
    field, and the echo/cursor guard lives **here, once**, instead of being hand-wired per field (#35).

    ``value_changed`` fires on every user edit; :meth:`set_value` writes a new value in without
    re-emitting (a blocked ``setText``), so a bound model change echoes back without a feedback loop.
    The text-equality check in :meth:`set_value` is not an optimization: ``setText`` resets the cursor
    to the end even for identical text, so echoing the editor's own keystroke back into it unguarded
    would teleport the cursor on every mid-string edit (#35).

    :param parent: optional Qt parent.
    """

    value_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.textChanged.connect(self.value_changed.emit)

    @property
    def value(self) -> str:
        """The current text; the value-widget contract's getter ([[plugins#field-toolkit]])."""
        return self.text()

    @value.setter
    def value(self, value: str) -> None:
        self.set_value(value)

    def set_value(self, value: str) -> None:
        """Write ``value`` in without re-emitting ``value_changed`` (the echo/cursor guard).

        :param value: the new text.
        """
        if self.text() != value:
            with QSignalBlocker(self):
                self.setText(value)
