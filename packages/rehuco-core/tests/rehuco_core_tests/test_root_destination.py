"""Tests for where a record would live under a root by the root's layouts, or why it may not (#577).

Pure: roots are built by hand, records named directly or from a document in memory.
"""

from pathlib import PurePosixPath
from typing import Final
from uuid import uuid4

from pytest import mark, param
from rehuco_core import (
    DEFAULT_PLUGIN_REGISTRY,
    KNOWN_PLACEHOLDERS,
    LocationPattern,
    RecordNaming,
    Refusal,
    RehucoRoot,
    RehuDocument,
    ReplacementRule,
    destination,
    layout_placeholders,
    layout_template,
    layout_template_problem,
    render_layout,
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
    return RehucoRoot(uuid4(), label, "//nas/data/Tutorials", layouts, fallbacks or {})


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

    * refuse a record under an unlabelled root
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
    assert answer.reason.startswith("Tutorials's layout for a tutorial cannot be used: This names a placeholder")


@mark.parametrize(
    "kind, counted",
    [param("ReferenceImages", True, id="a-pack-names-its-count"), param("Tutorial", False, id="a-tutorial-may-not")],
)
def test_a_document_is_named_by_its_type_and_fields(kind: str, counted: bool) -> None:
    """A document's naming reads its type's main key, its fields, and ``{count}`` only where its type declares it.

    **Test steps:**

    * build a document of each type, titled, authored and released, with an advertised count
    * verify its main key, folder name and values
    * verify ``{count}`` is accepted for a reference pack only
    """
    document = RehuDocument({"core": {"id": str(uuid4()), "type": kind}})
    document.title = "Intro"
    document.publisher = "Acme"
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
        "year": "2025",
        "count": "900+",
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
    * verify the own template, the ``*`` one, and ``None``
    """
    layouts = {"tutorial": "{title}", "*": "{authors}/*"}

    assert layout_template(root(layouts), "tutorial") == "{title}"
    assert layout_template(root(layouts), "reference_images") == "{authors}/*"
    assert layout_template(root({"tutorial": "{title}"}), "reference_images") is None


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
    """``*`` may name the base four; ``reference_images`` also ``{count}``; ``tutorial`` does not (#637).

    **Test steps:**

    * ask the registry for the placeholders of ``*``, ``tutorial`` and ``reference_images``
    * verify the base four, the base four, and the base four with ``count``
    """
    registry = DEFAULT_PLUGIN_REGISTRY

    assert layout_placeholders("*", registry) == KNOWN_PLACEHOLDERS
    assert layout_placeholders("tutorial", registry) == KNOWN_PLACEHOLDERS
    assert layout_placeholders("reference_images", registry) == KNOWN_PLACEHOLDERS | {"count"}


def test_render_layout_gives_none_for_a_level_that_renders_to_nothing() -> None:
    """A level with no name has no path (#637).

    **Test steps:**

    * render ``{authors}/{title}`` with empty authors and no fallback, and ``{title}`` with a title
    * verify ``None`` for the first, and the title as one level for the second
    """
    values = {name: "" for name in (*KNOWN_PLACEHOLDERS, "count")} | {"title": "Intro"}

    assert render_layout(LocationPattern("{authors}/{title}", KNOWN_PLACEHOLDERS), values, {}, ()) is None
    assert render_layout(LocationPattern("{title}", KNOWN_PLACEHOLDERS), values, {}, ()) == PurePosixPath("Intro")
