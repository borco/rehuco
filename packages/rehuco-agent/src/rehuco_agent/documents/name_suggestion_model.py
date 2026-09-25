"""The rename-suggestion **compute** role, extracted out of `RehuDocumentModel`
([[plugins#field-toolkit]], §13.2.1, #46): the source `PathField` displays and the view-model's
`rename_location` ultimately executes.
"""

from typing import Final

from borco_pyside.core import SimpleProperty
from PySide6.QtCore import QObject, Signal
from rehuco_core import author_name

from ..settings.location_templates_settings import (
    known_placeholders_for,
    render_location_pattern,
    shared_location_templates_settings,
)
from .rehu_document_model import RehuDocumentModel

NAME_SUGGESTION_SOURCE_FIELDS: Final = ("title", "authors", "publisher", "released", "advertised_count")
"""The fields a pattern from `LocationTemplatesSettings` interpolates; a change to any of them re-emits
:attr:`NameSuggestionModel.changed` so a `PathField` re-pulls the suggestions live."""

FALLBACK_RESOURCE_TYPE: Final = "tutorial"
"""What a foreign or typeless document's suggestions fall back to (#322): a type no installed plugin here
claims still gets a usable list rather than an empty one."""


class NameSuggestionModel(QObject):
    """Builds rename-candidate names from a `RehuDocumentModel`'s record fields ([[plugins#field-toolkit]]).

    Subscribes to :data:`NAME_SUGGESTION_SOURCE_FIELDS`' notify signals on ``model``, to
    ``model.resource_type_changed``, and to `LocationTemplatesSettings.patterns_changed`, so
    :attr:`changed` fires whenever a field :meth:`suggestions` is built from changes -- editing
    ``authors``, switching the document's type, or applying a Locations settings page all update the
    offered names without a reopen (#322). This is the **compute** role in the field toolkit's
    compute/present-command/execute split (§13.2.1): a `PathField` presents :meth:`suggestions` and
    forwards a clicked one as a command, and ``model.rename_location`` executes it -- this class
    never touches the filesystem.

    :param model: the record fields (``title`` / ``publisher`` / ``authors`` / ``released`` / ``advertised_count`` /
        ``resource_type``) to build suggestions from.
    :param parent: optional Qt parent; the caller typically parents this to ``model`` so its lifetime
        matches.
    """

    changed = Signal()
    """Fires when a field :meth:`suggestions` is built from (:data:`NAME_SUGGESTION_SOURCE_FIELDS`, the
    document's type, or the Locations settings) changes, so a `PathField` can re-pull it live."""

    def __init__(self, model: RehuDocumentModel, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__model: Final = model
        for name in NAME_SUGGESTION_SOURCE_FIELDS:
            signal_name = SimpleProperty.notify_signal_name(type(model), name)
            getattr(model, signal_name).connect(lambda *_: self.changed.emit())
        model.resource_type_changed.connect(self.changed)  # type: ignore[attr-defined]
        shared_location_templates_settings().patterns_changed.connect(self.changed)

    def suggestions(self) -> list[str]:
        """Build the rename-candidate names via this document type's `LocationTemplatesSettings` list.

        Raw strings only -- interpolated from ``title`` / ``publisher`` / joined ``authors`` / the
        released ``year`` / the advertised ``count`` -- left unsanitized; the `PathField` editor transliterates and
        filesystem-sanitizes them before display, and drops any that reduce to nothing. ``released``
        may be ``None`` (absent, [[field-schema#deferred-items]]) -- the year is empty then, same as
        for a too-short ``released`` string, and a pattern's ``{{ [{year}]}}`` group drops out with it.

        Two patterns rendering the same name are **merged** here, where the names are computed: a
        title-only record renders every shipped default to the bare title, which is one suggestion,
        not four. A pattern rendering to nothing at all is dropped for the same reason.

        ``count`` is always in ``values`` -- the model carries `~RehuDocumentModel.advertised_count`
        whatever the type -- but only a type declaring it (ReferenceImages, #349) has it among its
        :func:`~rehuco_agent.settings.location_templates_settings.known_placeholders_for`, so a pattern
        naming ``{count}`` never reaches here for any other type.

        :returns: the distinct candidate strings, in the order their patterns first produced them.
        """
        values = {
            "title": self.__model.title,
            "publisher": self.__model.publisher,
            "authors": ", ".join(author_name(entry) for entry in self.__model.authors),
            "year": (self.__model.released or "")[:4],
            "count": self.__model.advertised_count or "",
        }
        plugins = self.__model.document.plugins
        main_key = plugins.main_key(self.__model.resource_type)
        if main_key not in plugins:
            main_key = FALLBACK_RESOURCE_TYPE
        known_placeholders = known_placeholders_for(plugins.field_names(main_key))
        patterns = shared_location_templates_settings().patterns_for(main_key, known_placeholders)
        rendered = (render_location_pattern(pattern, values, known_placeholders) for pattern in patterns)
        return list(dict.fromkeys(name for name in rendered if name))
