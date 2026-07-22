"""Generic helpers for a ``QLineEdit`` kept in sync with a typed value via ``parse``/``format`` hooks."""

from collections.abc import Callable

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QLineEdit

from .dynamic_properties_helpers import toggle_dynamic_property


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


def write_through_or_none[T](
    line_edit: QLineEdit, text: str, parse: Callable[[str], T | None], write: Callable[[T | None], None]
) -> None:
    """Resolve a line edit's changed ``text`` and write it through for a value type whose own domain
    already includes ``None`` -- blank text is an explicit reset *to* ``None``, not "incomplete
    typing", so it can't share an older ``parsed_value_or_reset`` shape whose own ``None`` return
    meant "leave untouched", which collides with a caller whose *target* value is legitimately
    ``None``.

    Also toggles ``line_edit``'s ``warning`` dynamic property: set for non-blank, unparseable text,
    clear otherwise.

    :param line_edit: the line edit whose ``warning`` dynamic property is toggled.
    :param text: the line edit's current text.
    :param parse: parses non-blank text into a value, or ``None`` if unparseable (mid-typing).
    :param write: called with the value to write through -- ``None`` for blank text, else the parsed
        value.
    """
    if not text.strip():
        toggle_dynamic_property(line_edit, "warning", False)
        write(None)
        return
    parsed = parse(text)
    toggle_dynamic_property(line_edit, "warning", parsed is None)
    if parsed is not None:
        write(parsed)
