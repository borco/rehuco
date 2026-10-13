"""The measured sizes on disk -- the original and the current -- filled by **one** scan
([[plugins#field-toolkit]], [[field-schema#duration-size]], #232).
"""

# the duration editor's compute/copy/busy wiring reads much like this one's, and is deliberately its own
# copy: the two have genuinely different row shapes (a reading beside a spin box here, one `DurationEdit`
# there), and the base that once held the resemblance in common could only do it by giving one of them a
# column it never draws in -- the #233 layout bug. What they legitimately share is `MeasurementResult`.
# pylint: disable=duplicate-code

from collections.abc import Sequence
from typing import Final

import humanize
from borco_pyside.core import SimpleProperty
from borco_pyside.theming import ActionIconThemeHandler
from borco_pyside.widgets import UnboundedSpinBox
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QGridLayout, QToolButton, QWidget

from .measured_value_edit import APPLY_ICON_RESOURCE
from .measurement_result import MeasurementResult
from .value_readout import ValueReadout

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

STORED_COLUMN: Final = 0
"""Each row's human-readable reading of its stored bytes -- unlike a duration, a byte total is unreadable
as itself, and its editor carries no formatted half of its own."""

EDITOR_COLUMN: Final = 1
"""Each row's byte spin box -- the one widget on the row a field's binding writes through."""

COPY_COLUMN: Final = 2
"""Each row's copy action, which stores the measurement into *that* row alone."""

COMPUTED_COLUMN: Final = 3
"""The one measured readout, spanning every row."""

COMPUTE_COLUMN: Final = 4
"""The one compute action, spanning every row."""


class SizeRow(QObject):
    """One stored size: ``[human reading] [byte spin box] [copy]`` ([[field-schema#duration-size]], #232).

    A `QObject` rather than a widget, deliberately. Its three cells are added **into the editor's own
    grid**, because a row that packed them into a layout of its own would leave each row distributing its
    width independently and nothing would line the rows' spin boxes up -- which is the same reason
    [[plugins#field-toolkit]] has a composite return one editor widget rather than a list of them.

    It carries the value-widget contract (:attr:`value` plus the ``set_value`` slot ``SimpleProperty``
    synthesizes), so a field binds a row exactly the way it binds any other editor -- which is what lets
    one widget carry a binding per row.

    :param label: this row's display label, which names its copy action -- the buttons are icon-only and
        there is one per row, so the tooltip is what says which size each stores into.
    """

    value = SimpleProperty[int | None](None)
    """This row's **stored** size in whole bytes, or ``None`` when unmeasured -- the value-widget
    contract's property ([[plugins#field-toolkit]]). ``None`` is distinct from a genuine ``0``
    ([[field-schema#deferred-items]]). The spin box follows it rather than holding it, so a value set from
    anywhere -- the model, the copy action, the spin box itself -- lands in exactly one place."""

    computed = SimpleProperty[int | None](None)
    """What the editor's last measurement found, mirrored down here so the row can decide its own copy
    action. Widget state only: it is never written to the document, so setting it leaves :attr:`value`,
    and the document's dirty flag, alone."""

    busy = SimpleProperty(False)
    """Whether the editor's measurement is in flight, mirrored down from it -- **every** row is busy for
    the whole scan, since one scan answers all of them."""

    def __init__(self, label: str) -> None:
        super().__init__()
        self.__stored_label: Final = ValueReadout(STORED_TOOLTIP)
        self.__editor: Final = UnboundedSpinBox(value=None, minimum=0)
        self.__editor.setToolTip(SPIN_BOX_TOOLTIP)
        # the enabled state lives on the *action*, not the button: a QToolButton showing a default action
        # mirrors it, so disabling the button alone would be undone by the next action-driven refresh
        self.__copy_action: Final = QAction(self)
        self.__copy_action.setToolTip(f"Store the computed size in {label}")
        ActionIconThemeHandler(self.__copy_action, APPLY_ICON_RESOURCE)
        self.__copy_button: Final = QToolButton()
        self.__copy_button.setDefaultAction(self.__copy_action)

        self.__editor.value_changed.connect(self.set_value)  # type: ignore[attr-defined]
        self.value_changed.connect(self.__on_value_changed)  # type: ignore[attr-defined]
        self.computed_changed.connect(self.__render_action)  # type: ignore[attr-defined]
        self.busy_changed.connect(self.__render_action)  # type: ignore[attr-defined]
        self.__copy_action.triggered.connect(self.__copy)

        self.__on_value_changed(self.value)

    def add_to(self, grid: QGridLayout, row: int) -> None:
        """Place this row's cells in ``grid``'s ``row``, one per column.

        Called by the editor that owns the grid; the widgets are parented by the layout, and this object
        is parented to it, so the whole row is torn down with it.

        :param grid: the editor's grid.
        :param row: the grid row to fill.
        """
        grid.addWidget(self.__stored_label, row, STORED_COLUMN)
        grid.addWidget(self.__editor, row, EDITOR_COLUMN)
        grid.addWidget(self.__copy_button, row, COPY_COLUMN)

    def __on_value_changed(self, value: int | None) -> None:
        """Echo a stored-size change into the spin box and its human reading, and re-render the action.

        The guard is a compare against what the spin box already holds, not a signal blocker: its own edit
        reaches :attr:`value` through the very connection this echoes back over, and writing the value it
        already holds is where that stops.

        :param value: the new stored size.
        """
        if self.__editor.value != value:
            self.__editor.setValue(value)
        self.__stored_label.setText(SizeMeasurementEdit.format(value))
        self.__render_action()

    def __copy(self) -> None:
        """Store what was measured into *this* row -- the one action here that changes the document.

        Per row, and never for the group: ``original_size`` is the denominator for *how much is left*
        ([[field-schema#duration-size]]), so accepting a measurement into one row must leave the others
        exactly where they were. One scan, a separate explicit click each.
        """
        self.set_value(self.computed)  # type: ignore[attr-defined]

    def __render_action(self, *_: object) -> None:
        """Enable this row's copy only while a measurement exists and genuinely differs from **this
        row's** stored size, and hold it disabled for as long as the scan is in flight.

        Takes the notifying signal's argument and drops it: the state is read off the properties, and the
        same slot answers all three of them.
        """
        self.__copy_action.setEnabled(not self.busy and self.computed is not None and self.computed != self.value)


