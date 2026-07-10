"""A square checkable expand/collapse toggle drawn with a Phosphor `[+]`/`[-]` glyph
([[plugins#field-toolkit]]).
"""

from typing import Final

from PySide6.QtWidgets import QToolButton, QWidget

from rehuco_agent.glyphs import COLLAPSE_ACTION_GLYPH, EXPAND_ACTION_GLYPH

STYLESHEET: Final = f'QToolButton {{ font-family: "{EXPAND_ACTION_GLYPH.family}"; }}'
"""Renders the toggle's Phosphor glyph (both `[+]`/`[-]` glyphs share this weight)."""


class ExpandToggleButton(QToolButton):
    """A small square checkable toggle: a `[+]` glyph when unchecked (collapsed), `[-]` when checked
    (expanded). Purely presentational -- the owner wires ``toggled`` to whatever it expands.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setStyleSheet(STYLESHEET)
        self.__render(self.isChecked())
        square = self.sizeHint().height()
        self.setFixedSize(square, square)
        self.toggled.connect(self.__render)

    def __render(self, checked: bool) -> None:
        """Show the collapse glyph when checked, the expand glyph otherwise.

        :param checked: the toggle's current state.
        """
        self.setText((COLLAPSE_ACTION_GLYPH if checked else EXPAND_ACTION_GLYPH).codepoint)
