"""Reactive `QObject` properties that emit a change signal when their value changes."""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Final, Literal

from PySide6.QtCore import Property, QObject, Signal

OBJECT_SIGNAL_SIGNATURE: Final = "(PyObject)"
"""``Signal.signatures[0]`` of a single-argument ``Signal(object)`` -- always valid for any value."""

_signal_names: Final[dict[type, dict[str, str]]] = {}
"""Per-class ``name`` -> notify-signal-attribute-name registry, populated by ``SimpleProperty.__set_name__``."""


def signal_signature(signal: Signal) -> str:
    """Return a single-argument ``Signal``'s declared argument signature (e.g. ``"(int)"``).

    Reads PySide6's ``Signal.signatures`` via ``getattr`` because the attribute exists at runtime
    but is absent from the type stubs.

    :param signal: the signal to inspect.
    :returns: its first (and, for these single-argument signals, only) signature string.
    """
    return getattr(signal, "signatures")[0]


def notify_signal_name(owner: type, name: str) -> str:
    """Return the attribute name of the notify signal ``SimpleProperty`` wired for ``name`` on ``owner``.

    Usually ``f"{name}_changed"`` (the ``notify="auto"`` convention), but may be a differently-named
    signal if the property was declared with an explicit ``notify=``. Generic code that binds to a
    property by name (e.g. a reactive-model binding helper) should use this instead of assuming the
    naming convention.

    :param owner: the class the property was declared on.
    :param name: the property's attribute name.
    :returns: the notify signal's attribute name.
    :raises KeyError: if ``name`` is not a ``SimpleProperty`` declared on ``owner``.
    """
    try:
        return _signal_names[owner][name]
    except KeyError as exc:
        raise KeyError(f"no SimpleProperty '{name}' registered on {owner.__qualname__}") from exc


class TypedProperty[T](Property):
    """``QtCore.Property`` with a typed ``__init__``/``__get__``/``__set__`` for IDE hover/type-checking.

    ``QtCore.Property``'s stub doesn't declare ``__get__``/``__set__``, so type checkers show
    plain ``Property`` attributes instead of their declared type, with no docstring. This
    subclass adds no real behavior -- ``__init__`` just forwards to ``QtCore.Property``, and the
    ``__get__``/``__set__`` declarations only exist for type checkers (``if TYPE_CHECKING``). ``T``
    is inferred from the ``type: type[T]`` argument, so ``TypedProperty(bool, ...)`` is enough --
    no ``TypedProperty[bool](...)`` subscript needed.

    No runtime overhead vs. plain ``Property``: ``__init__`` only adds one extra forwarding call
    at class-definition time (once per property, not per access), and ``__get__``/``__set__`` are
    ``Property``'s own inherited implementations -- the ``TYPE_CHECKING`` block doesn't exist at
    runtime.

    :param type: the Qt property's value type.
    :param fget: getter callable.
    :param fset: setter callable, if the property is writable.
    :param notify: the change signal Qt associates with this property.
    :param doc: optional docstring surfaced to Qt tooling (e.g. Designer/QML).

    Direct usage (most callers want :class:`SimpleProperty` instead, which builds one of these
    for you):

    .. code-block:: python

        class Item(QObject):
            changed = Signal(object)

            def __get_name(self) -> str:
                return self.__name

            def __set_name(self, value: str) -> None:
                self.__name = value
                self.changed.emit(value)

            name = TypedProperty(str, fget=__get_name, fset=__set_name, notify=changed)

        item = Item()
        item.name = "foo"  # a type checker knows this is str, not Property
    """

    def __init__(
        self,
        # matches QtCore.Property's own parameter name (positional-only in practice)
        type: type[T],  # pylint: disable=redefined-builtin
        fget: Callable[[Any], T] | None = None,
        fset: Callable[[Any, T], None] | None = None,
        notify: Signal | None = None,
        doc: str = "",
    ) -> None:
        super().__init__(type, fget, fset, notify=notify, doc=doc)

    if TYPE_CHECKING:

        def __get__(self, instance: object, owner: type | None = None) -> T: ...
        def __set__(self, instance: object, value: T) -> None: ...


