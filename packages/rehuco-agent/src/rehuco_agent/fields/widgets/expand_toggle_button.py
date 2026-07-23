"""A square checkable expand/collapse toggle, its themed SVG icon swapped between the two states
([[plugins#field-toolkit]]).
"""

from typing import Final

from borco_pyside.theming import ActionIconThemeHandler
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QToolButton, QWidget

EXPAND_ICON_RESOURCE: Final = ":/icons/expand_off.svg"
"""Shown unchecked (collapsed) -- the action available next is to expand."""

COLLAPSE_ICON_RESOURCE: Final = ":/icons/expand_on.svg"
"""Shown checked (expanded) -- the action available next is to collapse."""


class ExpandToggleButton(QToolButton):
    """A small square checkable toggle: the expand icon when unchecked (collapsed), the collapse icon
    when checked (expanded), kept theme-recolored via :class:`~borco_pyside.theming.ActionIconThemeHandler`
    the same way every other themed control in the toolkit is (a ``QAction`` set as the button's
    default action, #104 -- #95's authors-editor lock indicator is the sibling precedent this mirrors,
    and this button keeps that same natural, un-shrunk size). Purely presentational -- the owner wires
    ``toggled`` to whatever it expands.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        action = QAction(self)
        action.setCheckable(True)
        self.__icon_handler: Final = ActionIconThemeHandler(action, EXPAND_ICON_RESOURCE)
        self.setDefaultAction(action)
        square = self.sizeHint().height()
        self.setFixedSize(square, square)
        action.toggled.connect(self.__render)

    def __render(self, checked: bool) -> None:
        """Swap to the collapse icon when checked, the expand icon otherwise.

        :param checked: the toggle's current state.
        """
        self.__icon_handler.set_icon(COLLAPSE_ICON_RESOURCE if checked else EXPAND_ICON_RESOURCE)
