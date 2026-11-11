"""The text a browser's *Copy paths* and *Copy paths as JSON* put on the clipboard (#646, [[plugins#rehuco-dock]]).

Two formats for two readers: :func:`quoted_paths` for a person pasting into a shell or an address bar, as Explorer's
*Copy as path* writes them, and :func:`json_paths` for a script, which reads back exactly whatever the names hold.
"""

import json
from collections.abc import Callable, Iterable
from pathlib import PurePath
from typing import Final

type PathsWriter = Callable[[Iterable[PurePath]], str]
"""Either format: the paths in, the clipboard's text out."""

QUOTED_PATH_ESCAPES: Final = str.maketrans({"\n": "\\n", "\r": "\\r", '"': '\\"'})
"""What a quoted path escapes, and nothing else: a line break would split the path over two lines and a quote would end
it early. A backslash is left alone -- it is Windows' separator, so the text is for reading, not for reversing."""

JSON_INDENT: Final = 2
"""How far each path is indented in the JSON list, one per line."""


def quoted_paths(paths: Iterable[PurePath]) -> str:
    """One path per line, each in double quotes, with a newline, a carriage return and a quote escaped.

    Every path is quoted, not only one with a leading or trailing space, so a quote is never part of a name.

    :param paths: the paths, in the order they are written.
    :returns: the text, with nothing after the last path.
    """
    return "\n".join(f'"{str(path).translate(QUOTED_PATH_ESCAPES)}"' for path in paths)


def json_paths(paths: Iterable[PurePath]) -> str:
    """A JSON list of the paths as strings, one per line, any character kept as it is.

    :param paths: the paths, in the order they are listed.
    :returns: the text, with nothing after the closing bracket.
    """
    return json.dumps([str(path) for path in paths], indent=JSON_INDENT, ensure_ascii=False)
