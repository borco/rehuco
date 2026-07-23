"""A bounded rating slider value widget owning the None-mapping and echo guard ([[plugins#field-toolkit]])."""

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import QSlider, QWidget


class RatingSlider(QSlider):
    """A horizontal ``QSlider`` exposing the value-widget contract ([[plugins#field-toolkit]]): a
    ``value_changed`` signal and a ``set_value`` slot -- so the ``rating`` editor binds through
    :meth:`~rehuco_agent.fields.field.Field.bind_value_widget` like every other content field, and the
    None-mapping and echo guard live **here, once**, on a real widget slot instead of a field-level
    lambda.

    Being a bound-method slot is what makes it lifetime-safe: Qt drops a ``binding.changed`` connection
    to :meth:`set_value` when this slider is destroyed (a document-form rebuild on a type switch), where a
    lambda capturing the slider would dangle and fire into the deleted widget.

    A ``None`` rating (unrated, [[field-schema#deferred-items]]) displays the same as ``0`` -- a slider
    has no "no position", and ``0`` renders as no stars either way ([[plugins#field-toolkit]]).

    :param minimum: the slider's minimum value.
    :param maximum: the slider's maximum value.
    :param parent: optional Qt parent.
    """

    value_changed = Signal(object)

    def __init__(self, minimum: int, maximum: int, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(minimum, maximum)
        self.valueChanged.connect(self.value_changed.emit)

    def set_value(self, value: int | None) -> None:
        """Move the slider to ``value`` (``None`` shown as ``0``) without re-emitting ``value_changed``
        (the echo guard).

        :param value: the new rating, or ``None`` for unrated (shown as ``0``).
        """
        position = value if value is not None else 0
        if self.value() != position:
            with QSignalBlocker(self):
                self.setValue(position)
