"""Tests for LearningPathsTableModel: ownership across scopes, subscribing, and delete-or-reparent."""

from typing import Any

from PySide6.QtCore import QModelIndex, Qt
from pytest import fixture, mark, param
from rehuco_agent.fields.widgets.learning_paths_table_model import (
    FOREIGN_SCOPE_TOOLTIP,
    OWN_SCOPE_TOOLTIP,
    OWNER_COLUMN,
    PUBLIC_SCOPE_TOOLTIP,
    SUBSCRIBED_COLUMN,
    LearningPathScopeFilterProxyModel,
    LearningPathsTableModel,
)
from rehuco_agent.fields.widgets.membership_table_model import INDEX_COLUMN, TITLE_COLUMN

USERNAME = "admin"
UNKNOWN = "unknown"

# Every ownership shape at once ([[field-schema#learning-path-ownership]]): ``public`` holds a published
# copy, ``admin`` owns one path and subscribes to the published one, and ``foo`` owns a private path.
RECORDS: dict[str, list[dict[str, Any]]] = {
    "public": [{"title": "Shared Order", "index": 3, "ref": 1}],
    "admin": [{"ref": 1}, {"title": "My Order", "index": 7, "ref": 2}],
    "foo": [{"title": "Private Study", "index": 1, "ref": 3}],
}

PUBLIC_ROW = 0
OWN_ROW = 1
FOREIGN_ROW = 2
"""The three rows :data:`RECORDS` makes, in scope-then-stored order -- the bare ``{ref}`` is not one."""


@fixture
def model() -> LearningPathsTableModel:
    """A model over :data:`RECORDS`, minting from slot ``4``.

    :returns: the seeded model.
    """
    model = LearningPathsTableModel(USERNAME, lambda: 4, UNKNOWN)
    model.set_entries(RECORDS)
    return model


def cell(model: LearningPathsTableModel, row: int, column: int, role: Qt.ItemDataRole) -> Any:
    """Read one cell.

    :param model: the model to read.
    :param row: the row to read.
    :param column: the column to read.
    :param role: the role to read it under.
    :returns: whatever the model answers.
    """
    return model.data(model.index(row, column), role)


# region what a row is


def test_a_row_is_an_owned_record_never_a_subscription(model: LearningPathsTableModel) -> None:
    """A bare ``{ref}`` has no title and no index of its own, so a row of it would be a blank line where
    the path it points at already has one -- following is a checkbox on *that* row instead.

    **Test steps:**

    * verify the three owned records are rows and the subscription is not
    * verify each row names its scope
    """
    assert model.rowCount() == 3
    assert [model.scope(row) for row in range(3)] == ["public", "admin", "foo"]
    assert [cell(model, row, TITLE_COLUMN, Qt.ItemDataRole.DisplayRole) for row in range(3)] == [
        "Shared Order",
        "My Order",
        "Private Study",
    ]


def test_the_table_carries_an_owner_and_a_subscribed_column(model: LearningPathsTableModel) -> None:
    """Four columns: the two shared ones, plus whose path it is and whether this identity follows it.

    **Test steps:**

    * verify the column count and the two extra headers
    * verify the owner cell shows the scope
    """
    assert model.columnCount() == 4
    assert model.headerData(OWNER_COLUMN, Qt.Orientation.Horizontal) == "Owner"
    assert model.headerData(SUBSCRIBED_COLUMN, Qt.Orientation.Horizontal) == "Subscribed"
    assert cell(model, FOREIGN_ROW, OWNER_COLUMN, Qt.ItemDataRole.DisplayRole) == "foo"


def test_a_record_that_is_neither_a_path_nor_a_subscription_is_carried_with_no_row() -> None:
    """Unshowable is not the same as unwanted: a record nobody can edit still round-trips, which is the
    whole point of the merge contract ([[data-model#write-integrity]]).

    **Test steps:**

    * seed a record carrying neither a title nor a slot
    * verify it makes no row and is still in the value
    """
    model = LearningPathsTableModel(USERNAME, lambda: 1, UNKNOWN)
    model.set_entries({USERNAME: [{"index": 2}]})

    assert model.rowCount() == 0
    assert model.entries == {USERNAME: [{"index": 2}]}


