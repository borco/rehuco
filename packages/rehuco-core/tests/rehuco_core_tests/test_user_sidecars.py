"""Tests for the per-user sidecar's names, reading, joining, splitting and writing (#513,
[[data-model#single-file]])."""

import json
import re
from pathlib import Path
from typing import Any, Final

from borco_core import atomic_write_text
from pytest import mark, raises
from pytest_mock import MockerFixture
from rehuco_core import CURRENT_REHUSER_VERSION, UserSidecarError, user_sidecar_path, user_sidecar_paths, user_slug
from rehuco_core.user_sidecars import (
    UnreadableSidecar,
    UserSidecar,
    join_user_sidecars,
    joined_text,
    read_user_sidecar,
    read_user_sidecars,
    sidecar_text,
    split_user_sidecars,
    user_sidecar_owner,
    write_user_sidecars,
)

MODULE: Final = "rehuco_core.user_sidecars"


def write_json(path: Path, payload: Any) -> None:
    """Write a JSON value to a file.

    :param path: the file.
    :param payload: the value.
    """
    path.write_text(json.dumps(payload), encoding="utf-8")


# region Names


@mark.parametrize(
    ("username", "slug"),
    [
        ("ioan", "ioan"),
        ("Ioan", "ioan"),
        ("Ioan Călin", "ioan_calin"),
        ("  a//b  ", "a_b"),
        ("first.last-2", "first.last-2"),
        ("public", "public"),
    ],
)
def test_a_username_folds_to_a_lower_case_ascii_slug(username: str, slug: str) -> None:
    """A sidecar's user name is lower-cased ASCII, safe in a file name: Windows and macOS compare names without case.

    **Test steps:**

    * fold ``username``
    * verify the slug
    """
    assert user_slug(username) == slug


@mark.parametrize("username", ["", "???", "日本"])
def test_a_username_with_nothing_left_after_the_fold_is_refused(username: str) -> None:
    """A name that folds to nothing names no file.

    **Test steps:**

    * fold ``username``
    * verify a ``ValueError``
    """
    with raises(ValueError, match="leaves nothing"):
        user_slug(username)


def test_a_sidecar_sits_beside_its_record_under_the_records_stem(tmp_path: Path) -> None:
    """``<stem>.user-<slug>.rehuser``, beside the record.

    **Test steps:**

    * ask for Ioan's sidecar of ``info.rehu`` and of ``lesson.rehu``
    * verify each is named after its record's stem and the slug
    """
    assert user_sidecar_path(tmp_path / "info.rehu", "Ioan") == tmp_path / "info.user-ioan.rehuser"
    assert user_sidecar_path(tmp_path / "lesson.rehu", "Ioan") == tmp_path / "lesson.user-ioan.rehuser"


@mark.parametrize(
    ("filename", "owner"),
    [
        ("info.user-ioan.rehuser", ("info", "ioan")),
        ("Lesson.One.User-Bob.REHUSER", ("Lesson.One", "Bob")),
        ("foo.rehuser", None),
        (".user-ioan.rehuser", None),
        ("foo.user-.rehuser", None),
        ("foo.user-ioan.rehuser.abcd1234.tmp", None),
        ("foo.user-ioan.json", None),
    ],
)
def test_a_sidecar_is_known_by_its_name_alone(filename: str, owner: tuple[str, str] | None) -> None:
    """A name with a stem, the ``.user-`` infix, a user and the suffix is a sidecar, whatever its case; an atomic
    write's temporary sibling is not.

    **Test steps:**

    * ask whose ``filename`` is
    * verify the record stem and user, or ``None``
    """
    assert user_sidecar_owner(filename) == owner


def test_a_records_sidecars_are_its_stems_only(tmp_path: Path) -> None:
    """Listing a record's sidecars takes its own stem's, whatever their case, and no other record's.

    **Test steps:**

    * put sidecars of ``lesson`` (one cased differently) and of ``lessons`` beside ``lesson.rehu``
    * verify only ``lesson``'s are listed, by lower-cased slug
    """
    for name in ("lesson.user-ioan.rehuser", "LESSON.user-Bob.rehuser", "lessons.user-ioan.rehuser"):
        (tmp_path / name).write_text("{}", encoding="utf-8")

    assert user_sidecar_paths(tmp_path / "lesson.rehu") == {
        "bob": tmp_path / "LESSON.user-Bob.rehuser",
        "ioan": tmp_path / "lesson.user-ioan.rehuser",
    }


