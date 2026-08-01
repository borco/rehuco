"""The measured-count editor: a stored-count spin box beside the count a measurement found, with the
explicit apply that moves one into the other ([[plugins#field-toolkit]], #198).
"""

# what is left in common with the other measure rows, now that all three share `MeasuredValueEdit`,
# is the constructor call naming that base's arguments -- which is the seam working, not a copy
# pylint: disable=duplicate-code

from typing import Final

from borco_pyside.widgets import UnboundedSpinBox
from PySide6.QtWidgets import QWidget

from .measured_value_edit import MeasuredValueEdit

COMPUTE_ICON_RESOURCE: Final = ":/icons/measure_image_count.svg"
"""The action that counts a reference-images resource's content images afresh."""

APPLY_TOOLTIP: Final = "Store the computed count"
"""Names the apply action; also how a test tells the row's two buttons apart, since both are icon-only."""

COMPUTE_TOOLTIP: Final = "Count the images inside this resource's archive(s)"
"""Names the compute action; see :data:`APPLY_TOOLTIP`."""

COMPUTED_TOOLTIP: Final = "The counted number of images"
"""What the readout beside the stored count shows."""


class ContentCountEdit(MeasuredValueEdit):
    """The ``[spin] [apply] [computed label] [compute]`` row: the **stored** count, editable, next to the
    count a measurement most recently found ([[data-model#image-meanings]], #198).

    A :class:`~rehuco_agent.fields.widgets.MeasuredValueEdit` over an
    `~borco_pyside.widgets.UnboundedSpinBox`, and the plainest of the three rows built on it: a count is
    already a human reading of itself, so it asks for no leading readout and the stored and computed
    figures take equal width.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        spin_box = UnboundedSpinBox(value=None)
        super().__init__(
            # the ignore is the one every value widget needs against a Protocol naming its members
            # statically: ``SimpleProperty`` is a *descriptor*, so a class-level ``value`` types as the
            # descriptor-or-value union rather than the value an instance exposes -- the same duality
            # ``bind_value_widget`` carries an ignore for
            spin_box,  # type: ignore[arg-type]
            set_editor_value=spin_box.setValue,
            compute_icon=COMPUTE_ICON_RESOURCE,
            compute_tooltip=COMPUTE_TOOLTIP,
            computed_tooltip=COMPUTED_TOOLTIP,
            apply_tooltip=APPLY_TOOLTIP,
            parent=parent,
        )
