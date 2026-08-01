"""The measured-duration editor: a stored-seconds `DurationEdit` beside the duration a scan found, with
the explicit apply that moves one into the other ([[plugins#field-toolkit]], #224).
"""

from typing import Final

from PySide6.QtWidgets import QWidget

from .duration_edit import DurationEdit
from .measured_value_edit import MeasuredValueEdit

COMPUTE_ICON_RESOURCE: Final = ":/icons/measure_duration.svg"
"""The action that sums how long this resource's videos run."""

APPLY_TOOLTIP: Final = "Store the computed duration"
"""Names the apply action; also how a test tells the row's two buttons apart, since both are icon-only."""

COMPUTE_TOOLTIP: Final = "Measure how long this resource's videos run"
"""Names the compute action; see :data:`APPLY_TOOLTIP`."""

COMPUTED_TOOLTIP: Final = "The measured duration, in seconds"
"""What the trailing readout shows, and why it is exact: it is compared against the seconds spin box
beside it, digit for digit rather than through a coarse ``2h 15m`` that a range of durations would
share."""


class MeasuredDurationEdit(MeasuredValueEdit):
    """The ``[human-readable] [seconds] [apply] [computed] [compute]`` row: the **stored** duration in
    whole seconds, editable, beside the duration a scan most recently found
    ([[field-schema#duration-size]], #224).

    A :class:`~rehuco_agent.fields.widgets.MeasuredValueEdit` over a
    :class:`~rehuco_agent.fields.widgets.DurationEdit`, which is the whole of the leading half: that
    widget already pairs a human ``1h 30m`` reading with the raw seconds, and both are *editable* --
    where the size row's leading reading is a readout, this one is the same second editor the field has
    always had, unchanged. So the row shows what the issue's sketch asks for without a fourth widget:
    the human reading, the stored seconds, and the measurement beside them.

    That also means the ms-vs-seconds rules hold unchanged ([[field-schema#ms-leak-history]]): the
    formatted string stays output-only, the stored number is never re-derived from it, and the total this
    row is handed was rounded once, at the end of the scan that produced it.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        duration_edit = DurationEdit()
        super().__init__(
            # the ignore is the one every value widget needs against a Protocol naming its members
            # statically: ``SimpleProperty`` is a *descriptor*, so a class-level ``value`` types as the
            # descriptor-or-value union rather than the value an instance exposes -- the same duality
            # ``bind_value_widget`` carries an ignore for
            duration_edit,  # type: ignore[arg-type]
            # set_value is the slot ``SimpleProperty`` synthesizes, which pyright cannot see
            set_editor_value=duration_edit.set_value,  # type: ignore[attr-defined]
            compute_icon=COMPUTE_ICON_RESOURCE,
            compute_tooltip=COMPUTE_TOOLTIP,
            computed_tooltip=COMPUTED_TOOLTIP,
            apply_tooltip=APPLY_TOOLTIP,
            # the editor holds two equal halves of its own -- the human reading and the seconds -- so
            # four parts against the readout's two leaves the three figures on this row the same width
            # each, matching the size row beside it on a form showing both
            editor_stretch=4,
            computed_stretch=2,
            parent=parent,
        )
