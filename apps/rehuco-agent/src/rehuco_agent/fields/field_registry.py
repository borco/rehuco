"""Maps a field-type string to its `Field` subclass so type lists resolve declaratively (§13.2.1)."""

from typing import Any, Final

from rehuco_agent.fields.field import Field
from rehuco_agent.fields.text_field import TextField


class FieldRegistry:
    """Resolves a field ``type`` selector to its :class:`Field` subclass (§13.2.1).

    :param field_types: the field classes to register; defaults to the built-in toolkit types.
    """

    def __init__(self, *field_types: type[Field[Any]]) -> None:
        self.__types: Final[dict[str, type[Field[Any]]]] = {}
        for field_type in field_types or (TextField,):
            self.__types[field_type.TYPE] = field_type

    @property
    def types(self) -> dict[str, type[Field[Any]]]:
        """The registered ``type`` -> :class:`Field` subclass mapping."""
        return self.__types

    def create(self, type_: str, name: str, label: str | None = None) -> Field[Any]:
        """Instantiate the field registered for ``type_``.

        :param type_: the field-type selector.
        :param name: the field's identifier on its model.
        :param label: optional display label; derived from ``name`` when omitted.
        :returns: a new field instance.
        :raises KeyError: if ``type_`` is not registered (the unknown-field fallback is A2.8/#28).
        """
        return self.__types[type_](name, label)
