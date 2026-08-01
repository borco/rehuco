"""The measured-size editor: a stored-bytes spin box between its human reading and the size a scan
found, with the explicit apply that moves one into the other ([[plugins#field-toolkit]], #223).
"""

# what is left in common with the other measure rows, now that all three share `MeasuredValueEdit`,
# is the constructor call naming that base's arguments -- which is the seam working, not a copy
# pylint: disable=duplicate-code

from typing import Final

import humanize
from borco_pyside.widgets import UnboundedSpinBox
from PySide6.QtWidgets import QWidget

from .measured_value_edit import MeasuredValueEdit

COMPUTE_ICON_RESOURCE: Final = ":/icons/measure_size_on_disk.svg"
"""The action that measures what the resource's content occupies on disk."""

APPLY_TOOLTIP: Final = "Store the computed size"
"""Names the apply action; also how a test tells the row's two buttons apart, since both are icon-only."""

COMPUTE_TOOLTIP: Final = "Measure this resource's content on disk"
"""Names the compute action; see :data:`APPLY_TOOLTIP`."""

STORED_TOOLTIP: Final = "The stored size, human-readable"
"""What the leading readout shows -- the spin box's own bytes, read the way the viewer renders them."""

COMPUTED_TOOLTIP: Final = "The measured size, in bytes"
"""What the trailing readout shows, and why it is exact: it is compared against the spin box beside it,
digit for digit rather than through a rounded ``1.4G`` that two different sizes would share."""


class FileSizeEdit(MeasuredValueEdit):
    """The ``[human-readable] [spin] [apply] [computed] [compute]`` row: the **stored** size in bytes,
    editable, between its human reading and the size a scan most recently found
    ([[field-schema#duration-size]], #223).

    A :class:`~rehuco_agent.fields.widgets.MeasuredValueEdit` over an
    `~borco_pyside.widgets.UnboundedSpinBox`, which is what makes the bytes an unbounded Python ``int``
    (#40) -- a single ~2 GB resource already sits at the C++ int32 ceiling. What this row adds to the
    shared one is the leading human reading: unlike a count, a byte total is unreadable as itself, and
    unlike a duration, its editor carries no formatted half of its own.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        spin_box = UnboundedSpinBox(value=None, minimum=0)
        spin_box.setToolTip("The stored size, in bytes")
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
            # the two byte figures get twice the human reading's width -- it holds a handful of
            # characters (``1.4G``) where they carry ten digits or more
            editor_stretch=2,
            computed_stretch=2,
            stored_format=self.format,
            stored_tooltip=STORED_TOOLTIP,
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
