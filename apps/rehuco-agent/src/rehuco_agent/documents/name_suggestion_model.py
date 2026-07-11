"""The rename-suggestion **compute** role, extracted out of `RehuDocumentModel`
([[plugins#field-toolkit]], §13.2.1, #46): the source `PathField` displays and the view-model's
`rename_location` ultimately executes.
"""

from typing import Final

from borco_pyside.core import SimpleProperty
from PySide6.QtCore import QObject, Signal

from rehuco_agent.documents.rehu_document_model import RehuDocumentModel

NAME_SUGGESTION_PATTERNS: Final = (
    "{title}",
    "{publisher} - {title}",
    "{title} [{year}]",
    "{authors} - {title}",
)
"""The folder/file-name suggestion patterns offered when renaming a resource ([[field-schema#field-mapping]]):
each is formatted from the record's own fields (``title`` / ``publisher`` / ``authors`` / the released
``year``) into a candidate name. A constant for now; a future revision may make it configurable."""

NAME_SUGGESTION_SOURCE_FIELDS: Final = ("title", "authors", "publisher", "released")
"""The fields :data:`NAME_SUGGESTION_PATTERNS` interpolate; a change to any of them re-emits
:attr:`NameSuggestionModel.changed` so a `PathField` re-pulls the suggestions live."""


class NameSuggestionModel(QObject):
    """Builds rename-candidate names from a `RehuDocumentModel`'s record fields ([[plugins#field-toolkit]]).

    Subscribes to :data:`NAME_SUGGESTION_SOURCE_FIELDS`' notify signals on ``model`` so
    :attr:`changed` fires whenever a field :meth:`suggestions` is built from changes -- e.g. editing
    ``authors`` updates the offered names. This is the **compute** role in the field toolkit's
    compute/present-command/execute split (§13.2.1): a `PathField` presents :meth:`suggestions` and
    forwards a clicked one as a command, and ``model.rename_location`` executes it -- this class
    never touches the filesystem.

    :param model: the record fields (``title`` / ``publisher`` / ``authors`` / ``released``) to build
        suggestions from.
    :param parent: optional Qt parent; the caller typically parents this to ``model`` so its lifetime
        matches.
    """

    changed = Signal()
    """Fires when a field :meth:`suggestions` is built from (:data:`NAME_SUGGESTION_SOURCE_FIELDS`)
    changes, so a `PathField` can re-pull it live."""

    def __init__(self, model: RehuDocumentModel, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__model: Final = model
        for name in NAME_SUGGESTION_SOURCE_FIELDS:
            signal_name = SimpleProperty.notify_signal_name(type(model), name)
            getattr(model, signal_name).connect(lambda *_: self.changed.emit())

    def suggestions(self) -> list[str]:
        """Build the rename-candidate names via :data:`NAME_SUGGESTION_PATTERNS`.

        Raw strings only -- interpolated from ``title`` / ``publisher`` / joined ``authors`` / the
        released ``year`` -- left unsanitized; the `PathField` editor transliterates and
        filesystem-sanitizes them before display, and drops any that reduce to nothing.

        :returns: one candidate string per pattern, in pattern order.
        """
        values = {
            "title": self.__model.title,
            "publisher": self.__model.publisher,
            "authors": ", ".join(self.__model.authors),
            "year": self.__model.released[:4],
        }
        return [pattern.format(**values) for pattern in NAME_SUGGESTION_PATTERNS]
