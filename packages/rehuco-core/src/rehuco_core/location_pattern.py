"""The Locations grammar: a name pattern with optional groups, parsed once and rendered against a record's
fields ([[plugins#tutorial-plugin]], #322, #349, #577).

**A pattern is a format string with optional groups.** ``{title}`` / ``{publisher}`` / ``{authors}`` /
``{year}`` interpolate the record's fields, and a ``{{ ... }}`` group is emitted only when every
placeholder inside it has a value -- so ``{title}{{ [{year}]}}`` names a resource ``Title [2026]`` with a
year and plain ``Title`` without one, instead of ``Title []``. Whitespace inside a group is kept
verbatim, which is how a group carries its own separator. This deliberately takes ``{{`` away from
:meth:`str.format`'s literal-brace meaning: a literal brace in a folder name is never wanted, and a
group that can drop out is.

The agent's rename suggestions and a root's layouts (:mod:`rehuco_core.root_destination`) both render through
it, so the two can never disagree on what a pattern means.
"""

import string
from collections.abc import Iterable, Mapping, Sequence
from typing import Final

from .rehu_document import AuthorEntry, author_name

KNOWN_PLACEHOLDERS: Final = frozenset({"title", "publisher", "authors", "year"})
"""The four fields every type's pattern may interpolate ([[field-schema#field-mapping]]), regardless of
which plugin it belongs to -- :func:`known_placeholders_for` is what a type's *full* set is, this plus
whichever :data:`PLUGIN_PLACEHOLDERS` entries that type's declared fields back (#349)."""

PLUGIN_PLACEHOLDERS: Final[Mapping[str, str]] = {"count": "advertised_count"}
"""Placeholders beyond the base four, each gated on the type actually declaring the field it renders
(#349) -- ``{count}`` needs ``advertised_count``, so it is offered on a reference-images pattern and
refused on a tutorial one, without either page's declaration knowing the other's shape. Keyed by
placeholder name, which is what a pattern spells and what :func:`known_placeholders_for` returns."""

PLACEHOLDERS: Final = ("title", "publisher", "authors", "year", "count")
"""Every placeholder a template of any type may name, in the order a page shows them: :data:`KNOWN_PLACEHOLDERS` and
the :data:`PLUGIN_PLACEHOLDERS` names (#637)."""

BLANK_PATTERN_PROBLEM: Final = "A pattern is a format string interpolating {title} / {publisher} / {authors} / {year}."
MALFORMED_PATTERN_PROBLEM: Final = (
    "This does not parse as a format string: a { or } is unbalanced, or a placeholder carries a "
    "format spec or conversion, which a name never needs."
)
UNKNOWN_PLACEHOLDER_PROBLEM: Final = "This names a placeholder this type's patterns do not accept."
EMPTY_GROUP_PROBLEM: Final = "A {{ ... }} group must name at least one placeholder, or it could never be left out."
STRAY_GROUP_MARKER_PROBLEM: Final = (
    "A {{ is not closed, a }} is not opened, or one {{ ... }} group sits inside another."
)


def known_placeholders_for(declared_field_names: Iterable[str]) -> frozenset[str]:
    """The placeholders usable by a type whose plugin declares ``declared_field_names``
    (`~rehuco_core.PluginRegistry.field_names`, #349).

    :param declared_field_names: the type's declared field names.
    :returns: :data:`KNOWN_PLACEHOLDERS` plus every :data:`PLUGIN_PLACEHOLDERS` entry whose backing
        field is among ``declared_field_names``.
    """
    declared = frozenset(declared_field_names)
    extra = (name for name, field in PLUGIN_PLACEHOLDERS.items() if field in declared)
    return KNOWN_PLACEHOLDERS.union(extra)


