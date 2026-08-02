"""The one measurement answering a group of rows: its readout and the action that fills it
([[plugins#field-toolkit]], [[field-schema#duration-size]], #233).
"""

from typing import Final

from borco_pyside.theming import ActionIconThemeHandler
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QGridLayout, QToolButton, QWidget

from .value_readout import ValueReadout


class MeasurementResult:
    """The ``[measured value] [compute]`` pair that spans every row of a measuring editor.

    **The one thing the size and duration editors genuinely share.** Their *rows* do not: a size row is a
    human reading beside an editable byte count, two separate widgets in two columns, where a duration row
    is one `DurationEdit` carrying both halves itself. Forcing those two shapes through a common row/grid
    abstraction is what left the duration editor with a column nothing was ever drawn in. What *is*
    identical is this: one exact readout and one action, spanning the rows, looking and behaving the same
    whatever sits beside them -- so this is what is shared, and nothing more.

    A plain object rather than a `QWidget` or `QObject`: it is two widgets placed in **the owner's** grid,
    so the rows' columns line up with them without a nested layout in between. The measurement *state*
    (``computed``, ``busy``, the compute request, the fan-out to rows) stays on the owner, which is where
    it differs between editors; this only renders what it is told and offers the action to connect to.

    :param compute_icon: the compute action's themed SVG resource path -- what is being measured.
    :param compute_tooltip: what the compute action measures, in words; the button is icon-only.
    :param computed_tooltip: what the readout shows.
    :param parent: the owning editor; parents both widgets and the action.
    """

    def __init__(self, *, compute_icon: str, compute_tooltip: str, computed_tooltip: str, parent: QWidget) -> None:
        self.label: Final = ValueReadout(computed_tooltip, parent)
        # the enabled state lives on the *action*, not the button: a QToolButton showing a default action
        # mirrors it, so disabling the button alone would be undone by the next action-driven refresh
        self.action: Final = QAction(parent)
        self.action.setToolTip(compute_tooltip)
        ActionIconThemeHandler(self.action, compute_icon)
        self.button: Final = QToolButton(parent)
        self.button.setDefaultAction(self.action)
        # pinned to the button's natural height -- the height every other control on these rows has. A
        # readout stretched over two rows would read as a different kind of control than the one-line
        # editors it answers.
        self.label.setFixedHeight(self.button.sizeHint().height())

    def add_to(self, grid: QGridLayout, *, label_column: int, button_column: int, row_span: int) -> None:
        """Place the readout and the compute button in ``grid``, spanning every row.

        Both span the rows without being *stretched* over them -- centered against the rows they answer,
        so the measurement reads as belonging to all of them rather than to whichever hosted it.

        :param grid: the owning editor's grid.
        :param label_column: the column the readout goes in.
        :param button_column: the column the compute button goes in.
        :param row_span: how many rows to span.
        """
        grid.addWidget(self.label, 0, label_column, row_span, 1, Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(self.button, 0, button_column, row_span, 1, Qt.AlignmentFlag.AlignVCenter)

    def render(self, computed: int | None, busy: bool) -> None:
        """Show the current measurement and offer (or withhold) the action.

        The value is shown **exactly**, never formatted: it is compared against the editors beside it
        digit for digit, where a rounded ``1.4G`` or ``2h 15m`` two different values would share could not
        settle whether they agree. A genuine ``0`` shows as ``0``, distinct from the empty never-measured
        readout ([[field-schema#deferred-items]]).

        :param computed: what the last measurement found, or ``None`` when none has run or none was possible.
        :param busy: whether a measurement is in flight; the action is withheld for as long as it is.
        """
        self.label.setText("" if computed is None else str(computed))
        self.action.setEnabled(not busy)