def test_a_record_whose_folder_is_gone_has_no_sidecars(tmp_path: Path) -> None:
    """Nothing to list is no sidecar, not an error.

    **Test steps:**

    * list the sidecars of a record in a folder that does not exist
    * verify none
    """
    assert not user_sidecar_paths(tmp_path / "gone" / "info.rehu")


# endregion

# region Reading


def test_a_sidecar_reads_as_its_blocks_without_its_stamp(tmp_path: Path) -> None:
    """A sidecar's fields are its blocks; its version stamp is the file's, not a block.

    **Test steps:**

    * write a stamped sidecar and an unstamped one
    * read both
    * verify each holds its blocks only, with its name, slug and text
    """
    stamped = tmp_path / "info.user-ioan.rehuser"
    write_json(stamped, {"format_version": 1, "tutorial": {"rating": 4}})
    unstamped = tmp_path / "info.user-bob.rehuser"
    write_json(unstamped, {"tutorial": {"viewed": True}})

    assert read_user_sidecar(stamped, "ioan") == UserSidecar(
        stamped.name, "ioan", {"tutorial": {"rating": 4}}, stamped.read_text(encoding="utf-8")
    )
    assert read_user_sidecar(unstamped, "bob").fields == {"tutorial": {"viewed": True}}


def test_reading_a_records_sidecars_reads_every_users(tmp_path: Path) -> None:
    """Every user's sidecar beside the record is read.

    **Test steps:**

    * write two users' sidecars beside ``info.rehu``
    * read the record's sidecars
    * verify both, in slug order
    """
    write_json(tmp_path / "info.user-ioan.rehuser", {"tutorial": {"rating": 4}})
    write_json(tmp_path / "info.user-bob.rehuser", {"tutorial": {"rating": 2}})

    sidecars, unreadable = read_user_sidecars(tmp_path / "info.rehu")

    assert [(sidecar.slug, sidecar.fields) for sidecar in sidecars] == [
        ("bob", {"tutorial": {"rating": 2}}),
        ("ioan", {"tutorial": {"rating": 4}}),
    ]
    assert not unreadable


@mark.parametrize(
    ("text", "message"),
    [
        ("{not json", "invalid JSON"),
        ("[1, 2]", "expected a JSON object"),
        (json.dumps({"format_version": CURRENT_REHUSER_VERSION + 1}), "newer than this build"),
    ],
)
def test_reading_a_records_sidecars_sets_one_that_cannot_be_read_apart(tmp_path: Path, text: str, message: str) -> None:
    """One bad sidecar costs its own scope: it is named with its reason, and the others are still read.

    **Test steps:**

    * write Ioan's sidecar and a bad one for Bob beside ``info.rehu``
    * read the record's sidecars
    * verify Ioan's is read and Bob's is unreadable, naming its file, its slug and the cause
    """
    write_json(tmp_path / "info.user-ioan.rehuser", {"tutorial": {"rating": 4}})
    (tmp_path / "info.user-bob.rehuser").write_text(text, encoding="utf-8")

    sidecars, unreadable = read_user_sidecars(tmp_path / "info.rehu")

    assert [sidecar.slug for sidecar in sidecars] == ["ioan"]
    assert [(sidecar.name, sidecar.slug) for sidecar in unreadable] == [("info.user-bob.rehuser", "bob")]
    assert re.match(rf"info\.user-bob\.rehuser: .*{message}", unreadable[0].reason)


