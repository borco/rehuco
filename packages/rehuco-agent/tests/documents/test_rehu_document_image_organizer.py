"""Tests for RehuDocumentImageOrganizer: where a resource's screenshot renames are aimed (#72)."""

from pathlib import Path
from typing import Final

import pytest
from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.documents.rehu_document_image_organizer import RehuDocumentImageOrganizer
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_core import RehuDocument

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


def test_remove_unlinks_first_and_closes_the_gap_after(mocker: MockerFixture, renumber: MockerFixture) -> None:
    """The file goes, then the survivors renumber -- so a failed delete never closes a gap that is
    still occupied (#72).

    **Test steps:**

    * remove the first of two screenshots
    * verify it was unlinked and the survivor renumbered
    """
    unlink = mocker.patch.object(Path, "unlink")
    organizer = RehuDocumentImageOrganizer(model_at(DIRECTORY / "info.rehu"))

    organizer.remove(PATHS[0], PATHS[1:])

    unlink.assert_called_once()
    renumber.assert_called_once_with(DIRECTORY, "info", PATHS[1:])  # type: ignore[attr-defined]


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
