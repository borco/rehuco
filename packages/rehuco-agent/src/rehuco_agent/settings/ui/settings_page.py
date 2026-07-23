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

    @property
    def title(self) -> str:
        """This page's label in the category tree."""
        ...  # pylint: disable=unnecessary-ellipsis

    def is_dirty(self) -> bool:
        """Whether this page has unsaved changes.

        Reserved for a later dirty-badging slice -- not yet consumed by `SettingsDialog`.
        """
        ...  # pylint: disable=unnecessary-ellipsis

    def save_changes(self) -> None:
        """Persist this page's current field values."""
        ...  # pylint: disable=unnecessary-ellipsis

    def drop_changes(self) -> None:
        """Discard this page's in-progress edits, reverting its fields to the last-saved values."""
        ...  # pylint: disable=unnecessary-ellipsis
