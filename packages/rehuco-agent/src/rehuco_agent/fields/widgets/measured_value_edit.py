"""The measure row every measured field's editor is built from: a stored value between what a scan found
and the explicit apply that moves one into the other ([[plugins#field-toolkit]], #224).
"""

from collections.abc import Callable
from typing import Final, Protocol

from borco_pyside.core import SimpleProperty
from borco_pyside.theming import ActionIconThemeHandler
from PySide6.QtCore import Signal, SignalInstance, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QHBoxLayout, QToolButton, QWidget

from .value_readout import ValueReadout

APPLY_ICON_RESOURCE: Final = ":/icons/measure_apply.svg"
"""The action that stores what was measured -- an arrow moving it into the stored slot. One icon for
every measure row: the gesture is the same wherever it appears, and the row beside it says what is being
measured."""

APPLY_TOOLTIP: Final = "Store the computed value"
"""Names the apply action where a row does not name it more specifically; also how a test tells a row's
two buttons apart, since both are icon-only."""


class StoredValueEditor(Protocol):
    """What :class:`MeasuredValueEdit` needs of the widget holding the stored value.

    Deliberately the two members the row reads -- the value, and its change signal -- so any value widget
    from the toolkit's own vocabulary can be the stored half of a measure row
    (`~borco_pyside.widgets.UnboundedSpinBox` for a count or a byte total,
    `~rehuco_agent.fields.widgets.DurationEdit` for seconds). *Writing* the value is passed in separately
    rather than named here: a spin box's ``setValue`` clamps to its own range where the synthesized
    ``set_value`` does not, and which of the two a row wants is the row's decision.
    """

    @property
    def value(self) -> int | None:
        """The value currently held."""
        ...  # pylint: disable=unnecessary-ellipsis

    @property
    def value_changed(self) -> SignalInstance:
        """Fires when :attr:`value` changes."""
        ...  # pylint: disable=unnecessary-ellipsis


