"""The ``authors`` editor: a comma line for the simple case, record rows for everything else
([[plugins#field-toolkit]], [[field-schema#authors]]).
"""

from collections.abc import Sequence
from typing import Final

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import QLineEdit, QVBoxLayout, QWidget
from rehuco_core import AuthorEntry, author_name, authors_comma_editable

from ..text_list_string import TextListString
from .authors_list_editor import AuthorsListEditor
from .authors_table_model import canonical_author_entry

SIMPLE_UNAVAILABLE_TOOLTIP: Final = (
    "Some authors have a link, or a comma in the name, that the simple editor can't show. Edit them as rows instead."
)
"""Why the simple editor is not on offer, said where the control that would switch to it is. The guard
prevents loss, it isn't a mere restriction ([[field-schema#authors]]): a comma line cannot represent a
record entry or a name containing a comma, so offering it would offer to drop one."""

SIMPLE_TOOLTIP: Final = "Names separated by commas. Switch to rows to add author links."
"""What the simple editor is, while it *is* available -- and where the other half went."""


class AuthorsEditor(QWidget):
    """Edits ``authors`` in one of two modes ([[field-schema#authors]]).

    **Simple** is the comma-separated line the other list fields use, available exactly while every
    entry survives a round-trip through it (:func:`~rehuco_core.authors_comma_editable`).
    **Advanced** is :class:`AuthorsListEditor`'s rows, which can carry an author-page URL and a name
    with a comma in it.

    **The mode never switches on its own.** Which one the user picked is remembered
    (:meth:`save_state`, per ``.rehu``); when the value cannot be shown simply, the rows are shown
    *instead* -- without touching that choice, so the moment the value is representable again the
    editor is back where the user left it. The alternative, rewriting the choice whenever the value
    happened to change shape, is how a user ends up in an editor they never asked for and cannot
    account for.

    Both halves write the same value out, so the owner binds one widget
    (:class:`~rehuco_agent.fields.field.ValueWidget`) and never learns which mode produced an edit.

    :param parent: optional Qt parent.
    """

    value_changed = Signal(object)
    """Fires with the new authors list on every user edit, from whichever mode made it."""

    mode_changed = Signal()
    """Fires when the mode being shown, or whether the simple one is available at all, changed -- what
    the owner's toggle is refreshed from."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__value: list[AuthorEntry] = []
        self.__chose_advanced = False
        """What the *user* picked, kept apart from :attr:`advanced` (what is actually shown), so a
        value the simple editor cannot represent never rewrites the choice."""

        self.__simple: Final = QLineEdit()
        self.__simple.setToolTip(SIMPLE_TOOLTIP)
        self.__advanced: Final = AuthorsListEditor()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.__simple)
        layout.addWidget(self.__advanced)

        self.__simple.textChanged.connect(self.__on_simple_edited)
        self.__advanced.values_changed.connect(self.__on_advanced_edited)
        self.__render()

    @property
    def value(self) -> list[AuthorEntry]:
        """The authors list as edited, string-or-record ([[field-schema#authors]]).

        A **list**, matching what the document holds: handing back a tuple would read as a change to
        every value comparison downstream even where nothing was edited.
        """
        return list(self.__value)

    def set_value(self, value: Sequence[AuthorEntry]) -> None:
        """Seed or echo the editor from ``value`` without reporting an edit (the echo guard).

        :param value: the authors list to show.
        """
        self.__value = [canonical_author_entry(entry) for entry in value]
        self.__render()

    @property
    def advanced(self) -> bool:
        """Whether the record rows are what is shown -- the user's choice, or forced by the value."""
        return self.__chose_advanced or not self.simple_available

    @property
    def simple_available(self) -> bool:
        """Whether the current value survives a round-trip through the comma line."""
        return authors_comma_editable(self.__value)

    def set_advanced(self, advanced: bool) -> None:
        """Pick the mode.

        Records the choice even when it cannot be honored right now (a value the simple editor cannot
        show stays in the rows), so the editor returns to it as soon as it can be.

        :param advanced: ``True`` for the record rows, ``False`` for the comma line.
        """
        if advanced == self.__chose_advanced:
            return
        self.__chose_advanced = advanced
        self.__render()

    @property
    def header_height(self) -> int:
        """The comma line's natural height (`HeaderPinned`, [[plugins#field-toolkit]]) -- the editor's
        first line in either mode, since the rows' first line is their header of the same order."""
        return self.__simple.sizeHint().height()

    def save_state(self) -> bytes:
        """Encode the chosen mode for per-``.rehu`` session persistence
        (:class:`~rehuco_agent.fields.field.StatefulWidget`).

        The **choice**, not what is being shown: a document whose authors are all records opens in the
        rows either way, and restoring "advanced" from that would silently make the choice permanent.

        :returns: a one-byte blob restorable by :meth:`restore_state`.
        """
        return b"\x01" if self.__chose_advanced else b"\x00"

    def restore_state(self, state: bytes) -> None:
        """Restore the chosen mode produced by :meth:`save_state`.

        :param state: the blob to restore from; anything but a leading ``0x01`` reads as the simple
            editor.
        """
        self.set_advanced(state[:1] == b"\x01")

    def __on_simple_edited(self, text: str) -> None:
        """Report the comma line's text as an authors list.

        :param text: the line's whole current text.
        """
        self.__set_and_report(TextListString.split(text))

    def __on_advanced_edited(self) -> None:
        """Report the rows' entries as an authors list."""
        self.__set_and_report(self.__advanced.entries)

    def __set_and_report(self, value: Sequence[AuthorEntry]) -> None:
        """Take an edit from one mode, keep the other in step with it, and report it once.

        :param value: the newly edited authors list.
        """
        self.__value = list(value)
        self.__render()
        self.value_changed.emit(self.value)

    def __render(self) -> None:
        """Show the mode in force, seed both halves from the value, and say what changed.

        Both halves are kept current, not just the visible one: switching modes then has nothing to
        do, and neither does becoming visible again after the value moved on.
        """
        advanced = self.advanced
        self.__simple.setVisible(not advanced)
        self.__advanced.setVisible(advanced)
        self.__seed_simple()
        # blocked: seeding is not an edit, and the rows report every change to their model
        with QSignalBlocker(self.__advanced):
            self.__advanced.set_entries(self.__value)
        self.mode_changed.emit()

    def __seed_simple(self) -> None:
        """Write the value into the comma line, unless it already parses to exactly that.

        Comparing the *parsed* text rather than the raw text is what keeps a user's own keystroke from
        bouncing back and resetting the cursor (the echo guard, cf. #35). A value the line cannot
        represent is still shown -- as plain names, a display the line is not enabled to write back
        from, since the rows are what is on screen then.
        """
        if self.simple_available:
            # authors_comma_editable's own guarantee: every entry is a plain string here
            names = [entry for entry in self.__value if isinstance(entry, str)]
            self.__simple.setEnabled(True)
            self.__simple.setToolTip(SIMPLE_TOOLTIP)
            if TextListString.split(self.__simple.text()) != names:
                with QSignalBlocker(self.__simple):
                    self.__simple.setText(TextListString.join(names))
            return
        self.__simple.setEnabled(False)
        self.__simple.setToolTip(SIMPLE_UNAVAILABLE_TOOLTIP)
        text = TextListString.join(author_name(entry) for entry in self.__value)
        if self.__simple.text() != text:
            with QSignalBlocker(self.__simple):
                self.__simple.setText(text)
