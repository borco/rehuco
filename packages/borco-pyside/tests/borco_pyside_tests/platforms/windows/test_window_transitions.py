"""Tests for the Windows open-transition suppressor (the ``DwmSetWindowAttribute`` bracket)."""

from typing import Final

from borco_pyside.platforms.windows import window_transitions
from PySide6.QtWidgets import QWidget
from pytest import mark, raises
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot

WT: Final = "borco_pyside.platforms.windows.window_transitions"
"""Module path prefix for ``mocker.patch`` targets below."""


def recorded_attribute_calls(mocker: MockerFixture) -> list[tuple[int, int, int]]:
    """Patch ``DwmSetWindowAttribute`` to record ``(hwnd, attribute, value)`` per call.

    ``ctypes.windll`` doesn't exist off Windows, so the call is patched with ``create=True``,
    matching ``test_window_activation.py``'s convention for this exact gotcha.

    :param mocker: the test's mocker.
    :returns: the list every call appends to.
    """
    calls: list[tuple[int, int, int]] = []

    def record(hwnd: object, attribute: int, value: object, size: int) -> int:
        del size
        calls.append((hwnd.value, attribute, value._obj.value))  # type: ignore[attr-defined]  # pylint: disable=protected-access
        return 0

    mocker.patch(f"{WT}.ctypes.windll.dwmapi.DwmSetWindowAttribute", create=True, side_effect=record)
    return calls


@mark.windows
def test_open_transition_disabled_brackets_the_block(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Transitions are forced off on the widget's own window before the block and back on after it.

    **Test steps:**

    * record every ``DwmSetWindowAttribute`` call
    * enter the context on a real widget and note what was recorded inside it
    * verify one disable before the block and one re-enable after, both on that widget's handle
    """
    widget = QWidget()
    qtbot.addWidget(widget)
    calls = recorded_attribute_calls(mocker)

    with window_transitions.open_transition_disabled(widget):
        inside = list(calls)

    hwnd = int(widget.winId())
    assert inside == [(hwnd, window_transitions.DWMWA_TRANSITIONS_FORCEDISABLED, 1)]
    assert calls == [
        (hwnd, window_transitions.DWMWA_TRANSITIONS_FORCEDISABLED, 1),
        (hwnd, window_transitions.DWMWA_TRANSITIONS_FORCEDISABLED, 0),
    ]


@mark.windows
def test_open_transition_is_re_enabled_even_if_the_block_raises(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A failure inside the block still hands the window's transitions back to the desktop.

    **Test steps:**

    * record every ``DwmSetWindowAttribute`` call
    * raise inside the context and expect it to propagate
    * verify the re-enable call was still made
    """
    widget = QWidget()
    qtbot.addWidget(widget)
    calls = recorded_attribute_calls(mocker)

    with raises(RuntimeError), window_transitions.open_transition_disabled(widget):
        raise RuntimeError("show failed")

    assert [value for _, _, value in calls] == [1, 0]
