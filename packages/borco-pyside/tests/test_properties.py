"""Tests for the SimpleProperty/TypedProperty reactive-property descriptors."""

from dataclasses import dataclass

import pytest
from borco_pyside.core import SimpleProperty, TypedProperty
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QCheckBox, QLineEdit
from pytestqt.qtbot import QtBot


# region Sample classes
class TypedPropertySample(QObject):
    """A `QObject` exercising `TypedProperty` directly, with hand-written `fget`/`fset`."""

    changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.__name = ""

    def __get_name(self) -> str:
        return self.__name

    def __set_name(self, value: str) -> None:
        self.__name = value
        self.changed.emit(value)

    name = TypedProperty(str, fget=__get_name, fset=__set_name, notify=changed)
    """Some typed property."""


class ObjectSample(QObject):
    """A `QObject` exercising `SimpleProperty` for the tests below."""

    title_changed = Signal(object)
    title = SimpleProperty("")
    """A title (auto-binds to title_changed)."""

    count_changed = Signal(object)
    count = SimpleProperty(0)
    """Some count (auto-binds to count_changed)."""

    active = SimpleProperty(False)
    """Whether active (no declared signal -- SimpleProperty synthesizes `active_changed`)."""


# endregion


# region TypedProperty tests
def test_typed_property_reads_and_writes_through_explicit_fget_fset() -> None:
    """A hand-built `TypedProperty` reads/writes through its own `fget`/`fset`, not `SimpleProperty`.

    **Test steps:**

    * construct a `TypedPropertySample`
    * verify `name` reads back its constructor-initialized default
    * set `name` to a new value
    * verify the getter reflects it
    """
    obj = TypedPropertySample()
    assert obj.name == ""

    obj.name = "Ada"

    assert obj.name == "Ada"


def test_typed_property_setter_emits_its_notify_signal() -> None:
    """Setting a `TypedProperty`-backed attribute fires the `notify` signal it was built with.

    **Test steps:**

    * construct a `TypedPropertySample` and connect to `changed`
    * set `name` to a new value
    * verify `changed` fired exactly once with that value
    """
    obj = TypedPropertySample()
    received: list[str] = []
    obj.changed.connect(received.append)

    obj.name = "Ada"

    assert received == ["Ada"]


# endregion


# region SimpleProperty behaviour tests
def test_property_returns_its_initial_value() -> None:
    """A freshly constructed instance reads back each property's declared initial value.

    **Test steps:**

    * construct an `ObjectSample`
    * verify `title` and `count` read their declared defaults
    """
    obj = ObjectSample()
    assert obj.title == ""
    assert obj.count == 0


def test_setting_property_updates_value_and_emits_changed() -> None:
    """Setting a property to a new value updates it and emits the declared `<name>_changed`.

    **Test steps:**

    * construct an `ObjectSample` and connect to `title_changed` (no `# type: ignore` -- it is declared)
    * set `title` to a new value
    * verify the property reads back the new value and the signal fired once with it
    """
    obj = ObjectSample()
    received: list[str] = []
    obj.title_changed.connect(received.append)

    obj.title = "Hello"

    assert obj.title == "Hello"
    assert received == ["Hello"]


def test_setting_property_to_equal_value_does_not_emit() -> None:
    """Setting a property to its current value is a no-op: no signal fires.

    **Test steps:**

    * construct an `ObjectSample`, set `count` to 5, then connect to `count_changed`
    * set `count` to 5 again
    * verify the signal did not fire
    """
    obj = ObjectSample()
    obj.count = 5
    received: list[int] = []
    obj.count_changed.connect(received.append)

    obj.count = 5

    assert not received


def test_set_name_helper_sets_the_value() -> None:
    """The generated `set_<name>` helper behaves like the property setter.

    **Test steps:**

    * construct an `ObjectSample`
    * call `set_title` directly, as another object's signal would when connected to it
    * verify `title` reflects the new value
    """
    obj = ObjectSample()
    obj.set_title("Via Helper")  # type: ignore[attr-defined]  # set_<name> is synthesized
    assert obj.title == "Via Helper"


def test_explicit_notify_signal_is_used() -> None:
    """`notify=` wires an explicit, differently-named signal instead of the `<name>_changed` default.

    **Test steps:**

    * declare a `QObject` with a `renamed` signal and `nickname = SimpleProperty("", notify=renamed)`
    * connect to `renamed`, then set `nickname`
    * verify `renamed` fired with the new value
    """

    class Named(QObject):
        """A `QObject` whose property notifies through an explicitly-named signal."""

        renamed = Signal(object)
        nickname = SimpleProperty("", notify=renamed)

    obj = Named()
    received: list[str] = []
    obj.renamed.connect(received.append)

    obj.nickname = "Ada"

    assert obj.nickname == "Ada"
    assert received == ["Ada"]


