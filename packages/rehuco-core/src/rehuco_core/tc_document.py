""".tc (tc4, YAML) -> RehuDocument mapping ([[acquisition-tooling#tc-to-rehu]]).

Reads the legacy tutcatalog4 file format and adapts it into a fresh ``.rehu``-shaped object
([[field-schema#field-mapping]]) -- ground-truthed against tc4's own ``Tutorial`` data model
(``tutorial.h``/``tutorial.cpp``), not the later tc5/resource-hub rewrites, which were never shipped
for this purpose. No line of any old reader survives verbatim; only the field list drives this
mapping. Read-only: no ``id``/``created``/``updated`` are minted or seeded here -- those are facts about
the *resource*, and minting them is an import (write) concern for the actual conversion, not this
view-only mapping. An ``id`` minted here would be a fresh UUID on every open; ``created``/``updated``
would timestamp a write that never happened.

``format_version`` is **not** in that category and *is* stamped ([[data-model#schema-version]]): it is a
fact about the *encoding*, not the resource. This module builds the object here and now, so it can only
ever emit the current layout -- the version is something it already knows rather than something an
importer must decide, and writing it down has no side effect and is idempotent.
"""

import math
from pathlib import Path
from typing import Any, Final

import yaml

from .migrations import CURRENT_FORMAT_VERSION, current_block_version
from .plugins import DEFAULT_PLUGIN_REGISTRY, DEFAULT_UNKNOWN_USERNAME, USERS_KEY
from .rehu_document import RehuDocument, RehuFormatError
from .rehu_format import CORE_BLOCK_KEY, FORMAT_VERSION_KEY


def load_tc(path: Path | str, *, username: str = DEFAULT_UNKNOWN_USERNAME) -> RehuDocument:
    """Read a legacy ``.tc`` (YAML) file and map it into a ``RehuDocument`` ([[acquisition-tooling#tc-to-rehu]]).

    :param path: path to the ``.tc`` file.
    :param username: the identity the imported per-user flags are filed under
        ([[field-schema#per-user-shared]], #109); defaults to
        :data:`~rehuco_core.plugins.DEFAULT_UNKNOWN_USERNAME` -- a flag carried in from a ``.tc`` was not
        set by *this* install's identity, so its real owner is unknown until a caller names one.
    :returns: a document mapped to the target ``.rehu`` shape, with :attr:`RehuDocument.legacy_tc` set.
    :raises RehuFormatError: if the file's top-level YAML value is neither a mapping nor empty.
    """
    return TcDocument.load(path).to_rehu_document(path, username=username)