class SimpleProperty[T]:
    """Read-write ``QObject`` property that emits a change signal on change.

    On a ``QObject`` subclass, bind the property to a change ``Signal`` -- by the ``<name>_changed``
    naming convention (the ``notify="auto"`` default) or by passing any signal explicitly as
    ``notify=``. Then ``obj.<name>`` reads and writes the value, the bound signal fires with the new
    value on every change (assigning the current value is a no-op), and ``obj.set_<name>(value)`` is
    a plain method usable as a slot.

    **Declaring `<name>_changed` is optional.** In ``"auto"`` mode, if the class already declares
    ``<name>_changed = Signal(...)``, that signal is used and, because it's a real class attribute,
    connecting to it type-checks with no ``# type: ignore``. If it isn't declared, one is synthesized
    (``Signal(object)``, wired on the class the same way ``TypedProperty`` itself is) so the property
    still works with zero boilerplate -- but a synthesized signal is invisible to a type checker, so
    connecting to it needs an inline ``# type: ignore[attr-defined]``, same as the ``set_<name>``
    helper always has. Declare the signal explicitly when a consumer needs typed ``.connect()``;
    generic code that must find a property's notify signal by name regardless of which case applies
    should use :func:`notify_signal_name` rather than assuming the ``<name>_changed`` convention.

    Which signal to declare: ``Signal(object)`` is always valid. A signal matching the value's **own**
    type is also valid -- the native primitives (``int``/``str``/``float``/``bool``) round-trip, and a
    ``QObject`` subclass is passed by pointer (identity preserved). Any other typed signal is rejected,
    because a mismatched value-type signal silently coerces on emit (``Signal(int)`` truncates ``3.9``
    to ``3``, ``Signal(str)`` turns ``None``/``42`` into ``""``), making the emitted value differ from
    what the getter returns. The value type comes from the initial ``value`` (or ``value_type=``), so a
    reference property that defaults to ``None`` reads as ``object`` -- give it a ``Signal(object)``.

    **Limitation:** every *custom* Python ``QObject`` subclass collapses to the signature
    ``(QObject*)`` (only built-in Qt C++ types like ``QLineEdit`` keep a distinct one), so a mismatch
    between two custom subclasses -- ``Signal(WidgetA)`` on a ``WidgetB`` value -- is **not** rejected
    here. This is harmless: emit still passes the object by pointer with identity preserved, never a
    coerced or copied value, so the invariant "you emit exactly what the getter returns" holds. The
    mismatch is caught statically by the property's own ``SimpleProperty[T]`` type, not at runtime.

    **Runtime cost:** validation and wiring run once per property at class-definition time, never per
    instance. A read is a Qt-property get plus one Python attribute lookup; a write adds an equality
    check and, only when the value actually changes, a signal emit -- negligible outside a tight loop.

    :param value: the initial value.
    :param notify: ``"auto"`` (default) uses the class's ``<name>_changed`` signal if declared, else
        synthesizes one; pass a ``Signal`` to wire an explicit, possibly differently-named one (which
        must itself be a class attribute). The signal's argument type is validated against the value
        type either way.
    :param value_type: ``"auto"`` (default) takes the value type from ``value``; pass an explicit
        type to override it for the signal check and the Qt property type -- e.g. ``value_type=object``
        for an optional defaulted to a non-``None`` value, so it correctly requires ``Signal(object)``.

    .. code-block:: python

        class Item(QObject):
            title_changed = Signal(object)          # object is always valid, for any value type
            title = SimpleProperty("")              # declared -- binds to it, fully typed .connect()

            count = SimpleProperty(0)               # not declared -- count_changed is synthesized
                                                     # (works the same; needs # type: ignore to connect)

            renamed = Signal(str)
            name = SimpleProperty("", notify=renamed)   # or wire an explicit, differently-named one

            summary_changed = Signal(object)
            summary = SimpleProperty[str | None](None)   # optional: None default already reads as object

            subtitle_changed = Signal(object)
            subtitle = SimpleProperty[str | None]("", value_type=object)  # optional, non-None default: force object

        item = Item()
        item.title_changed.connect(on_title)        # fully typed, no `# type: ignore`
        item.title = "New Title"                     # updates the value and emits title_changed
        another_object.some_signal.connect(item.set_title)  # set_<name> slot helper
    """

    def __init__(
        self,
        value: T,
        *,
        notify: Signal | Literal["auto"] = "auto",
        value_type: type | Literal["auto"] = "auto",
    ) -> None:
        self.__value: T = value
        self.__notify: Final = notify
        self.__declared_type: Final = value_type
        self.__private_name: str = ""
        self.__signal_name: str = ""

    def __set_name__(self, owner: type, name: str) -> None:
        """Install the backing attribute, setter helper, and Qt property wired to the resolved signal.

        :param owner: the class declaring this property.
        :param name: the property's attribute name.
        :raises RuntimeError: if ``owner`` is not a ``QObject`` subclass, if an explicit ``notify``
            signal is not a class attribute of ``owner``, or if the signal's argument type is
            incompatible with the value type.
        """
        if not issubclass(owner, QObject):
            raise RuntimeError(f"SimpleProperty {owner.__qualname__}.{name} requires a QObject subclass.")

        self.__private_name = f"__{name}"
        value_type = type(self.__value) if self.__declared_type == "auto" else self.__declared_type
        signal, self.__signal_name = self.__resolve_signal(owner, name)
        self.__check_signal_type(owner, name, signal, value_type)
        _signal_names.setdefault(owner, {})[name] = self.__signal_name

        # Wire the property onto the owner class: a private backing attribute, a set_<name>(value)
        # slot helper, and a real Qt Property (TypedProperty) that *replaces* this descriptor -- so
        # Qt's meta-object sees a typed property and obj.<name> routes through __fget/__fset.
        setattr(owner, self.__private_name, self.__value)
        setattr(owner, f"set_{name}", lambda obj, value: self.__fset(obj, value))  # pylint: disable=unnecessary-lambda
        setattr(owner, name, TypedProperty(value_type, fget=self.__fget, fset=self.__fset, notify=signal))

    def __resolve_signal(self, owner: type, name: str) -> tuple[Signal, str]:
        """Resolve the notify signal, returning it with its attribute name on ``owner``.

        :param owner: the class declaring this property.
        :param name: the property's attribute name.
        :returns: the ``Signal`` to notify and the attribute name it is declared under.
        :raises RuntimeError: if an explicit ``notify`` signal is not a class attribute of ``owner``.
        """
        if self.__notify == "auto":
            signal_name = f"{name}_changed"
            signal = owner.__dict__.get(signal_name)
            if not isinstance(signal, Signal):
                # Not declared -- synthesize one, wired onto the class the same way __set_name__
                # wires the property itself. Fully functional at runtime, but invisible to a type
                # checker (see the class docstring): connecting to it needs # type: ignore.
                signal = Signal(object)
                setattr(owner, signal_name, signal)
        else:
            signal = self.__notify
            signal_name = next((key for key, value in owner.__dict__.items() if value is signal), "")
            if not signal_name:
                raise RuntimeError(
                    f"SimpleProperty {owner.__qualname__}.{name}: the notify= signal must be declared as a "
                    f"class attribute of {owner.__qualname__}."
                )
        return signal, signal_name

    def __check_signal_type(self, owner: type, name: str, signal: Signal, value_type: type) -> None:
        """Reject a notify signal whose argument type would coerce the emitted value.

        ``Signal(object)`` is always allowed. A signal matching ``value_type``'s own Qt type is also
        allowed: the native primitives (``int``/``str``/``float``/``bool``) round-trip, and any
        ``QObject`` subclass is passed by pointer (Qt normalizes them all to ``QObject*``), so
        identity is preserved. Any other typed signal is a value-type signal that coerces on emit
        (``Signal(str)`` blanks a non-string, ``Signal(int)`` truncates a float), so it is rejected.

        :param owner: the class declaring this property.
        :param name: the property's attribute name.
        :param signal: the resolved notify signal.
        :param value_type: the property's value type (from ``value_type=`` or the initial value).
        :raises RuntimeError: if the signal's signature is incompatible with the value type.
        """
        signature = signal_signature(signal)
        # Qt's own type -> signature mapping for the value's type; equals "(PyObject)" for anything
        # it has no native converter for, so non-primitive/non-QObject values require Signal(object).
        native = signal_signature(Signal(value_type))
        if signature not in (OBJECT_SIGNAL_SIGNATURE, native):
            hint = "Signal(object)"
            if native != OBJECT_SIGNAL_SIGNATURE:
                hint = f"Signal(object) or Signal({value_type.__name__})"
            raise RuntimeError(
                f"SimpleProperty {owner.__qualname__}.{name}: notify signal signature {signature} is "
                f"incompatible with a {value_type.__name__} value; use {hint}."
            )

    def __fget(self, obj: object) -> T:
        return getattr(obj, self.__private_name)  # type: ignore[no-any-return]

    def __fset(self, obj: object, value: T) -> None:
        if getattr(obj, self.__private_name) == value:
            return
        setattr(obj, self.__private_name, value)
        getattr(obj, self.__signal_name).emit(value)

    if TYPE_CHECKING:
        # Never invoked at runtime: __set_name__ replaces this descriptor with a TypedProperty on the
        # class, so obj.<name> / obj.<name> = v go through that (and __fget/__fset above). These stubs
        # exist only so a type checker resolves access as T, since it can't see the setattr swap.
        def __get__(self, obj: object, _: type | None = None) -> T: ...
        def __set__(self, obj: object, value: T) -> None: ...
