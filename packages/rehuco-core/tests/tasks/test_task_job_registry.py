"""Tests for the job registry -- what turns a saved kind back into a job (#238).

The registry is the indirection that keeps a saved queue readable after a class moves, so every test
here is about one of the two things it owes: building the right job, and refusing -- quietly -- to
build one this build cannot.
"""

import logging
from typing import Any

import pytest
from pytest import fixture
from rehuco_core import TaskJobBase, TaskJobRegistry

# region Sample classes


class CounterJob(TaskJobBase):
    """A persistable job whose whole state is how far it has counted.

    :param label: the job's label.
    """

    kind = "counter"

    def __init__(self, label: str = "counter") -> None:
        super().__init__()
        self.label = label
        self.cursor = 0

    def validate(self) -> str | None:
        """Accept every start.

        :returns: ``None``, always.
        """
        return None

    def capture_state(self) -> dict[str, Any]:
        """Hand over the cursor.

        :returns: the state to write down.
        """
        return {"cursor": self.cursor}

    def restore_state(self, state: dict[str, Any]) -> None:
        """Take the cursor back.

        :param state: what :meth:`capture_state` wrote.
        """
        self.cursor = state["cursor"]

    def run(self, control: Any) -> None:
        """Do nothing; this class exists to be built and restored, not run.

        :param control: unused.
        """
        del control


class RefusingJob(CounterJob):
    """A job that cannot make sense of the state it is handed."""

    kind = "refusing"

    def restore_state(self, state: dict[str, Any]) -> None:
        """Refuse the state.

        :param state: unused.
        :raises KeyError: always.
        """
        del state
        raise KeyError("cursor")


# endregion

# region Fixtures


@fixture(name="registry")
def registry_fixture() -> TaskJobRegistry:
    """A registry of its own, so no test registers into the app-wide default.

    :returns: a registry holding :class:`CounterJob`.
    """
    registry = TaskJobRegistry()
    registry.register(CounterJob.kind, CounterJob)
    return registry


# endregion

# region Registering


def test_a_registered_kind_is_listed(registry: TaskJobRegistry) -> None:
    """What a build can reconstruct is readable from the registry itself.

    **Test steps:**

    * register one kind (the fixture)
    * verify it is the one kind listed
    """
    assert registry.kinds == ("counter",)


def test_two_classes_cannot_claim_one_kind(registry: TaskJobRegistry) -> None:
    """A kind is written into files users already have, so it cannot silently change owner.

    **Test steps:**

    * register a second factory under the kind the fixture already registered
    * verify the registration is refused
    """
    with pytest.raises(ValueError, match="counter"):
        registry.register(CounterJob.kind, CounterJob)


# endregion

# region Creating


def test_a_saved_kind_comes_back_holding_its_state(registry: TaskJobRegistry) -> None:
    """One call, not two: what leaves the registry is a job that has already been told what it was.

    **Test steps:**

    * create the registered kind from a saved state
    * verify the job is built and holds that state
    """
    job = registry.create("counter", {"cursor": 7})

    assert isinstance(job, CounterJob)
    assert job.cursor == 7


def test_an_unknown_kind_is_refused_rather_than_raised(registry: TaskJobRegistry) -> None:
    """A queue file from a newer build must not stop this one starting.

    **Test steps:**

    * create a kind nothing registered
    * verify the answer is ``None``
    """
    assert registry.create("checksum-verify", {}) is None


def test_a_job_that_refuses_its_state_is_dropped_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    """A half-built job is worse than a missing one, and the loss has to be readable afterwards.

    **Test steps:**

    * register a job whose ``restore_state`` raises
    * create it from a state
    * verify the answer is ``None`` and the failure was logged
    """
    registry = TaskJobRegistry()
    registry.register(RefusingJob.kind, RefusingJob)

    with caplog.at_level(logging.ERROR):
        assert registry.create("refusing", {"cursor": 1}) is None

    assert "refusing" in caplog.text


# endregion

# region The default registry


def test_the_default_registry_is_shared_rather_than_rebuilt() -> None:
    """A job class registers itself at import, which only works if there is one instance to register into.

    **Test steps:**

    * import the default registry twice
    * verify both names are the same object
    """
    from rehuco_core import DEFAULT_TASK_JOB_REGISTRY as first  # pylint: disable=import-outside-toplevel
    from rehuco_core.tasks import DEFAULT_TASK_JOB_REGISTRY as second  # pylint: disable=import-outside-toplevel

    assert first is second


# endregion