def test_a_published_copy_and_a_private_one_are_two_rows() -> None:
    """The editor acts on *records*, so a path published and also kept privately is two rows -- deleting
    the public copy while keeping the private one is a thing the spec asks for
    ([[field-schema#learning-path-ownership]]), where the viewer renders the pair as one path.

    **Test steps:**

    * seed the same slot owned in both scopes
    * verify there are two rows
    """
    model = LearningPathsTableModel(USERNAME, lambda: 2, UNKNOWN)
    model.set_entries(
        {
            USERNAME: [{"title": "Mine", "index": 1, "ref": 1}],
            "public": [{"title": "Mine", "index": 1, "ref": 1}],
        }
    )

    assert model.rowCount() == 2


def test_reseeding_the_same_records_is_not_a_change(model: LearningPathsTableModel) -> None:
    """The echo guard, exactly as the collections rows keep it.

    **Test steps:**

    * hand the model its own entries back
    * verify no model reset was reported
    """
    resets: list[None] = []
    model.modelReset.connect(lambda: resets.append(None))

    model.set_entries(model.entries)

    assert not resets


# endregion

# region who may edit what


@mark.parametrize(
    ("row", "editable"),
    [
        param(OWN_ROW, True, id="my-own-path"),
        param(PUBLIC_ROW, True, id="the-public-scope-belongs-to-nobody"),
        param(FOREIGN_ROW, False, id="another-identity-s-path"),
    ],
)
def test_only_the_rows_with_somebody_to_permit_them_are_editable(
    model: LearningPathsTableModel, row: int, editable: bool
) -> None:
    """A row is editable exactly where there is somebody to permit it: this identity's own, and the
    reserved ``public`` scope, which is not a person and so belongs to no one to refuse.

    **Test steps:**

    * read each row's title-cell flags
    * verify editability follows the scope
    """
    assert bool(model.flags(model.index(row, TITLE_COLUMN)) & Qt.ItemFlag.ItemIsEditable) is editable


def test_another_identitys_cells_refuse_a_write(model: LearningPathsTableModel) -> None:
    """Their titles are theirs -- following one is the checkbox rather than a copy of it.

    **Test steps:**

    * write a title and a position onto another identity's row
    * verify both are refused and the record is untouched
    """
    assert model.setData(model.index(FOREIGN_ROW, TITLE_COLUMN), "Stolen") is False
    assert model.setData(model.index(FOREIGN_ROW, INDEX_COLUMN), 9) is False
    assert model.entries["foo"] == [{"title": "Private Study", "index": 1, "ref": 3}]


@mark.parametrize(
    ("row", "expected"),
    [
        param(OWN_ROW, OWN_SCOPE_TOOLTIP, id="my-own-path"),
        param(PUBLIC_ROW, PUBLIC_SCOPE_TOOLTIP, id="the-public-scope"),
        param(FOREIGN_ROW, FOREIGN_SCOPE_TOOLTIP.format(owner="foo"), id="another-identity-s-path"),
    ],
)
def test_each_row_says_what_owning_it_means(model: LearningPathsTableModel, row: int, expected: str) -> None:
    """Ownership is structural and so invisible; the row says what it implies, where it applies.

    **Test steps:**

    * read the owner cell's tooltip on each row
    * verify each explains its own scope
    """
    assert cell(model, row, OWNER_COLUMN, Qt.ItemDataRole.ToolTipRole) == expected


def test_a_flagged_cell_keeps_its_own_reason_over_the_scope_note(model: LearningPathsTableModel) -> None:
    """A cell with something wrong with it says *that*: the scope note is the fallback, not a replacement.

    **Test steps:**

    * empty an owned row's title
    * verify the title cell explains the emptiness rather than the ownership
    """
    model.setData(model.index(OWN_ROW, TITLE_COLUMN), "")

    assert cell(model, OWN_ROW, TITLE_COLUMN, Qt.ItemDataRole.ToolTipRole) != OWN_SCOPE_TOOLTIP


