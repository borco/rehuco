"""Writes on an in-memory disk take no lock file: a ``/fake`` folder has nowhere to create one (#512)."""

from contextlib import nullcontext

from pytest_mock import MockerFixture


def take_no_lock_files(mocker: MockerFixture) -> None:
    """Make every write under :func:`~rehuco_core.record_file_lock.locked_record` take no lock file -- the in-process
    lock it takes first still serializes the writers of one test.

    :param mocker: pytest-mock fixture.
    """
    mocker.patch("rehuco_core.record_file_lock.RecordFileLock", side_effect=lambda *_, **__: nullcontext())
