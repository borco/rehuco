"""Several stored values sharing **one** measurement, each accepting it by its own copy
([[plugins#field-toolkit]], [[field-schema#duration-size]], #232).

The sibling of :class:`~rehuco_agent.fields.widgets.MeasuredValueEdit`, which stays exactly what it is
-- the row for a value with no twin (the reference-images count). What this adds is the case that widget
cannot express: fields measured by **one** scan, where pressing Compute on each of them in turn runs the
identical walk for the identical answer.

**Named for the sharing, not for two.** Every stored value here is a row in one grid and the count is the
caller's -- today the two sizes (#232) and, next, the two durations (#233), but nothing in this widget
says *two*, and a name that did would either be a lie the moment a third measured field shares a scan or
force a rename nobody should have to make.
"""

from collections.abc import Callable, Sequence
from typing import Final

from borco_pyside.core import SimpleProperty
from borco_pyside.theming import ActionIconThemeHandler
from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QGridLayout, QToolButton, QWidget

from .measured_value_edit import APPLY_ICON_RESOURCE, StoredValueEditor
from .value_readout import ValueReadout

STORED_COLUMN: Final = 0
"""The human-readable reading of each row's stored value; empty when the editors carry their own."""

EDITOR_COLUMN: Final = 1
"""Each row's stored-value editor -- the one widget on the row a field's binding writes through."""

COPY_COLUMN: Final = 2
"""Each row's copy action, which stores the measurement into *that* row alone."""

COMPUTED_COLUMN: Final = 3
"""The one measured readout, spanning every row: the measurement belongs to the whole
group, not to whichever row happened to host it."""

COMPUTE_COLUMN: Final = 4
"""The one compute action, spanning every row for the same reason."""


