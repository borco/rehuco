"""App-wide `QLineEdit` clear action, added to every line edit as it becomes visible."""

from typing import Final, override

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QAction, QIcon, QPalette
from PySide6.QtWidgets import QAbstractSpinBox, QComboBox, QLineEdit

from ..theming import GlyphActionIconThemeHandler


class LineEditClearActionFilter(QObject):
    """Adds a themed "clear text" trailing action to every plain ``QLineEdit`` app-wide, the moment
    it is first shown -- installed once (``app.installEventFilter(...)``) so every line edit gets
    one, including ``.ui``-file-generated line edits this app never constructs directly.

    Skips a ``QLineEdit`` owned by a ``QAbstractSpinBox`` or an editable ``QComboBox`` (its internal
    display line edit, ``spin_box.lineEdit()`` / ``combo_box.lineEdit()``): "clear the text" and
    "clear the value" aren't the same thing there -- clearing just the displayed text leaves the
    owner's real ``value()`` / ``currentIndex()`` untouched, so it snaps the old text right back on
    the next ``interpretText()`` or focus change (confirmed empirically for the spin box), and the
    owner's "empty" is its own domain concept (a spin box's minimum, typically shown via
    ``specialValueText``), not "no text". An owning field wanting a real clear-to-empty affordance
    needs one with the owner's own correct semantics, built for that widget specifically.

    Visible only while its line edit holds text; triggering it clears the text and restores focus.
    Visibility is resynced both on ``textChanged`` (instant feedback for ordinary typing) and, as a
    fallback, on every ``QEvent.Paint`` (which also covers a programmatic ``setText`` made under a
    ``QSignalBlocker`` -- the field toolkit's echo-guard pattern, used throughout, suppresses
    ``textChanged`` entirely but still schedules a real repaint; without this fallback, reverting a
    cleared field left the action stuck hidden even though the text came back, confirmed empirically).
    That per-repaint resync is delegated to a small per-widget filter installed on the equipped line
    edit alone (see :meth:`__ensure_clear_action`), so it runs only for line edits that actually
    carry a clear action -- never for the app's other widgets, nor for a skipped display line edit --
    and this app-wide filter keeps its own hot path (invoked for every event of every object) to a
    bare event-type check.

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
        # App-wide filter: invoked for every event of every object, so the common path stays a bare
        # event-type compare. Only a plain line edit's first Show needs work here; the far more
        # frequent per-repaint resync lives on a per-widget filter (see __ensure_clear_action).
        if (
            event.type() == QEvent.Type.Show
            and isinstance(watched, QLineEdit)
            and not self.__is_owned_display_edit(watched)
        ):
            self.__ensure_clear_action(watched)
        return super().eventFilter(watched, event)

    @staticmethod
    def __is_owned_display_edit(line_edit: QLineEdit) -> bool:
        """Report whether ``line_edit`` is the internal display edit of a spin box or editable combo
        box -- one whose text is a rendering of an owner's value, not free text to clear (see the
        class docstring for why such a line edit is skipped).

        :param line_edit: the line edit to test.
        :returns: ``True`` if its parent is a ``QAbstractSpinBox`` or ``QComboBox``.
        """
        return isinstance(line_edit.parentWidget(), (QAbstractSpinBox, QComboBox))

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
        line_edit.installEventFilter(self.__PaintResyncFilter(action, parent=line_edit))

    @staticmethod
    def __clear(line_edit: QLineEdit) -> None:
        """Clear ``line_edit``'s text and restore keyboard focus to it.

        :param line_edit: the line edit to clear.
        """
        line_edit.clear()
        line_edit.setFocus()

    class __PaintResyncFilter(QObject):  # pylint: disable=invalid-name
        """Per-line-edit event filter that re-matches one clear ``action``'s visibility to the line
        edit's current text on every repaint -- the fallback path for a signal-blocked ``setText``
        that emits no ``textChanged`` (see :class:`LineEditClearActionFilter`'s docstring).

        Installed on a single equipped line edit only (never app-wide) and closing over that line
        edit's own ``action``, so the resync touches just the equipped line edits and needs no
        property lookup to find the action. Parented to the line edit, so it dies with it.

        :param action: the clear action whose visibility to keep in sync.
        :param parent: the line edit this filter is installed on and parented to.
        """

        def __init__(self, action: QAction, parent: QLineEdit) -> None:
            super().__init__(parent)
            self.__action: Final = action

        @override
        def eventFilter(self, watched: QObject, event: QEvent) -> bool:
            if event.type() == QEvent.Type.Paint and isinstance(watched, QLineEdit):
                self.__action.setVisible(bool(watched.text()))
            return super().eventFilter(watched, event)
