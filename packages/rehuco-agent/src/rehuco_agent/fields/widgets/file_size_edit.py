"""The measured-size editor: a stored-bytes spin box between its human reading and the size a scan
found, with the explicit apply that moves one into the other ([[plugins#field-toolkit]], #223).
"""

# the measure/apply/busy half of this row is the shape ``ContentCountEdit`` (#198) also takes, and the
# two are deliberately still two widgets: this one carries a human-readable readout of its stored value,
# which a count -- already a human reading of itself -- has no use for. What they genuinely share is
# already shared: the readout widget, and the off-thread wiring in ``background_measurement``. #224 makes
# a third such row, which is the point at which a shared *base* earns its keep -- extracting one before
# the duration row says what it actually needs would be guessing at the seam
# pylint: disable=duplicate-code

from typing import Final

import humanize
from borco_pyside.core import SimpleProperty
from borco_pyside.theming import ActionIconThemeHandler
from borco_pyside.widgets import UnboundedSpinBox
from PySide6.QtCore import Signal, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QHBoxLayout, QToolButton, QWidget

from .value_readout import ValueReadout

APPLY_ICON_RESOURCE: Final = ":/icons/measure_apply.svg"
"""The action that stores the measured size -- an arrow moving it into the stored slot."""

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


class FileSizeEdit(QWidget):  # pylint: disable=too-many-instance-attributes
    """The ``[human-readable] [spin] [apply] [computed] [compute]`` row: the **stored** size in bytes,
    editable, between its human reading and the size a scan most recently found
    ([[field-schema#duration-size]], #223).

    A composite editor like any other widget -- :attr:`value` is the spin box's value and a field binds to
    that alone ([[plugins#field-toolkit]]'s value-widget contract); the two readouts and the two buttons
    are visualization and actions over it. The measurement belongs to the owner: this emits
    :attr:`compute_requested` and waits to be handed a result through :meth:`show_measurement`, so it
    carries no notion of files, paths, or settings. Sizes are whole **bytes**, an unbounded Python
    ``int`` on `~borco_pyside.widgets.UnboundedSpinBox` (#40) -- a single ~2 GB resource already sits at
    the C++ int32 ceiling.

    **Computing never touches the stored value.** A disagreement between the two numbers is information
    -- content added or deleted since the size was recorded -- so both are shown side by side and the
    difference is resolved by an explicit ``Apply``, enabled only while they genuinely differ. Which is
    also why nothing here runs on its own: an automatic fill would overwrite the evidence before anyone
    read it, and on ``original_size`` -- the footprint when complete, the denominator for *how much is
    left* -- it would silently overwrite that denominator with the remainder.

    **Both readouts are read-only and framed** (:class:`~rehuco_agent.fields.widgets.ValueReadout`, shared
    with the content-count row so the two never diverge on the same form): readings of a value, never a
    second place to enter one, with the border keeping the trailing one an anchor rather than a gap while
    it is still empty.

    :param parent: optional Qt parent.
    """

    compute_requested = Signal()
    """Fires when ``Compute`` is pressed; the owner measures and hands the result to
    :meth:`show_measurement`. :attr:`busy` is already ``True`` by the time it fires."""

    value = SimpleProperty[int | None](None)
    """The **stored** size in whole bytes, or ``None`` when unmeasured -- the value-widget contract's
    property, whose ``set_value`` slot ``SimpleProperty`` synthesizes ([[plugins#field-toolkit]]).
    ``None`` is distinct from a genuine ``0`` ([[field-schema#deferred-items]]). The spin box follows it
    rather than holding it, so a value set from anywhere -- the model, ``Apply``, the spin box itself --
    lands in exactly one place."""

    computed = SimpleProperty[int | None](None)
    """The size the last measurement found, or ``None`` when none has run (or none was possible -- a
    document with no path yet). Widget state only: it is never written to the document, so setting it
    leaves :attr:`value`, and the document's dirty flag, alone."""

    busy = SimpleProperty(False)
    """Whether a measurement is in flight. Set here the moment ``Compute`` is pressed and cleared by
    :meth:`show_measurement`, so the two buttons are disabled for exactly as long as the scan runs and a
    slow tree cannot be re-scanned, or half-applied, underneath itself."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__stored_label: Final = ValueReadout(STORED_TOOLTIP, self)
        self.__spin_box: Final = UnboundedSpinBox(value=None, minimum=0, parent=self)
        self.__spin_box.setToolTip("The stored size, in bytes")
        self.__computed_label: Final = ValueReadout(COMPUTED_TOOLTIP, self)
        # the enabled state lives on the *action*, not the button: a QToolButton showing a default action
        # mirrors it, so disabling the button alone would be undone by the next action-driven refresh
        self.__apply_action: Final = QAction(self)
        self.__apply_button: Final = self.__make_action_button(self.__apply_action, APPLY_ICON_RESOURCE, APPLY_TOOLTIP)
        self.__compute_action: Final = QAction(self)
        self.__compute_button: Final = self.__make_action_button(
            self.__compute_action, COMPUTE_ICON_RESOURCE, COMPUTE_TOOLTIP
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # the two byte figures get twice the human reading's width -- it holds a handful of characters
        # (``1.4G``) where they carry ten digits or more; the two icon buttons take their natural width,
        # so the row still spans the same content column every other editor on the form does and each
        # readout sits beside what it reads
        layout.addWidget(self.__stored_label, 1)
        layout.addWidget(self.__spin_box, 2)
        layout.addWidget(self.__apply_button)
        layout.addWidget(self.__computed_label, 2)
        layout.addWidget(self.__compute_button)

        self.__spin_box.value_changed.connect(self.set_value)  # type: ignore[attr-defined]
        self.value_changed.connect(self.__on_value_changed)  # type: ignore[attr-defined]
        self.computed_changed.connect(self.__on_computed_changed)  # type: ignore[attr-defined]
        self.busy_changed.connect(self.__on_busy_changed)  # type: ignore[attr-defined]
        self.__apply_action.triggered.connect(self.__apply)
        self.__compute_action.triggered.connect(self.__request_compute)

        self.__on_value_changed(self.value)

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

        A single slot rather than two property writes because it is what the owner's measurement
        connects to across a thread boundary (#223): a bound slot of this widget is dropped by Qt the
        moment the widget is destroyed, so a scan still running when the form is rebuilt (a type switch,
        a revert) reports into nothing rather than into a deleted editor.

        :param value: the size measured, or ``None`` when none could be -- a document with no path yet,
            or a scan that failed.
        """
        self.busy = False
        self.computed = value

    def __make_action_button(self, action: QAction, icon: str, tooltip: str) -> QToolButton:
        """Build one icon-only tool button driven by ``action``, kept theme-recolored.

        The same shape every other themed control in the toolkit takes -- a ``QAction`` set as the
        button's default action, its icon repainted by an
        :class:`~borco_pyside.theming.ActionIconThemeHandler` (#104) -- rather than a labeled button, so
        the row reads as two actions on a value instead of a sentence.

        :param action: the action to drive the button, parented here.
        :param icon: the action's themed SVG resource path.
        :param tooltip: what the action does, in words -- the button is icon-only.
        :returns: the button, parented to this widget.
        """
        action.setToolTip(tooltip)
        ActionIconThemeHandler(action, icon)
        button = QToolButton(self)
        button.setDefaultAction(action)
        return button

    def __on_value_changed(self, value: int | None) -> None:
        """Echo a stored-size change into the spin box and its human reading, and re-render the actions.

        The guard is the widget's own no-op-on-equal write, not a signal blocker: the spin box's edit
        reaches :attr:`value` through the very connection this echoes back over, and writing the value it
        already holds is where that stops.

        :param value: the new stored size.
        """
        if self.__spin_box.value != value:
            self.__spin_box.setValue(value)
        self.__stored_label.setText(self.format(value))
        self.__render_actions()

    def __on_computed_changed(self, value: int | None) -> None:
        """Show a fresh measurement beside the stored size and re-render the actions.

        :param value: the size just measured, or ``None`` when none could be.
        """
        self.__computed_label.setText("" if value is None else str(value))
        self.__render_actions()

    def __on_busy_changed(self, busy: bool) -> None:
        """Re-render the actions around a scan starting or finishing.

        :param busy: whether a measurement is now in flight.
        """
        del busy  # the state is read off the property; the argument is the signal's, not this method's
        self.__render_actions()

    def __request_compute(self) -> None:
        """Enter the busy state and ask the owner to measure."""
        self.busy = True
        self.compute_requested.emit()

    def __apply(self) -> None:
        """Store the measured size -- the one action here that changes the document."""
        self.set_value(self.computed)  # type: ignore[attr-defined]

    def __render_actions(self) -> None:
        """Enable ``Apply`` only while a measurement exists and genuinely differs from the stored size,
        and hold both actions disabled for as long as a scan is in flight."""
        self.__apply_action.setEnabled(not self.busy and self.computed is not None and self.computed != self.value)
        self.__compute_action.setEnabled(not self.busy)
