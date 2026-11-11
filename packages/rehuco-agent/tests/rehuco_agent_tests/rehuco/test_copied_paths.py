"""Tests for the text a browser's *Copy paths* and *Copy paths as JSON* write (#646)."""

import json
from pathlib import PureWindowsPath
from typing import Final, cast

from rehuco_agent.rehuco.copied_paths import json_paths, quoted_paths

PATHS: Final = (
    PureWindowsPath("T:/TUTORIALS/Foo"),
    PureWindowsPath("T:/TUTORIALS/ Bar "),
    PureWindowsPath("T:/REFS/pack.rehu"),
)
"""A directory-scoped record's folder, one whose name starts and ends with a space, and a standalone record, spelled
the Windows way on every platform: what is written is the path's own text, whatever the platform."""

ODD: Final = PureWindowsPath('T:/REFS/a\nb\rc"d')
"""A name holding a newline, a carriage return and a double quote."""


def test_copy_paths_quotes_every_path_one_per_line_in_order() -> None:
    """Each path is quoted as Explorer's *Copy as path* writes it, a space at either end kept inside the quotes, and
    nothing else is written between or after them.

    **Test steps:**

    * write three paths
    * verify one quoted path per line, in order, with no line after the last
    """
    assert quoted_paths(PATHS) == '"T:\\TUTORIALS\\Foo"\n"T:\\TUTORIALS\\ Bar "\n"T:\\REFS\\pack.rehu"'


def test_copy_paths_escapes_a_newline_a_carriage_return_and_a_quote_and_nothing_else() -> None:
    """A path stays on its line and inside its quotes; its backslashes are left as they are.

    **Test steps:**

    * write a path whose name holds a newline, a carriage return and a quote
    * verify they read as ``\\n``, ``\\r`` and ``\\"`` and the separators as single backslashes
    """
    assert quoted_paths([ODD]) == '"T:\\REFS\\a\\nb\\rc\\"d"'


def test_copy_paths_as_json_lists_the_paths_one_per_line_and_reads_them_back_exactly() -> None:
    """A script reads back every name as it is, whatever it holds.

    **Test steps:**

    * write three paths and the odd one as JSON
    * verify a list indented one path per line, which parses back to the paths' own text
    """
    text = json_paths([*PATHS, ODD])

    assert text.splitlines()[:2] == ["[", '  "T:\\\\TUTORIALS\\\\Foo",']
    assert text.endswith("\n]")
    assert cast(list[str], json.loads(text)) == [str(path) for path in (*PATHS, ODD)]


def test_copy_paths_as_json_keeps_a_non_ascii_name_readable() -> None:
    """A name with diacritics is written as itself, not as escapes a reader cannot read.

    **Test steps:**

    * write a path with diacritics as JSON
    * verify the text holds the name as spelled
    """
    assert json_paths([PureWindowsPath("T:/TUTORIALS/Română")]) == '[\n  "T:\\\\TUTORIALS\\\\Română"\n]'
