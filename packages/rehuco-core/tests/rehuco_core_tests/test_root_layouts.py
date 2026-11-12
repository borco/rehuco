"""Tests for a root's layouts as several path templates per type: how they are read, listed as rows and grouped back,
and how a ``.rehuroot`` keeps them (#638).

Real files in ``tmp_path``.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from pytest import mark, param
from rehuco_core import RehurootFile, grouped_layouts, layout_rows, read_layouts

ROOT: dict[str, Any] = {
    "format_version": 1,
    "id": "a41b9c3d-0000-4000-8000-000000000001",
    "label": "Tutorials",
    "location": "//nas/data/Tutorials",
    "fallbacks": {},
}


def test_a_plain_string_reads_as_one_template_and_a_list_as_its_templates() -> None:
    """A type's value is a list of templates; a string is a list of one.

    **Test steps:**

    * read layouts holding a string, a list and an empty list
    * verify each type's templates as a tuple, in order
    """
    layouts = read_layouts({"*": "*", "tutorial": ["{title}", "{authors}/{title}"], "other": []})

    assert layouts == {"*": ("*",), "tutorial": ("{title}", "{authors}/{title}"), "other": ()}


def test_reading_drops_an_exact_repeat_within_a_type() -> None:
    """A template a type lists twice is one.

    **Test steps:**

    * read a type listing a template twice, with another between
    * verify the first of each is kept, in order
    """
    assert read_layouts({"*": ["a", "b", "a"]}) == {"*": ("a", "b")}


@mark.parametrize(
    "value",
    [param([], id="not-an-object"), param({"*": 1}, id="number"), param({"*": ["a", 2]}, id="number-in-a-list")],
)
def test_reading_refuses_what_is_not_templates(value: object) -> None:
    """Anything but strings and lists of strings is refused.

    **Test steps:**

    * read each malformed value
    * verify ``ValueError``
    """
    with pytest.raises(ValueError, match="not|neither"):
        read_layouts(value)


def test_rows_list_each_template_in_offer_order_and_group_back() -> None:
    """The rows a table shows are one per template, and grouping them gives the layouts back.

    **Test steps:**

    * list the rows of layouts with a type holding two templates
    * verify the rows, then group them and verify the layouts
    """
    layouts = {"tutorial": ("{title}", "{authors}/{title}"), "*": ("*",)}

    rows = layout_rows(layouts)

    assert rows == (("tutorial", "{title}"), ("tutorial", "{authors}/{title}"), ("*", "*"))
    assert grouped_layouts(rows) == layouts


def test_grouping_gathers_a_type_at_its_first_row_and_drops_blank_types_and_repeats() -> None:
    """A type written in two places is one entry at its first row; a row with no type, and a row alike in both, count
    for nothing.

    **Test steps:**

    * group rows alternating two types, with a typeless row and an exact repeat
    * verify one entry per type, ordered by first appearance, each in row order
    """
    rows = [("a", "1"), ("b", "2"), ("", "x"), ("a", "3"), ("a", "1")]

    assert grouped_layouts(rows) == {"a": ("1", "3"), "b": ("2",)}


def test_a_file_reads_a_string_as_one_template_and_saves_lists(tmp_path: Path) -> None:
    """A hand-written file with a string is read, and a save writes every type as a list.

    **Test steps:**

    * load a file whose ``tutorial`` is a string and whose ``*`` is a list of two, then change its label and save
    * verify the layouts read, and the saved file holding both as lists
    """
    path = tmp_path / "t.rehuroot"
    path.write_text(json.dumps({**ROOT, "layouts": {"tutorial": "{title}", "*": ["*", "{title}"]}}), encoding="utf-8")
    root = RehurootFile.load(path)
    assert dict(root.layouts) == {"tutorial": ("{title}",), "*": ("*", "{title}")}
    assert not root.dirty

    root.label = "Courses"
    root.save()

    assert json.loads(path.read_text(encoding="utf-8"))["layouts"] == {"tutorial": ["{title}"], "*": ["*", "{title}"]}


def test_reordering_a_types_templates_dirties_the_file(tmp_path: Path) -> None:
    """The order of a type's templates is part of the file.

    **Test steps:**

    * load a file with two templates for a type, set the same layouts and verify it is clean
    * set them in the other order and verify it is dirty
    """
    path = tmp_path / "t.rehuroot"
    path.write_text(json.dumps({**ROOT, "layouts": {"*": ["a", "b"]}}), encoding="utf-8")
    root = RehurootFile.load(path)

    root.layouts = {"*": ("a", "b")}
    assert not root.dirty

    root.layouts = {"*": ("b", "a")}
    assert root.dirty