def test_one_signal_shared_by_multiple_properties() -> None:
    """Several properties may deliberately share one notify signal via `notify=` (a supported feature).

    **Test steps:**

    * declare a `QObject` with one `coords_changed` signal shared by `x` and `y`
    * connect to `coords_changed`, then set `x` and `y`
    * verify each change emits through the shared signal
    """

    class Position(QObject):
        """A `QObject` whose two coordinates share a single change signal."""

        coords_changed = Signal(object)
        x = SimpleProperty(0, notify=coords_changed)
        y = SimpleProperty(0, notify=coords_changed)

    obj = Position()
    received: list[int] = []
    obj.coords_changed.connect(received.append)

    obj.x = 3
    obj.y = 7

    assert (obj.x, obj.y) == (3, 7)
    assert received == [3, 7]


def test_missing_change_signal_is_synthesized() -> None:
    """A `SimpleProperty` with `notify="auto"` and no declared `<name>_changed` signal synthesizes one.

    **Test steps:**

    * declare a `QObject` with a `SimpleProperty` but no matching `<name>_changed` signal
    * connect to the synthesized signal (needs `# type: ignore`, since it isn't statically declared)
    * set the property and verify it updates and the synthesized signal fires
    """

    class Missing(QObject):
        """A `QObject` relying on `SimpleProperty` to synthesize its `value_changed` signal."""

        value = SimpleProperty(0)

    obj = Missing()
    received: list[int] = []
    obj.value_changed.connect(received.append)  # type: ignore[attr-defined]

    obj.value = 5

    assert obj.value == 5
    assert received == [5]


def test_explicit_notify_not_a_class_attribute_raises() -> None:
    """An explicit `notify=` signal that is not a class attribute of the owner raises.

    **Test steps:**

    * build a bare `Signal` not attached to the class, pass it as `notify=`
    * verify `RuntimeError` is raised while the class body is created
    """
    stray = Signal(object)

    with pytest.raises(RuntimeError, match="class attribute"):

        class Detached(QObject):  # pylint: disable=unused-variable
            """A `QObject` whose property's notify signal is not one of its class attributes."""

            value = SimpleProperty(0, notify=stray)


def test_declaring_on_non_qobject_raises() -> None:
    """Declaring a `SimpleProperty` on a class that is not a `QObject` subclass raises.

    **Test steps:**

    * declare a plain (non-`QObject`) class with a `SimpleProperty` class attribute
    * verify `RuntimeError` is raised while the class body is being created
    """
    with pytest.raises(RuntimeError, match="QObject subclass"):

        class NotAQObject:  # pylint: disable=too-few-public-methods,unused-variable
            """A non-`QObject` class, declared only to trigger the `__set_name__` guard."""

            title = SimpleProperty("")


# endregion


# region notify_signal_name tests
def test_notify_signal_name_resolves_a_declared_signal() -> None:
    """notify_signal_name resolves the auto-bound, class-declared signal's attribute name.

    **Test steps:**

    * call `notify_signal_name` for `ObjectSample.title`
    * verify it returns `"title_changed"`
    """
    assert SimpleProperty.notify_signal_name(ObjectSample, "title") == "title_changed"


def test_notify_signal_name_resolves_a_synthesized_signal() -> None:
    """notify_signal_name resolves a signal SimpleProperty synthesized (no declaration needed).

    **Test steps:**

    * declare a `QObject` with a `SimpleProperty` and no matching `<name>_changed` signal
    * verify `notify_signal_name` still resolves it to the synthesized `value_changed`
    """

    class Synthesized(QObject):
        """A `QObject` relying on `SimpleProperty` to synthesize its `value_changed` signal."""

        value = SimpleProperty(0)

    assert SimpleProperty.notify_signal_name(Synthesized, "value") == "value_changed"


def test_notify_signal_name_resolves_an_explicit_differently_named_signal() -> None:
    """notify_signal_name resolves an explicit notify= signal, not the `<name>_changed` convention.

    **Test steps:**

    * declare a `QObject` whose property notifies through a differently-named `renamed` signal
    * verify `notify_signal_name` returns `"renamed"`, not `"nickname_changed"`
    """

    class Named(QObject):
        """A `QObject` whose property notifies through an explicitly-named signal."""

        renamed = Signal(object)
        nickname = SimpleProperty("", notify=renamed)

    assert SimpleProperty.notify_signal_name(Named, "nickname") == "renamed"


