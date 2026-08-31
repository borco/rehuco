"""Tests for the `.tc` -> `.rehu` conversion sequence (safe replace, [[acquisition-tooling#tc-to-rehu]])."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import pytest
from pytest_mock import MockerFixture
from rehuco_core import (
    EXCLUDED_FILE_PATTERNS,
    ContentUnreachableError,
    RehuDocument,
    ScreenshotRename,
    convert_tc,
    current_block_version,
)

DIRECTORY: Final = Path("/fake/tutorial")
TC_PATH: Final = DIRECTORY / "info.tc"
TARGET_PATH: Final = DIRECTORY / "info.rehu"

TC_YAML: Final = "type: Tutorial\ntitle: Some Title\ndescription: '![](cover)'\n"

# The membership fields together: one scalar collection and several flat learning-path names, listed
# deliberately out of alphabetical order so the round-trip test can tell list order from a sort.
TC_YAML_WITH_MEMBERSHIPS: Final = (
    "type: Tutorial\n"
    "title: Some Title\n"
    "collection: Some Collection\n"
    "collection_index: 2\n"
    "learning_paths:\n"
    "  - Path B\n"
    "  - Path A\n"
)

TC_YAML_WITH_SIZE: Final = "type: Tutorial\ntitle: Some Title\ncurrent_size: 500 MB\n"

MTIME: Final = 1700000000.0
SEEDED_TIMESTAMP: Final = "2023-11-14T22:13:20Z"

RENAMES: Final = (
    ScreenshotRename("info00.jpg", "cover.jpg", ("cover.jpg", "sample-00.png")),
    ScreenshotRename("info01.jpg", "sample-01.jpg", ("sample-01.jpg",)),
)


def backup_path(original: Path) -> Path:
    """The ``.orig`` sibling :class:`~rehuco_core.tc_conversion.TcConverter` would use for ``original``."""
    return original.with_name(original.name + ".orig")


def mock_environment(  # pylint: disable=too-many-arguments
    mocker: MockerFixture,
    *,
    existing: frozenset[Path] = frozenset(),
    renames: Sequence[ScreenshotRename] = RENAMES,
    copy_side_effect: Any = None,
    tc_yaml: str = TC_YAML,
    measured_size: int | Exception = 0,
) -> dict[str, Any]:
    """Mock every filesystem touchpoint :class:`~rehuco_core.tc_conversion.TcConverter` uses.

    :param mocker: pytest-mock fixture.
    :param existing: paths that should report as already existing on disk.
    :param renames: the screenshot scan result to hand back.
    :param copy_side_effect: optional ``side_effect`` for the image-copy mock (e.g. to fail partway).
    :param tc_yaml: the ``.tc`` file's raw YAML text; defaults to :data:`TC_YAML`.
    :param measured_size: what :func:`~rehuco_core.content_size_on_disk` answers, or an exception
        instance (e.g. :class:`~rehuco_core.ContentUnreachableError`) for it to raise instead.
    :returns: the created mocks, keyed by what they stand in for.
    """
    mocker.patch.object(Path, "read_text", return_value=tc_yaml)
    mocker.patch.object(Path, "exists", autospec=True, side_effect=lambda self: self in existing)
    mocker.patch.object(
        Path, "stat", return_value=mocker.MagicMock(st_mtime=MTIME, st_size=len(tc_yaml.encode("utf-8")))
    )
    mock_write = mocker.patch("rehuco_core.rehu_document.atomic_write_text")
    mocker.patch("rehuco_core.tc_conversion.scan_tc_screenshots", return_value=renames)
    mock_rename = mocker.patch.object(Path, "rename", autospec=True)
    mock_unlink = mocker.patch.object(Path, "unlink", autospec=True)
    mock_copy = mocker.patch("rehuco_core.tc_conversion.shutil.copy2", side_effect=copy_side_effect)
    if isinstance(measured_size, Exception):
        mock_size = mocker.patch("rehuco_core.tc_conversion.content_size_on_disk", side_effect=measured_size)
    else:
        mock_size = mocker.patch("rehuco_core.tc_conversion.content_size_on_disk", return_value=measured_size)
    return {
        "write": mock_write,
        "rename": mock_rename,
        "unlink": mock_unlink,
        "copy": mock_copy,
        "content_size_on_disk": mock_size,
    }


def test_happy_path_discards_originals_by_default(mocker: MockerFixture) -> None:
    """A full conversion writes the new `.rehu`, installs both winning screenshots, and deletes every
    backup once everything new is confirmed written.

    **Test steps:**

    * mock a `.tc` with two recognized screenshot slots
    * convert with ``keep_backups=False``
    * verify the saved JSON's minted/rewritten fields, every original was backed up then unlinked, and
      each winner was copied from its backup to its final name
    """
    mocks = mock_environment(mocker)

    document = convert_tc(TC_PATH, keep_backups=False)

    assert isinstance(document, RehuDocument)
    assert document.legacy_tc is False
    saved = json.loads(mocks["write"].call_args[0][1])
    assert saved["core"]["sources"][0]["title"] == "Some Title"
    assert saved["core"]["description"] == "![](info00.jpg)"
    # two checks in one: ``UUID()`` raises on a string that is no UUID at all, and -- since it also
    # *accepts* non-canonical spellings (uppercase, braces, hyphenless) while ``str()`` always emits
    # the canonical lowercase-hyphenated form -- the equality only holds when the minted string was
    # already spelled canonically, i.e. exactly what ``str(uuid4())`` produces.
    assert saved["core"]["id"] == str(UUID(saved["core"]["id"]))
    assert saved["core"]["created"] == SEEDED_TIMESTAMP
    assert saved["core"]["updated"] == SEEDED_TIMESTAMP

    originals = [TC_PATH, DIRECTORY / "cover.jpg", DIRECTORY / "sample-00.png", DIRECTORY / "sample-01.jpg"]
    assert mocks["rename"].call_args_list == [mocker.call(o, backup_path(o)) for o in originals]
    assert mocks["copy"].call_args_list == [
        mocker.call(backup_path(DIRECTORY / "cover.jpg"), DIRECTORY / "info00.jpg"),
        mocker.call(backup_path(DIRECTORY / "sample-01.jpg"), DIRECTORY / "info01.jpg"),
    ]
    assert {call.args[0] for call in mocks["unlink"].call_args_list} == {backup_path(o) for o in originals}


def test_convert_files_per_user_flags_under_the_given_username(mocker: MockerFixture) -> None:
    """The identity given to :func:`convert_tc` reaches the saved block's ``users`` key, and the fresh
    document adopts it -- so an imported resource's per-user state has a known owner from the first write
    ([[field-schema#per-user-shared]]).

    **Test steps:**

    * convert a `.tc` under an explicit username
    * verify the saved current-stamped block nests the per-user flags under that username, and the
      returned document reads them back as that identity
    """
    mocks = mock_environment(mocker)

    document = convert_tc(TC_PATH, keep_backups=True, username="alice")

    saved = json.loads(mocks["write"].call_args[0][1])
    assert saved["tutorial"]["format_version"] == current_block_version("tutorial")
    assert set(saved["tutorial"]["users"]) == {"alice"}
    assert saved["tutorial"]["users"]["alice"]["favorite"] is False
    assert document.username == "alice"
    # the source `.tc` carried no rating, so none is fabricated: it is omitted, and reads back unrated
    # ([[field-schema#deferred-items]]) -- 0 is a genuine rating, so absent must not coerce to it
    assert "rating" not in saved["tutorial"]["users"]["alice"]
    assert document.rating is None


def test_convert_files_per_user_flags_under_the_unknown_user_by_default(mocker: MockerFixture) -> None:
    """Converting without an explicit username files the imported per-user flags under the *unknown* user
    (``unknown``) -- the flags were not set by this install's identity (#109).

    See [[field-schema#per-user-shared]].

    **Test steps:**

    * convert a `.tc` with no username
    * verify the saved block nests the per-user flags under ``unknown``, and the document adopts it
    """
    mocks = mock_environment(mocker)

    document = convert_tc(TC_PATH, keep_backups=True)

    saved = json.loads(mocks["write"].call_args[0][1])
    assert set(saved["tutorial"]["users"]) == {"unknown"}
    assert document.username == "unknown"


def test_convert_round_trips_collection_and_owned_learning_paths(mocker: MockerFixture) -> None:
    """A ``.tc`` carrying a collection and several learning paths converts into the settled membership
    shapes and round-trips through the written payload unchanged (#188,
    [[field-schema#learning-path-ownership]]).

    The paths come back **owned** by the importing identity: full ``{title, index, ref}`` entries with
    ``index: 0`` on every one (tc4's list order was never a curated position), refs minted in list
    order, and no retired ``visibility`` flag anywhere in the file. The written block is stamped at the
    plugin's current version, so loading the payload back runs no migration over it -- the shape on
    disk *is* the shape in memory.

    **Test steps:**

    * convert a ``.tc`` with one collection and two learning paths (listed out of alphabetical order)
    * verify the saved ``collections`` entry, and the owned learning-path entries in list order
    * verify no ``visibility`` key survives anywhere in the saved payload
    * construct a document from the saved payload and verify the block is not reshaped on load
    """
    mocks = mock_environment(mocker, tc_yaml=TC_YAML_WITH_MEMBERSHIPS)

    convert_tc(TC_PATH, keep_backups=True)

    saved = json.loads(mocks["write"].call_args[0][1])
    block = saved["tutorial"]
    assert block["format_version"] == current_block_version("tutorial")
    assert block["collections"] == [{"title": "Some Collection", "index": 2}]
    assert block["users"]["unknown"]["learning_paths"] == [
        {"title": "Path B", "index": 0, "ref": 1},
        {"title": "Path A", "index": 0, "ref": 2},
    ]
    assert "visibility" not in json.dumps(saved)

    reloaded = RehuDocument(json.loads(mocks["write"].call_args[0][1]))
    assert reloaded.data["tutorial"] == block


def test_keep_backups_leaves_the_orig_siblings(mocker: MockerFixture) -> None:
    """``keep_backups=True`` performs the same conversion but never deletes the backups.

    **Test steps:**

    * convert with ``keep_backups=True``
    * verify nothing was unlinked
    """
    mocks = mock_environment(mocker)

    convert_tc(TC_PATH, keep_backups=True)

    mocks["unlink"].assert_not_called()


def test_existing_target_without_overwrite_raises_and_touches_nothing(mocker: MockerFixture) -> None:
    """Converting onto an existing `.rehu` without ``overwrite=True`` raises before anything is renamed.

    **Test steps:**

    * mock the target `.rehu` as already existing
    * convert without ``overwrite``
    * verify ``FileExistsError`` and that no rename/copy/unlink calls happened
    """
    mocks = mock_environment(mocker, existing=frozenset({TARGET_PATH}))

    with pytest.raises(FileExistsError):
        convert_tc(TC_PATH, keep_backups=True)

    mocks["rename"].assert_not_called()
    mocks["copy"].assert_not_called()


def test_overwrite_backs_up_the_existing_target(mocker: MockerFixture) -> None:
    """``overwrite=True`` backs up the existing `.rehu` like every other original.

    **Test steps:**

    * mock the target `.rehu` as already existing
    * convert with ``overwrite=True``
    * verify the existing target was renamed to its own ``.orig`` sibling
    """
    mocks = mock_environment(mocker, existing=frozenset({TARGET_PATH}))

    convert_tc(TC_PATH, keep_backups=True, overwrite=True)

    assert mocker.call(TARGET_PATH, backup_path(TARGET_PATH)) in mocks["rename"].call_args_list


def test_stale_backup_raises_and_touches_nothing(mocker: MockerFixture) -> None:
    """A leftover `.orig` from a previous interrupted attempt aborts the conversion instead of being
    silently clobbered.

    **Test steps:**

    * mock a stale ``info.tc.orig`` as already existing
    * convert
    * verify ``FileExistsError`` and that no rename calls happened
    """
    mocks = mock_environment(mocker, existing=frozenset({backup_path(TC_PATH)}))

    with pytest.raises(FileExistsError):
        convert_tc(TC_PATH, keep_backups=True)

    mocks["rename"].assert_not_called()


def test_failure_mid_sequence_restores_every_backup_and_removes_new_files(mocker: MockerFixture) -> None:
    """A failure partway through installing images undoes everything: the already-written `.rehu` and
    the one already-copied image are removed, and every backup is restored to its original name.

    **Test steps:**

    * mock the second image copy to raise
    * convert
    * verify the exception propagates, the new `.rehu` and the one installed image were unlinked, and
      every original was restored via a reverse rename
    """
    mocks = mock_environment(mocker, copy_side_effect=[None, OSError("disk full")])

    with pytest.raises(OSError, match="disk full"):
        convert_tc(TC_PATH, keep_backups=False)

    unlinked = {call.args[0] for call in mocks["unlink"].call_args_list}
    assert unlinked == {TARGET_PATH, DIRECTORY / "info00.jpg"}

    originals = [TC_PATH, DIRECTORY / "cover.jpg", DIRECTORY / "sample-00.png", DIRECTORY / "sample-01.jpg"]
    forward = [mocker.call(o, backup_path(o)) for o in originals]
    backward = [mocker.call(backup_path(o), o) for o in originals]
    assert mocks["rename"].call_args_list == forward + backward


def test_failure_during_backup_restores_what_already_moved(mocker: MockerFixture) -> None:
    """A failure partway through the backup-renaming loop itself -- before any new file is written --
    restores whatever already moved back to its original name.

    **Test steps:**

    * mock the rename call to fail on its third invocation (after two originals already moved)
    * convert
    * verify the exception propagates, only the two already-moved originals were restored, and
      nothing was ever written or copied
    """
    mocks = mock_environment(mocker)
    calls: list[object] = []

    def rename_side_effect(_self: Path, _target: Path) -> None:
        calls.append(None)
        if len(calls) == 3:
            raise OSError("permission denied")

    mocks["rename"].side_effect = rename_side_effect

    with pytest.raises(OSError, match="permission denied"):
        convert_tc(TC_PATH, keep_backups=False)

    attempted = [TC_PATH, DIRECTORY / "cover.jpg", DIRECTORY / "sample-00.png"]
    restored = [TC_PATH, DIRECTORY / "cover.jpg"]
    forward = [mocker.call(o, backup_path(o)) for o in attempted]
    backward = [mocker.call(backup_path(o), o) for o in restored]
    assert mocks["rename"].call_args_list == forward + backward
    mocks["copy"].assert_not_called()
    mocks["write"].assert_not_called()


def test_preexisting_install_destination_is_backed_up_before_it_is_overwritten(mocker: MockerFixture) -> None:
    """A file already sitting at a ``<stem>NN`` install destination -- invisible to the legacy scan, so
    absent from the recognized set -- is backed up to its own ``.orig`` sibling before the winning
    screenshot's bytes overwrite it, honouring the module's never-overwrite contract.

    **Test steps:**

    * mock a pre-existing ``info00.jpg`` sitting exactly where slot 0's winner installs
    * convert
    * verify that file was renamed to its ``.orig`` sibling, yet the winners are still copied forward
    """
    mocks = mock_environment(mocker, existing=frozenset({DIRECTORY / "info00.jpg"}))

    convert_tc(TC_PATH, keep_backups=True)

    renamed = {call.args[0] for call in mocks["rename"].call_args_list}
    assert DIRECTORY / "info00.jpg" in renamed
    assert mocks["copy"].call_args_list == [
        mocker.call(backup_path(DIRECTORY / "cover.jpg"), DIRECTORY / "info00.jpg"),
        mocker.call(backup_path(DIRECTORY / "sample-01.jpg"), DIRECTORY / "info01.jpg"),
    ]


def test_failure_after_overwriting_a_preexisting_destination_restores_it(mocker: MockerFixture) -> None:
    """When installing fails after a pre-existing destination has already been overwritten, rollback
    removes the freshly written file *and* renames that file's ``.orig`` backup back -- so the user's
    original bytes survive rather than being unlinked outright (the data-loss finding, #173).

    **Test steps:**

    * mock a pre-existing ``info00.jpg`` at slot 0's destination, and fail the second image copy
    * convert
    * verify the exception propagates, the freshly written ``info00.jpg`` was unlinked, and the
      pre-existing file was restored via a reverse rename of its backup
    """
    mocks = mock_environment(
        mocker, existing=frozenset({DIRECTORY / "info00.jpg"}), copy_side_effect=[None, OSError("disk full")]
    )

    with pytest.raises(OSError, match="disk full"):
        convert_tc(TC_PATH, keep_backups=False)

    unlinked = {call.args[0] for call in mocks["unlink"].call_args_list}
    assert unlinked == {TARGET_PATH, DIRECTORY / "info00.jpg"}
    assert (
        mocker.call(backup_path(DIRECTORY / "info00.jpg"), DIRECTORY / "info00.jpg") in mocks["rename"].call_args_list
    )


def test_losing_variants_are_backed_up_but_never_copied_forward(mocker: MockerFixture) -> None:
    """A slot's losing filename (a smaller/duplicate variant of the winner) is backed up like the
    winner, but never appears as a copy source or destination -- only the winner's bytes survive.

    **Test steps:**

    * convert a `.tc` whose only slot has a winner and a loser
    * verify both were renamed to backups, but only the winner was copied forward
    """
    mocks = mock_environment(
        mocker, renames=[ScreenshotRename("info00.jpg", "sample-00.png", ("cover.jpg", "sample-00.png"))]
    )

    convert_tc(TC_PATH, keep_backups=True)

    renamed = {call.args[0] for call in mocks["rename"].call_args_list}
    assert DIRECTORY / "cover.jpg" in renamed
    assert mocks["copy"].call_args_list == [
        mocker.call(backup_path(DIRECTORY / "sample-00.png"), DIRECTORY / "info00.jpg")
    ]


def test_current_size_is_measured_rather_than_trusted(mocker: MockerFixture) -> None:
    """The saved ``current_size`` is a fresh disk measurement, not the (possibly years-stale) legacy
    string the ``.tc`` carried (#255).

    **Test steps:**

    * mock a `.tc` carrying a legacy ``current_size`` and the measurement answering a different number
    * convert
    * verify the saved ``current_size`` is the measured number, and the measurement ran over the `.tc`
      path with the default exclusion patterns
    """
    mocks = mock_environment(mocker, tc_yaml=TC_YAML_WITH_SIZE, measured_size=123)

    document = convert_tc(TC_PATH, keep_backups=True)

    saved = json.loads(mocks["write"].call_args[0][1])
    assert saved["core"]["current_size"] == 123
    assert document.current_size == 123
    mocks["content_size_on_disk"].assert_called_once_with(TC_PATH, EXCLUDED_FILE_PATTERNS)


def test_an_unreachable_resource_stores_no_current_size(mocker: MockerFixture) -> None:
    """A resource whose directory will not list is left without a stored ``current_size`` rather than
    given a wrong one -- neither the failed measurement nor the untrusted legacy value is written
    ([[mounts-and-storage#offline-mounts]], #255).

    **Test steps:**

    * mock a `.tc` carrying a legacy ``current_size`` and the measurement raising
      ``ContentUnreachableError``
    * convert
    * verify the saved payload carries no ``current_size`` at all
    """
    mocks = mock_environment(
        mocker, tc_yaml=TC_YAML_WITH_SIZE, measured_size=ContentUnreachableError("mount is offline")
    )

    convert_tc(TC_PATH, keep_backups=True)

    saved = json.loads(mocks["write"].call_args[0][1])
    assert "current_size" not in saved["core"]


def test_current_size_measurement_uses_the_given_excluded_patterns(mocker: MockerFixture) -> None:
    """A caller's exclusion patterns reach the measurement, the same discipline every other content
    walk in this codebase is handed them under (#226).

    **Test steps:**

    * convert with an explicit ``excluded_patterns``
    * verify the measurement was called with it, not the default
    """
    mocks = mock_environment(mocker)

    convert_tc(TC_PATH, keep_backups=True, excluded_patterns=("*.tmp",))

    mocks["content_size_on_disk"].assert_called_once_with(TC_PATH, ("*.tmp",))