class MeasuredValueEdit(QWidget):  # pylint: disable=too-many-instance-attributes
    """The ``[human reading] [stored editor] [apply] [computed] [compute]`` row
    ([[field-schema#duration-size]], #224).

    A composite editor like any other widget -- :attr:`value` is the stored editor's value and a field
    binds to that alone ([[plugins#field-toolkit]]'s value-widget contract); the readouts and the two
    buttons are visualization and actions over it. The measurement belongs to the owner: this emits
    :attr:`compute_requested` and waits to be handed a result through :meth:`show_measurement`, so it
    carries no notion of files, paths, settings, or *which thread* the scan ran on.

    **Computing never touches the stored value.** A disagreement between the two numbers is information
    -- content added or deleted since the value was recorded, a zip refreshed behind the app's back -- so
    both are shown side by side and the difference is resolved by an explicit ``Apply``, enabled only
    while they genuinely differ. Which is also why nothing here runs on its own: an automatic fill would
    overwrite the evidence before anyone read it, and on an ``original_*`` field -- the denominator for
    *how much is left* -- it would silently overwrite that denominator with the remainder.

    **The computed readout is exact**, never formatted: it is compared against the stored editor beside
    it digit for digit, rather than through a rounded ``1.4G`` or ``2h 15m`` that two different values
    would share.

    This is the row for a value with **no twin**. It was the base under all three measure rows until the
    two sizes and the two durations turned out to be pairs sharing one scan
    (:class:`~rehuco_agent.fields.widgets.SizeMeasurementEdit`,
    :class:`~rehuco_agent.fields.widgets.DurationMeasurementEdit`, #232/#233); what is left on it is the
    content count, whose ``advertised_count`` is a hand-entered claim rather than a second measurement of
    the same thing. All of them keep the same compute/apply/busy vocabulary, which is what lets a reader
    move between them.

    :param editor: the widget holding the stored value; reparented into the row's layout.
    :param set_editor_value: writes a value into ``editor``, called only when it holds a different one.
    :param compute_icon: the compute action's themed SVG resource path -- what is being measured.
    :param compute_tooltip: what the compute action measures, in words; the button is icon-only.
    :param computed_tooltip: what the trailing readout shows.
    :param apply_tooltip: names the apply action; also how a test tells the two icon-only buttons apart.
    :param editor_stretch: the stored editor's share of the row's width.
    :param computed_stretch: the computed readout's share of the row's width.
    :param parent: optional Qt parent.
    """

    compute_requested = Signal()
    """Fires when ``Compute`` is pressed; the owner measures and hands the result to
    :meth:`show_measurement`. :attr:`busy` is already ``True`` by the time it fires."""

    value = SimpleProperty[int | None](None)
    """The **stored** value, or ``None`` when unmeasured -- the value-widget contract's property, whose
    ``set_value`` slot ``SimpleProperty`` synthesizes ([[plugins#field-toolkit]]). ``None`` is distinct
    from a genuine ``0`` ([[field-schema#deferred-items]]). The editor follows it rather than holding it,
    so a value set from anywhere -- the model, ``Apply``, the editor itself -- lands in exactly one
    place."""

    computed = SimpleProperty[int | None](None)
    """What the last measurement found, or ``None`` when none has run (or none was possible -- a document
    with no path yet). Widget state only: it is never written to the document, so setting it leaves
    :attr:`value`, and the document's dirty flag, alone."""

    busy = SimpleProperty(False)
    """Whether a measurement is in flight. Set here the moment ``Compute`` is pressed and cleared by
    :meth:`show_measurement`, so the two buttons are disabled for exactly as long as the scan runs and a
    slow tree cannot be re-scanned, or half-applied, underneath itself."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        editor: StoredValueEditor,
        *,
        set_editor_value: Callable[[int | None], None],
        compute_icon: str,
        compute_tooltip: str,
        computed_tooltip: str,
        apply_tooltip: str = APPLY_TOOLTIP,
        editor_stretch: int = 1,
        computed_stretch: int = 1,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.__set_editor_value: Final = set_editor_value
        self.__editor: Final = editor
        self.__computed_label: Final = ValueReadout(computed_tooltip, self)
        # the enabled state lives on the *action*, not the button: a QToolButton showing a default action
        # mirrors it, so disabling the button alone would be undone by the next action-driven refresh
        self.__apply_action: Final = QAction(self)
        self.__apply_button: Final = self.__make_action_button(self.__apply_action, APPLY_ICON_RESOURCE, apply_tooltip)
        self.__compute_action: Final = QAction(self)
        self.__compute_button: Final = self.__make_action_button(self.__compute_action, compute_icon, compute_tooltip)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # the readout sits beside what it reads and the two icon buttons take their natural width, so
        # the row still spans the same content column every other editor on the form does
        layout.addWidget(editor, editor_stretch)  # type: ignore[arg-type]  # a Protocol over the widget it is
        layout.addWidget(self.__apply_button)
        layout.addWidget(self.__computed_label, computed_stretch)
        layout.addWidget(self.__compute_button)

        editor.value_changed.connect(self.set_value)  # type: ignore[attr-defined]
        self.value_changed.connect(self.__on_value_changed)  # type: ignore[attr-defined]
        self.computed_changed.connect(self.__on_computed_changed)  # type: ignore[attr-defined]
        self.busy_changed.connect(self.__on_busy_changed)  # type: ignore[attr-defined]
        self.__apply_action.triggered.connect(self.__apply)
        self.__compute_action.triggered.connect(self.__request_compute)

        self.__on_value_changed(self.value)

    @Slot(object)
    def show_measurement(self, value: int | None) -> None:
        """Show a completed measurement and leave the busy state -- the owner's one way back in.

        A single slot rather than two property writes because it is what the owner's measurement
        connects to across a thread boundary (#223): a bound slot of this widget is dropped by Qt the
        moment the widget is destroyed, so a scan still running when the form is rebuilt (a type switch,
        a revert) reports into nothing rather than into a deleted editor.

        :param value: what was measured, or ``None`` when nothing could be -- a document with no path
            yet, or a scan that failed.
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
        """Echo a stored-value change into the editor, and re-render the actions.

        The guard is a compare against what the editor already holds, not a signal blocker: the editor's
        own edit reaches :attr:`value` through the very connection this echoes back over, and writing the
        value it already holds is where that stops.

        :param value: the new stored value.
        """
        if self.__editor.value != value:
            self.__set_editor_value(value)
        self.__render_actions()

    def __on_computed_changed(self, value: int | None) -> None:
        """Show a fresh measurement beside the stored value and re-render the actions.

        :param value: what was just measured, or ``None`` when nothing could be.
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
        """Store what was measured -- the one action here that changes the document."""
        self.set_value(self.computed)  # type: ignore[attr-defined]

    def __render_actions(self) -> None:
        """Enable ``Apply`` only while a measurement exists and genuinely differs from the stored value,
        and hold both actions disabled for as long as a scan is in flight."""
        self.__apply_action.setEnabled(not self.busy and self.computed is not None and self.computed != self.value)
        self.__compute_action.setEnabled(not self.busy)