def test_notify_signal_name_resolves_both_kinds_on_one_class() -> None:
    """A class mixing a declared signal (`title`) and a synthesized one (`active`) resolves both.

    **Test steps:**

    * verify `notify_signal_name` resolves `ObjectSample.title` (declared) and `.active` (synthesized)
    * connect to the synthesized `active_changed` and verify set/emit still works
    """
    assert SimpleProperty.notify_signal_name(ObjectSample, "title") == "title_changed"
    assert SimpleProperty.notify_signal_name(ObjectSample, "active") == "active_changed"

    obj = ObjectSample()
    received: list[bool] = []
    obj.active_changed.connect(received.append)  # type: ignore[attr-defined]

    obj.active = True

    assert obj.active is True
    assert received == [True]


def test_notify_signal_name_raises_for_an_unregistered_name() -> None:
    """notify_signal_name raises for a name that isn't a `SimpleProperty` on the class.

    **Test steps:**

    * call `notify_signal_name` with a name never declared on `ObjectSample`
    * verify `KeyError` is raised
    """
    with pytest.raises(KeyError):
        SimpleProperty.notify_signal_name(ObjectSample, "nonexistent")


# endregion


# region SimpleProperty value-type tests
def test_int_value_notifies_through_matching_signal() -> None:
    """An `int` property may notify through a matching `Signal(int)`; the value round-trips.

    **Test steps:**

    * declare `count = SimpleProperty(0)` with `count_changed = Signal(int)`
    * connect, then set `count = 42`
    * verify the getter and the emitted value are `42`
    """

    class Model(QObject):
        """An `int`-valued property with a matching `Signal(int)`."""

        count_changed = Signal(int)
        count = SimpleProperty(0)

    obj = Model()
    received: list[int] = []
    obj.count_changed.connect(received.append)

    obj.count = 42

    assert obj.count == 42
    assert received == [42]


def test_bool_value_notifies_through_matching_signal() -> None:
    """A `bool` property may notify through a matching `Signal(bool)`.

    **Test steps:**

    * declare `flag = SimpleProperty(False)` with `flag_changed = Signal(bool)`
    * connect, then set `flag = True`
    * verify the getter and the emitted value are `True`
    """

    class Model(QObject):
        """A `bool`-valued property with a matching `Signal(bool)`."""

        flag_changed = Signal(bool)
        flag = SimpleProperty(False)

    obj = Model()
    received: list[bool] = []
    obj.flag_changed.connect(received.append)

    obj.flag = True

    assert obj.flag is True
    assert received == [True]


def test_str_value_notifies_through_matching_signal() -> None:
    """A `str` property may notify through a matching `Signal(str)`.

    **Test steps:**

    * declare `title = SimpleProperty("")` with `title_changed = Signal(str)`
    * connect, then set `title = "Hello"`
    * verify the getter and the emitted value are `"Hello"`
    """

    class Model(QObject):
        """A `str`-valued property with a matching `Signal(str)`."""

        title_changed = Signal(str)
        title = SimpleProperty("")

    obj = Model()
    received: list[str] = []
    obj.title_changed.connect(received.append)

    obj.title = "Hello"

    assert obj.title == "Hello"
    assert received == ["Hello"]


def test_float_value_notifies_through_matching_signal() -> None:
    """A `float` property may notify through a matching `Signal(float)`; a float is not truncated.

    **Test steps:**

    * declare `ratio = SimpleProperty(0.0)` with `ratio_changed = Signal(float)`
    * connect, then set `ratio = 3.5`
    * verify the getter and the emitted value are `3.5` (not truncated to `3`)
    """

    class Model(QObject):
        """A `float`-valued property with a matching `Signal(float)`."""

        ratio_changed = Signal(float)
        ratio = SimpleProperty(0.0)

    obj = Model()
    received: list[float] = []
    obj.ratio_changed.connect(received.append)

    obj.ratio = 3.5

    assert obj.ratio == 3.5
    assert received == [3.5]


