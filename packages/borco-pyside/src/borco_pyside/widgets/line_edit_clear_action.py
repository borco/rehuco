"""App-wide `QLineEdit` clear action, added to every line edit as it becomes visible."""

from typing import Final, cast, override

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QAbstractSpinBox, QComboBox, QLineEdit, QStyle

ACTION_NAME: Final = "_borco_clear_action"
"""The object name a line edit's clear action carries, which is how it is found again.

**No Python reference to the action is kept, because one cannot be trusted** (#365, #459): the action is
C++-owned by its line edit, and its wrapper has been seen invalidated while the C++ action lived on. Whoever
held that wrapper found it "already deleted" and, in the first version of this module, equipped a *second*
action beside the live first -- two clear buttons. The line edit's own ``actions()`` hands back a live wrapper
every time, so the action is looked up there by this name (:meth:`LineEditClearActionFilter.action_of`).
"""


class LineEditClearActionFilter(QObject):
    """Adds a "clear text" trailing action to every plain ``QLineEdit`` app-wide, the moment it is
    first shown -- installed once (``app.installEventFilter(...)``) so every line edit gets one,
    including ``.ui``-file-generated line edits this app never constructs directly.

    **It looks like Qt's own clear button** (#406): its icon is the style's
    ``SP_LineEditClearButton``, the one ``QLineEdit.setClearButtonEnabled`` draws, so it themes with
    the style. It is not that button, because Qt's stays hidden after a ``setText`` made under a
    ``QSignalBlocker`` (confirmed empirically) -- the field toolkit's echo guard -- which the resync
    below handles. A line edit that turned Qt's button on itself is skipped, so none shows two.

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
    ``QSignalBlocker`` -- a common echo-guard pattern that suppresses ``textChanged`` entirely but
    still schedules a real repaint; without this fallback, reverting a cleared field left the action
    stuck hidden even though the text came back, confirmed empirically).
    That per-repaint resync is delegated to a small per-widget filter installed on the equipped line
    edit alone (see :meth:`__ensure_clear_action`), so it runs only for line edits that actually
    carry a clear action -- never for the app's other widgets, nor for a skipped display line edit --
    and this app-wide filter keeps its own hot path (invoked for every event of every object) to a
    bare event-type check.

    A newly-added trailing action always renders nearest the text among a line edit's trailing
    actions, pushing any earlier ones further right (confirmed empirically) -- so a field
    wanting its own trailing action *outside* this one (e.g. a calendar popup) must add its action
    first, at construction, before the line edit is ever shown.

    :param parent: optional ``QObject`` parent.
    """

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        # App-wide filter: invoked for every event of every object, so the common path stays a bare
        # event-type compare. Only a plain line edit's first Show needs work here; the far more
        # frequent per-repaint resync lives on a per-widget filter (see __ensure_clear_action).
        if (
            event.type() == QEvent.Type.Show
            and isinstance(watched, QLineEdit)
            and not watched.isClearButtonEnabled()
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

    @staticmethod
    def action_of(line_edit: QLineEdit) -> QAction | None:
        """Find ``line_edit``'s clear action, if it has one.

        :param line_edit: the line edit to look in.
        :returns: the action, as a live wrapper, else ``None``.
        """
        return next((action for action in line_edit.actions() if action.objectName() == ACTION_NAME), None)

    def __ensure_clear_action(self, line_edit: QLineEdit) -> None:
        """Equip ``line_edit`` with its clear action once; a no-op on a later ``Show`` of an equipped one.

        An action deleted out from under a live line edit (#365) is simply missing here and is made again; one
        whose wrapper alone died (#459) is found by name and left be, so there is never a second one.

        :param line_edit: the line edit to equip.
        """
        resync = line_edit.findChild(self.__Resync)
        if resync is None:
            # once per line edit, for its whole life: connected here and never again, so a re-equipped action
            # does not stack a second listener
            resync = self.__Resync(line_edit)
            line_edit.installEventFilter(resync)
            line_edit.textChanged.connect(resync.sync)
        if self.action_of(line_edit) is None:
            icon = line_edit.style().standardIcon(QStyle.StandardPixmap.SP_LineEditClearButton, None, line_edit)
            action = line_edit.addAction(icon, QLineEdit.ActionPosition.TrailingPosition)
            action.setObjectName(ACTION_NAME)
            action.setToolTip("Clear")
            action.triggered.connect(resync.clear)
        resync.sync()

    class __Resync(QObject):  # pylint: disable=invalid-name
        """Per-line-edit helper that keeps the clear action's visibility matched to the line edit's text: on
        ``textChanged``, and on every repaint as the fallback for a signal-blocked ``setText`` that emits no
        ``textChanged`` (see :class:`LineEditClearActionFilter`'s docstring).

        Installed on a single equipped line edit only (never app-wide) and parented to it, so it dies with it.
        It holds no wrapper at all -- not the action's, looked up on the line edit by :data:`ACTION_NAME` each
        time, and not the line edit's, read from its own Qt parent each time (#459: a kept wrapper of a Qt-owned
        object can be invalidated while the object lives) -- so nothing dead is ever read back. With no action
        there is nothing to sync, and the line edit's next ``Show`` equips one.

        :param line_edit: the line edit this is installed on and parented to.
        """

        def __init__(self, line_edit: QLineEdit) -> None:
            super().__init__(line_edit)

        @property
        def __line_edit(self) -> QLineEdit:
            """The line edit this is installed on: its Qt parent, fetched anew so the wrapper is a live one."""
            return cast(QLineEdit, self.parent())

        def sync(self, *_args: object) -> None:
            """Show the clear action while the line edit holds text.

            :param _args: ``textChanged``'s text, unused: the line edit is asked.
            """
            line_edit = self.__line_edit
            action = LineEditClearActionFilter.action_of(line_edit)
            if action is not None:
                action.setVisible(bool(line_edit.text()))

        def clear(self) -> None:
            """Clear the line edit's text and restore keyboard focus to it -- what the clear action does."""
            line_edit = self.__line_edit
            line_edit.clear()
            line_edit.setFocus()

        @override
        def eventFilter(self, watched: QObject, event: QEvent) -> bool:
            if event.type() == QEvent.Type.Paint and isinstance(watched, QLineEdit):
                self.sync()
            return super().eventFilter(watched, event)
