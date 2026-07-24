"""Tests for RehuDocumentMenuEntry: title-over-dimmed-path layout, right-elision, and width cap.

The entry backs the `View` menu's open-documents list (#61) and the `File` menu's `Open recents`
list (#64); those menus are exercised through `MainWindow` in ``test_main_window.py``. These tests
cover the widget itself in isolation (the audit's zero-gap goal, #153).
"""

from pathlib import Path

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_menu_entry import MAX_WIDTH, RehuDocumentMenuEntry

ELLIPSIS = "\N{HORIZONTAL ELLIPSIS}"
"""The character `QFontMetrics.elidedText` appends when it trims text to fit."""


def make_entry(qtbot: QtBot, title: str, path: Path | None) -> RehuDocumentMenuEntry:
    """Build a `RehuDocumentMenuEntry`, registered with qtbot for teardown."""
    entry = RehuDocumentMenuEntry(title, path)
    qtbot.addWidget(entry)
    return entry


def labels_of(entry: RehuDocumentMenuEntry) -> tuple[QLabel, QLabel]:
    """The entry's ``(title_label, path_label)`` in build order -- title above, path beneath."""
    title_label, path_label = entry.findChildren(QLabel)
    return title_label, path_label


def test_shows_the_title_above_the_path(qtbot: QtBot) -> None:
    """The entry shows the title in its first label and the full path in the second.

    **Test steps:**

    * build an entry over a short title and path (short enough that neither elides)
    * verify the first label shows the title and the second shows ``str(path)``
    """
    path = Path("/home/ada/tutorials/my.rehu")
    entry = make_entry(qtbot, "My Tutorial", path)

    title_label, path_label = labels_of(entry)

    assert title_label.text() == "My Tutorial"
    assert path_label.text() == str(path)


def test_the_path_label_is_dimmed_via_the_placeholder_role(qtbot: QtBot) -> None:
    """The path sits under the title in dimmed text -- the theme's ``PlaceholderText`` color role.

    **Test steps:**

    * build an entry
    * verify only the path label carries the ``PlaceholderText`` foreground role
    """
    entry = make_entry(qtbot, "My Tutorial", Path("/home/ada/my.rehu"))

    title_label, path_label = labels_of(entry)

    assert path_label.foregroundRole() == QPalette.ColorRole.PlaceholderText
    assert title_label.foregroundRole() != QPalette.ColorRole.PlaceholderText


def test_the_path_label_uses_a_smaller_font_than_the_title(qtbot: QtBot) -> None:
    """The path line is set in a smaller font than the title, so the title reads as primary.

    **Test steps:**

    * build an entry
    * verify the path font is the title font scaled down by the entry's 0.80 factor
    """
    entry = make_entry(qtbot, "My Tutorial", Path("/home/ada/my.rehu"))

    title_label, path_label = labels_of(entry)

    title_size = title_label.font().pointSizeF()
    path_size = path_label.font().pointSizeF()
    assert path_size < title_size
    assert path_size == title_size * 0.80  # the path-font scale applied in RehuDocumentMenuEntry


def test_a_not_yet_saved_document_shows_an_empty_path_line(qtbot: QtBot) -> None:
    """A ``None`` path (a not-yet-saved document) yields an empty path label, not ``"None"``.

    **Test steps:**

    * build an entry with no path
    * verify the title still shows and the path label is empty
    """
    entry = make_entry(qtbot, "Untitled", None)

    title_label, path_label = labels_of(entry)

    assert title_label.text() == "Untitled"
    assert path_label.text() == ""


def test_a_long_title_is_right_elided(qtbot: QtBot) -> None:
    """A title too wide for the entry is right-elided rather than growing the menu.

    **Test steps:**

    * build an entry over a very long title
    * verify the shown title is trimmed and ends with the ellipsis
    """
    long_title = "A very long tutorial title " * 40
    entry = make_entry(qtbot, long_title, Path("/home/ada/my.rehu"))

    title_label, _ = labels_of(entry)

    assert title_label.text() != long_title
    assert title_label.text().endswith(ELLIPSIS)


def test_a_long_path_is_right_elided(qtbot: QtBot) -> None:
    """A path too wide for the entry is right-elided just like the title.

    **Test steps:**

    * build an entry over a deeply nested path
    * verify the shown path is trimmed and ends with the ellipsis
    """
    long_path = Path("/home/ada/" + "nested/" * 60 + "my.rehu")
    entry = make_entry(qtbot, "My Tutorial", long_path)

    _, path_label = labels_of(entry)

    assert path_label.text() != str(long_path)
    assert path_label.text().endswith(ELLIPSIS)


def test_caps_its_width_to_keep_the_menu_bounded(qtbot: QtBot) -> None:
    """The entry caps its own width, so a long title or path elides instead of widening the menu.

    **Test steps:**

    * build an entry
    * verify its maximum width is the module's cap
    """
    entry = make_entry(qtbot, "My Tutorial", Path("/home/ada/my.rehu"))

    assert entry.maximumWidth() == MAX_WIDTH
