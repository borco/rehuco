"""Tests for where a record would live under a root by the root's layouts, or why it may not (#577).

Pure: roots are built by hand, records named directly or from a document in memory.
"""

from pathlib import PurePosixPath
from typing import Final
from uuid import uuid4

from pytest import mark, param
from rehuco_core import (
    BUCKETS_IN_GROUP_PROBLEM,
    BUCKETS_LAST_PROBLEM,
    BUCKETS_NOT_A_LEVEL_PROBLEM,
    BUCKETS_PLACEHOLDER,
    BUCKETS_SHOWN,
    BUCKETS_TWICE_PROBLEM,
    DEFAULT_PLUGIN_REGISTRY,
    KNOWN_PLACEHOLDERS,
    UNKNOWN_PLACEHOLDER_PROBLEM_TEMPLATE,
    LayoutProblem,
    LocationPattern,
    Placement,
    RecordNaming,
    Refusal,
    RehucoRoot,
    RehuDocument,
    ReplacementRule,
    destinations,
    layout_placeholders,
    layout_template_problem,
    layout_templates,
    layout_values,
    render_layout,
    shown_place,
)

AUTHORS_THEN_TITLE: Final = "{authors}/{title}{{ [{year}]}}"

COLON: Final = (ReplacementRule(": ", " - "),)
"""A replacement table turning a colon into a separator a name keeps."""


def root(layouts: dict[str, str], fallbacks: dict[str, str] | None = None, label: str = "Tutorials") -> RehucoRoot:
    """A root with these layouts and fallbacks.

    :param layouts: its layouts.
    :param fallbacks: its fallbacks.
    :param label: its label.
    :returns: the root.
    """
    return RehucoRoot(
        uuid4(), label, "//nas/data/Tutorials", {key: (template,) for key, template in layouts.items()}, fallbacks or {}
    )


def destination(
    laid_out: RehucoRoot, record: RecordNaming, rules: tuple[ReplacementRule, ...]
) -> PurePosixPath | Refusal:
    """Where a root with one template per type puts a record.

    :param laid_out: the root.
    :param record: the record.
    :param rules: the Location Replacements.
    :returns: its one place, or why there is none.
    """
    placements = destinations(laid_out, record, rules)
    return placements if isinstance(placements, Refusal) else placements[0].relative


def naming(main_key: str = "tutorial", folder_name: str = "old name", **values: str) -> RecordNaming:
    """A record's naming: every placeholder empty unless given.

    :param main_key: its type.
    :param folder_name: its current name.
    :param values: the placeholders it fills.
    :returns: the naming.
    """
    filled = {name: "" for name in (*KNOWN_PLACEHOLDERS, "count")} | values
    return RecordNaming(main_key, folder_name, filled, KNOWN_PLACEHOLDERS)


def test_a_template_renders_one_folder_per_level_each_replaced_and_sanitized() -> None:
    """The template's ``/`` opens a level; each level gets the replacements, then the sanitize step.

    **Test steps:**

    * render ``{authors}/{title}{{ [{year}]}}`` for a record whose title holds a colon, a question mark and a letter no
      ASCII name keeps
    * verify two levels, the colon replaced, the question mark dropped, the letter transliterated
    """
    record = naming(authors="Jane Doe", title="Ünïcode: Intro?", year="2025")

    assert destination(root({"tutorial": AUTHORS_THEN_TITLE}), record, COLON) == PurePosixPath(
        "Jane Doe", "Unicode - Intro [2025]"
    )


@mark.parametrize("layouts", [param({"*": "*"}, id="any-type"), param({"tutorial": "*"}, id="its-own-type")])
def test_keep_name_keeps_the_records_current_name_at_the_top(layouts: dict[str, str]) -> None:
    """``*`` keeps the record's folder name, whatever its fields, at the root's top.

    **Test steps:**

    * ask for the destination under a root whose layout is ``*``, for any type or the record's own
    * verify the current name, one level deep
    """
    assert destination(root(layouts), naming(folder_name="My Course", title="x"), ()) == PurePosixPath("My Course")


def test_a_type_with_no_entry_and_no_star_is_not_admitted() -> None:
    """A root laid out for tutorials only refuses a reference pack, saying so.

    **Test steps:**

    * ask where a ``reference_images`` record goes under a tutorials-only root
    * verify the refusal names the root and the type
    """
    answer = destination(root({"tutorial": AUTHORS_THEN_TITLE}), naming("reference_images", title="Pack"), ())

    assert answer == Refusal("Tutorials does not take a reference_images: its layouts name no such type, and no '*'.")


