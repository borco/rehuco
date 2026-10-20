"""Merge a checksum run's entries into the record as it is on disk now (#512, [[sync#lock-file]]).

A verify or a generate reads its ``.checksum`` when it starts, hashes for as long as the content takes, and writes the
record once at the end. Whatever another writer put in the record meanwhile -- a claim moved in from a neighbour
(#257), an entry forgotten (#244), another machine's run -- would be lost if the run wrote its own copy back whole. So
the write happens under the record's lock, against the file re-read there, entry by entry, keyed by name:

- **An entry the run did not change** is the file's now: a claim moved in stays, an entry forgotten stays gone.
- **An entry the run changed, added or dropped** is the run's, unless the file changed it too.
- **Both changed it**: the side with the later ``verified`` date wins -- the more recent look at the bytes. A side
  with no date (a dropped entry, a dateless claim) is older than any date; a tie goes to the run.

An entry whose name cannot be read is never the run's to change, so it is carried as the file has it.
"""

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Final

from .checksum_record import CHECKSUM_VERIFIED_KEY, checksum_entry_name, parse_verified

NEVER: Final = datetime.min.replace(tzinfo=UTC)
"""The date of an entry with none: older than every check."""


def merge_checksum_entries(base: list[Any], mine: list[Any], theirs: list[Any]) -> list[Any]:
    """The entries to write: a run's result merged into the record as it is on disk now.

    :param base: the entries the run started from -- empty for a record it did not read from disk (seeded or new), so
        everything it holds counts as its own addition.
    :param mine: the entries as the run leaves them.
    :param theirs: the entries on disk now.
    :returns: the merged entries: the run's own, in the run's order, when nothing changed the file meanwhile; else
        each name in the run's order first, then the names only the file holds, in the file's order.
    """
    if theirs == base:
        return list(mine)
    base_by_name = first_by_name(base)
    mine_by_name = first_by_name(mine)
    theirs_by_name = first_by_name(theirs)
    merged: list[Any] = []
    placed: set[str] = set()
    for raw in [*mine, *theirs]:
        name = checksum_entry_name(raw)
        if name is None:
            continue
        if name in placed:
            continue
        placed.add(name)
        if mine_by_name.get(name) == base_by_name.get(name):
            merged.extend(entry for entry in theirs if checksum_entry_name(entry) == name)
            continue
        kept = resolved(base_by_name.get(name), mine_by_name.get(name), theirs_by_name.get(name))
        if kept is not None:
            merged.append(kept)
    merged.extend(raw for raw in theirs if checksum_entry_name(raw) is None)
    return merged


def resolved(base: Any | None, mine: Any | None, theirs: Any | None) -> Any | None:
    """One entry the run changed: the run's, unless the file changed it too and holds the later check.

    :param base: the entry as the run read it, or ``None`` when the run did not have it.
    :param mine: the entry as the run leaves it, or ``None`` when it dropped it.
    :param theirs: the entry on disk now, or ``None`` when the file does not hold it.
    :returns: the entry to write, or ``None`` for none.
    """
    if theirs == base:
        return mine
    return theirs if verified_of(theirs) > verified_of(mine) else mine


def verified_of(raw: Any | None) -> datetime:
    """When an entry's file was last checked, or :data:`NEVER`.

    :param raw: the entry, or ``None`` for none.
    :returns: its date.
    """
    if not isinstance(raw, dict):
        return NEVER
    moment = parse_verified(raw.get(CHECKSUM_VERIFIED_KEY))
    return moment if moment is not None else NEVER


def first_by_name(entries: Iterable[Any]) -> dict[str, Any]:
    """Each named entry, the first of its name.

    :param entries: the raw entries.
    :returns: entry by name; an entry whose name cannot be read is left out.
    """
    found: dict[str, Any] = {}
    for raw in entries:
        name = checksum_entry_name(raw)
        if name is not None and name not in found:
            found[name] = raw
    return found
