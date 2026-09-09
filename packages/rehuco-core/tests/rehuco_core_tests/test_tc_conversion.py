"""Tests for the `.tc` -> `.rehu` conversion sequence (safe replace, [[acquisition-tooling#tc-to-rehu]])."""

import json
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import pytest
from pytest_mock import MockerFixture
from rehuco_core import (
    EXCLUDED_FILE_PATTERNS,
    SCREENSHOT_NAME_PATTERNS,
    ContentUnreachableError,
    RehuDocument,
    ScreenshotRename,
    ScreenshotSkipReason,
    TcScreenshotPlan,
    UnconvertedScreenshot,
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

PLAN: Final = TcScreenshotPlan(
    (
        ScreenshotRename("info00.jpg", "cover.jpg"),
        ScreenshotRename("info01.jpg", "sample-01.jpg"),
    )
)

RENUMBERINGS: Final = [
    (DIRECTORY / "cover.jpg", DIRECTORY / "info00.jpg"),
    (DIRECTORY / "sample-01.jpg", DIRECTORY / "info01.jpg"),
]
"""What :data:`PLAN` renames, as ``(source, destination)`` pairs."""


def backup_path(original: Path) -> Path:
    """The ``.orig`` sibling :class:`~rehuco_core.tc_conversion.TcConverter` would use for ``original``."""
    return original.with_name(original.name + ".orig")


def mock_environment(
    mocker: MockerFixture,
    *,
    existing: frozenset[Path] = frozenset(),
    plan: TcScreenshotPlan = PLAN,
    tc_yaml: str = TC_YAML,
    measured_size: int | Exception = 0,
) -> dict[str, Any]:
    """Mock every filesystem touchpoint :class:`~rehuco_core.tc_conversion.TcConverter` uses.

    :param mocker: pytest-mock fixture.
    :param existing: paths that should report as already existing on disk.
    :param plan: the screenshot scan result to hand back.
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
    mocker.patch("rehuco_core.tc_conversion.scan_tc_screenshots", return_value=plan)
    mock_rename = mocker.patch.object(Path, "rename", autospec=True)
    mock_unlink = mocker.patch.object(Path, "unlink", autospec=True)
    if isinstance(measured_size, Exception):
        mock_size = mocker.patch("rehuco_core.tc_conversion.content_size_on_disk", side_effect=measured_size)
    else:
        mock_size = mocker.patch("rehuco_core.tc_conversion.content_size_on_disk", return_value=measured_size)
    return {
        "write": mock_write,
        "rename": mock_rename,
        "unlink": mock_unlink,
        "content_size_on_disk": mock_size,
    }


def test_happy_path_discards_originals_by_default(mocker: MockerFixture) -> None:
    """A full conversion writes the new `.rehu`, renames both screenshots to the numbers they carry,
    and deletes the one backup once everything new is confirmed written.

    **Test steps:**

    * mock a `.tc` with two numbered screenshots
    * convert with ``keep_backups=False``
    * verify the saved JSON's minted/rewritten fields, that the `.tc` was the only file backed up, and
      that each screenshot moved to its own slot
    """
    mocks = mock_environment(mocker)

    document = convert_tc(TC_PATH, keep_backups=False)

    assert isinstance(document, RehuDocument)
    assert document.legacy_tc is False
    saved = json.loads(mocks["write"].call_args[0][1])
    assert saved["core"]["sources"][0]["title"] == "Some Title"
    assert saved["core"]["description"] == "![](info00)"
    # two checks in one: ``UUID()`` raises on a string that is no UUID at all, and -- since it also
    # *accepts* non-canonical spellings (uppercase, braces, hyphenless) while ``str()`` always emits
    # the canonical lowercase-hyphenated form -- the equality only holds when the minted string was
    # already spelled canonically, i.e. exactly what ``str(uuid4())`` produces.
    assert saved["core"]["id"] == str(UUID(saved["core"]["id"]))
    assert saved["core"]["created"] == SEEDED_TIMESTAMP
    assert saved["core"]["updated"] == SEEDED_TIMESTAMP

    assert mocks["rename"].call_args_list == [
        mocker.call(TC_PATH, backup_path(TC_PATH)),
        *[mocker.call(source, destination) for source, destination in RENUMBERINGS],
    ]
    assert {call.args[0] for call in mocks["unlink"].call_args_list} == {backup_path(TC_PATH)}


def test_no_screenshot_is_ever_backed_up(mocker: MockerFixture) -> None:
    """The `.tc` is the only file a conversion backs up (#288): a screenshot is renamed, and an image
    the scan left alone is not touched at all.

    **Test steps:**

    * convert a `.tc` whose scan renames one image and leaves another under its own name
    * verify no ``.orig`` sibling was made for either image, and the untouched one never moved
    """
    plan = TcScreenshotPlan(
        (ScreenshotRename("info00.jpg", "cover.jpg"),),
        (UnconvertedScreenshot("sample-00.png", ScreenshotSkipReason.COLLISION),),
    )
    mocks = mock_environment(mocker, plan=plan)

    convert_tc(TC_PATH, keep_backups=True)

    assert mocks["rename"].call_args_list == [
        mocker.call(TC_PATH, backup_path(TC_PATH)),
        mocker.call(DIRECTORY / "cover.jpg", DIRECTORY / "info00.jpg"),
    ]


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


def test_keep_backups_leaves_the_orig_sibling(mocker: MockerFixture) -> None:
    """``keep_backups=True`` performs the same conversion but never deletes the backup.

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
    * verify ``FileExistsError`` and that no rename/unlink calls happened
    """
    mocks = mock_environment(mocker, existing=frozenset({TARGET_PATH}))

    with pytest.raises(FileExistsError):
        convert_tc(TC_PATH, keep_backups=True)

    mocks["rename"].assert_not_called()
    mocks["unlink"].assert_not_called()


def test_overwrite_backs_up_the_existing_target(mocker: MockerFixture) -> None:
    """``overwrite=True`` backs up the existing `.rehu` before writing the new one.

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


def test_failure_mid_sequence_undoes_every_rename_and_removes_new_files(mocker: MockerFixture) -> None:
    """A failure partway through renumbering undoes everything: the image already moved goes back to
    its own name, the already-written `.rehu` is removed, and the `.tc` is restored.

    **Test steps:**

    * mock the second image rename to raise
    * convert
    * verify the exception propagates, the new `.rehu` was unlinked, and both the moved image and the
      `.tc` were renamed back
    """
    mocks = mock_environment(mocker)
    attempts: list[object] = []

    def rename_side_effect(_self: Path, _target: Path) -> None:
        attempts.append(None)
        if len(attempts) == 3:
            raise OSError("disk full")

    mocks["rename"].side_effect = rename_side_effect

    with pytest.raises(OSError, match="disk full"):
        convert_tc(TC_PATH, keep_backups=False)

    assert {call.args[0] for call in mocks["unlink"].call_args_list} == {TARGET_PATH}
    assert mocks["rename"].call_args_list == [
        mocker.call(TC_PATH, backup_path(TC_PATH)),
        *[mocker.call(source, destination) for source, destination in RENUMBERINGS],
        mocker.call(DIRECTORY / "info00.jpg", DIRECTORY / "cover.jpg"),
        mocker.call(backup_path(TC_PATH), TC_PATH),
    ]


def test_a_rename_back_that_fails_does_not_stop_the_rest_of_the_rollback(mocker: MockerFixture) -> None:
    """Undoing runs on a disk that has already failed once, so a rename back that fails itself is
    skipped: restoring what can be restored beats abandoning the rest, and the error the caller sees
    stays the one that explains what happened.

    **Test steps:**

    * fail the second image rename, and then fail undoing the first one too
    * convert
    * verify the original failure is what propagates, and the `.tc` was still restored
    """
    mocks = mock_environment(mocker)
    attempts: list[object] = []

    def rename_side_effect(_self: Path, _target: Path) -> None:
        attempts.append(None)
        if len(attempts) == 3:
            raise OSError("disk full")
        if len(attempts) == 4:
            raise OSError("still full")

    mocks["rename"].side_effect = rename_side_effect

    with pytest.raises(OSError, match="disk full"):
        convert_tc(TC_PATH, keep_backups=False)

    assert mocks["rename"].call_args_list[-2:] == [
        mocker.call(DIRECTORY / "info00.jpg", DIRECTORY / "cover.jpg"),
        mocker.call(backup_path(TC_PATH), TC_PATH),
    ]


def test_failure_during_backup_restores_what_already_moved(mocker: MockerFixture) -> None:
    """A failure partway through the backup-renaming loop itself -- before any new file is written --
    restores whatever already moved back to its original name.

    **Test steps:**

    * overwrite an existing `.rehu` (so two files are backed up) and fail the second rename
    * convert
    * verify the exception propagates, the one already-moved original was restored, and nothing was
      ever written
    """
    mocks = mock_environment(mocker, existing=frozenset({TARGET_PATH}))
    attempts: list[object] = []

    def rename_side_effect(_self: Path, _target: Path) -> None:
        attempts.append(None)
        if len(attempts) == 2:
            raise OSError("permission denied")

    mocks["rename"].side_effect = rename_side_effect

    with pytest.raises(OSError, match="permission denied"):
        convert_tc(TC_PATH, keep_backups=False, overwrite=True)

    assert mocks["rename"].call_args_list == [
        mocker.call(TC_PATH, backup_path(TC_PATH)),
        mocker.call(TARGET_PATH, backup_path(TARGET_PATH)),
        mocker.call(backup_path(TC_PATH), TC_PATH),
    ]
    mocks["write"].assert_not_called()


def test_an_occupied_destination_refuses_rather_than_overwriting(mocker: MockerFixture) -> None:
    """A destination that exists when the rename is about to run aborts the conversion: the scan hands
    out no taken slot, so this can only be a race -- and *never overwrite* is the contract, which
    ``Path.rename`` does not honour on its own outside Windows.

    **Test steps:**

    * mock slot 0's destination as already existing
    * convert
    * verify ``FileExistsError``, that nothing was renamed onto it, and that the `.tc` came back
    """
    mocks = mock_environment(mocker, existing=frozenset({DIRECTORY / "info00.jpg"}))

    with pytest.raises(FileExistsError):
        convert_tc(TC_PATH, keep_backups=True)

    assert mocks["rename"].call_args_list == [
        mocker.call(TC_PATH, backup_path(TC_PATH)),
        mocker.call(backup_path(TC_PATH), TC_PATH),
    ]
    assert {call.args[0] for call in mocks["unlink"].call_args_list} == {TARGET_PATH}


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
    mocks["content_size_on_disk"].assert_called_once_with(TC_PATH, EXCLUDED_FILE_PATTERNS, SCREENSHOT_NAME_PATTERNS)


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

    mocks["content_size_on_disk"].assert_called_once_with(TC_PATH, ("*.tmp",), SCREENSHOT_NAME_PATTERNS)
