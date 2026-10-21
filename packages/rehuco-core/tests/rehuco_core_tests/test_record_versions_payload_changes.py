"""Tests for what one payload changed over another, and whether two field paths touch (#497): what a save's
merge-back keeps of the edits a document made while the save ran ([[sync#pending-saves]]).
"""

import copy
from typing import Any, Final

from pytest import mark
from rehuco_core import ABSENT, FieldPath, paths_overlap, payload_changes, put_paths

BEFORE: Final[dict[str, Any]] = {
    "format_version": 2,
    "core": {"type": "tutorial", "description": "original", "tags": ["a", "b"]},
    "tutorial": {"format_version": 1, "users": {"admin": {"rating": 1}}},
}
"""The earlier payload every change here is made over."""


def changed(**core: Any) -> dict[str, Any]:
    """:data:`BEFORE` with ``core`` fields replaced, removed where the value is :data:`ABSENT`.

    :param core: the fields.
    :returns: a new payload.
    """
    after = copy.deepcopy(BEFORE)
    for key, value in core.items():
        if value is ABSENT:
            del after["core"][key]
        else:
            after["core"][key] = value
    return after


# region payload changes
def test_equal_payloads_change_nothing() -> None:
    """Two equal payloads differ nowhere.

    **Test steps:**

    * compare a payload with a deep copy of itself; verify no changes
    """
    assert not payload_changes(BEFORE, copy.deepcopy(BEFORE))


def test_a_changed_added_and_removed_field_are_each_a_change() -> None:
    """A changed field carries its new value, an added one its value, a removed one :data:`ABSENT`.

    **Test steps:**

    * change the description, add a title and remove the tags
    * verify exactly those three paths, with the new values and :data:`ABSENT`
    """
    after = changed(description="edited", title="Sculpting", tags=ABSENT)

    assert payload_changes(BEFORE, after) == {
        ("core", "description"): "edited",
        ("core", "title"): "Sculpting",
        ("core", "tags"): ABSENT,
    }


def test_a_list_of_the_same_length_changes_item_by_item() -> None:
    """A list as long as before is compared item by item, so only the item that changed is a change.

    **Test steps:**

    * change the second tag; verify the one change is at its index
    """
    assert payload_changes(BEFORE, changed(tags=["a", "c"])) == {("core", "tags", 1): "c"}


def test_a_list_of_another_length_changes_as_a_whole() -> None:
    """A list that grew or shrank is one change, the whole new list.

    **Test steps:**

    * add a tag; verify the change is the whole list at the tags' path
    """
    assert payload_changes(BEFORE, changed(tags=["a", "b", "c"])) == {("core", "tags"): ["a", "b", "c"]}


def test_a_value_that_changed_kind_changes_as_a_whole() -> None:
    """An object that became something else is one change, the new value.

    **Test steps:**

    * replace the ``core`` object's tags list with text; verify the change is the text
    * replace the whole ``tutorial`` block with text; verify the change is the text, at the block's path
    * compare two different scalars at the top; verify the change is at the empty path
    """
    after = changed(tags="a, b")
    after["tutorial"] = "none"

    assert payload_changes(BEFORE, after) == {("core", "tags"): "a, b", ("tutorial",): "none"}
    assert payload_changes(1, 2) == {(): 2}


def test_per_user_fields_and_stamps_are_changes_too() -> None:
    """Unlike a conflict's differences, nothing is left out: a per-user field and a version stamp are changes.

    **Test steps:**

    * change a rating and the block's format version
    * verify both are changes
    """
    after = copy.deepcopy(BEFORE)
    after["tutorial"]["users"]["admin"]["rating"] = 5
    after["tutorial"]["format_version"] = 2

    assert payload_changes(BEFORE, after) == {
        ("tutorial", "users", "admin", "rating"): 5,
        ("tutorial", "format_version"): 2,
    }


def test_the_changes_put_onto_the_earlier_payload_give_the_later_one() -> None:
    """The changes are the shape :func:`~rehuco_core.put_paths` takes, so putting them onto the earlier payload
    gives the later one.

    **Test steps:**

    * make a change of each kind, take the changes, and put them onto a copy of the earlier payload
    * verify the copy now equals the later payload
    """
    after = changed(description="edited", title="Sculpting", tags=["a", "c"])
    del after["tutorial"]["users"]
    rebuilt = copy.deepcopy(BEFORE)

    put_paths(rebuilt, payload_changes(BEFORE, after))

    assert rebuilt == after


# region paths overlap
@mark.parametrize(
    ("first", "second", "expected"),
    [
        (("core", "title"), ("core", "title"), True),
        (("core",), ("core", "title"), True),
        (("core", "tags", 1), ("core", "tags"), True),
        ((), ("core", "title"), True),
        (("core", "title"), ("core", "description"), False),
        (("core", "tags", 0), ("core", "tags", 1), False),
        (("tutorial", "users"), ("core", "users"), False),
    ],
    ids=["same", "holds", "held", "root-holds-all", "siblings", "sibling-items", "other-block"],
)
def test_paths_overlap_when_one_holds_the_other(first: FieldPath, second: FieldPath, expected: bool) -> None:
    """Two paths overlap when they name the same value or one holds the other -- in either order.

    **Test steps:**

    * verify the answer for the pair, and that it is the same with the pair swapped
    """
    assert paths_overlap(first, second) is expected
    assert paths_overlap(second, first) is expected