class LocationPattern:
    """One pattern, parsed once into its plain and optional parts (#322).

    Parsing is a single left-to-right scan rather than a regex, because a group's inner text may itself
    hold braces -- ``{{{authors}}}`` is "authors, optional, and nothing else" -- and only a scan that
    knows it is inside a placeholder can tell that pattern's ``}}}`` apart from a group closing early.

    :param pattern: the raw pattern string, trimmed or not.
    :param known_placeholders: the placeholders this pattern may name -- :data:`KNOWN_PLACEHOLDERS`
        unless the caller's type accepts more (#349).
    """

    def __init__(self, pattern: str, known_placeholders: frozenset[str] = KNOWN_PLACEHOLDERS) -> None:
        self.__parts: list[tuple[str, bool]] = []
        """Each part's text and whether it is an optional group."""
        self.__placeholders: list[tuple[str, ...]] = []
        """Each part's placeholder names, parallel to :attr:`__parts`."""
        self.__known_placeholders: Final = known_placeholders
        self.__problem: Final = self.__parse(pattern.strip())

    @property
    def problem(self) -> str:
        """Why this pattern cannot render, or ``""`` when it can."""
        return self.__problem

    def render(self, values: Mapping[str, str], fallbacks: Mapping[str, str] | None = None) -> str:
        """Interpolate ``values``, emitting each optional group only when every placeholder inside it has
        a non-blank value.

        :param values: the record's fields, keyed by placeholder name; every known placeholder present.
        :param fallbacks: what a blank placeholder renders as **outside** an optional group (a root's fallbacks,
            [[mounts-and-storage#rehuroot]]); a group is never filled by one, so it still drops out.
        :returns: the rendered name, possibly empty; ``""`` when the pattern is invalid.
        """
        if self.__problem:
            return ""
        filled = {**values, **self.__fallen_back(values, fallbacks or {})}
        rendered: list[str] = []
        for (text, optional), placeholders in zip(self.__parts, self.__placeholders, strict=True):
            if optional and not all(values[name].strip() for name in placeholders):
                continue
            rendered.append(text.format(**(values if optional else filled)))
        return "".join(rendered)

    def missing(self, values: Mapping[str, str], fallbacks: Mapping[str, str] | None = None) -> tuple[str, ...]:
        """The placeholders outside every optional group that would render blank: the record leaves them empty and
        ``fallbacks`` names nothing for them.

        :param values: the record's fields, keyed by placeholder name; every known placeholder present.
        :param fallbacks: what a blank placeholder outside a group renders as.
        :returns: their names, each once, in pattern order; ``()`` for an invalid pattern.
        """
        if self.__problem:
            return ()
        filled = {**values, **self.__fallen_back(values, fallbacks or {})}
        required = (
            name
            for (_, optional), placeholders in zip(self.__parts, self.__placeholders, strict=True)
            if not optional
            for name in placeholders
        )
        return tuple(dict.fromkeys(name for name in required if not filled[name].strip()))

    @staticmethod
    def __fallen_back(values: Mapping[str, str], fallbacks: Mapping[str, str]) -> dict[str, str]:
        """The fallback of each placeholder the record leaves blank, where one is named and is not blank itself.

        :param values: the record's fields.
        :param fallbacks: what a blank placeholder renders as.
        :returns: the replacements, by placeholder name.
        """
        return {
            name: fallback
            for name, fallback in fallbacks.items()
            if name in values and not values[name].strip() and fallback.strip()
        }

    def __parse(self, pattern: str) -> str:
        """Split ``pattern`` into parts and check each one, filling the two part lists.

        :param pattern: the trimmed pattern.
        :returns: the first problem found, or ``""``.
        """
        if not pattern:
            return BLANK_PATTERN_PROBLEM
        problem = self.__split(pattern)
        for text, optional in self.__parts:
            if problem:
                break
            problem = self.__check_part(text, optional)
        return problem

    def __check_part(self, text: str, optional: bool) -> str:
        """Check one part's placeholders, recording their names when the part is fine.

        :param text: the part's text, a plain format string.
        :param optional: whether the part is a ``{{ ... }}`` group.
        :returns: the part's problem, or ``""``.
        """
        try:
            fields = [field for field in string.Formatter().parse(text) if field[1] is not None]
        except ValueError:
            return MALFORMED_PATTERN_PROBLEM
        # a spec or conversion is refused outright rather than passed to `str.format`: `parse` does
        # not look inside a spec, so ``{title:{series}}`` would read as valid here and raise there
        if any(spec or conversion for _, _, spec, conversion in fields):
            return MALFORMED_PATTERN_PROBLEM
        names = tuple(name for _, name, _, _ in fields if name is not None)
        if any(name not in self.__known_placeholders for name in names):
            return UNKNOWN_PLACEHOLDER_PROBLEM
        if optional and not names:
            return EMPTY_GROUP_PROBLEM
        self.__placeholders.append(names)
        return ""

    def __split(self, pattern: str) -> str:
        """Cut ``pattern`` at its ``{{`` / ``}}`` markers into :attr:`__parts`.

        A double brace only counts as a group marker outside a placeholder: while a single ``{`` is
        open, a ``}`` closes it first, so ``{{{authors}}}`` reads as one group holding ``{authors}``.

        :param pattern: the trimmed pattern.
        :returns: a group-marker problem, or ``""``.
        """
        current: list[str] = []
        in_group = False
        depth = 0
        position = 0
        while position < len(pattern):
            pair = pattern[position : position + 2]
            if pair == "{{" and depth == 0:
                if in_group:
                    return STRAY_GROUP_MARKER_PROBLEM
                self.__flush(current, optional=False)
                in_group = True
                position += 2
                continue
            if pair == "}}" and depth == 0:
                if not in_group:
                    return STRAY_GROUP_MARKER_PROBLEM
                self.__flush(current, optional=True)
                in_group = False
                position += 2
                continue
            char = pattern[position]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth < 0:
                    return MALFORMED_PATTERN_PROBLEM
            current.append(char)
            position += 1
        if in_group:
            return STRAY_GROUP_MARKER_PROBLEM
        if depth != 0:
            return MALFORMED_PATTERN_PROBLEM
        self.__flush(current, optional=False)
        return ""

    def __flush(self, current: list[str], *, optional: bool) -> None:
        """Close the part being gathered, if it holds anything, and start the next.

        :param current: the characters gathered so far; emptied.
        :param optional: whether they form a group.
        """
        if current or optional:
            self.__parts.append(("".join(current), optional))
        current.clear()


