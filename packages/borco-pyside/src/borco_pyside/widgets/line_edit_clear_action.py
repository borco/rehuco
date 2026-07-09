"""App-wide `QLineEdit` clear action, added to every line edit as it becomes visible."""

from typing import Final, override

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QAction, QIcon, QPalette
from PySide6.QtWidgets import QAbstractSpinBox, QLineEdit

from borco_pyside.theming import GlyphActionIconThemeHandler


class LineEditClearActionFilter(QObject):
    """Adds a themed "clear text" trailing action to every plain ``QLineEdit`` app-wide, the moment
    it is first shown -- installed once (``app.installEventFilter(...)``) so every line edit gets
    one, including ``.ui``-file-generated line edits this app never constructs directly.

    Skips a ``QLineEdit`` owned by a ``QAbstractSpinBox`` (its internal display line edit,
    ``spin_box.lineEdit()``): "clear the text" and "clear the value" aren't the same thing there --
    clearing just the displayed text leaves the spin box's real ``value()`` untouched, so it snaps
    the old text right back on the next ``interpretText()`` (e.g. a focus change), confirmed
    empirically -- and a spin box's "empty" is its own domain concept (typically its minimum, shown
    via ``specialValueText``), not "no text". A spin-box-owning field wanting a real clear-to-empty
    affordance needs one with spin-box-correct semantics, built for that widget specifically.

    Visible only while its line edit holds text; triggering it clears the text and restores focus.
    Visibility is resynced both on ``textChanged`` (instant feedback for ordinary typing) and on
    every ``QEvent.Paint`` (a fallback that also covers a programmatic ``setText`` made under a
    ``QSignalBlocker`` -- the field toolkit's echo-guard pattern, used throughout, suppresses
    ``textChanged`` entirely but still schedules a real repaint; without this fallback, reverting a
    cleared field left the action stuck hidden even though the text came back, confirmed empirically).

    A newly-added trailing action always renders nearest the text among a line edit's trailing
    actions, pushing any earlier ones further right (confirmed empirically, #24) -- so a field
    wanting its own trailing action *outside* this one (e.g. a calendar popup) must add its action
    first, at construction, before the line edit is ever shown.

    :param glyph: the glyph character drawn as the action's icon.
    :param family: the font family ``glyph`` resolves in; must already be loaded application-wide.
    :param color_role: the palette role the glyph is colored with.
    :param parent: optional ``QObject`` parent.
    """

    __ACTION_PROPERTY: Final = "_borco_clear_action"

    def __init__(
        self,
        glyph: str,
        family: str,
        color_role: QPalette.ColorRole = QPalette.ColorRole.Text,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.__glyph: Final = glyph
        self.__family: Final = family
        self.__color_role: Final = color_role

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if isinstance(watched, QLineEdit) and not isinstance(watched.parentWidget(), QAbstractSpinBox):
            if event.type() == QEvent.Type.Show:
                self.__ensure_clear_action(watched)
            elif event.type() == QEvent.Type.Paint:
                self.__resync_visibility(watched)
        return super().eventFilter(watched, event)

    def __ensure_clear_action(self, line_edit: QLineEdit) -> None:
        """Install ``line_edit``'s clear action once; a no-op on a later ``Show`` of the same widget.

        :param line_edit: the line edit to equip.
        """
        if line_edit.property(self.__ACTION_PROPERTY) is not None:
            return
        action = line_edit.addAction(QIcon(), QLineEdit.ActionPosition.TrailingPosition)
        GlyphActionIconThemeHandler(action, self.__glyph, self.__family, self.__color_role, parent=action)
        action.setToolTip("Clear")
        action.setVisible(bool(line_edit.text()))
        line_edit.textChanged.connect(lambda text: action.setVisible(bool(text)))
        action.triggered.connect(lambda: self.__clear(line_edit))
        line_edit.setProperty(self.__ACTION_PROPERTY, action)

    def __resync_visibility(self, line_edit: QLineEdit) -> None:
        """Re-match the clear action's visibility to the current text, a repaint's worth after the
        fact -- the fallback path for a signal-blocked ``setText`` (see the class docstring).

        :param line_edit: the line edit whose action to resync.
        """
        action = line_edit.property(self.__ACTION_PROPERTY)
        if isinstance(action, QAction):
            action.setVisible(bool(line_edit.text()))

    @staticmethod
    def __clear(line_edit: QLineEdit) -> None:
        """Clear ``line_edit``'s text and restore keyboard focus to it.

        :param line_edit: the line edit to clear.
        """
        line_edit.clear()
        line_edit.setFocus()
