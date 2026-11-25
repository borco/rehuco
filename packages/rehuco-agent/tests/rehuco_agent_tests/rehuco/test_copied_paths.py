"""Tests for the text a browser's *Copy paths* and *Copy paths as JSON* write (#646, #688)."""

import json
from pathlib import PureWindowsPath
from typing import Final, cast

from rehuco_agent.rehuco.copied_paths import CopiedPath, json_paths, quoted_paths

PATHS: Final = (
    PureWindowsPath("T:/TUTORIALS/Foo"),
    PureWindowsPath("T:/TUTORIALS/ Bar "),
    PureWindowsPath("T:/REFS/pack.rehu"),
)
"""A directory-scoped record's folder, one whose name starts and ends with a space, and a standalone record, spelled
the Windows way on every platform: what is written is the path's own text, whatever the platform."""

ODD: Final = PureWindowsPath('T:/REFS/a\nb\rc"d')
"""A name holding a newline, a carriage return and a double quote."""

COPIED: Final = tuple(CopiedPath(path) for path in PATHS)
"""The same, as the selection of resources a format is handed."""

LICENSE: Final = PureWindowsPath("T:/REFS/pack.rehuterms")
"""The license text of the standalone record, which has one."""


def test_copy_paths_quotes_every_path_one_per_line_in_order() -> None:
    """Each path is quoted as Explorer's *Copy as path* writes it, a space at either end kept inside the quotes, and
    nothing else is written between or after them.

    **Test steps:**

    * write three paths
    * verify one quoted path per line, in order, with no line after the last
    """
    assert quoted_paths(COPIED) == '"T:\\TUTORIALS\\Foo"\n"T:\\TUTORIALS\\ Bar "\n"T:\\REFS\\pack.rehu"'


def test_copy_paths_escapes_a_newline_a_carriage_return_and_a_quote_and_nothing_else() -> None:
    """A path stays on its line and inside its quotes; its backslashes are left as they are.

    **Test steps:**

    * write a path whose name holds a newline, a carriage return and a quote
    * verify they read as ``\\n``, ``\\r`` and ``\\"`` and the separators as single backslashes
    """
    assert quoted_paths([CopiedPath(ODD)]) == '"T:\\REFS\\a\\nb\\rc\\"d"'


def test_copy_paths_as_json_lists_an_object_for_each_resource_and_reads_the_paths_back_exactly() -> None:
    """A script reads back every name as it is, whatever it holds.

    **Test steps:**

    * write three paths and the odd one as JSON
    * verify a list with an object for each, indented one key per line, which parses back to the paths' own text
    """
    text = json_paths([*COPIED, CopiedPath(ODD)])

    assert text.splitlines()[:3] == ["[", "  {", '    "path": "T:\\\\TUTORIALS\\\\Foo"']
    assert text.endswith("\n]")
    entries = cast(list[dict[str, str]], json.loads(text))
    assert [entry["path"] for entry in entries] == [str(path) for path in (*PATHS, ODD)]


def test_copy_paths_as_json_keeps_a_non_ascii_name_readable() -> None:
    """A name with diacritics is written as itself, not as escapes a reader cannot read.

    **Test steps:**

    * write a path with diacritics as JSON
    * verify the text holds the name as spelled
    """
    text = json_paths([CopiedPath(PureWindowsPath("T:/TUTORIALS/Română"))])

    assert text == '[\n  {\n    "path": "T:\\\\TUTORIALS\\\\Română"\n  }\n]'


def test_copy_paths_as_json_names_the_license_text_of_a_resource_that_has_one_and_no_other_key() -> None:
    """The text of an asset's license is beside its path, so what reads the selection can read the terms (#688).

    **Test steps:**

    * write a folder with no license and a standalone record with one
    * verify an object each, the second with a ``license`` key and the first with none
    """
    text = json_paths([CopiedPath(PATHS[0]), CopiedPath(PATHS[2], LICENSE)])

    assert json.loads(text) == [{"path": str(PATHS[0])}, {"path": str(PATHS[2]), "license": str(LICENSE)}]


def test_copy_paths_quoted_never_names_a_license() -> None:
    """**Test steps:**

    * write a resource that has a license text in the quoted format
    * verify the line holds its path alone
    """
    assert quoted_paths([CopiedPath(PATHS[2], LICENSE)]) == '"T:\\REFS\\pack.rehu"'
