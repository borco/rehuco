"""A push button that is its own colour swatch, and carries the colour as a settings value (#221, #342)."""

from typing import Final

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QPushButton, QWidget

SWATCH_TEXT_FLIP: Final = 0.5
"""The lightness under which the swatch's own text turns white, so the colour's name stays readable
against whatever it names."""


class ColorSwatchButton(QPushButton):
    """Shows a colour as its own background, names it as its text, and picks a new one when pressed.

    **It holds the staged colour itself**, which is the point (#342). The page used to keep it in an
    attribute beside the button, where the settings dialog's frame snapshot could not see it: the
    frame never tinted when the colour changed, and once frames grew their own Apply / Reset buttons
    those stayed dead for the one frame whose value was invisible -- while the change still rode
    along with any *other* frame's Apply. A value that lives in the widget is read, compared, written
    back and committed by exactly the same generic path as every other control on every page.

    :meth:`settings_value` / :meth:`set_settings_value` are what `SettingsFrameFilter` reads and
    writes it through; `set_color` is the same setter under the name a caller would look for.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__color = ""
        self.clicked.connect(self.__pick)
        self.set_color(QColor().name())  # objectName not set yet -- see set_color

    def color(self) -> str:
        """The staged colour, as ``#rrggbb``."""
        return self.__color

    def set_color(self, color: str) -> None:
        """Show ``color``, normalized, as this button's swatch and text.

        **The stylesheet rule is scoped to this button's own objectName** (``QPushButton#name``, an
        ID selector), never a bare ``QPushButton {...}`` type selector: the moment *any* widget in the
        app sets one of those, Qt's stylesheet-aware style engine applies it to every ``QPushButton``
        application-wide, not just this one and its children -- confirmed empirically as the OK/Cancel
        buttons of the colour-picker dialog this button opens turning the same colour as the swatch.
        An ID selector matches only the one widget it names.

        A widget promoted from a ``.ui`` has no objectName yet during its own ``__init__`` -- ``uic``
        assigns it right after construction, from the outside -- so the very first call here (from
        this class's own constructor) styles nothing but still sets the text; the page's own
        ``drop_changes()``/``seed_defaults()``, called once ``setupUi()`` has finished and the name is
        set, is what actually paints the swatch.

        :param color: any string `QColor` accepts; stored and shown as ``#rrggbb``.
        """
        self.__color = QColor(color).name()
        text = "#ffffff" if QColor(self.__color).lightnessF() < SWATCH_TEXT_FLIP else "#000000"
        self.setText(self.__color)
        if name := self.objectName():
            self.setStyleSheet(f"QPushButton#{name} {{ background-color: {self.__color}; color: {text}; }}")

    def settings_value(self) -> object:
        """This control's value, for the frame snapshot -- the `ValueControl` half of the seam."""
        return self.__color

    def set_settings_value(self, value: object) -> None:
        """Write a snapshotted value back into this control.

        :param value: a colour as :meth:`settings_value` returned it.
        """
        self.set_color(str(value))

    def __pick(self) -> None:
        """Open the colour dialog on the staged colour and stage what it returns, if anything."""
        chosen = QColorDialog.getColor(QColor(self.__color), self.parentWidget(), "Pick a colour")
        if chosen.isValid():
            self.set_color(chosen.name())