def test_a_types_own_entry_wins_over_star() -> None:
    """The record's own type is looked up before ``*``.

    **Test steps:**

    * render under a root with both a ``tutorial`` entry and ``*``
    * verify the tutorial layout was used
    """
    layouts = {"tutorial": "{title}", "*": "*"}

    assert destination(root(layouts), naming(title="Intro"), ()) == PurePosixPath("Intro")


def test_a_fallback_fills_an_empty_placeholder_outside_a_group() -> None:
    """A record with no authors goes under the root's fallback for them.

    **Test steps:**

    * render ``{authors}/{title}`` for a record with no authors, under a root whose fallback names them
    * verify the fallback is the first level
    """
    answer = destination(root({"*": "{authors}/{title}"}, {"authors": "Unknown"}), naming(title="Intro"), ())

    assert answer == PurePosixPath("Unknown", "Intro")


def test_a_fallback_never_fills_an_optional_group() -> None:
    """An optional group still drops out when its placeholder is empty, a fallback for it notwithstanding.

    **Test steps:**

    * render ``{title}{{ [{year}]}}`` for a record with no year, under a root with a fallback for the year
    * verify the group is left out
    """
    answer = destination(root({"*": "{title}{{ [{year}]}}"}, {"year": "undated"}), naming(title="Intro"), ())

    assert answer == PurePosixPath("Intro")


@mark.parametrize("fallbacks", [param({}, id="none"), param({"authors": "  "}, id="blank")])
def test_an_empty_placeholder_with_no_fallback_forbids_the_root(fallbacks: dict[str, str]) -> None:
    """A level the record cannot name forbids the root, and the answer says which field is missing.

    **Test steps:**

    * render ``{authors}/{title}`` for a record with no authors, under a root with no fallback, or a blank one
    * verify the refusal names the field and the root
    """
    answer = destination(root({"*": "{authors}/{title}"}, fallbacks), naming(title="Intro"), ())

    assert answer == Refusal("The record has no authors, and Tutorials names no fallback for it.")


def test_a_root_with_no_label_is_named_by_its_location() -> None:
    """A refusal names the root by its location when its label is empty.

    **Test steps:**

    * refuse a record under an unlabeled root
    * verify the reason names the location
    """
    answer = destination(root({"*": "{authors}"}, label=""), naming(), ())

    assert answer == Refusal("The record has no authors, and //nas/data/Tutorials names no fallback for it.")


def test_a_slash_in_a_field_opens_no_level() -> None:
    """A field's own ``/`` is part of its name, as a rename suggestion treats it, never a separator.

    **Test steps:**

    * render ``{title}`` for a title holding a ``/``, with no rules, then with a rule replacing it
    * verify one level each time: the slash dropped by the sanitize step, then replaced by the rule
    """
    record = naming(title="AC/DC")
    layouts = {"*": "{title}"}

    assert destination(root(layouts), record, ()) == PurePosixPath("ACDC")
    assert destination(root(layouts), record, (ReplacementRule("/", " - "),)) == PurePosixPath("AC - DC")


@mark.parametrize(
    "authors, expected",
    [param("Jane", PurePosixPath("Jane", "Intro"), id="with-authors"), param("", PurePosixPath("Intro"), id="without")],
)
def test_a_level_inside_an_optional_group_drops_out_with_it(authors: str, expected: PurePosixPath) -> None:
    """``{{{authors}/}}`` is a level only a record with authors gets.

    **Test steps:**

    * render ``{{{authors}/}}{title}`` with authors and without
    * verify two levels, then one
    """
    assert destination(root({"*": "{{{authors}/}}{title}"}), naming(title="Intro", authors=authors), ()) == expected


@mark.parametrize(
    "template",
    [param("{title}/{{{year}}}", id="a-level-that-drops-out"), param("{title}/???", id="a-level-sanitized-away")],
)
def test_a_level_that_renders_to_nothing_forbids_the_root(template: str) -> None:
    """A folder with no name cannot be made, so the root refuses the record.

    **Test steps:**

    * render a template whose second level drops out, or sanitizes to nothing
    * verify the refusal
    """
    answer = destination(root({"*": template}), naming(title="Intro"), ())

    assert answer == Refusal("Tutorials's layout for a tutorial renders a folder with no name.")


