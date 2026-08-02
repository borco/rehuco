"""The `indexed list` leaf field: a read-only list of named entries carrying a position
([[plugins#field-toolkit]], [[field-schema#field-types]]).
"""

from collections.abc import Sequence
from typing import Protocol, override

from PySide6.QtWidgets import QLabel, QWidget

from .field import Field, FieldBinding, FieldEditorWidgets, FieldViewerWidgets
from .text_list_string import TextListString

UNPLACED_INDEX = 0
"""The index that means **no position chosen**, and so renders as no position at all.

A legacy import writes it for every entry it creates ([[field-schema#sources]]) -- tc4's list order was
never a curated position -- and an entry that simply omits its index reads as this too. Printing
``[0]`` there would show a placement nobody made; it is also indistinguishable from a genuine zero, but
that collision is the storage's (absent and zero are already the same value), not this rendering's."""


class IndexedEntry(Protocol):
    """What this field needs of a value to render it: a name, and where the resource sits in it.

    A **rendering** contract, deliberately not a shared domain type: the document's ``collections`` and
    ``learning_paths`` are unrelated things that a viewer happens to present the same way -- one is a
    publisher's series, the other is somebody's curated order -- so each keeps its own type in the core
    (`CollectionEntry` / `LearningPathEntry`) and they meet only here, in a widget. Their editors part
    ways again in #235, where each gets a table with its own columns.
    """

    @property
    def title(self) -> str:
        """The entry's display name."""
        ...  # pylint: disable=unnecessary-ellipsis

    @property
    def index(self) -> int:
        """Where this resource sits in it; :data:`UNPLACED_INDEX` for no position."""
        ...  # pylint: disable=unnecessary-ellipsis


class IndexedListField(Field[Sequence[IndexedEntry]]):
    """An ``indexed list`` field ([[plugins#field-toolkit]]): the viewer renders each entry as
    ``Title [3]`` -- or bare ``Title`` when it carries no position -- comma-joined, in the order the
    model resolved them in.

    Covers both of the document's record-list fields, ``collections`` ([[field-schema#sources]]) and
    ``learning_paths`` ([[field-schema#learning-path-ownership]]), through the `IndexedEntry` contract
    above rather than by knowing either.

    **Viewer-only** for now: :meth:`make_editor` returns an all-``None`` bundle, so the field adds a row
    to the viewer and none to the editor. Editing these needs a table -- sortable, filterable, and with
    per-field columns an owner only one of them has -- which is #235's memberships table; a comma
    line like the tag fields' could not carry the index, let alone the ownership.

    **An empty list hides the whole row** rather than showing an empty value, the same rule the image
    strip follows for a resource with no screenshots: most resources belong to nothing, and a permanently
    blank row teaches the reader to skip that part of the form. The row comes back live when the value
    does -- a revert, or a type switch to a block that has entries.
    """

    TYPE = "indexed_list"

    @override
    def make_viewer(self, binding: FieldBinding[Sequence[IndexedEntry]]) -> FieldViewerWidgets:
        label = self.make_label()
        viewer = QLabel()
        viewer.setWordWrap(True)
        # the row's cells, collected once: hiding *every* cell is what collapses the row, so an absent
        # label (a field built without one) simply isn't among them
        row = [widget for widget in (label, viewer) if widget is not None]
        self.__apply(row, viewer, binding.value)
        self.bind_external(binding.changed, lambda value: self.__apply(row, viewer, value))
        return FieldViewerWidgets(self.viewer_tab, label, viewer)

    @override
    def make_editor(self, binding: FieldBinding[Sequence[IndexedEntry]]) -> FieldEditorWidgets:
        # read-only until #235's memberships table: an all-``None`` bundle, so the assembler drops the
        # row entirely rather than showing a disabled one promising an edit that isn't there
        return FieldEditorWidgets(self.editor_tab, None, None)

    def __apply(self, row: Sequence[QWidget], viewer: QLabel, entries: Sequence[IndexedEntry]) -> None:
        """Render ``entries`` into the viewer and show or hide the whole row to match.

        Hiding every cell of a grid row collapses it (the row takes no height), the same mechanism the
        unknown-field fallback uses for a dropped key.

        :param row: the row's cells, label included, shown or hidden together.
        :param viewer: the value label to render into.
        :param entries: the entries to show; empty hides the row.
        """
        viewer.setText(self.display(entries))
        for widget in row:
            if entries and widget.parentWidget() is None:
                # never force a *show* while still parentless: setVisible(True) on a parentless widget
                # flashes it as a bare top-level window of its own (the lesson `ImageStrip` records).
                # A widget built and seeded before the form parents it is shown with that parent anyway,
                # so there is nothing to do here beyond leaving it alone.
                continue
            widget.setVisible(bool(entries))

    @staticmethod
    def display(entries: Sequence[IndexedEntry]) -> str:
        """Render the entries as the viewer's text.

        :param entries: the entries, already in display order.
        :returns: ``Title [index]`` per entry -- the title alone at :data:`UNPLACED_INDEX` -- comma-joined:
            a display form only, never re-parsed (unlike the comma text the tag editors round-trip through).
        """
        return TextListString.join(
            entry.title if entry.index == UNPLACED_INDEX else f"{entry.title} [{entry.index}]" for entry in entries
        )
