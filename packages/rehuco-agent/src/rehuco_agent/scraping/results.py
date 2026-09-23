"""What a fetch and a scrape hand back ([[acquisition-tooling#scraper-protocols]])."""

import importlib.resources
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final, cast

import fastjsonschema
from fastjsonschema import JsonSchemaValueException


@dataclass(frozen=True)
class Page:
    """One fetched page: what was asked for, where it actually landed, and its markup.

    :param url: the URL that was asked for.
    :param final_url: where the fetch actually landed, after any redirect -- the same as :attr:`url`
        when nothing redirected.
    :param html: the page's markup.
    """

    url: str
    final_url: str
    html: str


@dataclass(frozen=True)
class ScrapedImage:
    """One image a scrape found, not yet downloaded.

    :param slot: the two-digit screenshot slot (``0`` -> ``00``) this image will take, assigned by the
        scraper in encounter order. Stem-less on purpose: the `<stem>` of `<stem>NN`
        ([[data-model#image-meanings]]) is a per-document fact -- the folder name for a directory-scoped
        resource, else the ``.rehu`` file's stem -- that neither a scraper nor a `ScrapeJob` knows;
        whoever applies a result substitutes it.
    :param url: where to download the image from.
    :param referrer: the page to send as the download's referrer, or `None` when the site does not need
        one.
    """

    slot: int
    url: str
    referrer: str | None

    def to_json(self) -> dict[str, object]:
        """This image's JSON-shaped mapping ([[acquisition-tooling#scraper-protocols]])."""
        return {"slot": self.slot, "url": self.url, "referrer": self.referrer}

    @staticmethod
    def from_mapping(mapping: Mapping[str, object]) -> ScrapedImage:
        """Build one image from its already-validated JSON-shaped mapping.

        :param mapping: one entry of a validated result's ``images`` list.
        :returns: the built image.
        """
        # schema-guaranteed by the caller (`ScrapeResult.from_mapping` validates before this runs), so
        # each cast narrows a type the validator already checked rather than trusting unchecked input.
        # `int()` rather than a bare cast: JSON Schema's `integer` admits an integral float (`2.0`), and the
        # slot is the number the `<stem>NN` name is formatted from.
        slot = int(cast(float, mapping["slot"]))
        url = cast(str, mapping["url"])
        referrer = mapping.get("referrer")
        return ScrapedImage(slot=slot, url=url, referrer=referrer if isinstance(referrer, str) else None)


SCRAPED_FIELD_NAMES: Final = (
    "title",
    "publisher",
    "url",
    "authors",
    "released",
    "description",
    "advertised_tags",
    "advertised_duration",
    "advertised_count",
    "level",
)
"""The fields a `ScrapeResult` may carry ([[acquisition-tooling#scraper-protocols]]): the part of the
plugin field-name vocabulary a web page can actually show. A scraper only converts the page it fetched
into JSON; the values the app computes from the local files (`original_size`, `current_size`, the two
measured durations, `current_count`) and the user's own state (`hidden_images`, `extra_tags`, the
boolean flags, `rating`, `learning_paths`, the `.rehu` timestamps) come from elsewhere and have no page to
be read from, so :data:`SCRAPE_RESULT_SCHEMA` rejects them rather than accept a guess.

``description`` here names the *field* (a resource's own free-text notes an editor might also carry, kept
distinct from :attr:`ScrapeResult.description`, the scrape's own Markdown write-up) -- a scraper is free to
fill both, or neither."""


INTEGER_FIELD_NAMES: Final = frozenset({"advertised_duration"})
"""The entries of :data:`SCRAPED_FIELD_NAMES` the schema types as ``integer``. JSON Schema's ``integer``
admits an integral float (``3600.0``), which the document's own getter (`rehuco_core.rehu_locks.optional_int`)
would read as malformed, so `ScrapeResult.from_mapping` stores these as the `int` they denote. Spelled out
rather than derived from the schema at import so it reads at a glance; a test holds the two together."""

SCHEMA_FILENAME: Final = "scrape_result.schema.json"
"""The checked-in draft-07 scrape-result schema, beside this module -- in the wheel as a tracked file, and
copied verbatim by Briefcase with the rest of ``src/rehuco_agent``."""

SCRAPE_RESULT_SCHEMA_TEXT: Final = (importlib.resources.files(__package__) / SCHEMA_FILENAME).read_text(
    encoding="utf-8"
)
"""The schema file's text as checked in (line endings normalized to LF by the read) -- what
``rehuco-agent --scrape-schema PATH`` writes out for a script author to point their editor's JSON validation
at: the same text, not a re-serialization, so its key order, indentation and descriptions survive."""

SCRAPE_RESULT_SCHEMA: Final[dict[str, object]] = json.loads(SCRAPE_RESULT_SCHEMA_TEXT)
"""The same schema ([[acquisition-tooling#scraper-protocols]]), parsed."""

