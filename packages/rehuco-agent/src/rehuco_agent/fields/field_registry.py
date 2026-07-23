"""Maps a field-type string to its `Field` subclass so type lists resolve declaratively ([[plugins#field-toolkit]])."""

from typing import Any, Final

from .authors_field import AuthorsField
from .boolean_field import BooleanField
from .date_field import DateField
from .description_field import DescriptionField
from .duration_field import DurationField
from .field import Field, FieldsTab
from .file_size_field import FileSizeField
from .int_field import IntField
from .multiple_choice_field import MultipleChoiceField
from .path_field import PathField
from .rating_field import RatingField
from .text_field import TextField
from .text_list_field import TextListField
from .type_field import TypeField
from .url_field import UrlField


class FieldRegistry:
    """Resolves a field ``type`` selector to its :class:`Field` subclass ([[plugins#field-toolkit]]).

    :param field_types: the field classes to register; defaults to the built-in toolkit types.
    """

    def __init__(self, *field_types: type[Field[Any]]) -> None:
        self.__types: Final[dict[str, type[Field[Any]]]] = {}
        for field_type in field_types or (
            TextField,
            BooleanField,
            RatingField,
            IntField,
            TextListField,
            UrlField,
            AuthorsField,
            DateField,
            DurationField,
            FileSizeField,
            MultipleChoiceField,
            PathField,
            TypeField,
            DescriptionField,
        ):
            self.__types[field_type.TYPE] = field_type

    @property
    def types(self) -> dict[str, type[Field[Any]]]:
        """The registered ``type`` -> :class:`Field` subclass mapping."""
        return self.__types

    def create(
        self,
        type_: str,
        name: str,
        label: str | None = None,
        *,
        viewer_tab: FieldsTab,
        editor_tab: FieldsTab,
        **kwargs: Any,
    ) -> Field[Any]:
        """Instantiate the field registered for ``type_``.

        :param type_: the field-type selector.
        :param name: the field's identifier on its model.
        :param label: optional display label; derived from ``name`` when omitted.
        :param viewer_tab: the surface the field's viewer belongs to (passed to the field).
        :param editor_tab: the surface the field's editor belongs to (passed to the field).
        :param kwargs: extra constructor arguments a specific type needs (e.g.
            :class:`~rehuco_agent.fields.multiple_choice_field.MultipleChoiceField`'s ``choices``).
        :returns: a new field instance.
        :raises KeyError: if ``type_`` is not registered (the unknown-field fallback is #28).
        """
        return self.__types[type_](name, label, viewer_tab=viewer_tab, editor_tab=editor_tab, **kwargs)
