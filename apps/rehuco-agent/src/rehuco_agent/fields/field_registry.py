"""Maps a field-type string to its `Field` subclass so type lists resolve declaratively ([[plugins#field-toolkit]])."""

from typing import Any, Final

from rehuco_agent.fields.boolean_field import BooleanField
from rehuco_agent.fields.date_field import DateField
from rehuco_agent.fields.duration_field import DurationField
from rehuco_agent.fields.field import Field
from rehuco_agent.fields.file_size_field import FileSizeField
from rehuco_agent.fields.int_field import IntField
from rehuco_agent.fields.multiple_choice_field import MultipleChoiceField
from rehuco_agent.fields.path_field import PathField
from rehuco_agent.fields.rating_field import RatingField
from rehuco_agent.fields.text_field import TextField
from rehuco_agent.fields.text_list_field import TextListField
from rehuco_agent.fields.url_field import UrlField


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
            DateField,
            DurationField,
            FileSizeField,
            MultipleChoiceField,
            PathField,
        ):
            self.__types[field_type.TYPE] = field_type

    @property
    def types(self) -> dict[str, type[Field[Any]]]:
        """The registered ``type`` -> :class:`Field` subclass mapping."""
        return self.__types

    def create(self, type_: str, name: str, label: str | None = None, **kwargs: Any) -> Field[Any]:
        """Instantiate the field registered for ``type_``.

        :param type_: the field-type selector.
        :param name: the field's identifier on its model.
        :param label: optional display label; derived from ``name`` when omitted.
        :param kwargs: extra constructor arguments a specific type needs (e.g.
            :class:`~rehuco_agent.fields.multiple_choice_field.MultipleChoiceField`'s ``choices``).
        :returns: a new field instance.
        :raises KeyError: if ``type_`` is not registered (the unknown-field fallback is A2.8/#28).
        """
        return self.__types[type_](name, label, **kwargs)