def tc_to_rehu_data(tc_data: dict[str, Any], *, username: str = DEFAULT_UNKNOWN_USERNAME) -> dict[str, Any]:
    """Map a parsed ``.tc`` YAML object into a fresh ``.rehu``-shaped JSON object.

    :param tc_data: the parsed YAML mapping (empty for a blank ``.tc``).
    :param username: the identity the imported per-user flags are filed under; see :func:`load_tc`.
    :returns: a JSON object ready to back a :class:`RehuDocument`.
    """
    return TcDocument(tc_data).to_rehu_data(username=username)


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

    __TYPES_WITH_BLOCK: Final = ("Tutorial", "ReferenceImages")
    """The tc4 types whose fields need a plugin block ([[plugins#plugin-blocks]]); ``Collection`` has none.

    Which *key* that block takes is not spelled here: a type's normalized name **is** its block's key
    ([[plugins#plugin-blocks]]), so both come from the plugin's own declaration rather than from a second
    table that could drift out of step with it."""

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
            raise RehuFormatError(f"Invalid YAML — {exc}.") from exc
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise RehuFormatError("Expected a YAML mapping at the top level.")
        return cls(data)

    @property
    def data(self) -> dict[str, Any]:
        """The backing parsed YAML mapping."""
        return self.__data

    @property
    def type(self) -> str:
        """The resolved resource type -- ``data``'s ``type`` if recognized, else :attr:`DEFAULT_TYPE`."""
        return self.__type

    def to_rehu_document(
        self, path: Path | str | None = None, *, username: str = DEFAULT_UNKNOWN_USERNAME
    ) -> RehuDocument:
        """Map this document into a fresh :class:`RehuDocument`, marked :attr:`~RehuDocument.legacy_tc`.

        The same ``username`` seeds the mapped per-user flags *and* the document built around them, so the
        block's ``users`` key and the document's own :attr:`~RehuDocument.username` can never disagree
        ([[field-schema#per-user-shared]]).

        :param path: the ``RehuDocument``'s path; typically the ``.tc`` path itself, since Phase 1
            doesn't yet write a converted ``.rehu`` anywhere ([[acquisition-tooling#tc-to-rehu]]).
        :param username: the identity the imported per-user flags are filed under; see :func:`load_tc`.
        :returns: the mapped, locked-for-its-own-reason document.
        """
        return RehuDocument(
            self.to_rehu_data(username=username),
            Path(path) if path is not None else None,
            legacy_tc=True,
            username=username,
        )

    def to_rehu_data(self, *, username: str = DEFAULT_UNKNOWN_USERNAME) -> dict[str, Any]:
        """Map this document into a fresh ``.rehu``-shaped JSON object.

        tc4's capitalized type spellings (``Tutorial``, ``ReferenceImages``) are aliases of the plugins'
        declared main keys ([[plugins#plugin-blocks]]), so they normalize here on the way out rather than
        being carried into rehuco's vocabulary. Together with the ``format_version`` stamp, that makes
        this a genuinely ``.rehu``-shaped object -- self-describing, and canonical on its own rather than
        only once a :class:`RehuDocument` is built around it.

        :param username: the identity the imported per-user flags are filed under; see :func:`load_tc`.
        :returns: a JSON object ready to back a :class:`RehuDocument`.
        """
        resource_type = DEFAULT_PLUGIN_REGISTRY.main_key(self.__type)
        core: dict[str, Any] = {
            "type": resource_type,
            "sources": [self.__source()],
            "authors": self.__str_list("author"),
            "description": str(self.__data.get("description", "")),
            "advertised_tags": self.__str_list("tags"),
            "extra_tags": self.__str_list("extraTags"),
        }
        # The optional scalars are *omitted* when the .tc did not carry them -- absent is not 0/"" and must
        # not be fabricated ([[field-schema#deferred-items]]); an explicit legacy value (even 0) still
        # imports ([[field-schema#ms-leak-history]]). The strings/lists above keep their coercion defaults.
        self.__put_optional(core, "released", self.__optional_released())
        self.__put_optional(core, "original_size", self.__parsed_size("original_size"))
        self.__put_optional(core, "current_size", self.__parsed_size("current_size"))
        data: dict[str, Any] = {FORMAT_VERSION_KEY: CURRENT_FORMAT_VERSION, CORE_BLOCK_KEY: core}
        if self.__type in self.__TYPES_WITH_BLOCK:
            data[resource_type] = self.__type_fields(resource_type, username)
        return data

    @staticmethod
    def __put_optional(block: dict[str, Any], key: str, value: Any) -> None:
        """Store ``value`` under ``key`` only when it is not ``None`` -- a field the ``.tc`` did not carry is
        omitted, never fabricated as ``0``/``""``/``null`` ([[field-schema#deferred-items]])."""
        if value is not None:
            block[key] = value

    def __optional_released(self) -> str | None:
        """The ``released`` date the ``.tc`` carried, as a string, or ``None`` when it was absent or empty --
        an empty date is nothing to store, so it reads back as ``None`` rather than ``""``
        ([[field-schema#deferred-items]])."""
        text = str(self.__data.get("released", ""))
        return text or None

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

    def __type_fields(self, resource_type: str, username: str) -> dict[str, Any]:
        """Build the current type-keyed plugin block shared by Tutorial and ReferenceImages
        ([[field-schema#resource-types]], [[field-schema#per-user-shared]]).

        Emits the current block layout directly rather than an old block that construction then migrates:
        the per-user subset nests under ``users[username]`` from the start, so the imported flags are filed
        to a known owner at write time -- the whole point of recording ownership while the era is
        single-user. The shared fields (``complete`` / ``online`` / ``collections`` and each type's own
        extras) stay inline, and the block is stamped at its plugin's current block version
        (:func:`~rehuco_core.current_block_version`), so :meth:`~rehuco_core.RehuDocument` treats it as
        current and never re-migrates it.

        ``favorite`` is minted ``False`` -- it is new to rehuco with no tc4 source key
        ([[field-schema#per-user-shared]]). The optional scalars ``rating``/``original_duration`` are
        *omitted* unless the ``.tc`` carried them (an explicit ``0`` imports; a missing field is not
        fabricated, [[field-schema#deferred-items]]), and ``images_count`` is always omitted -- filled later
        by scanning, never reinterpreted from tc4's leaked ``duration`` ([[field-schema#duration-size]]).

        :param resource_type: the normalized block key, used to stamp the block's current version.
        :param username: the identity the per-user subset is filed under.
        :returns: the plugin block; ``Tutorial`` additionally carries ``level`` and, when the ``.tc`` had a
            ``duration``, ``original_duration``.
        """
        block: dict[str, Any] = {
            FORMAT_VERSION_KEY: current_block_version(resource_type),
            "complete": self.__coerced_bool("complete", True),
            "online": self.__coerced_bool("online", False),
            "collections": self.__collections(),
            USERS_KEY: {username: self.__user_fields()},
        }
        if self.__type == "Tutorial":
            self.__put_optional(block, "original_duration", self.__parsed_duration("duration"))
            block["level"] = self.__str_list("level")
        # ReferenceImages (the only other type built here, see __TYPES_WITH_BLOCK) carries no extra shared
        # scalar: images_count is omitted on import, not written as null.
        return block

    def __user_fields(self) -> dict[str, Any]:
        """Build this user's per-user subset ([[field-schema#per-user-shared]]).

        The boolean flags keep their coercion defaults; the optional ``rating`` scalar is omitted unless the
        ``.tc`` carried it (an explicit value, even ``0``, imports; absent is not ``0``,
        [[field-schema#deferred-items]]).

        :returns: the per-user field map.
        """
        user: dict[str, Any] = {
            "favorite": False,
            "keep": self.__coerced_bool("keep", False),
            "learning_paths": self.__learning_paths(),
            "todo": self.__coerced_bool("todo", False),
            "viewed": self.__coerced_bool("viewed", False),
        }
        self.__put_optional(user, "rating", self.__optional_int_field("rating"))
        return user

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
        """Coerce ``data[key]`` into an int, or ``default`` when absent/malformed -- ``bool`` excluded,
        the same defensive read every accessor gets ([[data-model#write-integrity]])."""
        value = self.__data.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else default

    def __coerced_bool(self, key: str, default: bool) -> bool:
        """Coerce ``data[key]`` into a bool, or ``default`` when absent/malformed."""
        value = self.__data.get(key)
        return value if isinstance(value, bool) else default

    def __optional_int_field(self, key: str) -> int | None:
        """``data[key]`` as an int when the ``.tc`` carried it (even ``0``), else ``None`` so the caller
        omits it rather than fabricating a value ([[field-schema#deferred-items]]). A present-but-malformed
        value is treated as absent (``None``), never coerced to ``0``."""
        if key not in self.__data:
            return None
        value = self.__data.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    def __parsed_size(self, key: str) -> int | None:
        """Parse ``data[key]``: a plain int, or tc4's legacy human-readable string fallback
        (``Tutorial::fileSizeFromYaml``).

        :returns: the size in bytes when the ``.tc`` carried the key and it parsed (an explicit value
            imports, even ``0``), or ``None`` when it was absent or unparseable, so the caller omits it
            rather than fabricating a ``0`` ([[field-schema#deferred-items]]).
        """
        if key not in self.__data:
            return None
        value = self.__data.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return self.__parse_legacy_size_string(value) if isinstance(value, str) else None

    def __parse_legacy_size_string(self, value: str) -> int | None:
        """Parse a tc4 legacy size string like ``"1.5 GB"``, base-1000 (``Tutorial::parsedFileSize``).

        :param value: the human-readable size string.
        :returns: the size in bytes, or ``None`` when the magnitude or suffix isn't recognized (including a
            ``nan``/``inf``/overflowing magnitude, which ``float`` accepts but no real file size carries) --
            absent, same policy as :meth:`__optional_int_field`, not a fabricated ``0``.
        """
        parts = value.split()
        if not parts:
            return None
        try:
            magnitude = float(parts[0])
        except ValueError:
            return None
        suffix = parts[1] if len(parts) > 1 else "B"
        if suffix not in self.__SIZE_SUFFIXES:
            return None
        size = magnitude * self.__SIZE_SUFFIXES[suffix]
        return int(size) if math.isfinite(size) else None

    def __parsed_duration(self, key: str) -> int | None:
        """Parse ``data[key]``: a plain int, or tc4's legacy human-readable string fallback
        (``Tutorial::durationFromYaml``).

        :returns: the duration in seconds when the ``.tc`` carried the key (an explicit value imports, even
            ``0``), or ``None`` when it was absent, so the caller omits it rather than fabricating a ``0``
            ([[field-schema#deferred-items]], [[field-schema#ms-leak-history]]).
        """
        if key not in self.__data:
            return None
        value = self.__data.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return self.__parse_legacy_duration_string(value) if isinstance(value, str) else None

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
