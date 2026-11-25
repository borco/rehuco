"""The text a browser's *Copy paths* and *Copy paths as JSON* put on the clipboard (#646, [[plugins#rehuco-dock]]).

Two formats for two readers: :func:`quoted_paths` for a person pasting into a shell or an address bar, as Explorer's
*Copy as path* writes them, and :func:`json_paths` for a script, which reads back exactly whatever the names hold --
and, for an asset that has one, where its license text is (#688, [[assets#licenses]]).
"""

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Final, NamedTuple


@dataclass(frozen=True)
class CopiedPath:
    """One selected resource, as a format writes it.

    :param path: what *Copy paths* puts down: a directory-scoped record's folder, a standalone record's file.
    :param license: the record's ``.rehuterms`` when it has one, or ``None``; only the JSON lists it.
    """

    path: PurePath
    license: PurePath | None = None


type PathsWriter = Callable[[Iterable[CopiedPath]], str]
"""Either format: the resources in, the clipboard's text out."""


class CopyFormat(NamedTuple):
    """One of the menu's ways to copy a selection's paths.

    :param text: the menu entry.
    :param write: the format.
    :param names_licenses: whether it lists each asset's license text, which asks the disk whether there is one: the
        copy then waits for a worker.
    """

    text: str
    write: PathsWriter
    names_licenses: bool = False


QUOTED_PATH_ESCAPES: Final = str.maketrans({"\n": "\\n", "\r": "\\r", '"': '\\"'})
"""What a quoted path escapes, and nothing else: a line break would split the path over two lines and a quote would end
it early. A backslash is left alone -- it is Windows' separator, so the text is for reading, not for reversing."""

JSON_INDENT: Final = 2
"""How far each path is indented in the JSON list, one per line."""


def quoted_paths(paths: Iterable[CopiedPath]) -> str:
    """One path per line, each in double quotes, with a newline, a carriage return and a quote escaped.

    Every path is quoted, not only one with a leading or trailing space, so a quote is never part of a name.

    :param paths: the resources, in the order they are written.
    :returns: the text, with nothing after the last path.
    """
    return "\n".join(f'"{str(item.path).translate(QUOTED_PATH_ESCAPES)}"' for item in paths)


def json_paths(paths: Iterable[CopiedPath]) -> str:
    """A JSON list with an object for each resource -- its ``path`` and, where it has one, the ``license`` text beside
    it -- one per line, any character kept as it is.

    :param paths: the resources, in the order they are listed.
    :returns: the text, with nothing after the closing bracket.
    """
    entries: list[dict[str, Any]] = []
    for item in paths:
        entry: dict[str, Any] = {"path": str(item.path)}
        if item.license is not None:
            entry["license"] = str(item.license)
        entries.append(entry)
    return json.dumps(entries, indent=JSON_INDENT, ensure_ascii=False)
