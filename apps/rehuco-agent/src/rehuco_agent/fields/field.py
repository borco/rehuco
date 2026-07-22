"""Field toolkit base: a `Field` binds one logical value to viewer/editor widgets ([[plugins#field-toolkit]])."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Protocol, runtime_checkable

from borco_pyside.core import ConnectionList
from PySide6.QtCore import SignalInstance
from PySide6.QtWidgets import QLabel, QWidget


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


@dataclass(frozen=True)
class FieldsTab:
    """A viewer/editor **surface** identity ([[plugins#field-toolkit]]): a dock's tab title and its
    theme-aware SVG icon. Fields declare which tab their widgets belong to, and the assembler groups
    the fields sharing a tab into one dock.

    :param text: the dock/tab title.
    :param icon: the light-theme SVG qrc resource path (e.g. ``:/icons/document_viewer.svg``); the
        assembler renders it theme-aware, so it is set once here and never thought about again.
    """

    text: str
    icon: str


@dataclass
class FieldViewerWidgets:
    """The widgets a field contributes to one viewer row ([[plugins#field-toolkit]]): the surface it
    belongs to, its name ``label``, and its ``viewer``. Any slot may be ``None`` -- the assembler
    leaves that column empty, drops the row when every slot is ``None``, and drops a tab that ends up
    with no rows.

    :param tab: the viewer surface this row belongs to.
    :param label: the field's name label, or ``None`` for none.
    :param viewer: the read-only value widget, or ``None`` for none.
    :param vertical: when ``True``, the row spans the whole grid width with the ``label`` stacked
        above the ``viewer`` instead of side by side; defaults to ``False``.
    :param fill: when ``True``, this row **takes all the available vertical space** on its tab -- the
        assembler gives it the leftover height (e.g. the prose ``description``, the image strip).
        When no row on a tab fills, the assembler instead packs the rows at the top so they keep their
        natural height rather than stretching apart. Independent of :attr:`vertical` (a full-width row
        need not fill, and vice versa); defaults to ``False``.
    """

    tab: FieldsTab
    label: QWidget | None
    viewer: QWidget | None
    vertical: bool = False
    fill: bool = False


@dataclass
class FieldEditorWidgets:
    """The widgets a field contributes to one editor row ([[plugins#field-toolkit]]): the surface it
    belongs to, its name ``label``, an optional ``misc`` control (middle column, e.g. the ``path``
    field's expand toggle), and its ``editor``. Any slot may be ``None`` with the same cascade as
    :class:`FieldViewerWidgets`.

    :param tab: the editor surface this row belongs to.
    :param label: the field's name label, or ``None`` for none.
    :param editor: the editor widget, or ``None`` for none.
    :param misc: the optional middle-column control (e.g. the ``path`` expand toggle); defaults to
        ``None``.
    :param vertical: when ``True``, the row spans the whole grid width with the ``label`` (and
        ``misc``, if any) stacked above the ``editor`` instead of side by side; defaults to ``False``.
    :param fill: when ``True``, this row **takes all the available vertical space** on its tab -- the
        assembler gives it the leftover height (e.g. the prose ``description`` editor, the image
        selector). When no row on a tab fills, the assembler instead packs the rows at the top so they
        keep their natural height. Independent of :attr:`vertical`; defaults to ``False``.
    """

    tab: FieldsTab
    label: QWidget | None
    editor: QWidget | None
    misc: QWidget | None = None
    vertical: bool = False
    fill: bool = False


@runtime_checkable
class ValueWidget[T](Protocol):
    """The **value-widget contract** a content field's editor satisfies ([[plugins#field-toolkit]]):
    a ``value`` property, a ``value_changed`` signal, and a ``set_value`` slot -- as ``DurationEdit`` /
    ``FileSizeEdit`` / ``DateEdit`` / ``LineEdit`` already do. :meth:`Field.bind_value_widget` binds any
    such widget two-way to a :class:`FieldBinding` in one call, so the standard four-line wiring lives
    once instead of per field. A scalar-or-list value fits directly (a ``multi_choice`` editor is just
    ``value: list[str]`` + ``value_changed``). The ``path`` field is deliberately **not** a value widget
    -- it is a location control, not content ([[plugins#field-toolkit]], #46).
    """

    @property
    def value(self) -> T:
        """The widget's current value."""
        ...  # pylint: disable=unnecessary-ellipsis

    @property
    def value_changed(self) -> SignalInstance:
        """The signal that fires with the new value on every user edit."""
        ...  # pylint: disable=unnecessary-ellipsis

    def set_value(self, value: T) -> None:
        """Write ``value`` in without re-emitting ``value_changed`` (the echo guard).

        :param value: the new value.
        """
        ...  # pylint: disable=unnecessary-ellipsis


@runtime_checkable
class StatefulWidget(Protocol):
    """A widget that persists its own UI state ([[plugins#field-toolkit]]) -- e.g. the ``path``
    editor's expand state. The assembler collects the widgets in a field's bundle that satisfy this
    protocol, keyed by field, and folds their state into the document's saved layout.
    """

    def save_state(self) -> bytes:
        """Encode this widget's UI state.

        :returns: the opaque blob, restorable by :meth:`restore_state`.
        """
        ...  # pylint: disable=unnecessary-ellipsis

    def restore_state(self, state: bytes) -> None:
        """Restore UI state previously produced by :meth:`save_state`.

        :param state: the blob to restore from.
        """
        ...  # pylint: disable=unnecessary-ellipsis


@runtime_checkable
class HeaderPinned(Protocol):  # pylint: disable=too-few-public-methods
    """An editor whose overall height can change after construction -- a collapsible panel (the
    ``path`` editor's suggestions list), a reflowing group (``multi_choice``'s checkbox `FlowLayout`)
    -- while its **first line** stays a stable height. `FieldsForm` pins a row's label (and optional
    ``misc`` control) to that first line instead of re-centering them against the row's live height,
    which would otherwise make them visibly jump as the editor grows or shrinks.
    """

    @property
    def header_height(self) -> int:
        """This editor's first line's natural height, stable regardless of whatever makes the
        editor's overall height vary."""
        ...  # pylint: disable=unnecessary-ellipsis


@runtime_checkable
class StatusReporter(Protocol):  # pylint: disable=too-few-public-methods
    """A field that reports a transient status-bar message ([[plugins#field-toolkit]]) -- e.g. the
    ``authors`` viewer announcing a hovered link's URL (:class:`~rehuco_agent.fields.authors_field.AuthorsField`).

    The field emits ``status_message`` and its **owner routes it** to the real status bar; a toolkit
    field never reaches for app chrome it does not own. The owner (`DocumentWidget`) collects the fields
    satisfying this protocol -- by protocol, not by field type -- and bubbles their messages up to the
    genuine top-level window's status bar (:meth:`FieldsForm.connect_status_messages`).
    """

    status_message: SignalInstance
    """Fires with the message text to show; an empty string clears it."""


class Field[T]:
    """Base for a field: binds one logical value to the widgets that view and edit it
    ([[plugins#field-toolkit]]).

    A field is a stateless factory: :meth:`make_viewer` and :meth:`make_editor` each build a widget
    bundle (:class:`FieldViewerWidgets` / :class:`FieldEditorWidgets`) from a :class:`FieldBinding`
    resolved by the model -- a field never holds document state itself, and never sees the model or
    view-model that produced its binding. Viewer and editor are deliberately separate widgets, not one
    widget in two modes ([[plugins#core-vs-plugin]]'s editor/viewer split). Each field maps to **one**
    editor; the multi-*surface* split (different fields in different docks, A2.6/#26) lives in the
    assembler, not here. A field declares which :class:`FieldsTab` its viewer and editor belong to.

    :param name: the field's identifier on its model (also the default label source).
    :param label: display label; derived from ``name`` when omitted.
    :param viewer_tab: the surface this field's viewer belongs to (keyword-only, required -- the
        concrete surface constants live in the assembler layer, not the toolkit).
    :param editor_tab: the surface this field's editor belongs to (keyword-only, required).
    """

    TYPE: str
    """The field-type selector ([[field-schema#field-types]]) the registry maps to this class. **Must be unique.**"""

    def __init__(
        self,
        name: str,
        label: str | None = None,
        *,
        viewer_tab: FieldsTab,
        editor_tab: FieldsTab,
    ) -> None:
        # cooperative super() call so a field that mixes in QObject for its own signals (the
        # ``authors`` field's status_message, StatusReporter) gets QObject initialized; a no-op
        # (object.__init__) for every plain, non-QObject field.
        super().__init__()
        self.__name: Final = name
        self.__label: Final = label if label is not None else self.__make_label(name)
        self.__viewer_tab: Final = viewer_tab
        self.__editor_tab: Final = editor_tab
        self.__connections: Final = ConnectionList()
        """This field's connections to long-lived signals, so :meth:`bind_external` can drop them when the
        widgets they touch are destroyed (a form rebuild). One list per field -- its widgets are built and
        torn down together."""

    @property
    def name(self) -> str:
        """This field's identifier on its model."""
        return self.__name

    @property
    def label(self) -> str:
        """The display label shown in the form."""
        return self.__label

    @property
    def viewer_tab(self) -> FieldsTab:
        """The surface this field's viewer belongs to."""
        return self.__viewer_tab

    @property
    def editor_tab(self) -> FieldsTab:
        """The surface this field's editor belongs to."""
        return self.__editor_tab

    def make_viewer(self, binding: FieldBinding[T]) -> FieldViewerWidgets:
        """Build this field's viewer-row widget bundle bound to the given binding.

        :param binding: the resolved value/signal/setter to bind to.
        :returns: the field's :class:`FieldViewerWidgets` (tab + label + a viewer that re-renders on change).
        :raises NotImplementedError: unless a subclass overrides it.
        """
        raise NotImplementedError

    def make_editor(self, binding: FieldBinding[T]) -> FieldEditorWidgets:
        """Build this field's editor-row widget bundle bound to the given binding.

        A field builds its label, its optional middle-column ``misc`` control, and its editor together
        here -- the ``path`` field's expand toggle is its ``misc`` widget, wired to the editor it just
        built.

        :param binding: the resolved value/signal/setter to bind to.
        :returns: the field's :class:`FieldEditorWidgets` (tab + label + misc + editor).
        :raises NotImplementedError: unless a subclass overrides it.
        """
        raise NotImplementedError

    @staticmethod
    def bind_value_widget(widget: ValueWidget[T], binding: FieldBinding[T]) -> None:
        """Wire a value widget two-way to a binding ([[plugins#field-toolkit]]): seed it, push user
        edits through to the model, and echo model changes back under the widget's own guard.

        Collapses the standard four-line ``make_editor`` wiring (seed, ``value_changed`` ->
        ``set_value``, ``changed`` -> ``set_value``) into one call, so every content field that meets
        the :class:`ValueWidget` contract binds identically.

        :param widget: the editor satisfying the value-widget contract.
        :param binding: the resolved value/signal/setter to bind it to.
        """
        widget.set_value(binding.value)
        widget.value_changed.connect(binding.set_value)
        binding.changed.connect(widget.set_value)

    def bind_external(self, signal: SignalInstance, slot: Callable[..., Any]) -> None:
        """Connect a **long-lived** signal (a model or settings signal that outlives this field's
        widgets) to ``slot``, **recording** the connection so :meth:`clear_external` can drop it later
        ([[plugins#field-toolkit]]).

        Qt already drops a connection when the signal's **sender** dies, and auto-disconnects a slot that
        is a **bound method of a `QObject`** (its receiver dies). A **lambda** has neither -- so a form
        rebuild (a type switch / revert, #83/#113/#114) that deletes the widget the lambda writes to would
        leave it firing into the dead widget on the next emit. Rather than tie each connection to a widget
        `destroyed` signal (fragile: PySide does not keep the lambda's captured field alive, so the field
        can be collected before that fires), the field just records the connection and the **owner clears
        it deterministically** -- :class:`~rehuco_agent.documents.document_widget.DocumentWidget` calls
        :meth:`clear_external` on every field before a rebuild and on destruction, while the fields are
        still alive.

        :param signal: the long-lived signal to connect.
        :param slot: the slot -- typically a lambda writing to a widget.
        """
        self.__connections.connect(signal, slot)

    def clear_external(self) -> None:
        """Disconnect every connection :meth:`bind_external` made ([[plugins#field-toolkit]]).

        The field's owner calls this the moment the field's widgets are about to go away -- a form
        rebuild, or the hosting widget's destruction -- so the connections are severed while the field is
        still alive, deterministically, instead of relying on a `destroyed` signal that may fire after the
        field has been collected. Idempotent.
        """
        self.__connections.clear()

    def make_label(self) -> QWidget | None:
        """Build the field's name label for the row's label column; override for a custom label widget
        or ``None`` (no label cell).

        :returns: a `QLabel` of :attr:`label` by default.
        """
        return QLabel(self.label)

    @staticmethod
    def __make_label(name: str) -> str:
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
