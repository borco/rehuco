""".tc (tc4, YAML) -> RehuDocument mapping ([[acquisition-tooling#tc-to-rehu]]).

Reads the legacy tutcatalog4 file format and adapts it into a fresh ``.rehu``-shaped object
([[field-schema#field-mapping]]) -- ground-truthed against tc4's own ``Tutorial`` data model
(``tutorial.h``/``tutorial.cpp``), not the later tc5/resource-hub rewrites, which were never shipped
for this purpose. No line of any old reader survives verbatim; only the field list drives this
mapping. Read-only: no ``id``/``created``/``updated``/``format_version`` are minted or seeded here --
that is an import (write) concern for the actual conversion, not this view-only mapping.
"""

from pathlib import Path
from typing import Any, Final

import yaml

from rehuco_core.rehu_document import RehuDocument, RehuFormatError


def load_tc(path: Path | str) -> RehuDocument:
    """Read a legacy ``.tc`` (YAML) file and map it into a ``RehuDocument`` ([[acquisition-tooling#tc-to-rehu]]).

    :param path: path to the ``.tc`` file.
    :returns: a document mapped to the target ``.rehu`` shape, with :attr:`RehuDocument.legacy_tc` set.
    :raises RehuFormatError: if the file's top-level YAML value is neither a mapping nor empty.
    """
    return TcDocument.load(path).to_rehu_document(path)


def tc_to_rehu_data(tc_data: dict[str, Any]) -> dict[str, Any]:
    """Map a parsed ``.tc`` YAML object into a fresh ``.rehu``-shaped JSON object.

    :param tc_data: the parsed YAML mapping (empty for a blank ``.tc``).
    :returns: a JSON object ready to back a :class:`RehuDocument`.
    """
    return TcDocument(tc_data).to_rehu_data()


