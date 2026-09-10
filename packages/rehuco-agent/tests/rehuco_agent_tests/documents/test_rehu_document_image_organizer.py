"""Tests for RehuDocumentImageOrganizer: where a resource's screenshot renames are aimed (#72, #291)."""

from pathlib import Path
from typing import Final

import pytest
from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.documents.rehu_document_image_organizer import RehuDocumentImageOrganizer
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.settings.screenshot_deletion_settings import shared_screenshot_deletion_settings
from rehuco_core import DEFAULT_DELETER, RehuDocument

DIRECTORY: Final = Path("/fake/tutorial")
PATHS: Final = [DIRECTORY / "info00.jpg", DIRECTORY / "info01.png"]


@fixture
def renumber(mocker: MockerFixture) -> MockerFixture:
    """Patch the core renumbering so no directory is touched and the call can be read back.

    :param mocker: pytest-mock fixture.
    :returns: the patched ``renumber_screenshots``.
    """
    return mocker.patch(
        "rehuco_agent.documents.rehu_document_image_organizer.renumber_screenshots",
        return_value={"info01.png": "info00.png"},
    )


def model_at(path: Path | None, *, legacy_tc: bool = False) -> RehuDocumentModel:
    """A document model bound to ``path``.

    :param path: the ``.rehu`` path the resource lives at, or ``None`` for one not saved yet.
    :param legacy_tc: whether the document is a pre-conversion ``.tc`` mapping.
    :returns: the model.
    """
    document = RehuDocument({"type": "Tutorial", "sources": [{"title": "Foo", "primary": True}]}, legacy_tc=legacy_tc)
    model = RehuDocumentModel(document)
    model.path = path
    return model


def test_reorder_renumbers_against_the_resources_own_directory_and_stem(renumber: MockerFixture) -> None:
    """The renames are aimed at exactly what the scanner lists from, so the two cannot disagree.

    **Test steps:**

    * reorder a document bound to ``/fake/tutorial/info.rehu``
    * verify the core was asked to renumber that directory's ``info`` set, and its report came back
    """
    organizer = RehuDocumentImageOrganizer(model_at(DIRECTORY / "info.rehu"))

    assert organizer.reorder(PATHS) == {"info01.png": "info00.png"}

    renumber.assert_called_once_with(DIRECTORY, "info", PATHS)  # type: ignore[attr-defined]


def test_remove_deletes_first_and_closes_the_gap_after(mocker: MockerFixture, renumber: MockerFixture) -> None:
    """The file goes, then the survivors renumber -- so a failed delete never closes a gap that is
    still occupied (#72).

    **Test steps:**

    * remove the first of two screenshots through an explicit deleter
    * verify that deleter was asked to delete it and the survivor renumbered
    """
    deleter = mocker.Mock()
    organizer = RehuDocumentImageOrganizer(model_at(DIRECTORY / "info.rehu"))

    organizer.remove(PATHS[0], PATHS[1:], deleter=deleter)

    deleter.delete.assert_called_once_with(PATHS[0])
    renumber.assert_called_once_with(DIRECTORY, "info", PATHS[1:])  # type: ignore[attr-defined]


def test_remove_defaults_to_the_recycle_bin_when_the_setting_is_on(
    mocker: MockerFixture, renumber: MockerFixture
) -> None:
    """Absent an explicit deleter, **Move deleted images to the Recycle Bin** (on by default, #291)
    is what chooses one.

    **Test steps:**

    * remove a screenshot with no deleter passed, the setting left at its default
    * verify ``send2trash`` -- not a plain unlink -- was asked to move it
    """
    del renumber
    send2trash = mocker.patch("rehuco_agent.documents.recycle_bin_deleter.send2trash")
    unlink = mocker.patch.object(Path, "unlink")
    organizer = RehuDocumentImageOrganizer(model_at(DIRECTORY / "info.rehu"))

    organizer.remove(PATHS[0], PATHS[1:])

    send2trash.assert_called_once_with(str(PATHS[0]))
    unlink.assert_not_called()


def test_remove_unlinks_when_the_recycle_bin_setting_is_off(mocker: MockerFixture, renumber: MockerFixture) -> None:
    """Turning the setting off is what makes an un-deleter'd remove permanent again (#291).

    **Test steps:**

    * turn **Move deleted images to the Recycle Bin** off
    * remove a screenshot with no deleter passed
    * verify it was unlinked and ``send2trash`` was never reached
    """
    del renumber
    shared_screenshot_deletion_settings().use_recycle_bin = False
    send2trash = mocker.patch("rehuco_agent.documents.recycle_bin_deleter.send2trash")
    unlink = mocker.patch.object(Path, "unlink")
    organizer = RehuDocumentImageOrganizer(model_at(DIRECTORY / "info.rehu"))

    organizer.remove(PATHS[0], PATHS[1:])

    unlink.assert_called_once()
    send2trash.assert_not_called()


