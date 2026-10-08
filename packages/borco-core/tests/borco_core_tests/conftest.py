"""pytest fixtures for borco-core."""

import pytest
from pytest_mock import MockerFixture

from .path_presence_support import MODULE, Probe


@pytest.fixture(name="probe")
def fixture_probe(mocker: MockerFixture) -> Probe:
    """Replace ``socket.create_connection`` with a recording fake that answers at once.

    :param mocker: pytest-mock fixture.
    :returns: the fake.
    """
    fake = Probe()
    mocker.patch(f"{MODULE}.socket.create_connection", side_effect=fake)
    return fake
