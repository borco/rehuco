"""App-wide `QLineEdit` clear action, added to every line edit as it becomes visible."""

from typing import Final, override

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QAbstractSpinBox, QComboBox, QLineEdit, QStyle
from shiboken6 import isValid

ACTION_PROPERTY: Final = "_borco_clear_action"
"""The dynamic property a line edit's clear action is stashed under, read back by
:meth:`LineEditClearActionFilter.__ensure_clear_action` to skip an already-equipped line edit.

Module-level rather than a ``__``-private attribute of the filter class: it is also read from
``__PaintResyncFilter``, a *nested* class, whose body mangles a ``__name`` against its own name and so
cannot reach a name-mangled attribute of its lexically enclosing class.

**Reading it back after its action has died crashes** -- an access violation, not a catchable
exception (#365; confirmed on a stock ``QLineEdit`` with the stored ``QAction`` deleted, no filter of
this module's involved). Qt keeps the ``QVariant`` over the now-dangling ``QObject*`` and
``QObject.property()`` hands it to shiboken to re-wrap; the exact step that faults is not pinned down,
and does not need to be: the resync filter below clears this property back to ``None`` itself the
moment it notices its action died, so it is never read back stale. ``setProperty`` only stores a new
``QVariant`` and never dereferences the old one, so the overwrite is safe where the read is not.
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

    def __ensure_clear_action(self, line_edit: QLineEdit) -> None:
        """Install ``line_edit``'s clear action once; a no-op on a later ``Show`` of the same widget.

        Also the recovery path for #365 (something deleting the clear action out from under a
        still-live line edit, e.g. from a QtAds auto-hide pin/unpin round trip; the deleter itself is
        still unidentified): this re-equips a fresh action whenever the stored property reads back
        ``None``, which is exactly what the resync filter below leaves behind once it notices the
        action it was tracking has died.

        :param line_edit: the line edit to equip.
        """
        if line_edit.property(ACTION_PROPERTY) is not None:
            return
        icon = line_edit.style().standardIcon(QStyle.StandardPixmap.SP_LineEditClearButton, None, line_edit)
        action = line_edit.addAction(icon, QLineEdit.ActionPosition.TrailingPosition)
        action.setToolTip("Clear")
        action.setVisible(bool(line_edit.text()))
        # as exposed to a dead action as the paint-resync filter is (#365), and guarded the same way
        line_edit.textChanged.connect(lambda text: action.setVisible(bool(text)) if isValid(action) else None)
        action.triggered.connect(lambda: self.__clear(line_edit))
        line_edit.setProperty(ACTION_PROPERTY, action)
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

        Something can delete ``action`` while the line edit it belongs to lives on (#365: seen from a
        QtAds auto-hide pin/unpin round trip; the deleter itself is still unidentified). Every repaint
        after that used to raise, forever, since ``action`` is a dead C++ object this filter still
        holds -- so a repaint first checks it is still alive and, if not, drops itself out, once. It
        also clears the line edit's stored-action property back to ``None`` right then, rather than
        leaving it holding a ``QVariant`` over a now-dangling pointer: reading that back is what
        crashes (see :data:`ACTION_PROPERTY`), not merely stale, so clearing it here is what lets
        :meth:`~LineEditClearActionFilter.__ensure_clear_action` re-equip a fresh one on the line
        edit's next ``Show`` without ever reading the dead one back.

        :param action: the clear action whose visibility to keep in sync.
        :param parent: the line edit this filter is installed on and parented to.
        """

        def __init__(self, action: QAction, parent: QLineEdit) -> None:
            super().__init__(parent)
            self.__action: Final = action

        @override
        def eventFilter(self, watched: QObject, event: QEvent) -> bool:
            if event.type() == QEvent.Type.Paint and isinstance(watched, QLineEdit):
                if isValid(self.__action):
                    self.__action.setVisible(bool(watched.text()))
                else:
                    watched.setProperty(ACTION_PROPERTY, None)
                    watched.removeEventFilter(self)
                    self.deleteLater()
            return super().eventFilter(watched, event)