def test_an_editable_cell_falls_back_to_the_scope_note(model: LearningPathsTableModel) -> None:
    """With nothing wrong with it, the title cell explains whose path it is.

    **Test steps:**

    * read a well-formed owned title's tooltip
    * verify it is the ownership note
    """
    assert cell(model, OWN_ROW, TITLE_COLUMN, Qt.ItemDataRole.ToolTipRole) == OWN_SCOPE_TOOLTIP


def test_retyping_an_owned_title_keeps_its_slot(model: LearningPathsTableModel) -> None:
    """The merge contract matters most here: the ``ref`` is what every subscription resolves through, so
    a title cell that rebuilt its record would break every follower (#235).

    **Test steps:**

    * retype this identity's own path
    * verify the slot survived
    """
    model.setData(model.index(OWN_ROW, TITLE_COLUMN), "Renamed")

    assert model.entries["admin"][1] == {"title": "Renamed", "index": 7, "ref": 2}


# endregion

# region subscribing


@mark.parametrize(
    ("row", "subscribable"),
    [
        param(FOREIGN_ROW, True, id="another-identity-s-path"),
        param(OWN_ROW, False, id="owning-is-not-following"),
        param(PUBLIC_ROW, False, id="published-paths-need-no-subscription"),
    ],
)
def test_only_another_identitys_path_offers_the_checkbox(
    model: LearningPathsTableModel, row: int, subscribable: bool
) -> None:
    """Not one's own rows, and not ``public`` -- a published path is visible to everyone without
    subscribing ([[field-schema#learning-path-ownership]]).

    **Test steps:**

    * read each row's checkbox flag and state
    * verify only another identity's path is checkable
    """
    checkable = bool(model.flags(model.index(row, SUBSCRIBED_COLUMN)) & Qt.ItemFlag.ItemIsUserCheckable)

    assert checkable is subscribable
    assert (cell(model, row, SUBSCRIBED_COLUMN, Qt.ItemDataRole.CheckStateRole) is not None) is subscribable


def test_a_path_nothing_can_point_at_is_not_subscribable() -> None:
    """A record carrying no slot is a path nothing can point at, so following it is not a thing that can
    be done at all.

    **Test steps:**

    * seed another identity's refless path
    * verify it offers no checkbox
    """
    model = LearningPathsTableModel(USERNAME, lambda: 1, UNKNOWN)
    model.set_entries({"foo": [{"title": "Refless", "index": 1}]})

    assert model.row_is_subscribable(0) is False


def test_subscribing_adds_a_bare_ref_to_this_identitys_own_scope(model: LearningPathsTableModel) -> None:
    """Subscribing is adding a ``{ref}``, never copying the row: a subscriber has no title and no index of
    their own, so an owner's later fix reaches them with no work.

    **Test steps:**

    * check the box on another identity's path
    * verify a bare ``{ref}`` landed in this identity's scope and nothing else did
    """
    assert (
        model.setData(
            model.index(FOREIGN_ROW, SUBSCRIBED_COLUMN), Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole
        )
        is True
    )

    assert model.entries["admin"] == [{"ref": 1}, {"title": "My Order", "index": 7, "ref": 2}, {"ref": 3}]
    assert model.is_subscribed(FOREIGN_ROW) is True


def test_unsubscribing_drops_the_ref_and_nothing_else(model: LearningPathsTableModel) -> None:
    """Only the pointer goes; the path it pointed at is its owner's.

    **Test steps:**

    * subscribe then unsubscribe
    * verify this identity's records are back where they started and ``foo``'s path is untouched
    """
    model.set_subscribed(FOREIGN_ROW, True)

    model.set_subscribed(FOREIGN_ROW, False)

    assert model.entries["admin"] == [{"ref": 1}, {"title": "My Order", "index": 7, "ref": 2}]
    assert model.entries["foo"] == [{"title": "Private Study", "index": 1, "ref": 3}]