def test_qobject_value_notifies_through_matching_signal() -> None:
    """A `QObject`-subclass value may notify through a matching `Signal(<subclass>)`, by pointer.

    **Test steps:**

    * declare a custom `Widget(QObject)`; `item = SimpleProperty(Widget())` with `item_changed = Signal(Widget)`
    * connect, then set a fresh `Widget`
    * verify the emitted object is the identical instance (pointer, not a coerced copy)
    """

    class Widget(QObject):
        """A minimal custom `QObject` used as a property value."""

    class Model(QObject):
        """A `Widget`-valued property notifying through a `QObject`-typed signal."""

        item_changed = Signal(Widget)
        item = SimpleProperty(Widget())

    obj = Model()
    other = Widget()
    received: list[object] = []
    obj.item_changed.connect(received.append)

    obj.item = other

    assert obj.item is other
    assert received[0] is other


def test_simple_datatype_value_notifies_through_object_signal() -> None:
    """A non-Qt 'simple datatype' (e.g. a dataclass) uses `Signal(object)`; identity is preserved.

    **Test steps:**

    * declare a frozen `Point` dataclass (a non-frozen one is unhashable, i.e. mutable by
      convention, and the mutable-default rejection would demand `default_factory` instead);
      `point = SimpleProperty(Point())` with `point_changed = Signal(object)`
    * connect, then set a fresh `Point`
    * verify the getter and the emitted value are the identical instance
    """

    @dataclass(frozen=True)
    class Point:
        """A plain dataclass value type (not a `QObject`)."""

        x: int = 0
        y: int = 0

    class Model(QObject):
        """A dataclass-valued property notifying through `Signal(object)`."""

        point_changed = Signal(object)
        point = SimpleProperty(Point())

    obj = Model()
    other = Point(1, 2)
    received: list[object] = []
    obj.point_changed.connect(received.append)

    obj.point = other

    assert obj.point is other
    assert received[0] is other


def test_optional_value_supports_none_and_a_value() -> None:
    """An optional `T | None` property defaults to `None` and round-trips both `None` and a value.

    An optional must use `Signal(object)`: the `None` default makes the runtime value type
    effectively `object`, and a typed primitive signal (e.g. `Signal(str)`) would coerce `None`.

    **Test steps:**

    * declare `subtitle = SimpleProperty[str | None](None)` with `subtitle_changed = Signal(object)`
    * connect, then set a `str` and then `None`
    * verify the initial `None`, and that both values round-trip through the getter and the signal
    """

    class Model(QObject):
        """A `QObject` with an optional `str | None` property."""

        subtitle_changed = Signal(object)
        subtitle = SimpleProperty[str | None](None)

    obj = Model()
    received: list[object] = []
    obj.subtitle_changed.connect(received.append)

    assert obj.subtitle is None
    obj.subtitle = "hello"
    obj.subtitle = None

    assert received == ["hello", None]


def test_value_type_object_secures_a_non_none_default_optional() -> None:
    """`value_type=object` makes an optional defaulted to a non-`None` value require `Signal(object)`.

    Without it the check would see the `""` default (a `str`) and wrongly allow `Signal(str)`, which
    coerces `None` on emit. `value_type=object` rejects the typed signal and keeps `None` intact.

    **Test steps:**

    * verify a `Signal(str)` with `value_type=object` is rejected at declaration
    * verify a `Signal(object)` with `value_type=object` round-trips both a `str` and `None`
    """
    with pytest.raises(RuntimeError, match="incompatible"):

        class Bad(QObject):  # pylint: disable=unused-variable
            """A non-`None`-default optional whose typed signal would coerce `None`."""

            subtitle_changed = Signal(str)
            subtitle = SimpleProperty[str | None]("", value_type=object)

    class Good(QObject):
        """A non-`None`-default optional secured with `value_type=object` and `Signal(object)`."""

        subtitle_changed = Signal(object)
        subtitle = SimpleProperty[str | None]("", value_type=object)

    obj = Good()
    received: list[object] = []
    obj.subtitle_changed.connect(received.append)

    obj.subtitle = "hi"
    obj.subtitle = None

    assert received == ["hi", None]


def test_mismatched_primitive_signal_raises() -> None:
    """A typed signal whose argument does not match the value's primitive type is rejected.

    **Test steps:**

    * declare a `QObject` with `count_changed = Signal(str)` but `count = SimpleProperty(0)` (int)
    * verify `RuntimeError` about incompatibility is raised while the class is created
    """
    with pytest.raises(RuntimeError, match="incompatible"):

        class Bad(QObject):  # pylint: disable=unused-variable
            """A `QObject` whose notify signal type mismatches its value type."""

            count_changed = Signal(str)
            count = SimpleProperty(0)