def test_a_template_that_does_not_parse_forbids_the_root_with_its_problem() -> None:
    """A broken layout refuses every record, saying what is wrong with it.

    **Test steps:**

    * render a template naming a placeholder no type accepts
    * verify the refusal carries the grammar's problem
    """
    answer = destination(root({"*": "{series}/{title}"}), naming(title="Intro"), ())

    assert isinstance(answer, Refusal)
    problem = UNKNOWN_PLACEHOLDER_PROBLEM_TEMPLATE.format(name="series")
    assert answer.reason == f"Tutorials's layout for a tutorial cannot be used: {problem}"


@mark.parametrize(
    "kind, counted",
    [param("ReferenceImages", True, id="a-pack-names-its-count"), param("Tutorial", False, id="a-tutorial-may-not")],
)
def test_a_document_is_named_by_its_type_and_fields(kind: str, counted: bool) -> None:
    """A document's naming reads its type's main key, its fields -- the site its publisher, the site id its primary
    source's (#680) -- and ``{count}`` only where its type declares it.

    **Test steps:**

    * build a document of each type, titled, authored and released, with an advertised count and a site id
    * verify its main key, folder name and values
    * verify ``{count}`` is accepted for a reference pack only
    """
    document = RehuDocument({"core": {"id": str(uuid4()), "type": kind}})
    document.title = "Intro"
    document.publisher = "Acme"
    document.site_id = "a1b2"
    document.authors = ["Jane", {"name": "John", "url": "https://example.com"}]
    document.released = "2025-03-01"
    document.advertised_count = "900+"

    record = RecordNaming.of(document, "intro")

    assert record.main_key == kind.replace("ReferenceImages", "reference_images").lower()
    assert record.folder_name == "intro"
    assert record.values == {
        "title": "Intro",
        "publisher": "Acme",
        "authors": "Jane, John",
        "author_0": "Jane",
        "year": "2025",
        "count": "900+",
        "site": "Acme",
        "site_id": "a1b2",
    }
    assert ("count" in record.placeholders) is counted


def test_a_slash_in_a_fallback_opens_no_level() -> None:
    """A fallback stands in for a field, so its ``/`` is part of the name as a field's would be.

    **Test steps:**

    * render ``{authors}/{title}`` for a record with no authors, under a root whose fallback for them holds a ``/``
    * verify two levels, the fallback's slash dropped by the sanitize step
    """
    answer = destination(root({"*": "{authors}/{title}"}, {"authors": "Unknown/Misc"}), naming(title="Intro"), ())

    assert answer == PurePosixPath("UnknownMisc", "Intro")


def test_a_type_takes_its_own_template_else_the_star_one_else_none() -> None:
    """The template a root gives a type is its own, then ``*``'s, then none (#639).

    **Test steps:**

    * ask a root naming a type and ``*`` for each, and a root naming neither
    * verify the own templates, the ``*`` ones, and none
    """
    layouts = {"tutorial": "{title}", "*": "{authors}/*"}

    assert layout_templates(root(layouts), "tutorial") == ("{title}",)
    assert layout_templates(root(layouts), "reference_images") == ("{authors}/*",)
    assert layout_templates(root({"tutorial": "{title}"}), "reference_images") == ()


def test_a_type_with_an_empty_list_takes_the_star_templates() -> None:
    """A type whose list is empty is a type with no entry (#638).

    **Test steps:**

    * ask a root whose ``tutorial`` list is empty and whose ``*`` has two templates
    * verify the ``*`` templates, in order
    """
    laid_out = RehucoRoot(uuid4(), "Tutorials", "//nas/x", {"tutorial": (), "*": ("{title}", "*")})

    assert layout_templates(laid_out, "tutorial") == ("{title}", "*")


def several(templates: tuple[str, ...], fallbacks: dict[str, str] | None = None) -> RehucoRoot:
    """A root with these templates for any type.

    :param templates: the ``*`` templates.
    :param fallbacks: its fallbacks.
    :returns: the root.
    """
    return RehucoRoot(uuid4(), "Tutorials", "//nas/x", {"*": templates}, fallbacks or {})