def test_deletes_to_trash_reflects_the_live_setting(renumber: MockerFixture) -> None:
    """Read live rather than cached, so a page Saved after this organizer was built is still honoured.

    **Test steps:**

    * read ``deletes_to_trash`` before and after flipping the setting on an existing organizer
    * verify each read reflects what the setting held at that moment
    """
    del renumber
    organizer = RehuDocumentImageOrganizer(model_at(DIRECTORY / "info.rehu"))

    assert organizer.deletes_to_trash is True

    shared_screenshot_deletion_settings().use_recycle_bin = False

    assert organizer.deletes_to_trash is False


def test_an_explicit_deleter_overrides_the_setting(mocker: MockerFixture, renumber: MockerFixture) -> None:
    """A caller passing its own deleter (the permanent-delete fallback, #291) is never second-guessed
    by the setting.

    **Test steps:**

    * remove a screenshot with the Recycle Bin setting on, but an explicit permanent deleter passed
    * verify the explicit deleter ran and neither ``send2trash`` nor the setting's own choice did
    """
    del renumber
    send2trash = mocker.patch("rehuco_agent.documents.recycle_bin_deleter.send2trash")
    unlink = mocker.patch.object(Path, "unlink")
    organizer = RehuDocumentImageOrganizer(model_at(DIRECTORY / "info.rehu"))

    organizer.remove(PATHS[0], PATHS[1:], deleter=DEFAULT_DELETER)

    unlink.assert_called_once()
    send2trash.assert_not_called()


def test_a_document_with_no_path_yet_refuses_to_rearrange(renumber: MockerFixture) -> None:
    """There is no directory to rename in until the document has been saved somewhere.

    The refusal raises rather than answering with an empty map: an empty map already means "nothing
    needed renaming", and a caller reading a refusal as that would move its rows while the directory
    stayed put.

    **Test steps:**

    * reorder a document with no path
    * verify the refusal raised and nothing was renamed
    """
    organizer = RehuDocumentImageOrganizer(model_at(None))

    with pytest.raises(PermissionError):
        organizer.reorder(PATHS)

    renumber.assert_not_called()  # type: ignore[attr-defined]


def test_a_legacy_tc_resource_is_left_alone(renumber: MockerFixture) -> None:
    """A ``.tc``'s screenshots are pre-conversion originals, so renumbering them early would be a
    conversion nobody asked for -- and one taking no backups (#72).

    **Test steps:**

    * reorder a legacy ``.tc`` document
    * verify the refusal raised and nothing was renamed
    """
    organizer = RehuDocumentImageOrganizer(model_at(DIRECTORY / "info.tc", legacy_tc=True))

    with pytest.raises(PermissionError):
        organizer.reorder(PATHS)

    renumber.assert_not_called()  # type: ignore[attr-defined]


def test_a_legacy_tc_resource_is_not_deleted_from_either(mocker: MockerFixture, renumber: MockerFixture) -> None:
    """The same refusal covers delete, and it fires **before** anything is unlinked.

    **Test steps:**

    * remove a screenshot from a legacy ``.tc`` document
    * verify the refusal raised, nothing was unlinked and nothing renamed
    """
    unlink = mocker.patch.object(Path, "unlink")
    organizer = RehuDocumentImageOrganizer(model_at(DIRECTORY / "info.tc", legacy_tc=True))

    with pytest.raises(PermissionError):
        organizer.remove(PATHS[0], PATHS[1:])

    unlink.assert_not_called()
    renumber.assert_not_called()  # type: ignore[attr-defined]


def test_convert_numbers_one_image_against_this_resources_stem(mocker: MockerFixture) -> None:
    """Convert hands the core the resource's own stem and reports the rename as a one-entry map (#270).

    A map rather than the new path, so the curated-out list follows it exactly as it follows a
    reorder's ([[data-model#image-meanings]]).

    **Test steps:**

    * convert ``cover.jpg`` on a document bound to ``/fake/tutorial/info.rehu``
    * verify the core was asked with that stem and the configured patterns
    * verify the report is ``{old: new}``
    """
    convert = mocker.patch(
        "rehuco_agent.documents.rehu_document_image_organizer.convert_screenshot",
        return_value=DIRECTORY / "info02.jpg",
    )
    organizer = RehuDocumentImageOrganizer(model_at(DIRECTORY / "info.rehu"))

    assert organizer.convert(DIRECTORY / "cover.jpg") == {"cover.jpg": "info02.jpg"}

    assert convert.call_args.args[:2] == (DIRECTORY / "cover.jpg", "info")


def test_a_legacy_tc_resource_is_not_converted_one_image_at_a_time(mocker: MockerFixture) -> None:
    """A ``.tc``'s images are numbered by the whole-directory conversion and nothing else (#270).

    **Test steps:**

    * convert one image on a legacy ``.tc`` document
    * verify the refusal raised before the core was reached at all
    """
    convert = mocker.patch("rehuco_agent.documents.rehu_document_image_organizer.convert_screenshot")
    organizer = RehuDocumentImageOrganizer(model_at(DIRECTORY / "info.tc", legacy_tc=True))

    with pytest.raises(PermissionError):
        organizer.convert(DIRECTORY / "cover.jpg")

    convert.assert_not_called()
