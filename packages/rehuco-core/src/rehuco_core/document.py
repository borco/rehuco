""".rehu document model: JSON read/write that preserves unknown fields on round-trip.

The parsed JSON object is kept verbatim as the source of truth; typed accessors read and
write the common-core fields (§17.2.1) on top of it. Keys the model does not understand --
including the whole type-keyed plugin block -- are never dropped, satisfying the
preserve-unknown-fields rule (§4.10). Writes go through :func:`borco_core.atomic_write_text`
so a crash never yields a torn file (§4.9).
"""

import json
from pathlib import Path
from typing import Any, Final

from borco_core import atomic_write_text

PRIMARY_KEY: Final = "primary"
"""Marker key on the canonical entry in ``sources`` (§17.2.3)."""


class RehuFormatError(ValueError):
    """Raised when a ``.rehu`` payload is not a JSON object."""


class RehuDocument:
    """In-memory view over one ``.rehu`` JSON document.

    Wraps the parsed object and exposes the common-core fields as typed properties while
    keeping every other key (notably the plugin block) untouched for round-trips.

    :param data: the parsed JSON object backing this document.
    :param path: the file this document was loaded from, used as the default save target.
    """

    def __init__(self, data: dict[str, Any], path: Path | None = None) -> None:
        self.__data: Final = data
        self.__path = path

    @classmethod
    def load(cls, path: Path | str) -> RehuDocument:
        """Read and parse a ``.rehu`` file from disk.

        :param path: path to the ``.rehu`` file.
        :returns: a document backed by the parsed JSON object.
        :raises RehuFormatError: if the file's top-level JSON value is not an object.
        """
        path = Path(path)
        try:
            data: object = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RehuFormatError(f"{path}: invalid JSON — {exc}") from exc
        if not isinstance(data, dict):
            raise RehuFormatError(f"{path}: expected a JSON object at the top level")
        return cls(data, path)

    def save(self, path: Path | str | None = None) -> None:
        """Atomically write the document back to disk as pretty-printed JSON.

        :param path: destination; defaults to the path the document was loaded from.
        :raises ValueError: if no path is given and the document has no loaded path.
        """
        target = Path(path) if path is not None else self.__path
        if target is None:
            raise ValueError("no path given and document was not loaded from a file")
        text = json.dumps(self.__data, indent=2, ensure_ascii=False) + "\n"
        atomic_write_text(target, text)
        self.__path = target

    @property
    def data(self) -> dict[str, Any]:
        """The backing JSON object (the source of truth, including unknown keys)."""
        return self.__data

    @property
    def path(self) -> Path | None:
        """The file this document was loaded from or last saved to, if any."""
        return self.__path

    @property
    def type(self) -> str:
        """The resource type selector (``Tutorial`` / ``ReferenceImages`` / ``Collection``)."""
        return str(self.__data.get("type", ""))

    @property
    def id(self) -> str:
        """The resource UUID (§4.2); empty string if absent (e.g. a not-yet-imported file)."""
        return str(self.__data.get("id", ""))

    @property
    def sources(self) -> list[dict[str, Any]]:
        """The ``sources`` list (§17.2.3); empty when the key is absent."""
        sources = self.__data.get("sources", [])
        return sources if isinstance(sources, list) else []

    @property
    def primary_source(self) -> dict[str, Any] | None:
        """The canonical source, resolved permissively per §17.2.3.

        The first entry flagged ``primary: true`` wins; if none is flagged, the first entry
        is treated as primary; if there are no sources, ``None``.

        :returns: the primary source object, or ``None`` when there are no sources.
        """
        sources = self.sources
        for source in sources:
            if isinstance(source, dict) and source.get(PRIMARY_KEY) is True:
                return source
        return sources[0] if sources else None

    @property
    def title(self) -> str:
        """The display title -- the primary source's ``title`` (§17.2.3); empty if none."""
        primary = self.primary_source
        return str(primary.get("title", "")) if primary else ""

    @title.setter
    def title(self, value: str) -> None:
        primary = self.primary_source
        if primary is None:
            self.__data.setdefault("sources", []).append({"title": value, PRIMARY_KEY: True})
        else:
            primary["title"] = value

    @property
    def publisher(self) -> str:
        """The primary source's ``publisher`` (§17.2.3); empty if none."""
        primary = self.primary_source
        return str(primary.get("publisher", "")) if primary else ""

    @property
    def url(self) -> str:
        """The primary source's ``url`` (§17.2.3); empty if none."""
        primary = self.primary_source
        return str(primary.get("url", "")) if primary else ""

    @property
    def authors(self) -> list[str]:
        """The shared ``authors`` list (§17.2.1); empty when absent."""
        authors = self.__data.get("authors", [])
        return [str(a) for a in authors] if isinstance(authors, list) else []

    @property
    def released(self) -> str:
        """The partial-precision content release date (§17.2), as stored; empty if absent."""
        return str(self.__data.get("released", ""))

    @property
    def advertised_tags(self) -> list[str]:
        """The web-scraped ``advertised_tags`` list (§17.2); empty when absent."""
        tags = self.__data.get("advertised_tags", [])
        return [str(t) for t in tags] if isinstance(tags, list) else []

    @property
    def extra_tags(self) -> list[str]:
        """The personal ``extra_tags`` list (§17.2); empty when absent."""
        tags = self.__data.get("extra_tags", [])
        return [str(t) for t in tags] if isinstance(tags, list) else []

    @property
    def description(self) -> str:
        """The Markdown ``description`` (§17.4), as stored; empty when absent."""
        return str(self.__data.get("description", ""))