class SharedMeasurementRow(QObject):
    """One stored value in a shared measurement: ``[human reading] [stored editor] [copy]``
    ([[field-schema#duration-size]], #232).

    A `QObject` rather than a widget, deliberately. Its three cells are added **into the group's own
    grid**, because a row that packed them into a layout of its own would leave each row distributing
    its width independently and nothing would line the rows' editors up -- which is the same reason
    [[plugins#field-toolkit]] has a composite return one editor widget rather than a list of them.

    It carries the value-widget contract (:attr:`value` plus the ``set_value`` slot ``SimpleProperty``
    synthesizes), so a field binds a row exactly the way it binds any other editor -- which is what lets
    one widget carry a binding per row.

    :param editor: the widget holding this row's stored value; reparented into the group's grid.
    :param set_editor_value: writes a value into ``editor``, called only when it holds a different one.
    :param copy_tooltip: names this row's copy action -- the button is icon-only and there is one per
        row, so the tooltip is what says which row each one stores into.
    :param stored_format: renders the stored value for the leading human-readable reading; ``None`` for a
        row whose editor carries one of its own (a duration).
    :param stored_tooltip: what that leading reading shows; ignored without ``stored_format``.
    """

    value = SimpleProperty[int | None](None)
    """This row's **stored** value, or ``None`` when unmeasured -- the value-widget contract's property
    ([[plugins#field-toolkit]]). ``None`` is distinct from a genuine ``0``
    ([[field-schema#deferred-items]]). The editor follows it rather than holding it, so a value set from
    anywhere -- the model, the copy action, the editor itself -- lands in exactly one place."""

    computed = SimpleProperty[int | None](None)
    """What the group's last measurement found, mirrored down here so the row can decide its own copy
    action. Widget state only: it is never written to the document, so setting it leaves :attr:`value`,
    and the document's dirty flag, alone."""

    busy = SimpleProperty(False)
    """Whether the group's measurement is in flight, mirrored down from it -- **every** row is busy
    for the whole scan, since one scan answers all of them."""

    def __init__(
        self,
        editor: StoredValueEditor,
        *,
        set_editor_value: Callable[[int | None], None],
        copy_tooltip: str,
        stored_format: Callable[[int | None], str] | None = None,
        stored_tooltip: str = "",
    ) -> None:
        super().__init__()
        self.__editor: Final = editor
        self.__set_editor_value: Final = set_editor_value
        self.__stored_format: Final = stored_format
        self.__stored_label: Final = ValueReadout(stored_tooltip) if stored_format is not None else None
        # the enabled state lives on the *action*, not the button: a QToolButton showing a default action
        # mirrors it, so disabling the button alone would be undone by the next action-driven refresh
        self.__copy_action: Final = QAction(self)
        self.__copy_action.setToolTip(copy_tooltip)
        ActionIconThemeHandler(self.__copy_action, APPLY_ICON_RESOURCE)
        self.__copy_button: Final = QToolButton()
        self.__copy_button.setDefaultAction(self.__copy_action)

        editor.value_changed.connect(self.set_value)  # type: ignore[attr-defined]
        self.value_changed.connect(self.__on_value_changed)  # type: ignore[attr-defined]
        self.computed_changed.connect(self.__render_action)  # type: ignore[attr-defined]
        self.busy_changed.connect(self.__render_action)  # type: ignore[attr-defined]
        self.__copy_action.triggered.connect(self.__copy)

        self.__on_value_changed(self.value)

    def add_to(self, grid: QGridLayout, row: int) -> None:
        """Place this row's cells in ``grid``'s ``row``, one per column.

        Called by the group that owns the grid; the widgets are parented by the layout, and this object
        is parented to it, so the whole row is torn down with it.

        :param grid: the group's grid.
        :param row: the grid row to fill.
        """
        if self.__stored_label is not None:
            grid.addWidget(self.__stored_label, row, STORED_COLUMN)
        grid.addWidget(self.__editor, row, EDITOR_COLUMN)  # type: ignore[arg-type]  # a Protocol over the widget it is
        grid.addWidget(self.__copy_button, row, COPY_COLUMN)

    def __on_value_changed(self, value: int | None) -> None:
        """Echo a stored-value change into the editor and its human reading, and re-render the action.

        The guard is a compare against what the editor already holds, not a signal blocker: the editor's
        own edit reaches :attr:`value` through the very connection this echoes back over, and writing the
        value it already holds is where that stops.

        :param value: the new stored value.
        """
        if self.__editor.value != value:
            self.__set_editor_value(value)
        if self.__stored_label is not None and self.__stored_format is not None:
            self.__stored_label.setText(self.__stored_format(value))
        self.__render_action()

    def __copy(self) -> None:
        """Store what was measured into *this* row -- the one action here that changes the document.

        Per row, and never for the group: ``original_*`` is the denominator for *how much is left*
        ([[field-schema#duration-size]]), so accepting a measurement into one row must leave the others
        exactly where they were. One scan, a separate explicit click each.
        """
        self.set_value(self.computed)  # type: ignore[attr-defined]

    def __render_action(self, *_: object) -> None:
        """Enable this row's copy only while a measurement exists and genuinely differs from **this
        row's** stored value, and hold it disabled for as long as the scan is in flight.

        Takes the notifying signal's argument and drops it: the state is read off the properties, and the
        same slot answers all three of them.
        """
        self.__copy_action.setEnabled(not self.busy and self.computed is not None and self.computed != self.value)


