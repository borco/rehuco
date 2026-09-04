"""Protocol for one settings dialog category page (#47)."""

from typing import Protocol, runtime_checkable


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
