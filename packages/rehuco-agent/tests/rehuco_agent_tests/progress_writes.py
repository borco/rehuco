"""Watch progress written the way a document writes it, on the test's own thread, and writes held until a test lets them
run (#316); with the fixtures that hold or run them, imported by name into the package's ``conftest.py``."""

from collections.abc import Hashable
from typing import Final

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.documents.progress_writer import Answer, ProgressWriter, Work
from rehuco_core.access import LoadedRecord


def run_work(work: Work, answer: Answer) -> None:
    """Run one write and hand its outcome over, as the writer's thread and the GUI thread do between them.

    :param work: the write.
    :param answer: what hears its outcome.
    """
    try:
        outcome: LoadedRecord | Exception | None = work()
    except Exception as error:  # pylint: disable=broad-exception-caught
        outcome = error
    answer(outcome)


class HeldWrites:
    """Every write a document hands its writer, held back until a test lets it run -- in the order the test chooses, and
    replaced by a later one of its key as the writer replaces it, so a write overtaken or still out is something a test
    makes happen rather than waits for."""

    def __init__(self) -> None:
        self.waiting: Final[dict[Hashable, tuple[Work, Answer]]] = {}
        """The writes not run yet, by key, oldest first."""

    @property
    def keys(self) -> list[Hashable]:
        """The keys of the writes waiting, oldest first."""
        return list(self.waiting)

    def submit(self, key: Hashable, work: Work, answer: Answer, scope: Hashable | None = None) -> None:
        """Hold a write, in place of an earlier one of the same key.

        :param key: what makes two writes the same one.
        :param work: the write.
        :param answer: what hears its outcome.
        :param scope: the log scope; unused.
        """
        del scope
        self.waiting.pop(key, None)
        self.waiting[key] = (work, answer)

    def release(self, key: Hashable) -> None:
        """Run the waiting write of ``key`` and hand its outcome over.

        :param key: which write.
        """
        work, answer = self.waiting.pop(key)
        run_work(work, answer)

    def release_all(self) -> None:
        """Run every waiting write, oldest first."""
        while self.waiting:
            self.release(next(iter(self.waiting)))


@fixture(name="inline_progress_writes", autouse=True)
def fixture_inline_progress_writes(mocker: MockerFixture) -> None:
    """Have every write a document hands its writer run at once, on the caller's thread, unless a test holds them
    (#316).

    :class:`~rehuco_agent.documents.progress_writer.ProgressWriter` has a thread and its own tests; everything else
    records progress and looks at it straight away.

    :param mocker: pytest-mock fixture.
    """

    def submit(
        _writer: ProgressWriter, key: Hashable, work: Work, answer: Answer, scope: Hashable | None = None
    ) -> None:
        del key, scope
        run_work(work, answer)

    mocker.patch.object(ProgressWriter, "submit", submit)


@fixture(name="held_writes")
def fixture_held_writes(inline_progress_writes: None, mocker: MockerFixture) -> HeldWrites:
    """Hold back every write a document hands its writer until the test runs it, in place of
    :func:`inline_progress_writes`; the writer reads as busy while any waits.

    :param inline_progress_writes: the inline stand-in this replaces, so it is in place first.
    :param mocker: pytest-mock fixture.
    :returns: the writes handed over.
    """
    del inline_progress_writes
    held = HeldWrites()

    def submit(
        _writer: ProgressWriter, key: Hashable, work: Work, answer: Answer, scope: Hashable | None = None
    ) -> None:
        held.submit(key, work, answer, scope)

    mocker.patch.object(ProgressWriter, "submit", submit)
    mocker.patch.object(
        ProgressWriter, "busy", new_callable=mocker.PropertyMock, side_effect=lambda: bool(held.waiting)
    )
    return held