def test_every_template_that_renders_is_a_place_in_row_order() -> None:
    """Each template offers its place, the template that made it beside it, in the order of the rows (#638).

    **Test steps:**

    * ask a root with three templates for a record
    * verify three places, in row order, each with its template
    """
    record = naming(authors="Jane", title="Intro")

    answer = destinations(several(("{authors}/{title}", "{title}", "*")), record, ())

    assert answer == (
        Placement(PurePosixPath("Jane", "Intro"), "{authors}/{title}"),
        Placement(PurePosixPath("Intro"), "{title}"),
        Placement(PurePosixPath("old name"), "*"),
    )


def test_two_templates_rendering_one_place_offer_it_once_at_the_first() -> None:
    """A place two templates make, even in another case, is offered once, by the first (#638).

    **Test steps:**

    * ask a root whose templates render ``Intro`` and ``intro``
    * verify one place, the first template's
    """
    answer = destinations(several(("{title}", "{title}/", "intro")), naming(title="Intro"), ())

    assert answer == (Placement(PurePosixPath("Intro"), "{title}"),)


def test_a_template_that_cannot_render_is_skipped_while_another_does() -> None:
    """A refused template offers nothing, and the others still do (#638).

    **Test steps:**

    * ask a root whose first template needs an author the record lacks, with no fallback
    * verify only the second template's place
    """
    answer = destinations(several(("{authors}/{title}", "{title}")), naming(title="Intro"), ())

    assert answer == (Placement(PurePosixPath("Intro"), "{title}"),)


def test_a_root_whose_every_template_refuses_says_why_by_the_first() -> None:
    """When nothing renders, the answer is the first template's refusal (#638).

    **Test steps:**

    * ask a root whose two templates both need a field the record lacks
    * verify a refusal naming the first missing field
    """
    answer = destinations(several(("{authors}/{title}", "{publisher}/{title}")), naming(title="Intro"), ())

    assert answer == Refusal("The record has no authors, and Tutorials names no fallback for it.")


def test_a_root_with_no_template_for_the_type_refuses_it() -> None:
    """A root naming no such type and no ``*`` takes none of it (#638).

    **Test steps:**

    * ask a root with only a ``tutorial`` entry for a reference-images record
    * verify the refusal naming the type
    """
    laid_out = RehucoRoot(uuid4(), "Tutorials", "//nas/x", {"tutorial": ("{title}",)})

    assert destinations(laid_out, naming("reference_images"), ()) == Refusal(
        "Tutorials does not take a reference_images: its layouts name no such type, and no '*'."
    )


@mark.parametrize("template", ["*", " * ", "{authors}/{title}", "{title}{{ [{year}]}}"])
def test_a_usable_template_has_no_problem(template: str) -> None:
    """``*`` and a template naming only known placeholders have no problem (#637).

    **Test steps:**

    * ask for the problem of each template under the base placeholders
    * verify each is empty
    """
    assert layout_template_problem(template, KNOWN_PLACEHOLDERS) == ""


@mark.parametrize("template", ["{author}/{title}", "{count}", "{title", ""])
def test_an_unusable_template_says_why(template: str) -> None:
    """A typo, a placeholder the type lacks, an unbalanced brace and a blank each have a problem (#637).

    **Test steps:**

    * ask for the problem of each template under the base placeholders
    * verify each is the grammar's own problem for it
    """
    assert (
        layout_template_problem(template, KNOWN_PLACEHOLDERS) == LocationPattern(template, KNOWN_PLACEHOLDERS).problem
    )
    assert layout_template_problem(template, KNOWN_PLACEHOLDERS)


def test_star_takes_the_base_placeholders_and_a_type_takes_its_own() -> None:
    """``*`` may name the base set; ``reference_images`` also ``{count}``; ``tutorial`` does not; each may bucket
    (#637, #680).

    **Test steps:**

    * ask the registry for the placeholders of ``*``, ``tutorial`` and ``reference_images``
    * verify the base set, the base set, and the base set with ``count``, each with ``buckets``
    """
    registry = DEFAULT_PLUGIN_REGISTRY
    base = KNOWN_PLACEHOLDERS | {BUCKETS_PLACEHOLDER}

    assert layout_placeholders("*", registry) == base
    assert layout_placeholders("tutorial", registry) == base
    assert layout_placeholders("reference_images", registry) == base | {"count"}


