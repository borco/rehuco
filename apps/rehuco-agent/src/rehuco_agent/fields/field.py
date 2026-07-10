"""Field toolkit base: a `Field` binds one logical value to viewer/editor widgets ([[plugins#field-toolkit]])."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Protocol

from PySide6.QtCore import SignalInstance
from PySide6.QtWidgets import QWidget


@dataclass
class FieldBinding[T]:
    """The current value, change signal, and setter a `Field` needs to bind one widget ([[plugins#field-toolkit]]).

    Deliberately narrow: a `Field` only ever sees this, never the model that produced it, so the
    toolkit stays reusable across any model shape that can produce one ([[plugins#field-toolkit]],
    [[appendices.open-questions#still-open]]).

    :param value: the field's current value.
    :param changed: the signal that fires with the new value on every change.
    :param set_value: writes a new value through to the model.
    """

    value: T
    changed: SignalInstance
    set_value: Callable[[T], None]


class FieldModel(Protocol):  # pylint: disable=too-few-public-methods
    """What a view-model must provide for the field toolkit to bind to it
    ([[plugins#field-toolkit]], [[plugins#view-model]]).
    """

    def bind[T](self, field: Field[T]) -> FieldBinding[T]:
        """Resolve a field into its current binding.

        :param field: the field to resolve.
        :returns: the field's binding on this model.
        """
        ...  # pylint: disable=unnecessary-ellipsis


class Field[T]:
    """Base for a field: binds one logical value to the widgets that view and edit it
    ([[plugins#field-toolkit]]).

    A field is a stateless factory: :meth:`make_viewer` and :meth:`make_editors` build widgets from
    a :class:`FieldBinding` resolved by the model -- a field never holds document state itself, and
    never sees the model or view-model that produced its binding. Viewer and editor are deliberately
    separate widgets, not one widget in two modes ([[plugins#core-vs-plugin]]'s editor/viewer
    split); :meth:`make_editors` is plural so a field can surface across more than one editor later
    (the multi-editor split, A2.6/#26) without changing the base.

    :param name: the field's identifier on its model (also the default label source).
    :param label: display label; derived from ``name`` when omitted.
    """

    TYPE: str
    """The field-type selector ([[field-schema#field-types]]) the registry maps to this class. **Must be unique.**"""

    def __init__(self, name: str, label: str | None = None) -> None:
        self.__name: Final = name
        self.__label: Final = label if label is not None else self.make_label(name)

    @property
    def name(self) -> str:
        """This field's identifier on its model."""
        return self.__name

    @property
    def label(self) -> str:
        """The display label shown in the form."""
        return self.__label

    def make_viewer(self, binding: FieldBinding[T]) -> QWidget:
        """Build the read-only viewer widget bound to the given binding.

        :param binding: the resolved value/signal/setter to bind to.
        :returns: a widget that re-renders when the bound value changes.
        :raises NotImplementedError: unless a subclass overrides it.
        """
        raise NotImplementedError

    def make_editors(self, binding: FieldBinding[T]) -> list[QWidget]:
        """Build the editor widgets bound to the given binding (plural for the future multi-editor split).

        :param binding: the resolved value/signal/setter to bind to.
        :returns: the editor widgets that write back through the binding on edit.
        :raises NotImplementedError: unless a subclass overrides it.
        """
        raise NotImplementedError

    def make_misc(self, binding: FieldBinding[T], editors: list[QWidget]) -> QWidget | None:
        """Build an optional widget for the editor form's **misc** column, between the label and the
        editor ([[plugins#field-toolkit]]) -- e.g. the ``path`` field's expand/collapse toggle.

        Receives the already-built ``editors`` so it can wire to them (the toggle drives its
        `PathEditor`'s expand state). Most fields have no misc widget and return ``None`` (the base
        default), leaving that column empty for the row.

        :param binding: the resolved value/signal/setter for this field.
        :param editors: the widgets :meth:`make_editors` just returned for this field.
        :returns: the misc widget, or ``None`` for none (the base default).
        """
        del binding, editors  # interface params, unused by the base (no misc widget)

    @staticmethod
    def make_label(name: str) -> str:
        """Derive a display label from a field name (``foo_bar`` / ``FooBar`` -> ``Foo Bar``).

        :param name: the field name.
        :returns: the title-cased, word-split label; empty for an empty name.
        """
        return " ".join(Field.__camel_case_split(name)).replace("_", " ").title() if name else ""

    @staticmethod
    def __camel_case_split(value: str) -> list[str]:
        """Split a camelCase string into words, returning ``[value]`` when it isn't camelCase.

        :param value: the string to split.
        :returns: the split words.
        """
        parts = re.findall(r"[A-Z](?:[a-z]+|[A-Z]*(?=[A-Z]|$))", value)
        return parts if "".join(parts) == value else [value]
