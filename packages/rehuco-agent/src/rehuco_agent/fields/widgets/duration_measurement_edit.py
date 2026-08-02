"""The measured durations -- the original and the current -- filled by **one** scan
([[plugins#field-toolkit]], [[field-schema#duration-size]], #233).
"""

# the size editor's compute/copy/busy wiring reads much like this one's, and is deliberately its own
# copy: the two fill the same columns with different widgets (one `DurationEdit` spanning both here, a
# readout and a spin box there), so a base holding the resemblance in common could only impose one row's
# internals on the other. What they legitimately share is the column geometry and `MeasurementResult`.
# pylint: disable=duplicate-code

from collections.abc import Sequence
from typing import Final

from borco_pyside.core import SimpleProperty
from borco_pyside.theming import ActionIconThemeHandler
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QGridLayout, QToolButton, QWidget

from .duration_edit import DurationEdit
from .measured_value_edit import APPLY_ICON_RESOURCE
from .measurement_result import MeasurementResult

COMPUTE_ICON_RESOURCE: Final = ":/icons/measure_duration.svg"
"""The action that sums how long this resource's videos run."""

COMPUTE_TOOLTIP: Final = "Measure how long this resource's videos run"
"""Names the compute action; the button is icon-only."""

COMPUTED_TOOLTIP: Final = "The measured duration, in seconds"
"""What the spanning readout shows, and why it is exact: it is compared against the seconds spin boxes
beside it, digit for digit rather than through a coarse ``2h 15m`` that two different durations would
share."""

EDITOR_COLUMN: Final = 0
"""Each row's `DurationEdit` -- the one widget on the row a field's binding writes through."""

EDITOR_COLUMN_SPAN: Final = 2
"""How many columns that editor covers. `DurationEdit` is **two** boxes -- the human ``1h 30m`` reading
and the raw seconds, both editable -- which it splits evenly across its own width
(`~borco_pyside.widgets.equal_width_row`). Spanning two columns is what puts that split on the same
boundary the size rows put theirs on, so a form showing both pairs lines all four rows up: the readings
over each other, the numbers over each other, and every button in one vertical line."""

COPY_COLUMN: Final = 2
"""Each row's copy action, which stores the measurement into *that* row alone."""

COMPUTED_COLUMN: Final = 3
"""The one measured readout, spanning every row."""

COMPUTE_COLUMN: Final = 4
"""The one compute action, spanning every row."""


class DurationRow(QObject):
    """One stored duration: ``[duration editor] [copy]`` ([[field-schema#duration-size]], #233).

    A `QObject` rather than a widget, deliberately. Its two cells are added **into the editor's own
    grid**, because a row that packed them into a layout of its own would leave each row distributing its
    width independently and nothing would line the rows' editors up -- which is the same reason
    [[plugins#field-toolkit]] has a composite return one editor widget rather than a list of them.

    It carries the value-widget contract (:attr:`value` plus the ``set_value`` slot ``SimpleProperty``
    synthesizes), so a field binds a row exactly the way it binds any other editor -- which is what lets
    one widget carry a binding per row.

    The ms-vs-seconds rules hold unchanged ([[field-schema#ms-leak-history]]): `DurationEdit`'s formatted
    string stays output-only, the stored number is never re-derived from it, and the total handed to the
    row was rounded once at the end of the scan.

    :param label: this row's display label, which names its copy action -- the buttons are icon-only and
        there is one per row, so the tooltip is what says which duration each stores into.
    """

    value = SimpleProperty[int | None](None)
    """This row's **stored** duration in whole seconds, or ``None`` when unmeasured -- the value-widget
    contract's property ([[plugins#field-toolkit]]). ``None`` is distinct from a genuine ``0``
    ([[field-schema#deferred-items]]). The editor follows it rather than holding it, so a value set from
    anywhere -- the model, the copy action, the editor itself -- lands in exactly one place."""

    computed = SimpleProperty[int | None](None)
    """What the editor's last measurement found, mirrored down here so the row can decide its own copy
    action. Widget state only: it is never written to the document, so setting it leaves :attr:`value`,
    and the document's dirty flag, alone."""

    busy = SimpleProperty(False)
    """Whether the editor's measurement is in flight, mirrored down from it -- **every** row is busy for
    the whole scan, since one scan answers all of them."""

    def __init__(self, label: str) -> None:
        super().__init__()
        self.__editor: Final = DurationEdit()
        # the enabled state lives on the *action*, not the button: a QToolButton showing a default action
        # mirrors it, so disabling the button alone would be undone by the next action-driven refresh
        self.__copy_action: Final = QAction(self)
        self.__copy_action.setToolTip(f"Store the computed duration in {label}")
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
        grid.addWidget(self.__editor, row, EDITOR_COLUMN, 1, EDITOR_COLUMN_SPAN)
        grid.addWidget(self.__copy_button, row, COPY_COLUMN)

    def __on_value_changed(self, value: int | None) -> None:
        """Echo a stored-duration change into the editor, and re-render the action.

        The guard is a compare against what the editor already holds, not a signal blocker: its own edit
        reaches :attr:`value` through the very connection this echoes back over, and writing the value it
        already holds is where that stops.

        :param value: the new stored duration.
        """
        if self.__editor.value != value:
            self.__editor.set_value(value)  # type: ignore[attr-defined]  # the slot SimpleProperty synthesizes
        self.__render_action()

    def __copy(self) -> None:
        """Store what was measured into *this* row -- the one action here that changes the document.

        Per row, and never for the group: ``original_duration`` is the denominator for *how much is left*
        ([[field-schema#duration-size]]), so accepting a measurement into one row must leave the others
        exactly where they were. One scan, a separate explicit click each.
        """
        self.set_value(self.computed)  # type: ignore[attr-defined]

    def __render_action(self, *_: object) -> None:
        """Enable this row's copy only while a measurement exists and genuinely differs from **this
        row's** stored duration, and hold it disabled for as long as the scan is in flight.

        Takes the notifying signal's argument and drops it: the state is read off the properties, and the
        same slot answers all three of them.
        """
        self.__copy_action.setEnabled(not self.busy and self.computed is not None and self.computed != self.value)


