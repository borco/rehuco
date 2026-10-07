"""Protocol for one settings dialog category page (#47)."""

from typing import Protocol, runtime_checkable

from PySide6.QtCore import SignalInstance
from PySide6.QtWidgets import QFrame


@runtime_checkable
class SettingsPage(Protocol):
    """A single category page in the settings dialog's filterable tree + stacked pages.

    Implementers are ordinary ``QWidget`` subclasses (``.ui``-backed, per
    [[appendices.code-conventions]]) that additionally satisfy this shape -- matching the
    ``StatefulWidget``/``FieldModel`` structural-protocol style already used for the field toolkit
    (:class:`rehuco_agent.fields.field.StatefulWidget`). ``SettingsDialog.add_page`` narrows a page
    back to ``QWidget`` where it actually needs one (e.g. to add it to the stacked widget).
    """

    def is_dirty(self) -> bool:  # pyright: ignore[reportReturnType]
        """Whether this page has unsaved changes.

        `SettingsDialog` polls this to badge the page's category-tree row, enable/disable its
        Apply/Reset actions, and -- while auto-apply is on -- commit the page (#77).
        """

    def save_changes(self) -> None:
        """Persist this page's current field values."""

    def drop_changes(self) -> None:
        """Discard this page's in-progress edits, reverting its fields to the last-saved values."""

    def seed_defaults(self) -> None:
        """Fill this page's fields with their **factory** values -- what a fresh install would show
        (#342).

        A staged edit like typing: nothing is saved, so Apply still decides. `SettingsDialog.add_page`
        calls it once, to capture each frame's defaults snapshot, then ``drop_changes`` to put the
        saved values back; the toolbar's Defaults / Defaults All call it on demand.
        """


@runtime_checkable
class ExternallySavedPage(Protocol):  # pylint: disable=too-few-public-methods
    """The optional signal a page has when what it edits can also be **saved from elsewhere** (#457).

    The saved value is then not only what Apply wrote: a menu toggle applies the same setting at once. The page emits
    ``saved_changed`` whenever the saved value changes, and the dialog rebases the page: a frame with no edit shows the
    new saved value and stays clean, one with an edit keeps it -- compared now with the new saved value, so an edit
    that equals it is no longer one -- and *Reset* restores the new saved value.
    """

    @property
    def saved_changed(self) -> SignalInstance:  # pyright: ignore[reportReturnType]
        """Emitted whenever the saved value changes, by anyone."""


@runtime_checkable
class SaveGatedPage(Protocol):  # pylint: disable=too-few-public-methods
    """The optional hook a page implements to refuse a commit while its staged values are not savable.

    A page that does not satisfy this shape can always save. The dialog reads it in Apply enablement (the
    toolbar and each frame's header) and in the auto-apply path, and skips a commit it forbids -- the page
    stays dirty, showing what it holds, until the edits are fixed or reset. A page should also refuse in
    ``save_changes`` itself, as a last line of defence.
    """

    def can_save(self) -> bool:  # pyright: ignore[reportReturnType]
        """Whether the staged values may be committed now."""


@runtime_checkable
class FrameRestoringPage(Protocol):
    """The optional hooks a page implements to take over its frames' Apply, Reset and Defaults
    buttons (#342).

    The dialog's generic path writes a captured snapshot back into a frame's value widgets by type,
    and commits one frame by parking the others around the whole-page save -- which covers every
    plain control. A page implements these instead when that path cannot see all of its state: an
    editor that is not a value widget (a table model the filter cannot read), or a value kept *off*
    its widgets that a write-back would clobber (`DescriptionsPage`'s draft of the engine not shown).
    The dialog prefers them whenever the page satisfies this shape. Each acts on one frame; the two
    restores stage only, exactly as the generic path does.
    """

    def apply_frame(self, frame: QFrame) -> None:
        """Persist ``frame``'s staged values, and only those."""

    def reset_frame(self, frame: QFrame) -> None:
        """Put ``frame``'s controls back to the last-saved values."""

    def restore_frame_defaults(self, frame: QFrame) -> None:
        """Put ``frame``'s controls back to their factory values."""
