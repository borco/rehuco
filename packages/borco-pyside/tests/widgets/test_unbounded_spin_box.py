"""Tests for UnboundedSpinBox: an unbounded-Python-int spin box editor (#40)."""

from collections.abc import Callable

from borco_pyside.widgets import UnboundedSpinBox
from PySide6.QtGui import QValidator
from pytest import mark, param
from pytestqt.qtbot import QtBot

BEYOND_INT32: int = 2**40
"""A value far past the C++ ``int`` (32-bit) ceiling ``QSpinBox`` is stuck with."""


# region construction and value tests
@mark.parametrize(
    ("value", "minimum", "maximum", "expected"),
    [
        param(0, None, None, 0, id="default-is-zero"),
        param(BEYOND_INT32, None, None, BEYOND_INT32, id="beyond-int32-held-exactly"),
        param(100, 0, 10, 10, id="clamped-to-maximum-at-construction"),
    ],
)
def test_starting_value(qtbot: QtBot, value: int, minimum: int | None, maximum: int | None, expected: int) -> None:
    """The starting ``value`` -- exact for any Python int, boxed into ``minimum``/``maximum`` if given --
    is held and shown immediately.

    **Test steps:**

    * build the widget with ``value``/``minimum``/``maximum``
    * verify its value and line edit text both match ``expected``
    """
    spin_box = UnboundedSpinBox(value=value, minimum=minimum, maximum=maximum)
    qtbot.addWidget(spin_box)

    assert spin_box.value == expected
    assert spin_box.lineEdit().text() == str(expected)


def test_value_changed_carries_the_exact_python_int_uncoerced(qtbot: QtBot) -> None:
    """``value_changed`` emits the exact Python ``int``, not a C++-``int``-coerced copy.

    A ``Signal(int)`` would silently truncate or raise on a value beyond int32 -- this is the
    behavior ``Signal(object)`` (declared on ``UnboundedSpinBox``) exists to avoid.

    **Test steps:**

    * build the widget, connect to ``value_changed``
    * set a value beyond int32 via ``setValue``
    * verify the received value equals it exactly
    """
    spin_box = UnboundedSpinBox()
    qtbot.addWidget(spin_box)
    received: list[int] = []
    spin_box.value_changed.connect(received.append)  # type: ignore[attr-defined]

    spin_box.setValue(BEYOND_INT32)

    assert received == [BEYOND_INT32]


@mark.parametrize(
    ("minimum", "maximum"),
    [
        param(None, None, id="no-bounds"),
        param(-10, 10, id="explicit-bounds"),
    ],
)
def test_minimum_and_maximum_accessors_reflect_the_configured_range(
    qtbot: QtBot, minimum: int | None, maximum: int | None
) -> None:
    """``minimum()``/``maximum()`` read back exactly what was configured, including ``None`` for no bound
    (unlike ``QSpinBox``, which always reads back an actual ``int``).

    **Test steps:**

    * build a widget with ``minimum``/``maximum``
    * verify the accessors match
    """
    spin_box = UnboundedSpinBox(minimum=minimum, maximum=maximum)
    qtbot.addWidget(spin_box)

    assert spin_box.minimum() == minimum
    assert spin_box.maximum() == maximum


# endregion


# region setValue vs. raw value assignment tests
@mark.parametrize(
    ("setter", "expected"),
    [
        param(lambda spin_box, value: setattr(spin_box, "value", value), 999, id="raw-value-assignment-unclamped"),
        param(lambda spin_box, value: spin_box.set_value(value), 999, id="set-value-slot-unclamped"),
        param(lambda spin_box, value: spin_box.setValue(value), 10, id="setValue-method-clamps-to-maximum"),
    ],
)
def test_writing_an_out_of_range_value_differs_by_which_setter_is_used(
    qtbot: QtBot, setter: Callable[[UnboundedSpinBox, int], None], expected: int
) -> None:
    """Only ``setValue`` (the ``QSpinBox.setValue`` counterpart) enforces ``minimum``/``maximum`` -- a raw
    ``value =`` assignment or the ``SimpleProperty``-synthesized ``set_value`` slot both write through
    unclamped.

    **Test steps:**

    * build a bounded widget
    * write ``999`` in via ``setter``
    * verify the resulting value matches ``expected`` (unclamped, or boxed to ``maximum``)
    """
    spin_box = UnboundedSpinBox(minimum=0, maximum=10)
    qtbot.addWidget(spin_box)

    setter(spin_box, 999)

    assert spin_box.value == expected


# endregion


# region stepBy tests
@mark.parametrize(
    ("value", "minimum", "maximum", "single_step", "steps", "expected"),
    [
        param(10, None, None, 5, 1, 15, id="increments-by-single-step"),
        param(10, None, None, 1, -1, 9, id="decrements-for-negative-steps"),
        param(2_147_483_647 + 1, None, None, 1, 1, 2_147_483_647 + 2, id="past-int32-with-no-wraparound"),
        param(9, None, 10, 1, 5, 10, id="clamps-at-the-maximum"),
        param(1, 0, None, 1, -5, 0, id="clamps-at-the-minimum"),
    ],
)
def test_step_by(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    qtbot: QtBot,
    value: int,
    minimum: int | None,
    maximum: int | None,
    single_step: int,
    steps: int,
    expected: int,
) -> None:
    """``stepBy`` moves ``value`` by ``steps * single_step``, boxed into ``minimum``/``maximum``, with no
    32-bit wraparound past int32.

    **Test steps:**

    * build a widget at ``value`` with the given ``single_step``/range
    * call ``stepBy(steps)``
    * verify the resulting value matches ``expected``
    """
    spin_box = UnboundedSpinBox(value=value, minimum=minimum, maximum=maximum, single_step=single_step)
    qtbot.addWidget(spin_box)

    spin_box.stepBy(steps)

    assert spin_box.value == expected