class SharedMeasurementEdit(QWidget):
    """Any number of stored values sharing **one** measurement
    ([[field-schema#duration-size]], #232)::

        [human reading] [stored editor] [copy]  [measured] [measure]
        [human reading] [stored editor] [copy]

    The measured readout and the compute action span every row, because the measurement belongs to the
    whole group rather than to any one of them: ``original_size`` and ``current_size`` are the same scan
    of the same tree, differing only in *when* the user accepts it, and the same holds for the two
    durations over the far slower video probe (#233). One press, one walk, an answer each row accepts
    separately.

    **How many rows is the caller's business.** Two is merely what both of today's callers pass; the
    grid, the busy fan-out and the spanning cells are all written over ``rows``, so a third field sharing
    a scan needs no new widget and no rename.

    Everything else is the vocabulary
    :class:`~rehuco_agent.fields.widgets.MeasuredValueEdit` established and this reuses unchanged:
    **computing never touches a stored value** (a disagreement is information -- content added or
    deleted since the value was recorded -- so both numbers are shown and the difference is resolved by
    an explicit copy), **nothing runs on its own**, and **the measured readout is exact**, never
    formatted, so it can be compared against the editors beside it digit for digit.

    The rows live in one `QGridLayout` owned here, so their columns line up without any pixel math -- the
    reason [[plugins#field-toolkit]] has a composite return **one** editor widget. Its vertical twin is
    `~borco_pyside.widgets.equal_height_column`, which the owning field stacks the row labels with so the
    label column lines up with these rows.

    :param rows: the stored rows, top to bottom; reparented here.
    :param compute_icon: the compute action's themed SVG resource path -- what is being measured.
    :param compute_tooltip: what the compute action measures, in words; the button is icon-only.
    :param computed_tooltip: what the spanning readout shows.
    :param stored_stretch: the human-reading column's share of the row's width.
    :param editor_stretch: the stored-editor column's share.
    :param computed_stretch: the measured readout's share.
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
    :meth:`show_measurement`, so every action in the group is disabled for exactly as long as the scan
    runs and a slow tree cannot be re-scanned, or half-accepted, underneath itself."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        rows: Sequence[SharedMeasurementRow],
        *,
        compute_icon: str,
        compute_tooltip: str,
        computed_tooltip: str,
        stored_stretch: int = 1,
        editor_stretch: int = 1,
        computed_stretch: int = 1,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.__rows: Final = tuple(rows)
        self.__computed_label: Final = ValueReadout(computed_tooltip, self)
        self.__compute_action: Final = QAction(self)
        self.__compute_action.setToolTip(compute_tooltip)
        ActionIconThemeHandler(self.__compute_action, compute_icon)
        self.__compute_button: Final = QToolButton(self)
        self.__compute_button.setDefaultAction(self.__compute_action)

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        # no vertical spacing, and every row given the same stretch: the two rows then divide this
        # widget's height into equal bands, which is exactly what the stacked label column beside it does
        # with the same height -- so the two line up without either side measuring the other
        grid.setVerticalSpacing(0)
        for index, row in enumerate(self.__rows):
            row.setParent(self)
            row.add_to(grid, index)
            grid.setRowStretch(index, 1)
        span = max(len(self.__rows), 1)
        # both span every row but neither is *stretched* over them: a two-row-tall frame beside one-line
        # rows reads as a different kind of control. They stay **one row tall** -- the readout pinned to
        # the button's natural height, which is the height every other control on these rows already has
        # -- and sit centered against the rows they answer, so the measurement reads as belonging to both
        self.__computed_label.setFixedHeight(self.__compute_button.sizeHint().height())
        grid.addWidget(self.__computed_label, 0, COMPUTED_COLUMN, span, 1, Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(self.__compute_button, 0, COMPUTE_COLUMN, span, 1, Qt.AlignmentFlag.AlignVCenter)
        grid.setColumnStretch(STORED_COLUMN, stored_stretch)
        grid.setColumnStretch(EDITOR_COLUMN, editor_stretch)
        grid.setColumnStretch(COMPUTED_COLUMN, computed_stretch)

        self.computed_changed.connect(self.__on_computed_changed)  # type: ignore[attr-defined]
        self.busy_changed.connect(self.__on_busy_changed)  # type: ignore[attr-defined]
        self.__compute_action.triggered.connect(self.__request_compute)

    @property
    def rows(self) -> tuple[SharedMeasurementRow, ...]:
        """The stored rows, top to bottom -- what the owning field binds, one model name each."""
        return self.__rows

    @Slot(object)
    def show_measurement(self, value: int | None) -> None:
        """Show a completed measurement and leave the busy state -- the owner's one way back in.

        A single slot rather than two property writes because it is what the owner's measurement
        connects to across a thread boundary (#223): a bound slot of this widget is dropped by Qt the
        moment the widget is destroyed, so a scan still running when the form is rebuilt (a type switch,
        a revert) reports into nothing rather than into a deleted editor.

        :param value: what was measured, or ``None`` when nothing could be -- a document with no path
            yet, or a scan that failed. ``None`` leaves **every** row with an empty readout and nothing
            to copy, rather than half a state.
        """
        self.busy = False
        self.computed = value

    def __on_computed_changed(self, value: int | None) -> None:
        """Show a fresh measurement beside the stored values and hand it down to every row.

        :param value: what was just measured, or ``None`` when nothing could be.
        """
        self.__computed_label.setText("" if value is None else str(value))
        for row in self.__rows:
            row.computed = value
        self.__render_action()

    def __on_busy_changed(self, busy: bool) -> None:
        """Hand the busy state down to every row and re-render the compute action.

        :param busy: whether a measurement is now in flight.
        """
        for row in self.__rows:
            row.busy = busy
        self.__render_action()

    def __request_compute(self) -> None:
        """Enter the busy state and ask the owner to measure -- once, for every row."""
        self.busy = True
        self.compute_requested.emit()

    def __render_action(self) -> None:
        """Hold the compute action disabled for as long as a scan is in flight."""
        self.__compute_action.setEnabled(not self.busy)