def test_render_layout_names_why_a_level_has_no_place() -> None:
    """A level with no name has no place (#637).

    **Test steps:**

    * render ``{authors}/{title}`` with empty authors and no fallback, and ``{title}`` with a title
    * verify the nameless-level problem for the first, and the title as one level for the second
    """
    values = layout_values({name: "" for name in (*KNOWN_PLACEHOLDERS, "count")} | {"title": "Intro"})

    assert (
        render_layout(LocationPattern("{authors}/{title}", KNOWN_PLACEHOLDERS), values, {}, ())
        is LayoutProblem.NAMELESS_LEVEL
    )
    assert render_layout(LocationPattern("{title}", KNOWN_PLACEHOLDERS), values, {}, ()) == Placement(
        PurePosixPath("Intro"), ""
    )


# region {buckets} (#680)

BUCKETING: Final = frozenset(KNOWN_PLACEHOLDERS | {BUCKETS_PLACEHOLDER})
"""The placeholders a layout for any type may name."""


@mark.parametrize(
    "template, values, relative, bucketed",
    [
        param(
            "{publisher}/{buckets}/{authors}/{title}",
            {"publisher": "Acme", "authors": "Jane", "title": "Intro"},
            ("Acme", "Jane", "Intro"),
            (1,),
            id="bucketed-author-folders",
        ),
        param(
            "AUTHORS/{buckets}/{authors} - {title}",
            {"authors": "Jane", "title": "Intro"},
            ("AUTHORS", "Jane - Intro"),
            (1,),
            id="bucketed-items-by-author",
        ),
        param(
            "TUTORIALS/{buckets}/{title}{{ - {authors}}}",
            {"title": "Intro"},
            ("TUTORIALS", "Intro"),
            (1,),
            id="bucketed-by-title",
        ),
        param(
            "{site}/{buckets}/{site_id}",
            {"publisher": "fab", "site": "fab", "site_id": "01abc"},
            ("fab", "01abc"),
            (1,),
            id="a-store-library",
        ),
        param(
            "{site}/{buckets}/{authors}/{buckets}/{title}",
            {"site": "fab", "authors": "Jane", "title": "Intro"},
            ("fab", "Jane", "Intro"),
            (1, 2),
            id="two-bucketed-levels",
        ),
        param("{buckets}/{title}", {"title": "Intro"}, ("Intro",), (0,), id="at-the-roots-top"),
    ],
)
def test_a_buckets_level_marks_the_level_after_it(
    template: str, values: dict[str, str], relative: tuple[str, ...], bucketed: tuple[int, ...]
) -> None:
    """``{buckets}`` is no folder of its own: the place leaves it out and marks the level after it as bucketed.

    **Test steps:**

    * ask for the place a template naming ``{buckets}`` gives a record, for each shape the owner uses
    * verify the place without its buckets, and the indices of the bucketed levels
    """
    answer = destinations(root({"*": template}), naming(**values), ())

    assert answer == (Placement(PurePosixPath(*relative), template, bucketed),)


@mark.parametrize(
    "template, problem",
    [
        param("{{{buckets}/}}{title}", BUCKETS_IN_GROUP_PROBLEM, id="in-a-group"),
        param("x{buckets}/{title}", BUCKETS_NOT_A_LEVEL_PROBLEM, id="part-of-a-level"),
        param("{buckets}{buckets}/{title}", BUCKETS_NOT_A_LEVEL_PROBLEM, id="twice-in-one-level"),
        param("{title}/{buckets}", BUCKETS_LAST_PROBLEM, id="last"),
        param("{buckets}/{buckets}/{title}", BUCKETS_TWICE_PROBLEM, id="right-after-another"),
    ],
)
def test_a_buckets_level_out_of_place_is_a_templates_problem(template: str, problem: str) -> None:
    """``{buckets}`` is a whole level, outside every group, followed by a level that is not one too.

    **Test steps:**

    * ask for the problem of each misplaced ``{buckets}``, and the place a root with it gives a record
    * verify the problem, and the refusal carrying it
    """
    assert layout_template_problem(template, BUCKETING) == problem
    answer = destination(root({"*": template}), naming(title="Intro"), ())
    assert answer == Refusal(f"Tutorials's layout for a tutorial cannot be used: {problem}")


