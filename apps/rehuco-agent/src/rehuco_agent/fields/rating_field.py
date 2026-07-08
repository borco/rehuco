"""The `rating` leaf field: a per-user integer rating, shown as stars and edited on a range slider
([[plugins#field-toolkit]]).
"""

from typing import Final, override

from borco_pyside.widgets import Rating
from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import QSlider, QWidget

from rehuco_agent.fields.colors import WARNING_COLOR
from rehuco_agent.fields.field import Field, FieldBinding

POSITIVE_STAR_GLYPH: Final = "\ue46a"
"""Phosphor's "star" icon codepoint for a positive rating: shared across every Phosphor weight
font, so :data:`POSITIVE_STYLESHEET`'s ``font-family`` (:data:`FILLED_STAR_FONT_FAMILY`) alone
renders it filled."""

NEGATIVE_STAR_GLYPH: Final = "\ue46a"
"""Phosphor's "star" icon codepoint for a negative rating: the same codepoint as
:data:`POSITIVE_STAR_GLYPH` -- :data:`NEGATIVE_STYLESHEET`'s ``font-family``
(:data:`OUTLINE_STAR_FONT_FAMILY`) is what renders it outlined instead."""

FILLED_STAR_FONT_FAMILY: Final = "Phosphor-Fill"
"""Font family for a positive rating's filled stars; registered app-wide at startup (``app.py``)."""

OUTLINE_STAR_FONT_FAMILY: Final = "Phosphor"
"""Font family for a negative rating's outline stars; registered app-wide at startup (``app.py``)."""

POSITIVE_STYLESHEET: Final = f'QLabel {{ font-family: "{FILLED_STAR_FONT_FAMILY}"; }}'
"""Stylesheet for the viewer's positive stars ([[plugins#field-toolkit]]): filled font, inherited color."""

NEGATIVE_STYLESHEET: Final = f'QLabel {{ font-family: "{OUTLINE_STAR_FONT_FAMILY}"; color: {WARNING_COLOR}; }}'
"""Stylesheet for the viewer's negative stars (§17.4): outline font, warning color."""


class RatingField(Field[int]):
    """A ``rating`` field ([[plugins#field-toolkit]], [[field-schema#field-types]]): a per-user integer that
    **may be negative**.

    The viewer is a :class:`~borco_pyside.widgets.Rating`: ``|value|`` stars, filled (default color) for a
    positive rating, outline and red for a negative one -- a single shared Phosphor star glyph with a
    font-family swap between the two states, rather than two separate icon assets. The editor is a bounded
    ``QSlider``, not a spin box -- ``rating`` is distinct from the plain ``int`` type
    ([[field-schema#field-types]]) and does not share :class:`~rehuco_agent.fields.int_field.IntField`'s
    widgets.

    :param name: the field's identifier on its model.
    :param label: display label; derived from ``name`` when omitted.
    :param minimum: the editor's minimum value; defaults to :attr:`RATING_MINIMUM`.
    :param maximum: the editor's maximum value; defaults to :attr:`RATING_MAXIMUM`.
    """

    TYPE = "rating"

    RATING_MINIMUM: Final = -5
    RATING_MAXIMUM: Final = 5

    def __init__(
        self,
        name: str,
        label: str | None = None,
        minimum: int = RATING_MINIMUM,
        maximum: int = RATING_MAXIMUM,
    ) -> None:
        super().__init__(name, label)
        self.__minimum = minimum
        self.__maximum = maximum

    @override
    def make_viewer(self, binding: FieldBinding[int]) -> QWidget:
        rating = Rating(
            positive_style=POSITIVE_STYLESHEET,
            positive_text=POSITIVE_STAR_GLYPH,
            negative_style=NEGATIVE_STYLESHEET,
            negative_text=NEGATIVE_STAR_GLYPH,
            value=binding.value,
        )
        binding.changed.connect(rating.set_value)  # type: ignore[attr-defined]
        return rating

    @override
    def make_editors(self, binding: FieldBinding[int]) -> list[QWidget]:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(self.__minimum, self.__maximum)
        slider.setValue(binding.value)
        slider.valueChanged.connect(binding.set_value)
        binding.changed.connect(lambda value: self.__echo(slider, value))
        return [slider]

    @staticmethod
    def __echo(slider: QSlider, value: int) -> None:
        """Update the editor from a binding change without re-emitting ``valueChanged`` (echo guard).

        :param slider: the editor to update.
        :param value: the new value.
        """
        if slider.value() != value:
            with QSignalBlocker(slider):
                slider.setValue(value)