def test_unsubscribing_drops_every_copy_of_a_duplicated_ref() -> None:
    """A file carrying the same bare ``{ref}`` twice is unfollowed in one press, not one press per copy.

    Nothing this app writes makes a duplicate -- ``set_subscribed`` refuses to add a second -- but a
    ``.rehu`` is plain JSON anyone can edit by hand ([[data-model#rehu-format]]), and a leftover copy
    would read back as still followed: the checkbox would refuse to turn off, with no way to see why.

    **Test steps:**

    * seed an identity whose own scope holds one path and the same subscription ref twice
    * unsubscribe
    * verify both copies are gone and the identity's own path stayed
    """
    model = LearningPathsTableModel(USERNAME, lambda: 3, UNKNOWN)
    model.set_entries(
        {
            USERNAME: [{"ref": 1}, {"title": "Mine", "index": 2, "ref": 2}, {"ref": 1}],
            "foo": [{"title": "Theirs", "index": 1, "ref": 1}],
        }
    )
    foreign_row = next(row for row in range(model.rowCount()) if model.row_is_subscribable(row))
    assert model.is_subscribed(foreign_row) is True

    model.set_subscribed(foreign_row, False)

    assert model.entries[USERNAME] == [{"title": "Mine", "index": 2, "ref": 2}]
    assert model.is_subscribed(foreign_row) is False


def test_unsubscribing_the_last_record_drops_the_scope() -> None:
    """A scope that only ever existed to hold a subscription goes with it, rather than leaving an identity
    in the file that was never really there.

    **Test steps:**

    * seed an identity holding nothing but a subscription
    * unsubscribe
    * verify the identity is gone
    """
    model = LearningPathsTableModel(USERNAME, lambda: 2, UNKNOWN)
    model.set_entries({USERNAME: [{"ref": 1}], "foo": [{"title": "Theirs", "index": 1, "ref": 1}]})

    model.set_subscribed(0, False)

    assert USERNAME not in model.entries


def test_subscribing_to_what_is_already_followed_changes_nothing(model: LearningPathsTableModel) -> None:
    """An edit that changes nothing is not an edit.

    **Test steps:**

    * ask for the state each row is already in
    * verify both are refused
    """
    assert model.set_subscribed(FOREIGN_ROW, False) is False
    model.set_subscribed(FOREIGN_ROW, True)
    assert model.set_subscribed(FOREIGN_ROW, True) is False


def test_a_row_that_cannot_be_followed_refuses_the_write(model: LearningPathsTableModel) -> None:
    """Owning is not following, so the checkbox that is not there cannot be set either.

    **Test steps:**

    * try to subscribe to this identity's own path
    * verify it is refused
    """
    assert model.set_subscribed(OWN_ROW, True) is False


# endregion

# region delete, or reparent


def test_deleting_an_unfollowed_path_removes_it() -> None:
    """With no subscribers a deleted path simply goes.

    **Test steps:**

    * delete this identity's only, unfollowed, path
    * verify the row and the scope are gone
    """
    model = LearningPathsTableModel(USERNAME, lambda: 2, UNKNOWN)
    model.set_entries({USERNAME: [{"title": "Mine", "index": 1, "ref": 1}]})

    model.delete(0)

    assert model.rowCount() == 0
    assert model.entries == {}


def test_deleting_a_followed_path_reparents_it_to_the_unknown_identity() -> None:
    """An owned path that others follow moves to the ``unknown`` identity rather than stranding them:
    their subscriptions still resolve, and what is lost is the ownership, not the path
    ([[field-schema#learning-path-ownership]]).

    **Test steps:**

    * delete a path another identity subscribes to
    * verify it moved scope, kept its slot, and left this identity's own view
    """
    model = LearningPathsTableModel(USERNAME, lambda: 2, UNKNOWN)
    model.set_entries({USERNAME: [{"title": "Mine", "index": 1, "ref": 1}], "foo": [{"ref": 1}]})

    model.delete(0)

    assert model.scope(0) == UNKNOWN
    assert model.entries[UNKNOWN] == [{"title": "Mine", "index": 1, "ref": 1}]
    assert USERNAME not in model.entries
    assert model.row_is_visible(0) is False