class SizeMeasurementEdit(QWidget):
    """The sizes' editor: one ``[human reading] [spin] [copy]`` row per bound size, beside the one
    measurement that fills them all ([[field-schema#duration-size]], #232)::

        [human reading] [spin] [copy]  [measured] [measure]
        [human reading] [spin] [copy]

    **Why they share a measurement.** ``original_size`` and ``current_size`` are the same walk of the same
    tree over the same exclusion list (#223/#226) -- *when* you press one is the whole difference. Two
    rows each carrying a Compute meant running the identical scan twice for the identical answer. One
    press now fills one readout that both rows accept from, and accepting stays two separate, explicit
    clicks.

    **Self-contained, deliberately.** This shares no row or grid machinery with
    :class:`~rehuco_agent.fields.widgets.DurationMeasurementEdit`: a size row splits a human reading and an
    editable byte count across two columns where a duration row's `DurationEdit` carries both itself, so
    the two have genuinely different shapes and a common base could only force one of them into the
    other's. What they *do* share is :class:`MeasurementResult` -- the spanning readout and compute action,
    which are identical whatever sits beside them.

    The rows use `~borco_pyside.widgets.UnboundedSpinBox`, which is what makes the bytes an unbounded
    Python ``int`` (#40) -- a single ~2 GB resource already sits at the C++ int32 ceiling.

    Built from **labels rather than a fixed count**, because how many rows there are is the document's
    answer, not this widget's: a type declaring only one of the two size names composes a coherent single
    row (:class:`~rehuco_agent.fields.size_pair_field.SizePairField`), and each label is what tells the
    otherwise identical copy buttons apart.

    **Computing never touches a stored size.** A disagreement between the numbers is information --
    content added or deleted since the value was recorded -- so both are shown and the difference is
    resolved by an explicit copy. Nothing here runs on its own.

    :param row_labels: the bound sizes' display labels, top to bottom -- one row each.
    :param parent: optional Qt parent.
    """

    compute_requested = Signal()
    """Fires when ``Compute`` is pressed; the owner measures and hands the result to
    :meth:`show_measurement`. :attr:`busy` is already ``True`` by the time it fires."""

    computed = SimpleProperty[int | None](None)
    """What the last measurement found, or ``None`` when none has run (or none was possible -- a document
    with no local path). Mirrored into every row. Widget state only: it is never written to the document."""

    busy = SimpleProperty(False)
    """Whether a measurement is in flight. Set the moment ``Compute`` is pressed and cleared by
    :meth:`show_measurement`, so every action is disabled for exactly as long as the scan runs and a slow
    tree cannot be re-scanned, or half-accepted, underneath itself."""

    def __init__(self, row_labels: Sequence[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__rows: Final = tuple(SizeRow(label) for label in row_labels)
        self.__result: Final = MeasurementResult(
            compute_icon=COMPUTE_ICON_RESOURCE,
            compute_tooltip=COMPUTE_TOOLTIP,
            computed_tooltip=COMPUTED_TOOLTIP,
            parent=self,
        )

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        # no vertical spacing, and every row given the same stretch: the rows then divide this widget's
        # height into equal bands, which is exactly what the stacked label column beside it does with the
        # same height -- so the two line up without either side measuring the other
        grid.setVerticalSpacing(0)
        for index, row in enumerate(self.__rows):
            row.setParent(self)
            row.add_to(grid, index)
            grid.setRowStretch(index, 1)
        self.__result.add_to(
            grid,
            label_column=COMPUTED_COLUMN,
            button_column=COMPUTE_COLUMN,
            row_span=max(len(self.__rows), 1),
        )
        grid.setColumnStretch(STORED_COLUMN, 1)
        grid.setColumnStretch(EDITOR_COLUMN, 1)
        grid.setColumnStretch(COPY_COLUMN, 0)
        grid.setColumnStretch(COMPUTED_COLUMN, 1)
        grid.setColumnStretch(COMPUTE_COLUMN, 0)

        self.computed_changed.connect(self.__on_computed_changed)  # type: ignore[attr-defined]
        self.busy_changed.connect(self.__on_busy_changed)  # type: ignore[attr-defined]
        self.__result.action.triggered.connect(self.__request_compute)

    @property
    def rows(self) -> tuple[SizeRow, ...]:
        """The stored rows, top to bottom -- what the owning field binds, one model name each."""
        return self.__rows

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

    @Slot(object)
    def show_measurement(self, value: int | None) -> None:
        """Show a completed measurement and leave the busy state -- the owner's one way back in.

        A single slot rather than two property writes because it is what the owner's measurement connects
        to across a thread boundary (#223): a bound slot of this widget is dropped by Qt the moment the
        widget is destroyed, so a scan still running when the form is rebuilt (a type switch, a revert)
        reports into nothing rather than into a deleted editor.

        :param value: what was measured, or ``None`` when nothing could be -- a document with no local path,

            or a scan that failed. ``None`` leaves **every** row with an empty readout and nothing to copy,
            rather than half a state.
        """
        self.busy = False
        self.computed = value

    def __on_computed_changed(self, value: int | None) -> None:
        """Show a fresh measurement and hand it down to every row.

        :param value: what was just measured, or ``None`` when nothing could be.
        """
        for row in self.__rows:
            row.computed = value
        self.__result.render(self.computed, self.busy)

    def __on_busy_changed(self, busy: bool) -> None:
        """Hand the busy state down to every row and re-render the measurement.

        :param busy: whether a measurement is now in flight.
        """
        for row in self.__rows:
            row.busy = busy
        self.__result.render(self.computed, self.busy)

    def __request_compute(self) -> None:
        """Enter the busy state and ask the owner to measure -- once, for every row."""
        self.busy = True
        self.compute_requested.emit()