class TcDocument:
    """In-memory view over one legacy ``.tc`` (tc4, YAML) document ([[acquisition-tooling#tc-to-rehu]]).

    Ground-truthed against tc4's own ``Tutorial`` data model (``tutorial.h``/``tutorial.cpp``) -- not
    tc5 or resource-hub's reader, which were never shipped for this purpose. Read-only: it exists only
    to map into a fresh :class:`RehuDocument` ([[field-schema#field-mapping]]); no line of any old
    reader survives verbatim, only the field list drives the mapping.

    :param data: the parsed YAML mapping (empty for a blank ``.tc``).
    """

    VALID_TYPES: Final = ("Tutorial", "ReferenceImages", "Collection")
    """The ``type`` values tc4 wrote (its ``TutorialType`` enum, [[field-schema#resource-types]])."""

    DEFAULT_TYPE: Final = "Tutorial"
    """Fallback for a missing/unrecognized ``type``, matching tc4's own
    ``EnumHelper::fromString<TutorialType>(...).value_or(TutorialType::Tutorial)``."""

    __TYPE_FIELDS_KEYS: Final = {"Tutorial": "tutorial", "ReferenceImages": "reference_images"}
    """Plugin-block key per type ([[field-schema#resource-types]]); ``Collection`` has none."""

    __SIZE_SUFFIXES: Final = {
        "B": 1,
        "KB": 1000,
        "MB": 1000**2,
        "GB": 1000**3,
        "TB": 1000**4,
        "PB": 1000**5,
        "EB": 1000**6,
    }
    """Base-1000 multipliers for tc4's legacy human-readable size strings (``Tutorial::parsedFileSize``)."""

    __DURATION_UNIT_SECONDS: Final = {"h": 3600, "m": 60, "s": 1}
    """Seconds per unit for tc4's legacy human-readable duration strings (``Tutorial::parsedDuration``)."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.__data: Final = data
        resource_type = data.get("type")
        self.__type: Final = resource_type if resource_type in self.VALID_TYPES else self.DEFAULT_TYPE

    @classmethod
    def load(cls, path: Path | str) -> TcDocument:
        """Read and parse a ``.tc`` file from disk.

        An empty file parses to an empty document (all defaults) rather than erroring -- tc4 itself
        can leave a genuinely empty ``info.tc`` on disk.

        :param path: path to the ``.tc`` file.
        :returns: a document backed by the parsed YAML mapping.
        :raises RehuFormatError: if the file's top-level YAML value is neither a mapping nor empty.
        """
        path = Path(path)
        try:
            data: object = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise RehuFormatError(f"{path}: invalid YAML — {exc}") from exc
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise RehuFormatError(f"{path}: expected a YAML mapping at the top level")
        return cls(data)

    @property
    def data(self) -> dict[str, Any]:
        """The backing parsed YAML mapping."""
        return self.__data

    @property
    def type(self) -> str:
        """The resolved resource type -- ``data``'s ``type`` if recognized, else :attr:`DEFAULT_TYPE`."""
        return self.__type

    def to_rehu_document(self, path: Path | str | None = None) -> RehuDocument:
        """Map this document into a fresh :class:`RehuDocument`, marked :attr:`~RehuDocument.legacy_tc`.

        :param path: the ``RehuDocument``'s path; typically the ``.tc`` path itself, since Phase 1
            doesn't yet write a converted ``.rehu`` anywhere ([[acquisition-tooling#tc-to-rehu]]).
        :returns: the mapped, locked-for-its-own-reason document.
        """
        return RehuDocument(self.to_rehu_data(), Path(path) if path is not None else None, legacy_tc=True)

    def to_rehu_data(self) -> dict[str, Any]:
        """Map this document into a fresh ``.rehu``-shaped JSON object.

        :returns: a JSON object ready to back a :class:`RehuDocument`.
        """
        data: dict[str, Any] = {
            "type": self.__type,
            "sources": [self.__source()],
            "authors": self.__str_list("author"),
            "released": str(self.__data.get("released", "")),
            "description": str(self.__data.get("description", "")),
            "advertised_tags": self.__str_list("tags"),
            "extra_tags": self.__str_list("extraTags"),
            "original_size": self.__parsed_size("original_size"),
            "current_size": self.__parsed_size("current_size"),
        }
        type_fields_key = self.__TYPE_FIELDS_KEYS.get(self.__type)
        if type_fields_key is not None:
            data[type_fields_key] = self.__type_fields()
        return data

    def __source(self) -> dict[str, Any]:
        """Build the single primary ``sources`` entry from tc4's scalar title/publisher/url.

        :returns: one ``sources`` record, always created even when blank ([[field-schema#sources]]'s
            legacy-import rule).
        """
        return {
            "title": str(self.__data.get("title", "")),
            "publisher": str(self.__data.get("publisher", "")),
            "url": str(self.__data.get("url", "")),
            "primary": True,
        }

    def __type_fields(self) -> dict[str, Any]:
        """Build the type-keyed plugin block shared by Tutorial and ReferenceImages ([[field-schema#resource-types]]).

        :returns: the plugin block; ``Tutorial`` additionally carries ``original_duration``/``level``.
            ReferenceImages' leaked tc4 `duration` is dropped, not reinterpreted as `images_count`
            ([[field-schema#duration-size]]) -- left absent, to be filled later by scanning.
        """
        block: dict[str, Any] = {
            "rating": self.__coerced_int("rating", 0),
            "complete": self.__coerced_bool("complete", True),
            "online": self.__coerced_bool("online", False),
            "viewed": self.__coerced_bool("viewed", False),
            "todo": self.__coerced_bool("todo", False),
            "keep": self.__coerced_bool("keep", False),
            "collections": self.__collections(),
            "learning_paths": self.__learning_paths(),
        }
        if self.__type == "Tutorial":
            block["original_duration"] = self.__parsed_duration("duration")
            block["level"] = self.__str_list("level")
        return block

    def __collections(self) -> list[dict[str, Any]]:
        """Synthesize the ``collections`` membership list from tc4's scalar ``collection``/``collection_index``.

        :returns: a single-entry list, or empty when ``collection`` is blank ([[field-schema#sources]]).
        """
        title = str(self.__data.get("collection", ""))
        if not title.strip():
            return []
        return [{"title": title, "index": self.__coerced_int("collection_index", 0)}]

    def __learning_paths(self) -> list[dict[str, Any]]:
        """Synthesize the ``learning_paths`` record list from tc4's flat list of path names.

        :returns: one record per name, ``index`` by stored order (1-based) and ``visibility``
            defaulted to ``"private"`` -- tc4 had no visibility concept, and v1 has no swarm to share
            a public path with yet ([[field-schema#sources]]).
        """
        return [
            {"title": title, "index": index, "visibility": "private"}
            for index, title in enumerate(self.__str_list("learning_paths"), start=1)
        ]

    def __str_list(self, key: str) -> list[str]:
        """Coerce ``data[key]`` into a list of strings, or empty when absent/malformed."""
        value = self.__data.get(key)
        return [str(item) for item in value] if isinstance(value, list) else []

    def __coerced_int(self, key: str, default: int) -> int:
        """Coerce ``data[key]`` into an int, or ``default`` when absent/malformed (bool excluded, #35-style)."""
        value = self.__data.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else default

    def __coerced_bool(self, key: str, default: bool) -> bool:
        """Coerce ``data[key]`` into a bool, or ``default`` when absent/malformed."""
        value = self.__data.get(key)
        return value if isinstance(value, bool) else default

    def __parsed_size(self, key: str) -> int:
        """Parse ``data[key]``: a plain int, or tc4's legacy human-readable string fallback
        (``Tutorial::fileSizeFromYaml``).

        :returns: the size in bytes, or ``0`` when absent/malformed.
        """
        value = self.__data.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return self.__parse_legacy_size_string(value) if isinstance(value, str) else 0

    def __parse_legacy_size_string(self, value: str) -> int:
        """Parse a tc4 legacy size string like ``"1.5 GB"``, base-1000 (``Tutorial::parsedFileSize``).

        :param value: the human-readable size string.
        :returns: the size in bytes, or ``0`` when the magnitude or suffix isn't recognized.
        """
        parts = value.split()
        if not parts:
            return 0
        try:
            magnitude = float(parts[0])
        except ValueError:
            return 0
        suffix = parts[1] if len(parts) > 1 else "B"
        return int(magnitude * self.__SIZE_SUFFIXES.get(suffix, 0))

    def __parsed_duration(self, key: str) -> int:
        """Parse ``data[key]``: a plain int, or tc4's legacy human-readable string fallback
        (``Tutorial::durationFromYaml``).

        :returns: the duration in seconds, or ``0`` when absent/malformed.
        """
        value = self.__data.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return self.__parse_legacy_duration_string(value) if isinstance(value, str) else 0

    def __parse_legacy_duration_string(self, value: str) -> int:
        """Parse a tc4 legacy duration string like ``"2h 15m"`` (``Tutorial::parsedDuration``).

        :param value: the human-readable duration string.
        :returns: the total duration in seconds; an unrecognized token contributes ``0``.
        """
        total = 0
        for token in value.split():
            suffix, magnitude = token[-1:], token[:-1]
            if suffix in self.__DURATION_UNIT_SECONDS and magnitude.isdigit():
                total += int(magnitude) * self.__DURATION_UNIT_SECONDS[suffix]
        return total