def test_typed_signal_for_non_primitive_value_raises() -> None:
    """A typed signal for a non-primitive value is rejected -- only `Signal(object)` is allowed there.

    **Test steps:**

    * declare a `QObject` with `data_changed = Signal(int)` but a tuple-valued `SimpleProperty`
    * verify `RuntimeError` about incompatibility is raised while the class is created
    """
    with pytest.raises(RuntimeError, match="incompatible"):

        class Bad(QObject):  # pylint: disable=unused-variable
            """A `QObject` whose non-primitive property is wired to a typed signal."""

            data_changed = Signal(int)
            data = SimpleProperty[tuple[int, ...]](())


def test_mismatched_builtin_qobject_signal_raises(qtbot: QtBot) -> None:  # pylint: disable=unused-argument
    """A built-in-Qt-typed signal mismatching the value's built-in type is rejected.

    Qt gives *registered* C++ types distinct signatures (``QLineEdit*`` vs ``QCheckBox*``), so this
    mismatch is caught. (Two *custom* Python `QObject` subclasses both normalize to ``QObject*`` and
    cannot be told apart -- a harmless typing gap, since emit still passes the object by pointer.)

    **Test steps:**

    * (the `qtbot` fixture provides the `QApplication` the widgets need)
    * declare a `QObject` with `edited = Signal(QLineEdit)` but a `QCheckBox`-valued property
    * verify `RuntimeError` about incompatibility is raised while the class is created
    """
    with pytest.raises(RuntimeError, match="incompatible"):

        class Bad(QObject):  # pylint: disable=unused-variable
            """A `QObject` whose widget value type mismatches its notify signal type."""

            edited = Signal(QLineEdit)
            widget = SimpleProperty(QCheckBox(), notify=edited)


def test_object_signal_carries_non_primitive_without_coercion() -> None:
    """`Signal(object)` carries a non-primitive value through get and emit with identity intact.

    Guards the `Signal(object)` convention: a typed primitive signal would coerce (e.g. truncate a
    float or blank a mismatched value), so this checks a value the getter returns and the signal
    emits are the *same object*, not a coerced copy.

    **Test steps:**

    * declare a `QObject` with a `SimpleProperty` defaulting to an empty tuple + `Signal(object)`
    * connect, then set a fresh tuple value
    * verify both the getter and the emitted value are identical (`is`) to the value set
    """

    class Holder(QObject):
        """A `QObject` with a single non-primitive (`tuple`) `SimpleProperty`."""

        data_changed = Signal(object)
        data = SimpleProperty[tuple[str, ...]](())

    value = ("publisher", "title", "url")
    obj = Holder()
    received: list[object] = []
    obj.data_changed.connect(received.append)

    obj.data = value

    assert obj.data is value
    assert received[0] is value


# endregion


# region SimpleProperty default_factory tests
def test_mutable_default_value_raises() -> None:
    """A mutable (unhashable) initial value is rejected -- `default_factory` is the supported spelling (#35).

    Without the rejection, the class-level seed would be one object silently shared by every
    instance (Python's mutable-default-argument trap; `dataclasses.field` rejects it the same way).

    **Test steps:**

    * construct a `SimpleProperty` with a `[]`, `{}`, and `set()` default in turn
    * verify each raises `RuntimeError` pointing at `default_factory`
    """
    mutables: tuple[object, ...] = ([], {}, set())
    for mutable in mutables:
        with pytest.raises(RuntimeError, match="default_factory"):
            SimpleProperty(mutable)


def test_value_and_default_factory_together_raise() -> None:
    """Passing both an initial value and a factory is rejected -- they are mutually exclusive.

    **Test steps:**

    * construct a `SimpleProperty` with both `value` and `default_factory`
    * verify `RuntimeError` is raised
    """
    with pytest.raises(RuntimeError, match="not both"):
        SimpleProperty(0, default_factory=lambda: 0)  # type: ignore[call-overload]


def test_neither_value_nor_default_factory_raises() -> None:
    """Passing neither an initial value nor a factory is rejected -- exactly one is required.

    **Test steps:**

    * construct a `SimpleProperty` with no arguments
    * verify `RuntimeError` is raised
    """
    with pytest.raises(RuntimeError, match="default_factory"):
        SimpleProperty()  # type: ignore[call-overload]