def test_another_identity_owning_the_slot_is_not_a_subscriber() -> None:
    """A *full* record carrying the same slot is another owner, not a follower -- only a bare ``{ref}``
    is a subscription, which is what makes ownership structural.

    **Test steps:**

    * delete a path a second identity separately owns at the same slot
    * verify it was removed rather than reparented
    """
    model = LearningPathsTableModel(USERNAME, lambda: 2, UNKNOWN)
    model.set_entries(
        {
            USERNAME: [{"title": "Mine", "index": 1, "ref": 1}],
            "foo": [{"title": "Also Mine", "index": 2, "ref": 1}],
        }
    )

    model.delete(0)

    assert UNKNOWN not in model.entries
    assert list(model.entries) == ["foo"]


def test_deleting_a_refless_path_removes_it() -> None:
    """Nothing can point at a path with no slot, so nothing can be stranded by its going.

    **Test steps:**

    * delete an owned path carrying no slot
    * verify it is gone
    """
    model = LearningPathsTableModel(USERNAME, lambda: 1, UNKNOWN)
    model.set_entries({USERNAME: [{"title": "Refless", "index": 1}]})

    model.delete(0)

    assert model.entries == {}


def test_deleting_a_row_this_identity_may_not_edit_is_a_no_op(model: LearningPathsTableModel) -> None:
    """A row this identity may not edit is not one it may delete.

    **Test steps:**

    * delete another identity's row, and a negative row
    * verify nothing moved
    """
    model.delete(FOREIGN_ROW)
    model.delete(-1)

    assert model.rowCount() == 3


# endregion

# region minting


def test_an_insert_mints_a_path_of_this_identitys_own(model: LearningPathsTableModel) -> None:
    """A new path is this identity's whoever's row was current, and its slot comes from outside -- file
    -wide uniqueness is more than this model can see.

    **Test steps:**

    * insert while another identity's row is current
    * verify a blank owned path landed in this identity's scope, carrying the minted slot
    """
    row = model.insert(FOREIGN_ROW)

    assert row == 3
    assert model.scope(row) == USERNAME
    assert model.entries["admin"][-1] == {"title": "", "index": 0, "ref": 4}


def test_an_insert_into_an_identity_with_no_scope_yet_creates_one() -> None:
    """The first path an identity mints is also the first record it has.

    **Test steps:**

    * insert into a model holding nothing
    * verify the scope was created around it
    """
    model = LearningPathsTableModel(USERNAME, lambda: 7, UNKNOWN)

    model.insert(-1)

    assert model.entries == {USERNAME: [{"title": "", "index": 0, "ref": 7}]}


def test_only_an_append_of_one_is_accepted(model: LearningPathsTableModel) -> None:
    """A path is minted into this identity's own scope, so there is no other position in the rows for it
    to land at.

    **Test steps:**

    * call ``insertRows`` at a row that is not the end, with a count that is not one, and under a parent
    * verify each is refused
    """
    assert model.insertRows(0, 1) is False
    assert model.insertRows(3, 2) is False
    assert model.insertRows(3, 1, model.index(0, TITLE_COLUMN)) is False


@mark.parametrize(
    ("row", "count"),
    [param(3, 1, id="past-the-end"), param(-1, 1, id="before-the-start"), param(0, 2, id="more-than-one")],
)
def test_an_out_of_range_removal_is_refused(model: LearningPathsTableModel, row: int, count: int) -> None:
    """Qt's own primitive answers honestly rather than corrupting the rows.

    **Test steps:**

    * call ``removeRows`` with each refused shape
    * verify it is refused and the rows are untouched
    """
    assert model.removeRows(row, count) is False
    assert model.rowCount() == 3


