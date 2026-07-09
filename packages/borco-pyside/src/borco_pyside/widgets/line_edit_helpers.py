"""Generic helpers for a ``QLineEdit`` kept in sync with a typed value via ``parse``/``format`` hooks."""

from collections.abc import Callable

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QLineEdit


def resync_line_edit[T](
    line_edit: QLineEdit, value: T, parse: Callable[[str], T | None], format_value: Callable[[T], str]
) -> None:
    """Re-sync ``line_edit`` to ``value`` (an echo guard, under a signal blocker).

    Compares ``line_edit``'s current text *parsed* against ``value``, not the raw text -- so a
    keystroke that round-trips through ``value`` doesn't bounce back and reset the cursor or
    silently reformat text a caller is still typing (e.g. ``"1h30m"`` staying as typed instead of
    snapping to ``"1h 30m"``).

    :param line_edit: the line edit to resync.
    :param value: the value it should reflect.
    :param parse: parses the line edit's text back into a value, or ``None`` if unparseable.
    :param format_value: renders ``value`` as display text.
    """
    if parse(line_edit.text()) != value:
        with QSignalBlocker(line_edit):
            line_edit.setText(format_value(value))


def parsed_value_or_reset[T](text: str, reset: T, parse: Callable[[str], T | None]) -> T | None:
    """Resolve a line edit's changed text into the value it should write through, if any.

    Blank text is treated as an explicit reset to ``reset``, not "incomplete typing" -- distinct
    from genuinely unparseable non-empty text, which resolves to ``None`` so mid-keystroke typing
    (e.g. ``"1h 3"``) is never clobbered.

    :param text: the line edit's current text.
    :param reset: the value blank text should reset to.
    :param parse: parses non-blank text into a value, or ``None`` if unparseable.
    :returns: the value to write through, or ``None`` to leave the current value untouched.
    """
    if not text.strip():
        return reset
    return parse(text)