VALIDATE_SCRAPE_RESULT: Final = cast(Callable[[object], object], fastjsonschema.compile(SCRAPE_RESULT_SCHEMA))
"""The compiled validator: built once, at import, and the one check every result -- built-in or
user-scripted, dataclass or mapping -- goes through (`ScrapeResult.from_mapping`). Raises
`fastjsonschema.JsonSchemaValueException` on the first violation and returns the value otherwise.

The cast is there because `fastjsonschema.compile` builds its validator with ``exec`` and carries no
return-type annotation, so pyright infers an unrelated structural type from the generated code's own
locals rather than "a callable"."""


class InvalidScrapeResultError(ValueError):
    """A scrape result failed :data:`SCRAPE_RESULT_SCHEMA`.

    :param path: the first error's location, e.g. ``data.fields.authors[0].url``.
    :param reason: the schema violation's own message.
    """

    def __init__(self, path: str, reason: str) -> None:
        self.path: Final = path
        self.reason: Final = reason
        super().__init__(f"{path}: {reason}")


@dataclass(frozen=True)
class ScrapeResult:
    """What one scrape found on a page: field values, a description, and images to download.

    :param fields: a plain, unvalidated mapping -- a scraper spells its keys from
        `SCRAPED_FIELD_NAMES`, the part of the plugin field-name vocabulary
        (`rehuco_core.DEFAULT_PLUGIN_REGISTRY.field_names`) a web page can show, so the spelling lines up
        with what one resource type declares while never claiming a local or personal value. A field the
        scraper could not find is simply absent, never a guess.
    :param description: Markdown, with any embedded images already rewritten to the stem-less
        placeholder :func:`~.markdown_images.rewrite_markdown_images` produces, or `None` when the
        scraper found no description.
    :param images: images to download, in the order their slots were assigned. A scraper decides for
        itself whether any of these are also referenced in :attr:`description` -- nothing here requires
        it.
    """

    fields: Mapping[str, object]
    description: str | None
    images: tuple[ScrapedImage, ...]

    def to_json(self) -> dict[str, object]:
        """This result's JSON-shaped mapping ([[acquisition-tooling#scraper-protocols]]): what a scraper
        may return directly, what `to_json`/`from_mapping` round-trip, and what
        ``rehuco-agent --scrape`` prints.

        :returns: ``{"fields": {...}, "description": str|None, "images": [{"slot", "url", "referrer"}]}``.
        """
        return {
            "fields": dict(self.fields),
            "description": self.description,
            "images": [image.to_json() for image in self.images],
        }

    @staticmethod
    def from_mapping(mapping: Mapping[str, object]) -> ScrapeResult:
        """Validate ``mapping`` against `SCRAPE_RESULT_SCHEMA` and build the result it describes.

        :param mapping: a JSON-shaped mapping, as :meth:`to_json` produces or a user script returns
            directly.
        :returns: the validated result.
        :raises InvalidScrapeResultError: ``mapping`` fails the schema, naming the first error's path.
        """
        try:
            VALIDATE_SCRAPE_RESULT(mapping)
        except JsonSchemaValueException as error:
            raise InvalidScrapeResultError(cast(str, error.name), cast(str, error.message)) from error
        # schema-guaranteed by the successful validate() call above, same as `ScrapedImage.from_mapping`'s
        # own casts -- pyright otherwise sees only `Mapping[str, object]`'s generic `.get`/`__getitem__`.
        raw_images = cast("list[Mapping[str, object]]", mapping.get("images", ()))
        images = tuple(ScrapedImage.from_mapping(entry) for entry in raw_images)
        fields = dict(cast(Mapping[str, object], mapping["fields"]))
        for name in INTEGER_FIELD_NAMES:
            value = fields.get(name)
            if isinstance(value, float):
                fields[name] = int(value)
        description = cast("str | None", mapping.get("description"))
        return ScrapeResult(fields=fields, description=description, images=images)

    @classmethod
    def coerce(cls, result: object) -> ScrapeResult:
        """Normalize whatever a `~.protocols.SiteScraper.scrape_page` call returned into a validated
        `ScrapeResult` -- the one path both `~.scrape_job.ScrapeJob` and the ``--scrape`` CLI use.

        A scraper is user code, so what it returns is treated as input from outside the app: every
        result is checked here, whether it arrived as a `ScrapeResult` or a JSON-shaped mapping, and the
        built-in scrapers are checked the same way ([[acquisition-tooling#scraper-protocols]]).

        :param result: whatever `~.protocols.SiteScraper.scrape_page` returned.
        :returns: the validated result.
        :raises InvalidScrapeResultError: ``result`` fails the schema, or is neither a `ScrapeResult` nor
            a mapping.
        """
        if isinstance(result, ScrapeResult):
            return cls.from_mapping(result.to_json())
        if isinstance(result, Mapping):
            return cls.from_mapping(result)
        raise InvalidScrapeResultError("data", f"must be a ScrapeResult or a mapping, got {type(result).__name__}")
