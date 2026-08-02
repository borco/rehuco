"""The measured sizes on disk -- the original and the current -- filled by **one** scan
([[plugins#field-toolkit]], [[field-schema#duration-size]], #232).
"""

from collections.abc import Sequence
from typing import Final

import humanize
from borco_pyside.widgets import UnboundedSpinBox
from PySide6.QtWidgets import QWidget

from .shared_measurement_edit import SharedMeasurementEdit, SharedMeasurementRow

COMPUTE_ICON_RESOURCE: Final = ":/icons/measure_size_on_disk.svg"
"""The action that measures what the resource's content occupies on disk."""

COMPUTE_TOOLTIP: Final = "Measure this resource's content on disk"
"""Names the compute action; the button is icon-only."""

STORED_TOOLTIP: Final = "The stored size, human-readable"
"""What each row's leading readout shows -- that row's own bytes, read the way the viewer renders them."""

COMPUTED_TOOLTIP: Final = "The measured size, in bytes"
"""What the spanning readout shows, and why it is exact: it is compared against the spin boxes beside it,
digit for digit rather than through a rounded ``1.4G`` that two different sizes would share."""

SPIN_BOX_TOOLTIP: Final = "The stored size, in bytes"
"""What each row's spin box holds."""


class SizeMeasurementEdit(SharedMeasurementEdit):
    """The sizes' editor: one ``[human-readable] [spin] [copy]`` row per bound size, beside the one
    measurement that fills them all ([[field-schema#duration-size]], #232).

    A :class:`~rehuco_agent.fields.widgets.SharedMeasurementEdit` over one
    `~borco_pyside.widgets.UnboundedSpinBox` per row, which is what makes the bytes an unbounded Python
    ``int`` (#40) -- a single ~2 GB resource already sits at the C++ int32 ceiling. What the size rows add
    to the shared base is the leading human reading: unlike a count, a byte total is unreadable as itself,
    and unlike a duration, its editor carries no formatted half of its own.

    Built from **labels rather than a fixed count**, because how many rows there are is the document's
    answer, not this widget's: a type declaring only one of the two size names composes a coherent single
    row (:class:`~rehuco_agent.fields.size_pair_field.SizePairField`), and each label is what tells the
    otherwise identical copy buttons apart.

    :param row_labels: the bound sizes' display labels, top to bottom -- one row each.
    :param parent: optional Qt parent.
    """

    def __init__(self, row_labels: Sequence[str], parent: QWidget | None = None) -> None:
        super().__init__(
            [self.__make_row(label) for label in row_labels],
            compute_icon=COMPUTE_ICON_RESOURCE,
            compute_tooltip=COMPUTE_TOOLTIP,
            computed_tooltip=COMPUTED_TOOLTIP,
            # the two byte figures get twice the human reading's width -- it holds a handful of
            # characters (``1.4G``) where they carry ten digits or more
            editor_stretch=2,
            computed_stretch=2,
            parent=parent,
        )

    @staticmethod
    def format(size: int | None) -> str:
        """Render whole bytes as GNU ``ls -sh`` style text.

        :param size: the size in bytes, or ``None`` when unmeasured.
        :returns: the formatted string, e.g. ``"1.4G"``, ``"300B"``; ``""`` for ``None`` (unmeasured);
            ``"0B"`` -- honestly, not blank -- for a genuine ``0``.
        """
        if size is None:
            return ""
        return humanize.naturalsize(size, gnu=True)

    @staticmethod
    def __make_row(label: str) -> SharedMeasurementRow:
        """Build one size row: an unbounded byte spin box behind its human reading and its own copy.

        :param label: the bound size's display label, which names that row's copy action -- there is one
            per row and they are icon-only.
        :returns: the row, ready to be placed in the group's grid.
        """
        spin_box = UnboundedSpinBox(value=None, minimum=0)
        spin_box.setToolTip(SPIN_BOX_TOOLTIP)
        return SharedMeasurementRow(
            # the ignore is the one every value widget needs against a Protocol naming its members
            # statically: ``SimpleProperty`` is a *descriptor*, so a class-level ``value`` types as the
            # descriptor-or-value union rather than the value an instance exposes -- the same duality
            # ``bind_value_widget`` carries an ignore for
            spin_box,  # type: ignore[arg-type]
            set_editor_value=spin_box.setValue,
            copy_tooltip=f"Store the computed size in {label}",
            stored_format=SizeMeasurementEdit.format,
            stored_tooltip=STORED_TOOLTIP,
        )
