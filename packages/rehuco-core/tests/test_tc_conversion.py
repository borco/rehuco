"""Tests for the `.tc` -> `.rehu` conversion sequence (safe replace, [[acquisition-tooling#tc-to-rehu]])."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

import pytest
from pytest_mock import MockerFixture
from rehuco_core import RehuDocument, ScreenshotRename, convert_tc

DIRECTORY: Final = Path("/fake/tutorial")
TC_PATH: Final = DIRECTORY / "info.tc"
TARGET_PATH: Final = DIRECTORY / "info.rehu"

TC_YAML: Final = "type: Tutorial\ntitle: Some Title\ndescription: '![](cover)'\n"

MTIME: Final = 1700000000.0
SEEDED_TIMESTAMP: Final = "2023-11-14T22:13:20Z"

RENAMES: Final = (
    ScreenshotRename("info00.jpg", "cover.jpg", ("cover.jpg", "sample-00.png")),
    ScreenshotRename("info01.jpg", "sample-01.jpg", ("sample-01.jpg",)),
)


def backup_path(original: Path) -> Path:
    """The ``.orig`` sibling :class:`~rehuco_core.tc_conversion.TcConverter` would use for ``original``."""
    return original.with_name(original.name + ".orig")


def mock_environment(
    mocker: MockerFixture,
    *,
    existing: frozenset[Path] = frozenset(),
    renames: Sequence[ScreenshotRename] = RENAMES,
    copy_side_effect: Any = None,
) -> dict[str, Any]:
    """Mock every filesystem touchpoint :class:`~rehuco_core.tc_conversion.TcConverter` uses.

    :param mocker: pytest-mock fixture.
    :param existing: paths that should report as already existing on disk.
    :param renames: the screenshot scan result to hand back.
    :param copy_side_effect: optional ``side_effect`` for the image-copy mock (e.g. to fail partway).
    :returns: the created mocks, keyed by what they stand in for.
    """
    mocker.patch.object(Path, "read_text", return_value=TC_YAML)
    mocker.patch.object(Path, "exists", autospec=True, side_effect=lambda self: self in existing)
    mocker.patch.object(Path, "stat", return_value=mocker.MagicMock(st_mtime=MTIME))
    mock_write = mocker.patch("rehuco_core.rehu_document.atomic_write_text")
    mocker.patch("rehuco_core.tc_conversion.scan_tc_screenshots", return_value=renames)
    mock_rename = mocker.patch.object(Path, "rename", autospec=True)
    mock_unlink = mocker.patch.object(Path, "unlink", autospec=True)
    mock_copy = mocker.patch("rehuco_core.tc_conversion.shutil.copy2", side_effect=copy_side_effect)
    return {"write": mock_write, "rename": mock_rename, "unlink": mock_unlink, "copy": mock_copy}


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
    assert saved["core"]["id"]
    assert saved["core"]["created"] == SEEDED_TIMESTAMP
    assert saved["core"]["updated"] == SEEDED_TIMESTAMP

    originals = [TC_PATH, DIRECTORY / "cover.jpg", DIRECTORY / "sample-00.png", DIRECTORY / "sample-01.jpg"]
    assert mocks["rename"].call_args_list == [mocker.call(o, backup_path(o)) for o in originals]
    assert mocks["copy"].call_args_list == [
        mocker.call(backup_path(DIRECTORY / "cover.jpg"), DIRECTORY / "info00.jpg"),
        mocker.call(backup_path(DIRECTORY / "sample-01.jpg"), DIRECTORY / "info01.jpg"),
    ]
    assert {call.args[0] for call in mocks["unlink"].call_args_list} == {backup_path(o) for o in originals}


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
