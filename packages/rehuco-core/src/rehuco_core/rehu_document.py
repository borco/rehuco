""".rehu document model: JSON read/write that preserves unknown fields on round-trip.

The parsed JSON object is kept verbatim as the source of truth; typed accessors read and
write the common-core fields ([[field-schema#resource-types]]) on top of it. Keys the model does not understand --
including the whole type-keyed plugin block -- are never dropped, satisfying the
preserve-unknown-fields rule ([[data-model#schema-version]]). Writes go through :func:`borco_core.atomic_write_text`
so a crash never yields a torn file ([[data-model#write-integrity]]).
"""

import json
import re
from pathlib import Path
from typing import Any, Final

from borco_core import atomic_write_text

PRIMARY_KEY: Final = "primary"
"""Marker key on the canonical entry in ``sources`` ([[field-schema#sources]])."""


class RehuFormatError(ValueError):
    """Raised when a ``.rehu`` payload is not a JSON object."""


class RehuDocument:  # pylint: disable=too-many-public-methods
    """In-memory view over one ``.rehu`` JSON document.

    Wraps the parsed object and exposes the common-core fields as typed properties while
    keeping every other key (notably the plugin block) untouched for round-trips.

    :param data: the parsed JSON object backing this document.
    :param path: the file this document was loaded from, used as the default save target.
    """

    CURRENT_FORMAT_VERSION: Final = 1
    """The file-wide ``format_version`` this build understands and stamps on save
    ([[data-model#schema-version]]). A loaded document whose :attr:`format_version` is higher than this
    was written by a newer build; callers (e.g. rehuco-agent) compare against it to decide whether to
    lock the document read-only."""

    def __init__(self, data: dict[str, Any], path: Path | None = None) -> None:
        # Final forbids rebinding __data to a different dict, not mutating this one -- every
        # setter edits __data (or a dict nested inside it) in place, so it is always current
        # and save() never needs a separate sync step. __path has no such guarantee: save()
        # legitimately rebinds it when called with an explicit path.
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

        Stamps :attr:`format_version` up to :data:`CURRENT_FORMAT_VERSION` when it is currently lower
        (the upgrade-on-write half of [[data-model#schema-version]]) -- but never lowers it: a document
        loaded at a *newer* format version than this build understands still carries fields from that
        newer schema verbatim ([[data-model#schema-version]]'s preserve-unknown-fields rule), so
        overwriting its version stamp with this build's lower one would mislabel it.

        :param path: destination; defaults to the path the document was loaded from.
        :raises ValueError: if no path is given and the document has no loaded path.
        """
        target = Path(path) if path is not None else self.__path
        if target is None:
            raise ValueError("no path given and document was not loaded from a file")
        if self.format_version < self.CURRENT_FORMAT_VERSION:
            self.__data["format_version"] = self.CURRENT_FORMAT_VERSION
        text = json.dumps(self.__data, indent=2, ensure_ascii=False) + "\n"
        atomic_write_text(target, text)
        self.__path = target

    def reload(self) -> None:
        """Re-read this document from its own path, replacing all in-memory data in place.

        Picks up an out-of-band change ([[data-model#write-integrity]]) -- an edit made outside this
        app -- rather than just resetting to the last-loaded snapshot. Keeps this document's identity
        (the same backing :attr:`data` object a caller may already hold a reference to): the dict is
        cleared and refilled, not replaced.

        :raises ValueError: if this document has no path (never loaded from or saved to a file).
        :raises RehuFormatError: if the file's top-level JSON value is not an object.
        """
        if self.__path is None:
            raise ValueError("no path to reload from -- document was not loaded from a file")
        fresh = RehuDocument.load(self.__path)
        self.__data.clear()
        self.__data.update(fresh.data)

    @property
    def data(self) -> dict[str, Any]:
        """The backing JSON object (the source of truth, including unknown keys)."""
        return self.__data

    @property
    def path(self) -> Path | None:
        """The file this document was loaded from or last saved to, if any."""
        return self.__path

    @property
    def format_version(self) -> int:
        """The file-wide format-version field ([[data-model#schema-version]]); ``0`` when absent (the
        historical `.tc`-origin shape, format v0, [[acquisition-tooling#tc-to-rehu]]) or malformed (#35)."""
        value = self.__data.get("format_version", 0)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    @property
    def type(self) -> str:
        """The resource type selector (``Tutorial`` / ``ReferenceImages`` / ``Collection``)."""
        return str(self.__data.get("type", ""))

    @property
    def id(self) -> str:
        """The resource UUID ([[data-model#stable-identity]]); empty string if absent (e.g. a not-yet-imported file)."""
        return str(self.__data.get("id", ""))

    @property
    def sources(self) -> list[dict[str, Any]]:
        """The ``sources`` list ([[field-schema#sources]]); empty when the key is absent."""
        sources = self.__data.get("sources", [])
        return sources if isinstance(sources, list) else []

    @property
    def primary_source(self) -> dict[str, Any] | None:
        """The canonical source, resolved permissively per [[field-schema#sources]].

        The first entry flagged ``primary: true`` wins; if none is flagged, the first entry
        is treated as primary; if there are no sources, ``None``. Non-object entries in a
        malformed ``sources`` are skipped in both passes rather than crashing the accessors (#35).

        :returns: the primary source object, or ``None`` when there are no sources.
        """
        sources = self.sources
        for source in sources:
            if isinstance(source, dict) and source.get(PRIMARY_KEY) is True:
                return source
        return next((source for source in sources if isinstance(source, dict)), None)

    @property
    def title(self) -> str:
        """The display title -- the primary source's ``title`` ([[field-schema#sources]]); empty if none."""
        primary = self.primary_source
        return str(primary.get("title", "")) if primary else ""

    @title.setter
    def title(self, value: str) -> None:
        self.__primary_source_or_create()["title"] = value

    @property
    def publisher(self) -> str:
        """The primary source's ``publisher`` ([[field-schema#sources]]); empty if none."""
        primary = self.primary_source
        return str(primary.get("publisher", "")) if primary else ""

    @publisher.setter
    def publisher(self, value: str) -> None:
        self.__primary_source_or_create()["publisher"] = value

    @property
    def url(self) -> str:
        """The primary source's ``url`` ([[field-schema#sources]]); empty if none."""
        primary = self.primary_source
        return str(primary.get("url", "")) if primary else ""

    @url.setter
    def url(self, value: str) -> None:
        self.__primary_source_or_create()["url"] = value

    def __primary_source_or_create(self) -> dict[str, Any]:
        """Return the mutable primary source, appending a new flagged entry to ``sources`` if none exists.

        :returns: the primary source dict ([[field-schema#sources]]), attached by reference to ``sources`` so
            mutating it in place is reflected on the next :meth:`save`.
        """
        primary = self.primary_source
        if primary is None:
            primary = {PRIMARY_KEY: True}
            self.__data.setdefault("sources", []).append(primary)
        return primary

    @property
    def type_fields_key(self) -> str:
        """The type-keyed plugin block's key ([[field-schema#resource-types]]): the resource ``type`` in
        snake_case (``Tutorial`` -> ``tutorial``, ``ReferenceImages`` -> ``reference_images``); empty when
        the type is."""
        return re.sub(r"(?<!^)(?=[A-Z])", "_", self.type).lower()

    @property
    def type_fields(self) -> dict[str, Any]:
        """The type-keyed plugin block holding this type's own fields ([[field-schema#resource-types]]); an
        empty dict when the block is absent or malformed (not an object)."""
        block = self.__data.get(self.type_fields_key)
        return block if isinstance(block, dict) else {}

    def type_field(self, key: str, default: Any = None) -> Any:
        """Read a value from the type-keyed plugin block ([[field-schema#resource-types]]).

        Generic value access only -- **not** the live/inert block save invariant (A3, [[data-model#rehu-format]]).

        :param key: the key to read inside the block.
        :param default: value to return when the block or key is absent.
        :returns: the stored value, or ``default`` when absent.
        """
        return self.type_fields.get(key, default)

    def set_type_field(self, key: str, value: Any) -> None:
        """Write a value into the type-keyed plugin block ([[field-schema#resource-types]]), creating the block
        if it is absent or malformed.

        Generic value access only -- **not** the live/inert block save invariant (A3, [[data-model#rehu-format]]).

        :param key: the key to write inside the block.
        :param value: the value to store.
        """
        self.__type_fields_or_create()[key] = value

    def remove_type_field(self, key: str) -> bool:
        """Delete a key from the type-keyed plugin block ([[field-schema#resource-types]]).

        Generic value access only -- **not** the live/inert block save invariant (A3,
        [[data-model#rehu-format]]). Used to drop an unrecognized field the user explicitly discards
        via the fallback editor's remove action ([[plugins#fallback-editor]], A2.8/#28); an unremoved
        unknown field is otherwise carried verbatim on round-trip.

        :param key: the key to delete inside the block.
        :returns: ``True`` if the key was present and removed, ``False`` if the block or key was absent.
        """
        block = self.__data.get(self.type_fields_key)
        if isinstance(block, dict) and key in block:
            del block[key]
            return True
        return False

    def __type_fields_or_create(self) -> dict[str, Any]:
        """Return the mutable plugin block, installing a fresh one when absent or malformed.

        :returns: the block dict, attached by reference to ``data`` so mutating it in place is reflected
            on the next :meth:`save`.
        """
        block = self.__data.get(self.type_fields_key)
        if not isinstance(block, dict):
            block = {}
            self.__data[self.type_fields_key] = block
        return block

    @property
    def authors(self) -> list[str]:
        """The shared ``authors`` list ([[field-schema#resource-types]]); empty when absent."""
        authors = self.__data.get("authors", [])
        return [str(a) for a in authors] if isinstance(authors, list) else []

    @authors.setter
    def authors(self, value: list[str]) -> None:
        self.__data["authors"] = list(value)

    @property
    def released(self) -> str:
        """The partial-precision content release date ([[field-schema#field-mapping]]), as stored; empty if absent."""
        return str(self.__data.get("released", ""))

    @released.setter
    def released(self, value: str) -> None:
        self.__data["released"] = value

    @property
    def original_size(self) -> int:
        """Measured total size, in bytes, of the complete download ([[field-schema#duration-size]]);
        ``0`` when absent (e.g. a Collection, which has none of its own) or malformed (#35)."""
        value = self.__data.get("original_size", 0)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    @original_size.setter
    def original_size(self, value: int) -> None:
        self.__data["original_size"] = value

    @property
    def current_size(self) -> int:
        """Disk space, in bytes, currently used by this copy ([[field-schema#duration-size]]); ``0``
        when absent or malformed (#35)."""
        value = self.__data.get("current_size", 0)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    @current_size.setter
    def current_size(self, value: int) -> None:
        self.__data["current_size"] = value

    @property
    def advertised_tags(self) -> list[str]:
        """The web-scraped ``advertised_tags`` list ([[field-schema#field-mapping]]); empty when absent."""
        tags = self.__data.get("advertised_tags", [])
        return [str(t) for t in tags] if isinstance(tags, list) else []

    @advertised_tags.setter
    def advertised_tags(self, value: list[str]) -> None:
        self.__data["advertised_tags"] = list(value)

    @property
    def extra_tags(self) -> list[str]:
        """The personal ``extra_tags`` list ([[field-schema#field-mapping]]); empty when absent."""
        tags = self.__data.get("extra_tags", [])
        return [str(t) for t in tags] if isinstance(tags, list) else []

    @extra_tags.setter
    def extra_tags(self, value: list[str]) -> None:
        self.__data["extra_tags"] = list(value)

    @property
    def description(self) -> str:
        """The Markdown ``description`` ([[field-schema#field-types]]), as stored; empty when absent."""
        return str(self.__data.get("description", ""))

    @description.setter
    def description(self, value: str) -> None:
        self.__data["description"] = value

    @property
    def hidden_images(self) -> list[str]:
        """The screenshot filenames curated *out* of the lightbox ([[data-model#image-meanings]], #27).

        App-managed presentation metadata: the lightbox defaults to showing every ``<stem>NN`` sibling
        screenshot, so only the **hidden exceptions** are stored -- an empty/absent list means all are
        shown. Filenames (basenames) only, never paths. Empty when the key is absent or malformed (#35)."""
        names = self.__data.get("hidden_images", [])
        return [str(name) for name in names] if isinstance(names, list) else []

    @hidden_images.setter
    def hidden_images(self, value: list[str]) -> None:
        self.__data["hidden_images"] = list(value)