def test_a_usable_buckets_template_has_no_problem() -> None:
    """A ``{buckets}`` level before a level, with spaces around it, is fine; a template naming none is too.

    **Test steps:**

    * ask for the problems of a spaced ``{buckets}`` level and of a plain template, under the bucketing set
    * verify both are empty
    """
    assert layout_template_problem("{site}/ {buckets} /{site_id}", BUCKETING) == ""
    assert layout_template_problem("{title}", BUCKETING) == ""


def test_buckets_needs_a_layouts_placeholders() -> None:
    """A template naming ``{buckets}`` under a rename pattern's placeholders refuses it by name.

    **Test steps:**

    * ask for the problem of a ``{buckets}`` template under the base set alone
    * verify the unknown-placeholder problem naming it
    """
    problem = layout_template_problem("{buckets}/{title}", KNOWN_PLACEHOLDERS)

    assert problem == UNKNOWN_PLACEHOLDER_PROBLEM_TEMPLATE.format(name=BUCKETS_PLACEHOLDER)


def test_a_level_after_buckets_that_drops_out_refuses_the_record() -> None:
    """A bucketed level carried by an optional group the record leaves out leaves nothing to bucket.

    **Test steps:**

    * ask for the place ``{title}/{buckets}{{/{authors}}}`` gives a record with no authors, and with them
    * verify the refusal, then the place with its author bucketed
    """
    template = "{title}/{buckets}{{/{authors}}}"

    assert destination(root({"*": template}), naming(title="Intro"), ()) == Refusal(
        "Tutorials's layout for a tutorial renders no level after {buckets}."
    )
    assert destinations(root({"*": template}), naming(title="Intro", authors="Jane"), ()) == (
        Placement(PurePosixPath("Intro", "Jane"), template, (1,)),
    )


def test_a_bucketed_place_and_a_plain_one_are_two_places() -> None:
    """The same path with buckets and without is offered twice: they end in different folders.

    **Test steps:**

    * ask a root with ``fab/{title}`` and ``fab/{buckets}/{title}`` for a record
    * verify both places, in row order
    """
    answer = destinations(several(("fab/{title}", "fab/{buckets}/{title}")), naming(title="Intro"), ())

    assert answer == (
        Placement(PurePosixPath("fab", "Intro"), "fab/{title}"),
        Placement(PurePosixPath("fab", "Intro"), "fab/{buckets}/{title}", (1,)),
    )


def test_a_bucketed_place_shows_its_buckets_unresolved() -> None:
    """A place's buckets are drawn as an ellipsis before each bucketed level until they are read off the disk.

    **Test steps:**

    * read how a place with two bucketed levels is shown, and one with none
    * verify the ellipsis before each bucketed level, and the plain place
    """
    place = Placement(PurePosixPath("fab", "Jane", "Intro"), "", (1, 2))

    assert place.shown == PurePosixPath("fab", BUCKETS_SHOWN, "Jane", BUCKETS_SHOWN, "Intro")
    assert shown_place(PurePosixPath("fab", "Intro"), ()) == PurePosixPath("fab", "Intro")


# endregion


@mark.parametrize("title", [".hidden", ". hidden"])
def test_a_level_starting_with_a_dot_refuses_the_record(title: str) -> None:
    """No location starts with a dot (#680): a level that renders to one refuses the record.

    **Test steps:**

    * ask for the place ``{title}`` gives a record whose title starts with a dot
    * verify the refusal saying so
    """
    answer = destination(root({"*": "{title}"}), naming(title=title), ())

    assert answer == Refusal(
        "Tutorials's layout for a tutorial renders a folder starting with a dot, which no location may."
    )


@mark.parametrize("title", ["_inbox", "[2020] Intro", "(Remastered) Intro", "#1 Hits"])
def test_a_level_starting_with_another_sign_is_kept(title: str) -> None:
    """Only a dot is refused at a name's start; other signs stay (#680).

    **Test steps:**

    * ask for the place ``{title}`` gives a record whose title starts with an underscore, a bracket or a hash
    * verify the title is the place
    """
    assert destination(root({"*": "{title}"}), naming(title=title), ()) == PurePosixPath(title)


def test_keep_name_keeps_a_name_starting_with_a_dot() -> None:
    """``*`` keeps the name a record has, a dot or not: the rule is for names being made.

    **Test steps:**

    * ask a ``*`` root for the place of a record named with a leading dot
    * verify that name is the place
    """
    assert destination(root({"*": "*"}), naming(folder_name=".old"), ()) == PurePosixPath(".old")