# endregion


# region stepEnabled tests
@mark.parametrize(
    ("value", "minimum", "maximum", "expected"),
    [
        param(
            0,
            None,
            None,
            UnboundedSpinBox.StepEnabledFlag.StepUpEnabled | UnboundedSpinBox.StepEnabledFlag.StepDownEnabled,
            id="unbounded-both-enabled",
        ),
        param(0, 0, None, UnboundedSpinBox.StepEnabledFlag.StepUpEnabled, id="at-minimum-down-disabled"),
        param(10, None, 10, UnboundedSpinBox.StepEnabledFlag.StepDownEnabled, id="at-maximum-up-disabled"),
        param(5, 5, 5, UnboundedSpinBox.StepEnabledFlag.StepNone, id="minimum-equals-maximum-both-disabled"),
    ],
)
def test_step_enabled_reflects_position_within_range(
    qtbot: QtBot,
    value: int,
    minimum: int | None,
    maximum: int | None,
    expected: UnboundedSpinBox.StepEnabledFlag,
) -> None:
    """``stepEnabled`` reports which direction(s) are available at the current value.

    **Test steps:**

    * build a widget at ``value`` within ``minimum``/``maximum``
    * verify ``stepEnabled`` matches ``expected``
    """
    spin_box = UnboundedSpinBox(value=value, minimum=minimum, maximum=maximum)
    qtbot.addWidget(spin_box)

    assert spin_box.stepEnabled() == expected


# endregion


# region validate tests
@mark.parametrize(
    ("text", "expected_state"),
    [
        param("", QValidator.State.Intermediate, id="empty-is-intermediate"),
        param("-", QValidator.State.Intermediate, id="bare-minus-is-intermediate"),
        param("+", QValidator.State.Intermediate, id="bare-plus-is-intermediate"),
        param("0", QValidator.State.Acceptable, id="zero-is-acceptable"),
        param("-42", QValidator.State.Acceptable, id="negative-number-is-acceptable"),
        param(str(BEYOND_INT32), QValidator.State.Acceptable, id="beyond-int32-is-acceptable"),
        param("12abc", QValidator.State.Invalid, id="trailing-garbage-is-invalid"),
        param("abc", QValidator.State.Invalid, id="non-numeric-is-invalid"),
    ],
)
def test_validate_classifies_input_text(qtbot: QtBot, text: str, expected_state: QValidator.State) -> None:
    """``validate`` classifies mid-typing text as ``Intermediate``, a full number as ``Acceptable``,
    and anything else as ``Invalid``.

    **Test steps:**

    * build a default widget
    * call ``validate`` with ``text``
    * verify the returned state matches ``expected_state``
    """
    spin_box = UnboundedSpinBox()
    qtbot.addWidget(spin_box)

    state, returned_text, pos = spin_box.validate(text, len(text))

    assert state == expected_state
    assert returned_text == text
    assert pos == len(text)


# endregion


# region fixup tests
@mark.parametrize(
    ("value", "minimum", "maximum", "text", "expected"),
    [
        param(0, 0, 10, "999", "10", id="boxes-a-valid-out-of-range-number-into-range"),
        param(7, None, None, "not a number", "7", id="falls-back-to-the-current-value-for-garbage"),
    ],
)
def test_fixup(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    qtbot: QtBot, value: int, minimum: int | None, maximum: int | None, text: str, expected: str
) -> None:
    """``fixup`` boxes a syntactically valid but out-of-range number into range, or falls back to the
    widget's current value for genuinely unparseable text.

    **Test steps:**

    * build a widget at ``value`` with the given range
    * call ``fixup`` with ``text``
    * verify the returned text matches ``expected``
    """
    spin_box = UnboundedSpinBox(value=value, minimum=minimum, maximum=maximum)
    qtbot.addWidget(spin_box)

    assert spin_box.fixup(text) == expected


# endregion


# region typed-text write-through tests
@mark.parametrize(
    ("value", "minimum", "maximum", "text", "expected"),
    [
        param(0, 0, 100, "42", 42, id="writes-through-once-it-parses"),
        param(0, None, None, str(BEYOND_INT32), BEYOND_INT32, id="beyond-int32-writes-through-exactly"),
        param(0, 0, 10, "999", 10, id="out-of-range-is-clamped-on-write-through"),
        param(5, None, None, "-", 5, id="mid-typing-text-does-not-write-through"),
    ],
)
def test_typed_text_write_through(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    qtbot: QtBot, value: int, minimum: int | None, maximum: int | None, text: str, expected: int
) -> None:
    """Typing into the line edit writes a parseable number through to ``value``, clamped into range if
    configured; text that doesn't parse yet (e.g. a bare ``-`` mid-typing a negative number) leaves
    ``value`` untouched.

    **Test steps:**

    * build a widget at ``value`` with the given range
    * set the line edit's text to ``text``
    * verify ``value`` matches ``expected``
    """
    spin_box = UnboundedSpinBox(value=value, minimum=minimum, maximum=maximum)
    qtbot.addWidget(spin_box)

    spin_box.lineEdit().setText(text)

    assert spin_box.value == expected


def test_value_change_re_renders_the_line_edit(qtbot: QtBot) -> None:
    """Setting ``value`` directly re-renders the line edit's text to match.

    **Test steps:**

    * build a widget
    * set ``value`` directly to a new number
    * verify the line edit's text follows
    """
    spin_box = UnboundedSpinBox()
    qtbot.addWidget(spin_box)

    spin_box.value = 123

    assert spin_box.lineEdit().text() == "123"


# endregion