def test_reading_a_records_sidecars_sets_one_that_cannot_be_opened_apart(tmp_path: Path, mocker: MockerFixture) -> None:
    """A sidecar the OS refuses -- a share's permission error, say -- is unreadable like a malformed one, with the
    OS's own words as its reason.

    **Test steps:**

    * write a sidecar and make reading it raise ``PermissionError``
    * read the record's sidecars
    * verify it is unreadable, its reason naming the file and the error
    """
    write_json(tmp_path / "info.user-bob.rehuser", {"tutorial": {"rating": 2}})
    mocker.patch(f"{MODULE}.read_user_sidecar", side_effect=PermissionError("denied"))

    sidecars, unreadable = read_user_sidecars(tmp_path / "info.rehu")

    assert not sidecars
    assert [sidecar.reason for sidecar in unreadable] == ["info.user-bob.rehuser: could not be read — denied."]


def test_reading_a_records_sidecars_leaves_out_one_gone_between_the_listing_and_its_read(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """Another device deleting a sidecar after it was listed is no failure of that sidecar: it is in neither list.

    **Test steps:**

    * write a sidecar and make reading it raise ``FileNotFoundError``
    * read the record's sidecars
    * verify neither list holds it
    """
    write_json(tmp_path / "info.user-bob.rehuser", {"tutorial": {"rating": 2}})
    mocker.patch(f"{MODULE}.read_user_sidecar", side_effect=FileNotFoundError())

    assert read_user_sidecars(tmp_path / "info.rehu") == ([], [])


@mark.parametrize(
    ("text", "message"),
    [
        ("{not json", "invalid JSON"),
        ("[1, 2]", "expected a JSON object"),
        (json.dumps({"format_version": CURRENT_REHUSER_VERSION + 1}), "newer than this build"),
    ],
)
def test_a_sidecar_that_cannot_be_read_as_one_is_refused(tmp_path: Path, text: str, message: str) -> None:
    """Malformed JSON, a value that is no object, and a stamp from a newer build are refused, naming the file.

    **Test steps:**

    * write ``text`` as a sidecar
    * read it
    * verify a ``UserSidecarError`` naming the file and the cause
    """
    path = tmp_path / "info.user-ioan.rehuser"
    path.write_text(text, encoding="utf-8")

    with raises(UserSidecarError, match=rf"info\.user-ioan\.rehuser: .*{message}"):
        read_user_sidecar(path, "ioan")


@mark.parametrize("cap", ["oversized_file_reason", "excessive_nesting_reason", "excessive_entry_reason"])
def test_a_sidecar_is_held_to_a_records_sanity_caps(tmp_path: Path, mocker: MockerFixture, cap: str) -> None:
    """A sidecar is untrusted input as a record is: each of the record's caps refuses it too.

    **Test steps:**

    * make ``cap`` find a sidecar out of bounds
    * read it
    * verify a ``UserSidecarError`` carrying the cap's reason
    """
    path = tmp_path / "info.user-ioan.rehuser"
    write_json(path, {"tutorial": {}})
    mocker.patch(f"{MODULE}.{cap}", return_value="far too much")

    with raises(UserSidecarError, match="refusing to parse — far too much"):
        read_user_sidecar(path, "ioan")


# endregion

# region Joining and splitting


def test_joining_files_the_current_users_sidecar_under_their_username() -> None:
    """The current user's sidecar fills their own scope, however their name is spelled; another's fills the scope its
    slug spells.

    **Test steps:**

    * join Ioan's and the ``public`` sidecar into a record opened as ``Ioan``
    * verify Ioan's fields are under ``Ioan`` and the public ones under ``public``
    """
    data: dict[str, Any] = {"tutorial": {"format_version": 2}}
    sidecars = [
        UserSidecar("info.user-ioan.rehuser", "ioan", {"tutorial": {"rating": 4}}, ""),
        UserSidecar("info.user-public.rehuser", "public", {"tutorial": {"learning_paths": []}}, ""),
    ]

    join_user_sidecars(data, sidecars, "Ioan")

    assert data == {
        "tutorial": {"format_version": 2, "users": {"Ioan": {"rating": 4}, "public": {"learning_paths": []}}}
    }


def test_a_sidecar_replaces_the_scope_its_record_still_carries() -> None:
    """A record saved before the sidecars existed still carries its maps; a sidecar for the same scope is newer, and
    wins whole. Another scope the record carries stays.

    **Test steps:**

    * join Ioan's sidecar into a record carrying Ioan's and Bob's maps
    * verify Ioan's scope is the sidecar's alone and Bob's is the record's
    """
    data: dict[str, Any] = {"tutorial": {"users": {"ioan": {"rating": 1, "viewed": True}, "bob": {"rating": 2}}}}

    join_user_sidecars(data, [UserSidecar("info.user-ioan.rehuser", "ioan", {"tutorial": {"rating": 4}}, "")], "ioan")

    assert data == {"tutorial": {"users": {"ioan": {"rating": 4}, "bob": {"rating": 2}}}}


def test_joining_leaves_out_the_scope_of_a_sidecar_that_could_not_be_read() -> None:
    """The record's own copy of that scope goes too -- left in, the next save would split it back out over the file
    that could not be read. Other scopes, and slugs that only fold alike, are judged by slug.

    **Test steps:**

    * join into a record still carrying Bob's, ``BOB``'s and Ioan's maps, with Bob's sidecar unreadable
    * verify only Ioan's scope is left
    """
    data: dict[str, Any] = {"tutorial": {"users": {"bob": {"rating": 2}, "BOB": {"rating": 3}, "ioan": {"rating": 1}}}}

    join_user_sidecars(data, [], "ioan", [UnreadableSidecar("info.user-bob.rehuser", "bob", "bad")])

    assert data == {"tutorial": {"users": {"ioan": {"rating": 1}}}}


def test_joining_makes_the_block_a_sidecar_names_and_skips_a_malformed_one() -> None:
    """A block only a sidecar names is made to hold it; a block the record holds as no object is left alone.

    **Test steps:**

    * join a sidecar naming a missing block and a block that is a string
    * verify the missing block holds the user's fields and the string is untouched
    """
    data: dict[str, Any] = {"broken": "text"}
    sidecar = UserSidecar("info.user-ioan.rehuser", "ioan", {"tutorial": {"rating": 4}, "broken": {"x": 1}}, "")

    join_user_sidecars(data, [sidecar], "ioan")

    assert data == {"broken": "text", "tutorial": {"users": {"ioan": {"rating": 4}}}}


def test_joining_leaves_a_users_map_that_is_no_object_alone() -> None:
    """A record whose ``users`` map is malformed keeps it as it is: there is no scope to put a sidecar's fields in.

    **Test steps:**

    * join Ioan's sidecar into a block whose ``users`` is a list
    * verify the list unchanged
    """
    data: dict[str, Any] = {"tutorial": {"users": [1]}}

    join_user_sidecars(data, [UserSidecar("info.user-ioan.rehuser", "ioan", {"tutorial": {"rating": 4}}, "")], "ioan")

    assert data == {"tutorial": {"users": [1]}}


def test_splitting_moves_every_scope_to_its_sidecar_and_keeps_the_rest() -> None:
    """The record keeps everything but its ``users`` maps -- a block left with its stamp keeps the stamp -- and each
    scope goes to the sidecar its slug names, block by block.

    **Test steps:**

    * split a payload with two blocks' maps over two scopes
    * verify the record holds no map and each slug's sidecar its fields per block
    """
    payload = {
        "format_version": 2,
        "core": {"id": "1"},
        "tutorial": {"format_version": 2, "users": {"Ioan": {"rating": 4}, "public": {"learning_paths": []}}},
        "reference_images": {"format_version": 4, "keep": True, "users": {"Ioan": {"favorite": True}}},
    }

    record, sidecars = split_user_sidecars(payload)

    assert record == {
        "format_version": 2,
        "core": {"id": "1"},
        "tutorial": {"format_version": 2},
        "reference_images": {"format_version": 4, "keep": True},
    }
    assert sidecars == {
        "ioan": {"tutorial": {"rating": 4}, "reference_images": {"favorite": True}},
        "public": {"tutorial": {"learning_paths": []}},
    }


def test_what_has_no_sidecar_to_go_to_stays_in_the_record() -> None:
    """A scope with no slug and a ``users`` map that is no object have nowhere else to live: the record keeps them.

    **Test steps:**

    * split a payload whose maps hold an unsluggable scope beside a good one, and a block whose map is a list
    * verify the record keeps the unsluggable scope and the list, and the good scope moves
    """
    payload = {"tutorial": {"users": {"???": {"rating": 1}, "ioan": {"rating": 4}}}, "other": {"users": [1]}}

    record, sidecars = split_user_sidecars(payload)

    assert record == {"tutorial": {"users": {"???": {"rating": 1}}}, "other": {"users": [1]}}
    assert sidecars == {"ioan": {"tutorial": {"rating": 4}}}


def test_a_scope_holding_nothing_gets_no_sidecar() -> None:
    """A block migration files an empty map under the identity it ran as; a user with no state gets no file for it.

    **Test steps:**

    * split a payload whose map holds an empty scope beside a rated one
    * verify the empty scope is in neither the record nor any sidecar
    """
    payload = {"reference_images": {"users": {"admin": {}, "ioan": {"rating": 4}}}}

    record, sidecars = split_user_sidecars(payload)

    assert record == {"reference_images": {}}
    assert sidecars == {"ioan": {"reference_images": {"rating": 4}}}


def test_two_scopes_folding_to_one_slug_share_its_sidecar() -> None:
    """``Ioan`` and ``ioan`` are one user on a case-blind file system: their fields go to one sidecar, the later
    name's winning a field both hold.

    **Test steps:**

    * split a payload holding ``Ioan`` and ``ioan``, both rating it and one marking it viewed
    * verify one sidecar holding the viewed flag and ``ioan``'s rating
    """
    payload = {"tutorial": {"users": {"ioan": {"rating": 4}, "Ioan": {"rating": 1, "viewed": True}}}}

    assert split_user_sidecars(payload)[1] == {"ioan": {"tutorial": {"rating": 4, "viewed": True}}}


def test_a_sidecars_text_is_stamped_and_ordered() -> None:
    """A sidecar's text leads with its stamp, then its blocks and each block's fields in key order.

    **Test steps:**

    * render fields given out of order
    * verify the stamp first and the keys sorted, pretty-printed with a trailing newline
    """
    text = sidecar_text({"tutorial": {"viewed": True, "rating": 4}, "core_extra": {"b": 1, "a": 2}})

    assert text == (
        json.dumps(
            {
                "format_version": CURRENT_REHUSER_VERSION,
                "core_extra": {"a": 2, "b": 1},
                "tutorial": {"rating": 4, "viewed": True},
            },
            indent=2,
        )
        + "\n"
    )
    assert list(json.loads(text)) == ["format_version", "core_extra", "tutorial"]


def test_a_version_hashes_every_sidecars_name_and_text() -> None:
    """The text a version hashes changes with a sidecar's content and with which sidecar it is.

    **Test steps:**

    * join a record's text with one sidecar, the same sidecar changed, and the same text under another name
    * verify the three differ and each starts with the record's text
    """
    one = joined_text("record", [UserSidecar("a.user-x.rehuser", "x", {}, "1")])
    changed = joined_text("record", [UserSidecar("a.user-x.rehuser", "x", {}, "2")])
    renamed = joined_text("record", [UserSidecar("a.user-y.rehuser", "y", {}, "1")])

    assert len({one, changed, renamed}) == 3
    assert all(text.startswith("record") for text in (one, changed, renamed))


# endregion

# region Writing


def test_writing_writes_only_the_sidecars_that_change(tmp_path: Path, mocker: MockerFixture) -> None:
    """A sidecar whose text is already the one to write is left alone; a changed one and a new one are written.

    **Test steps:**

    * put Bob's and Ioan's sidecars beside a record, Bob's already as it will be written
    * write Bob's unchanged, Ioan's changed and a new public one, spying on the atomic write
    * verify only Ioan's and the public one were written, and every file holds its fields
    """
    record = tmp_path / "info.rehu"
    (tmp_path / "info.user-bob.rehuser").write_text(sidecar_text({"tutorial": {"rating": 2}}), encoding="utf-8")
    write_json(tmp_path / "info.user-ioan.rehuser", {"tutorial": {"rating": 1}})
    written = mocker.patch(f"{MODULE}.atomic_write_text", wraps=atomic_write_text)

    write_user_sidecars(
        record,
        {"bob": {"tutorial": {"rating": 2}}, "ioan": {"tutorial": {"rating": 4}}, "public": {"tutorial": {"x": 1}}},
    )

    assert sorted(Path(call.args[0]).name for call in written.call_args_list) == [
        "info.user-ioan.rehuser",
        "info.user-public.rehuser",
    ]
    assert json.loads((tmp_path / "info.user-ioan.rehuser").read_text(encoding="utf-8")) == {
        "format_version": CURRENT_REHUSER_VERSION,
        "tutorial": {"rating": 4},
    }


def test_a_sidecar_whose_user_has_nothing_left_keeps_only_its_stamp(tmp_path: Path) -> None:
    """Everything of a user's removed: the sidecar still on disk would read it back, so it is emptied to its stamp --
    under the name it already has.

    **Test steps:**

    * put Ioan's sidecar, spelled in capitals, beside a record
    * write the record's sidecars with Ioan's gone
    * verify the file under its own name holds the stamp alone
    """
    path = tmp_path / "info.user-IOAN.rehuser"
    write_json(path, {"tutorial": {"rating": 4}})

    write_user_sidecars(tmp_path / "info.rehu", {})

    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["info.user-IOAN.rehuser"]
    assert json.loads(path.read_text(encoding="utf-8")) == {"format_version": CURRENT_REHUSER_VERSION}


def test_a_sidecar_a_newer_build_wrote_is_never_written_over(tmp_path: Path) -> None:
    """Its fields are ones this build has never seen: writing is refused, and the file keeps them.

    **Test steps:**

    * put a sidecar stamped one version ahead beside a record
    * write that user's sidecar
    * verify a ``UserSidecarError``, and the file unchanged
    """
    path = tmp_path / "info.user-ioan.rehuser"
    newer = json.dumps({"format_version": CURRENT_REHUSER_VERSION + 1, "tutorial": {"future": 1}})
    path.write_text(newer, encoding="utf-8")

    with raises(UserSidecarError, match="newer than this build"):
        write_user_sidecars(tmp_path / "info.rehu", {"ioan": {"tutorial": {"rating": 4}}})

    assert path.read_text(encoding="utf-8") == newer


@mark.parametrize(
    "text",
    ["{broken", "[1, 2]", json.dumps({"format_version": CURRENT_REHUSER_VERSION + 1, "tutorial": {"future": 1}})],
)
def test_a_sidecar_that_cannot_be_read_is_left_alone_when_nothing_is_written_for_it(tmp_path: Path, text: str) -> None:
    """Its scope was left out of the record when it was read, so the save holds nothing for it -- and an emptied stamp
    written over it would destroy what a hand-fix or a newer build can still read.

    **Test steps:**

    * put a sidecar that is not JSON, no object, or from a newer build beside a record
    * write another user's sidecar, holding nothing for it
    * verify the unreadable file is byte-identical and the other user's was written
    """
    path = tmp_path / "info.user-bob.rehuser"
    path.write_text(text, encoding="utf-8")

    write_user_sidecars(tmp_path / "info.rehu", {"ioan": {"tutorial": {"rating": 4}}})

    assert path.read_text(encoding="utf-8") == text
    assert (tmp_path / "info.user-ioan.rehuser").read_text(encoding="utf-8") == sidecar_text(
        {"tutorial": {"rating": 4}}
    )


def test_a_sidecar_that_is_no_longer_json_is_never_written_over(tmp_path: Path) -> None:
    """Fields for a scope that was never read -- a write that reached it past the load -- are refused, not written over
    the file.

    **Test steps:**

    * put a sidecar that is not JSON beside a record
    * write that user's sidecar
    * verify a ``UserSidecarError`` naming the file, and the file unchanged
    """
    path = tmp_path / "info.user-ioan.rehuser"
    path.write_text("{broken", encoding="utf-8")

    with raises(UserSidecarError, match=r"info\.user-ioan\.rehuser: invalid JSON"):
        write_user_sidecars(tmp_path / "info.rehu", {"ioan": {"tutorial": {"rating": 4}}})

    assert path.read_text(encoding="utf-8") == "{broken"


# endregion