def test_default_factory_seeds_each_instance_with_its_own_value() -> None:
    """`default_factory=list` gives every instance its own (equal but distinct) empty list (#35).

    **Test steps:**

    * declare a list-valued property with `default_factory=list` and construct two instances
    * verify both read an empty list, and the two lists are distinct objects
    """

    class Model(QObject):
        """A `QObject` with a factory-backed empty-list property."""

        tags_changed = Signal(object)
        tags = SimpleProperty[list[str]](default_factory=list)

    first, second = Model(), Model()

    assert first.tags == []
    assert second.tags == []
    assert first.tags is not second.tags


def test_default_factory_populated_default_is_not_shared() -> None:
    """A populated factory default (`lambda: [1, 2, 3]`) is rebuilt per instance -- mutating one
    instance's value leaves the other untouched (#35).

    **Test steps:**

    * declare a property with `default_factory=lambda: [1, 2, 3]` and construct two instances
    * append to the first instance's list in place
    * verify only the first instance changed
    """

    class Model(QObject):
        """A `QObject` with a factory-backed populated-list property."""

        tags_changed = Signal(object)
        tags = SimpleProperty[list[int]](default_factory=lambda: [1, 2, 3])

    first, second = Model(), Model()

    first.tags.append(4)

    assert first.tags == [1, 2, 3, 4]
    assert second.tags == [1, 2, 3]


def test_factory_backed_set_before_any_get_works() -> None:
    """Assigning a factory-backed property before ever reading it seeds, compares, and emits normally.

    Guards the set-first path: `__fset` must seed the instance default (there is no class-level
    fallback in factory mode) rather than raise `AttributeError`.

    **Test steps:**

    * construct an instance and assign the property without any prior read
    * verify the value took and the change signal fired once with it
    """

    class Model(QObject):
        """A `QObject` with a factory-backed list property."""

        tags_changed = Signal(object)
        tags = SimpleProperty[list[str]](default_factory=list)

    obj = Model()
    received: list[object] = []
    obj.tags_changed.connect(received.append)

    obj.tags = ["a"]

    assert obj.tags == ["a"]
    assert received == [["a"]]


def test_factory_backed_set_equal_to_default_does_not_emit() -> None:
    """Assigning a value equal to the factory default is a no-op: no signal fires.

    **Test steps:**

    * construct an instance and assign an empty list over the factory-made empty default
    * verify the signal did not fire
    """

    class Model(QObject):
        """A `QObject` with a factory-backed list property."""

        tags_changed = Signal(object)
        tags = SimpleProperty[list[str]](default_factory=list)

    obj = Model()
    received: list[object] = []
    obj.tags_changed.connect(received.append)

    obj.tags = []

    assert not received


def test_mutate_and_emit_escape_hatch_preserves_identity() -> None:
    """In-place mutation + manual emit delivers the same mutated object (the documented escape hatch).

    Pins the two foundations the docstring's escape hatch relies on: reads return the same object
    every time (no copy through the Qt property layer), and a manual emit through `Signal(object)`
    passes that object by reference.

    **Test steps:**

    * verify two consecutive reads return the identical list object
    * append in place, then emit the change signal manually
    * verify the connected slot received that same object, holding the appended value
    """

    class Model(QObject):
        """A `QObject` with a factory-backed list property."""

        tags_changed = Signal(object)
        tags = SimpleProperty[list[str]](default_factory=list)

    obj = Model()
    received: list[object] = []
    obj.tags_changed.connect(received.append)
    assert obj.tags is obj.tags

    obj.tags.append("x")
    obj.tags_changed.emit(obj.tags)

    assert received[0] is obj.tags
    assert obj.tags == ["x"]


def test_list_typed_signal_raises() -> None:
    """`Signal(list)` is rejected for a list value: its `QVariantList` conversion copies on emit (#35).

    Emitting a list through `Signal(list)` delivers a QVariant-converted *copy* to the slot
    (verified empirically), breaking the emit-what-the-getter-returns invariant -- so only
    `Signal(object)` is acceptable for list/dict values.

    **Test steps:**

    * declare a `QObject` wiring a list-valued property to `tags_changed = Signal(list)`
    * verify `RuntimeError` about incompatibility is raised while the class is created
    """
    with pytest.raises(RuntimeError, match="incompatible"):

        class Bad(QObject):  # pylint: disable=unused-variable
            """A `QObject` whose list-valued property is wired to a coercing `Signal(list)`."""

            tags_changed = Signal(list)
            tags = SimpleProperty[list[str]](default_factory=list)


# endregion