def location_pattern_problem(pattern: str, known_placeholders: frozenset[str] = KNOWN_PLACEHOLDERS) -> str:
    """Why ``pattern`` is unusable, or ``""`` when it is fine -- one spelling shared by
    :func:`normalize_location_templates`, the settings page's per-row flag and its Try-it preview.

    :param pattern: the raw pattern string, trimmed or not.
    :param known_placeholders: the placeholders this pattern may name (#349).
    :returns: one of the ``*_PROBLEM`` strings, or ``""``.
    """
    return LocationPattern(pattern, known_placeholders).problem


def location_pattern_is_valid(pattern: str, known_placeholders: frozenset[str] = KNOWN_PLACEHOLDERS) -> bool:
    """Whether ``pattern`` renders: names only known placeholders, balances its braces, and gives every
    ``{{ ... }}`` group a placeholder to depend on.

    :param pattern: the raw pattern string, trimmed or not.
    :param known_placeholders: the placeholders this pattern may name (#349).
    :returns: ``not location_pattern_problem(pattern, known_placeholders)``.
    """
    return not location_pattern_problem(pattern, known_placeholders)


def render_location_pattern(
    pattern: str, values: Mapping[str, str], known_placeholders: frozenset[str] = KNOWN_PLACEHOLDERS
) -> str:
    """Interpolate ``values`` into ``pattern``, dropping every optional group whose placeholders are not
    all filled.

    :param pattern: the raw pattern string.
    :param values: the record's fields, keyed by placeholder name; every known placeholder present.
    :param known_placeholders: the placeholders this pattern may name (#349).
    :returns: the rendered name, possibly empty; ``""`` for an invalid pattern.
    """
    return LocationPattern(pattern, known_placeholders).render(values)


def location_values(
    title: str, publisher: str, authors: Sequence[AuthorEntry], released: str | None, advertised_count: str | None
) -> dict[str, str]:
    """A record's fields as a pattern reads them, every placeholder present -- the one spelling the rename
    suggestions and a root's layouts share.

    :param title: the record's title.
    :param publisher: its publisher.
    :param authors: its author entries, joined by ``", "`` under their names.
    :param released: its release date, whose first four characters are the year; ``None`` leaves the year empty.
    :param advertised_count: its advertised count, ``None`` when it has none.
    :returns: the values, keyed by placeholder name.
    """
    return {
        "title": title,
        "publisher": publisher,
        "authors": ", ".join(author_name(entry) for entry in authors),
        "year": (released or "")[:4],
        "count": advertised_count or "",
    }