def test_a_child_parent_is_refused_by_removal(model: LearningPathsTableModel) -> None:
    """The model is flat, so nothing can be removed *under* a row.

    **Test steps:**

    * call ``removeRows`` with a valid parent
    * verify it is refused
    """
    assert model.removeRows(0, 1, model.index(0, TITLE_COLUMN)) is False


def test_an_invalid_index_carries_no_data(model: LearningPathsTableModel) -> None:
    """Qt asks about invalid indexes; the answer is nothing, never a crash.

    **Test steps:**

    * read and write an invalid index
    * verify both answer emptily
    """
    assert model.data(QModelIndex()) is None
    assert model.setData(QModelIndex(), Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole) is False


def test_the_owner_cell_answers_no_other_role(model: LearningPathsTableModel) -> None:
    """The owner column is a name and an explanation, nothing else.

    **Test steps:**

    * read the owner cell under a role it has no answer for
    * verify it is empty
    """
    assert cell(model, OWN_ROW, OWNER_COLUMN, Qt.ItemDataRole.EditRole) is None


# endregion

# region the scope filter


def test_the_filter_shows_what_this_identity_is_in(model: LearningPathsTableModel) -> None:
    """The identity's own view: its paths, the ones it follows, and the reserved ``public`` scope -- the
    same three sources the viewer resolves ([[field-schema#learning-path-ownership]]).

    **Test steps:**

    * put the filter over the model
    * verify another identity's unfollowed path is hidden
    """
    proxy = LearningPathScopeFilterProxyModel()
    proxy.setSourceModel(model)

    assert proxy.rowCount() == 2
    assert model.row_is_visible(FOREIGN_ROW) is False


def test_the_all_scopes_view_shows_every_path(model: LearningPathsTableModel) -> None:
    """Another identity's private paths are exactly what the editor exists to be able to act on, so the
    other view hides nothing.

    **Test steps:**

    * switch the filter to every scope
    * verify all three rows are shown
    """
    proxy = LearningPathScopeFilterProxyModel()
    proxy.setSourceModel(model)

    proxy.set_all_scopes(True)

    assert proxy.all_scopes is True
    assert proxy.rowCount() == 3


def test_a_followed_path_joins_the_identitys_own_view(model: LearningPathsTableModel) -> None:
    """Following a path is what puts it in the identity's view, and the filter re-evaluates on the edit
    rather than needing to be told.

    **Test steps:**

    * subscribe to another identity's path
    * verify it appears in the filtered view
    """
    proxy = LearningPathScopeFilterProxyModel()
    proxy.setSourceModel(model)

    model.set_subscribed(FOREIGN_ROW, True)

    assert proxy.rowCount() == 3


def test_switching_to_the_same_view_changes_nothing(model: LearningPathsTableModel) -> None:
    """A switch that switches nothing is not one.

    **Test steps:**

    * ask for the view already in force
    * verify it stayed
    """
    proxy = LearningPathScopeFilterProxyModel()
    proxy.setSourceModel(model)

    proxy.set_all_scopes(False)

    assert proxy.all_scopes is False


def test_the_filter_hides_nothing_under_a_row(model: LearningPathsTableModel) -> None:
    """The model is flat, so a child row is nothing to accept.

    **Test steps:**

    * ask the filter about a row under a valid parent
    * verify it is refused
    """
    proxy = LearningPathScopeFilterProxyModel()
    proxy.setSourceModel(model)

    assert proxy.filterAcceptsRow(0, model.index(0, TITLE_COLUMN)) is False


def test_the_filter_accepts_everything_over_a_model_it_does_not_know() -> None:
    """A proxy is not the place to refuse a source it was not built for; a filter it cannot evaluate is
    no filter at all rather than an empty view.

    **Test steps:**

    * ask the filter about a row with no source model set
    * verify it accepts
    """
    assert LearningPathScopeFilterProxyModel().filterAcceptsRow(0, QModelIndex()) is True


# endregion
