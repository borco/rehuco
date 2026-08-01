"""The measured-count editor: a stored-count spin box beside the count a measurement found, with the
explicit apply that moves one into the other ([[plugins#field-toolkit]], #198).
"""

# the measure/apply/busy half of this row is the shape ``FileSizeEdit`` (#223) also takes; see that
# widget's own note on what the two already share and why they are still two widgets
# pylint: disable=duplicate-code

from typing import Final

from borco_pyside.core import SimpleProperty
from borco_pyside.theming import ActionIconThemeHandler
from borco_pyside.widgets import UnboundedSpinBox
from PySide6.QtCore import Signal, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QHBoxLayout, QToolButton, QWidget

from .value_readout import ValueReadout

APPLY_ICON_RESOURCE: Final = ":/icons/measure_apply.svg"
"""The action that stores the measured count -- an arrow moving it into the stored slot."""

COMPUTE_ICON_RESOURCE: Final = ":/icons/measure_image_count.svg"
"""The action that counts a reference-images resource's content images afresh."""

APPLY_TOOLTIP: Final = "Store the computed count"
"""Names the apply action; also how a test tells the row's two buttons apart, since both are icon-only."""

COMPUTE_TOOLTIP: Final = "Count the images inside this resource's archive(s)"
"""Names the compute action; see :data:`APPLY_TOOLTIP`."""

COMPUTED_TOOLTIP: Final = "The counted number of images"
"""What the readout beside the stored count shows."""


class ContentCountEdit(QWidget):  # pylint: disable=too-many-instance-attributes
    """The ``[spin] [apply] [computed label] [compute]`` row: the **stored** count, editable, next to the
    count a measurement most recently found ([[data-model#image-meanings]], #198).

    A composite editor like any other widget -- :attr:`value` is the spin box's value and a field binds to
    that alone ([[plugins#field-toolkit]]'s value-widget contract); the readout and the two buttons are
    visualization and actions over it. The measurement belongs to the owner: this emits
    :attr:`compute_requested` and waits to be handed a result through :meth:`show_measurement`, so it
    carries no notion of archives, paths, or settings -- including *which thread* it ran on.

    The readout is the same :class:`~rehuco_agent.fields.widgets.ValueReadout` the size rows use, so the
    two kinds of measure row cannot drift apart on a form that shows both.

    **Computing never touches the stored value.** A disagreement between the two numbers is information --
    a zip refreshed behind the app's back -- so both are shown side by side and the difference is resolved
    by an explicit ``Apply``, enabled only while they genuinely differ. Which is also why nothing here runs
    on its own: an automatic fill would overwrite the evidence before anyone read it.

    :param parent: optional Qt parent.
    """

    compute_requested = Signal()
    """Fires when ``Compute`` is pressed; the owner measures and hands the result to
    :meth:`show_measurement`. :attr:`busy` is already ``True`` by the time it fires."""

    value = SimpleProperty[int | None](None)
    """The **stored** count, or ``None`` when unset -- the value-widget contract's property, whose
    ``set_value`` slot ``SimpleProperty`` synthesizes ([[plugins#field-toolkit]]). The spin box follows it
    rather than holding it, so a value set from anywhere -- the model, ``Apply``, the spin box itself --
    lands in exactly one place."""

    computed = SimpleProperty[int | None](None)
    """The count the last measurement found, or ``None`` when none has run (or none was possible -- a
    document with no path yet). Widget state only: it is never written to the document, so setting it
    leaves :attr:`value`, and the document's dirty flag, alone."""

    busy = SimpleProperty(False)
    """Whether a measurement is in flight. Set here the moment ``Compute`` is pressed and cleared by
    :meth:`show_measurement`, so the two buttons are disabled for exactly as long as the count runs and
    the archives cannot be re-opened, or a half-finished answer applied, underneath themselves."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__spin_box: Final = UnboundedSpinBox(value=None, parent=self)
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
        # the spin box takes the leftover width, so the stored count spans the row's content column like
        # every other editor on the form and the actions sit at its trailing edge
        layout.addWidget(self.__spin_box, 1)
        layout.addWidget(self.__apply_button)
        layout.addWidget(self.__computed_label, 1)
        layout.addWidget(self.__compute_button)

        self.__spin_box.value_changed.connect(self.set_value)  # type: ignore[attr-defined]
        self.value_changed.connect(self.__on_value_changed)  # type: ignore[attr-defined]
        self.computed_changed.connect(self.__on_computed_changed)  # type: ignore[attr-defined]
        self.busy_changed.connect(self.__on_busy_changed)  # type: ignore[attr-defined]
        self.__apply_action.triggered.connect(self.__apply)
        self.__compute_action.triggered.connect(self.__request_compute)

        self.__render_actions()

    @Slot(object)
    def show_measurement(self, value: int | None) -> None:
        """Show a completed measurement and leave the busy state -- the owner's one way back in.

        A single slot rather than two property writes because it is what the owner's measurement
        connects to across a thread boundary (#223): a bound slot of this widget is dropped by Qt the
        moment the widget is destroyed, so a count still running when the form is rebuilt (a type switch,
        a revert) reports into nothing rather than into a deleted editor.

        :param value: the count measured, or ``None`` when none could be -- a document with no path yet,
            or a count that failed.
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
        """Echo a stored-count change into the spin box and re-render ``Apply``.

        The guard is the widget's own no-op-on-equal write, not a signal blocker: the spin box's edit
        reaches :attr:`value` through the very connection this echoes back over, and writing the value it
        already holds is where that stops.

        :param value: the new stored count.
        """
        if self.__spin_box.value != value:
            self.__spin_box.setValue(value)
        self.__render_actions()

    def __on_computed_changed(self, value: int | None) -> None:
        """Show a fresh measurement beside the stored count and re-render the actions.

        :param value: the count just measured, or ``None`` when none could be.
        """
        self.__computed_label.setText("" if value is None else str(value))
        self.__render_actions()

    def __on_busy_changed(self, busy: bool) -> None:
        """Re-render the actions around a count starting or finishing.

        :param busy: whether a measurement is now in flight.
        """
        del busy  # the state is read off the property; the argument is the signal's, not this method's
        self.__render_actions()

    def __request_compute(self) -> None:
        """Enter the busy state and ask the owner to measure."""
        self.busy = True
        self.compute_requested.emit()

    def __apply(self) -> None:
        """Store the measured count -- the one action here that changes the document."""
        self.set_value(self.computed)  # type: ignore[attr-defined]

    def __render_actions(self) -> None:
        """Enable ``Apply`` only while a measurement exists and genuinely differs from the stored count,
        and hold both actions disabled for as long as a count is in flight."""
        self.__apply_action.setEnabled(not self.busy and self.computed is not None and self.computed != self.value)
        self.__compute_action.setEnabled(not self.busy)
