"""Tests for read_resource_bytes and as_drawn_icon."""

from collections.abc import Callable
from typing import Any

import pytest
from borco_pyside.theming.utils import as_drawn_icon, read_resource_bytes
from PySide6.QtGui import QIcon
from pytestqt.qtbot import QtBot

DATA: bytes = b"some file content"


def test_reads_the_files_full_contents(mock_qfile: Callable[..., Any]) -> None:
    """A path that opens successfully returns its full contents.

    **Test steps:**

    * mock QFile to read fixed bytes
    * read the (mocked) path
    * verify the returned bytes match
    """
    mock_qfile(DATA)

    assert read_resource_bytes("some/path.svg") == DATA


def test_raises_when_the_file_cannot_be_opened(mock_qfile: Callable[..., Any]) -> None:
    """A path that fails to open raises, instead of silently returning nothing.

    **Test steps:**

    * mock QFile.open to fail
    * read the (mocked) path
    * verify RuntimeError is raised, naming the path
    """
    mock_qfile(DATA, open_ok=False)

    with pytest.raises(RuntimeError, match="missing.svg"):
        read_resource_bytes("missing.svg")


def test_as_drawn_icon_builds_a_plain_qicon(qtbot: QtBot) -> None:
    """The opt-out is exactly `QIcon(path)` -- no recolor, no palette subscription.

    **Test steps:**

    * ask for an as-drawn icon over a path
    * verify a `QIcon` came back
    """
    del qtbot

    assert isinstance(as_drawn_icon("some/path.svg"), QIcon)