class DurationMeasurementEdit(QWidget):
    """The durations' editor: one ``[duration editor] [copy]`` row per bound duration, beside the one
    measurement that fills them all ([[field-schema#duration-size]], #233)::

        [duration editor] [copy]  [measured] [measure]
        [duration editor] [copy]

    **Why they share a measurement.** ``original_duration`` and ``current_duration`` are the same reading
    of the same videos over the same exclusion list (#224/#226) -- *when* you press one is the whole
    difference. Two rows each carrying a Compute meant running the identical scan twice for the identical
    answer, and this is the slow scan: a container header read per video, or a subprocess per video with
    the external backend. One press now fills one readout that both rows accept from, and accepting stays
    two separate, explicit clicks.

    **Self-contained, deliberately.** This shares no row or grid machinery with
    :class:`~rehuco_agent.fields.widgets.SizeMeasurementEdit`: a duration row fills its two content
    columns with **one** widget, since `DurationEdit` already pairs the human ``1h 30m`` reading with the
    raw seconds and splits its own width between them, where a size row fills the same two columns with
    two separate widgets -- a readout and a spin box. Same columns, different occupants, so a common base
    could only impose one row's internals on the other. What they *do* share is the **column geometry**
    (``1, 1, 0, 1, 0``, so a form showing both pairs lines all four rows up) and
    :class:`MeasurementResult` -- the spanning readout and compute action, identical whatever sits beside
    them.

    **Not ``advertised_duration``**, which keeps a plain
    :class:`~rehuco_agent.fields.widgets.DurationEdit`: it is the coarse web claim, kept precisely so
    ``original_duration`` can be checked against it ([[field-schema#duration-size]]'s *"did I get
    everything"*), and a measure row on it would erase the comparison.

    Built from **labels rather than a fixed count**, because how many rows there are is the document's
    answer, not this widget's: a type declaring only one of the two duration names composes a coherent
    single row (:class:`~rehuco_agent.fields.duration_pair_field.DurationPairField`), and each label is
    what tells the otherwise identical copy buttons apart.

    **Computing never touches a stored duration.** A disagreement between the numbers is information --
    videos deleted as they were watched, the very method the ``current_*`` axis exists for -- so both are
    shown and the difference is resolved by an explicit copy. Nothing here runs on its own.

    :param row_labels: the bound durations' display labels, top to bottom -- one row each.
    :param parent: optional Qt parent.
    """

    compute_requested = Signal()
    """Fires when ``Compute`` is pressed; the owner measures and hands the result to
    :meth:`show_measurement`. :attr:`busy` is already ``True`` by the time it fires."""

    computed = SimpleProperty[int | None](None)
    """What the last measurement found, or ``None`` when none has run (or none was possible -- a document
    with no path yet, a probe backend that cannot run here). Mirrored into every row. Widget state only:
    it is never written to the document."""

    busy = SimpleProperty(False)
    """Whether a measurement is in flight. Set the moment ``Compute`` is pressed and cleared by
    :meth:`show_measurement`, so every action is disabled for exactly as long as the scan runs and a slow
    probe cannot be re-run, or half-accepted, underneath itself."""

    def __init__(self, row_labels: Sequence[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__rows: Final = tuple(DurationRow(label) for label in row_labels)
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
        grid.setColumnStretch(EDITOR_COLUMN, 1)
        grid.setColumnStretch(EDITOR_COLUMN + 1, 1)
        grid.setColumnStretch(COPY_COLUMN, 0)
        grid.setColumnStretch(COMPUTED_COLUMN, 1)
        grid.setColumnStretch(COMPUTE_COLUMN, 0)

        self.computed_changed.connect(self.__on_computed_changed)  # type: ignore[attr-defined]
        self.busy_changed.connect(self.__on_busy_changed)  # type: ignore[attr-defined]
        self.__result.action.triggered.connect(self.__request_compute)

    @property
    def rows(self) -> tuple[DurationRow, ...]:
        """The stored rows, top to bottom -- what the owning field binds, one model name each."""
        return self.__rows

    @Slot(object)
    def show_measurement(self, value: int | None) -> None:
        """Show a completed measurement and leave the busy state -- the owner's one way back in.

        A single slot rather than two property writes because it is what the owner's measurement connects
        to across a thread boundary (#224): a bound slot of this widget is dropped by Qt the moment the
        widget is destroyed, so a scan still running when the form is rebuilt (a type switch, a revert)
        reports into nothing rather than into a deleted editor.

        :param value: what was measured, or ``None`` when nothing could be -- a document with no path yet,
            a probe backend that cannot run here, or a scan that failed. ``None`` leaves **every** row with
            an empty readout and nothing to copy, rather than half a state.
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
