"""Sanity caps for parsing an untrusted ``.rehu``/``.tc`` payload ([[data-model#write-integrity]], #88).

A ``.rehu`` is genuinely hostile-reachable -- double-click / file association, swarm sync, a received
export -- so a well-formed-looking file must not be able to exhaust memory or wedge the app before its
content is even read. Three checks, run in the order that is cheapest first:

- :func:`oversized_file_reason` -- a byte cap against ``stat()``, checked **before** the file is read
  into memory at all.
- :func:`excessive_nesting_reason` -- a string-aware scan of the raw text for JSON object/array nesting
  depth, run **before** ``json.loads`` -- CPython's JSON scanner does not consult
  ``sys.getrecursionlimit()``, it guards on C-stack headroom, so on some platforms it will happily parse
  nesting deep enough to be a memory/CPU concern regardless of the interpreter's recursion limit.
- :func:`excessive_entry_reason` -- a walk of the **parsed** value capping any one collection's length
  and any one string's length, run after parsing.

Each returns the violation as a human-readable reason, or ``None`` when the payload is within bounds --
the same shape :func:`~rehuco_core.rehu_locks.invalid_field_reasons` uses, so a caller turns a non-``None``
result into a refusal (or, per file, a locked read-only open) without this module needing to know which.

The caps below are picked against real converted data, which today runs a few kilobytes per file
([[appendices.code-conventions]] test fixtures) -- each cap sits orders of magnitude above that, so it
costs a legitimate file nothing, while still sitting far below the point a hostile payload would exhaust
memory or noticeably stall the app.
"""

from typing import Final

MAX_FILE_BYTES: Final = 1024 * 1024
"""Byte cap on a ``.rehu``/``.tc`` file, checked against ``stat()`` before it is read into memory. Nothing
in the format embeds binary data -- screenshots and videos are referenced by filename, not inlined -- so
even a verbose description or a long ``sources``/``authors`` list stays well under this."""

MAX_JSON_NESTING_DEPTH: Final = 100
"""Cap on JSON object/array nesting depth. A real ``.rehu`` nests 5 deep today; [[plugins#field-toolkit]]
lets a plugin field legitimately nest arbitrarily, so this is set far above any plausible legitimate
depth rather than at it."""

MAX_COLLECTION_LENGTH: Final = 10_000
"""Cap on the number of entries in any one JSON object or array in the parsed payload."""

MAX_STRING_LENGTH: Final = 256 * 1024
"""Cap on the length of any one JSON string in the parsed payload. Kept well below
:data:`MAX_FILE_BYTES` -- one string at the file cap would always be caught by that cap first, which
would make this one unreachable -- so this is what actually catches a single field dominating an
otherwise-compliant file."""


def oversized_file_reason(size_bytes: int) -> str | None:
    """Whether a file's size trips :data:`MAX_FILE_BYTES`.

    :param size_bytes: the file's size, e.g. from ``Path.stat().st_size``.
    :returns: a reason naming the size and the cap, or ``None`` when within bounds.
    """
    if size_bytes > MAX_FILE_BYTES:
        return f"{size_bytes} bytes exceeds the {MAX_FILE_BYTES}-byte sanity cap."
    return None


def excessive_nesting_reason(text: str) -> str | None:
    """Whether raw JSON text nests deeper than :data:`MAX_JSON_NESTING_DEPTH`, scanned **before** parsing.

    String-aware: a brace or bracket inside a JSON string (a title, a Markdown description) is ordinary
    user text, not structure, so it must not count toward depth. Tracks only whether each character sits
    inside a string literal -- it does not otherwise validate the JSON, that is ``json.loads``'s job.

    :param text: the raw file text, not yet parsed.
    :returns: a reason naming the depth and the cap, or ``None`` when within bounds.
    """
    depth = 0
    max_depth = 0
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            depth += 1
            max_depth = max(max_depth, depth)
        elif char in "}]":
            depth -= 1
    if max_depth > MAX_JSON_NESTING_DEPTH:
        return f"nesting depth {max_depth} exceeds the {MAX_JSON_NESTING_DEPTH}-level sanity cap."
    return None


def excessive_entry_reason(data: object) -> str | None:
    """Whether a parsed value holds a collection or string past :data:`MAX_COLLECTION_LENGTH` /
    :data:`MAX_STRING_LENGTH` anywhere in it. Mapping **keys** are capped like any other string -- a
    single giant key dominates a file exactly the way a giant value does.

    Walked with an explicit stack rather than recursion, and each *physical* container is visited
    **once** (by identity). For JSON the two are just belt-and-braces against unbounded depth; for YAML
    they are the whole point. ``yaml.safe_load`` honours anchors and aliases, so a few hundred bytes of
    ``.tc`` can parse into a shared DAG whose logical entry count is exponential in its size (the
    billion-laughs shape), and a self-referencing anchor parses into a genuine **cycle** -- a naive tree
    walk takes exponential time on the first and never terminates on the second, turning this very check
    into the wedge it exists to prevent. Per distinct container the caps still hold, and the visited set
    is bounded by the number of physical containers, which the byte cap already bounds.

    :param data: the parsed value (``.rehu``'s or ``.tc``'s top-level mapping, or a nested value).
    :returns: a reason naming the offending collection/string and the cap, or ``None`` when within bounds.
    """
    seen_containers: set[int] = set()
    stack = [data]
    while stack:
        value = stack.pop()
        if isinstance(value, str):
            if len(value) > MAX_STRING_LENGTH:
                return f"a string of {len(value)} characters exceeds the {MAX_STRING_LENGTH}-character sanity cap."
        elif isinstance(value, dict):
            if id(value) in seen_containers:
                continue
            seen_containers.add(id(value))
            if len(value) > MAX_COLLECTION_LENGTH:
                return f"an object with {len(value)} keys exceeds the {MAX_COLLECTION_LENGTH}-entry sanity cap."
            stack.extend(value.keys())
            stack.extend(value.values())
        elif isinstance(value, list):
            if id(value) in seen_containers:
                continue
            seen_containers.add(id(value))
            if len(value) > MAX_COLLECTION_LENGTH:
                return f"a list with {len(value)} entries exceeds the {MAX_COLLECTION_LENGTH}-entry sanity cap."
            stack.extend(value)
    return None
