"""pytest fixtures for borco-core."""

from collections.abc import Iterator

import pytest
from pytest_mock import MockerFixture

from .path_presence_support import MODULE, Probe, UnansweringServer


@pytest.fixture(name="probe")
def fixture_probe(mocker: MockerFixture) -> Probe:
    """Replace ``socket.create_connection`` with a recording fake that answers at once.

    :param mocker: pytest-mock fixture.
    :returns: the fake.
    """
    fake = Probe()
    mocker.patch(f"{MODULE}.socket.create_connection", side_effect=fake)
    return fake


@pytest.fixture(name="unanswering_server")
def fixture_unanswering_server() -> Iterator[UnansweringServer]:
    """A real listener on the loopback address that never completes a connection.

    :returns: the server; closed when the test ends.
    """
    server = UnansweringServer()
    yield server
    server.close()
