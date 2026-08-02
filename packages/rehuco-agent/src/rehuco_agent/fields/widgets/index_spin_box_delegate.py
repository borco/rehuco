"""The **Index** cell's editor: a spin box, because a position is a number and typing one is not free text
([[field-schema#sources]]).
"""

from typing import Final, override

from PySide6.QtCore import QModelIndex, QPersistentModelIndex
from PySide6.QtWidgets import QSpinBox, QStyledItemDelegate, QStyleOptionViewItem, QWidget

from ..indexed_list_field import UNPLACED_INDEX
from .membership_table_model import MAXIMUM_INDEX

UNPLACED_TEXT: Final = "—"
"""What an open editor shows at :data:`~rehuco_agent.fields.indexed_list_field.UNPLACED_INDEX` -- an em
dash, where the *closed* cell shows nothing at all.

The two disagree on purpose. A cell showing nothing follows the viewer's own rule (no position chosen
renders as no position, [[field-schema#sources]]); a spin box showing nothing reads as a control that
failed to load, in a row of numbers where every other one is filled in."""


def index_spin_box(parent: QWidget | None) -> QSpinBox:
    """One spin box configured the way an Index cell's editor is.

    Public because two callers need to agree on it: this module opens one when a cell is edited, and the
    memberships table measures one to size the column it will open in
    (:class:`~rehuco_agent.fields.widgets.memberships_editor.MembershipsEditor`). Were the two to
    configure it differently, the column would be sized for a control other than the one that appears
    in it -- which is exactly the bug of a column sized for the *text* instead.

    :param parent: the widget to build it in -- the table, so it is styled the way the real editor will
        be; a measurement taken off an unparented one reads the default style rather than the app's.
    :returns: the spin box.
    """
    spin = QSpinBox(parent)
    spin.setRange(UNPLACED_INDEX, MAXIMUM_INDEX)
    spin.setSpecialValueText(UNPLACED_TEXT)
    return spin


class IndexSpinBoxDelegate(QStyledItemDelegate):
    """Opens a membership's position in a spin box rather than a line edit.

    Not a validation choice -- the model coerces whatever reaches it either way -- but a *keyboard* one:
    the position is stepped far more often than it is typed (one along, one back), and the arrow keys and
    the wheel are what a number cell is expected to answer to.

    The bounds are the spin box's own necessity, not the format's
    (:data:`~rehuco_agent.fields.widgets.membership_table_model.MAXIMUM_INDEX`): nothing on disk is refused
    for sitting outside them.

    :param parent: optional Qt parent.
    """

    @override
    def createEditor(  # noqa: N802  (Qt API name)
        self,
        parent: QWidget,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QWidget:
        del option, index
        editor = index_spin_box(parent)
        # the cell is the frame: a second one inside it draws a box within a box at every open editor
        editor.setFrame(False)
        return editor
