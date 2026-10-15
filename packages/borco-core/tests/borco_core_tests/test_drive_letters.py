"""Tests for the drive-letter helper the Windows tests pick an unused letter with (#501)."""

import os
import string

import pytest
from pytest import mark
from pytest_mock import MockerFixture

from borco_core_tests import drive_letters


@mark.windows
def test_the_system_drive_is_in_use() -> None:
    """The letter Windows runs from is listed, so it is never offered as unused.

    **Test steps:**

    * ask which letters are in use
    * verify the system drive's letter is among them
    """
    assert os.environ.get("SystemDrive", "C:")[0].upper() in drive_letters.letters_in_use()


def test_an_unused_drive_is_a_letter_nothing_lists_or_remembers(mocker: MockerFixture) -> None:
    """Only a letter neither listed nor remembered is offered -- a disconnected mapping is still remembered.

    **Test steps:**

    * make every letter but ``Q`` in use
    * verify ``Q:`` is offered
    """
    mocker.patch.object(drive_letters, "letters_in_use", return_value=set(string.ascii_uppercase) - {"Q"})

    assert drive_letters.unused_drive() == "Q:"


def test_a_machine_with_every_letter_in_use_skips(mocker: MockerFixture) -> None:
    """With no letter free, the test asking is skipped rather than handed a letter in use.

    **Test steps:**

    * make every letter in use, and ask for an unused one
    * verify the test is skipped
    """
    mocker.patch.object(drive_letters, "letters_in_use", return_value=set(string.ascii_uppercase))

    with pytest.raises(pytest.skip.Exception):
        drive_letters.unused_drive()
