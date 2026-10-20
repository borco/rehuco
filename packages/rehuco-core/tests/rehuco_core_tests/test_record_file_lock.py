"""Tests for a record's lock file (#512, [[sync#lock-file]]): taking it, waiting out a busy one, breaking a stale one,
removing it, and refusing a rename while someone else holds it -- against real files under ``tmp_path``, with
``time.time`` and ``time.sleep`` patched to a clock a sleep moves on."""

# one cohesive module on one class's contract; the split of every module past the cap is #499's
# pylint: disable=too-many-lines

import io
import logging
import os
import socket
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from pytest import LogCaptureFixture, fixture, mark, param, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    DEFAULT_LOCK_TIMEOUT_SECONDS,
    DEFAULT_LOCK_TTL_SECONDS,
    RELEASE_RETRY_SECONDS,
    LockHolder,
    RecordFileLock,
    RecordLockedError,
    is_lock_name,
    lock_path_for,
)

START: Final = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)
"""When every test's fake clock starts."""

OTHER: Final = LockHolder("bob", "elsewhere", 4242, "rehuco-agent", START)
"""Another machine's process holding a lock, taken at :data:`START`."""


class Clock:
    """A clock a lock reads and its back-off advances, so a timeout passes without waiting.

    :param start: the time it starts at.
    """

    def __init__(self, start: datetime = START) -> None:
        self.now = start.timestamp()
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        """The time now.

        :returns: seconds since the epoch.
        """
        return self.now

    def sleep(self, seconds: float) -> None:
        """Wait, by moving the clock on.

        :param seconds: how long.
        """
        self.sleeps.append(seconds)
        self.now += seconds


@fixture(autouse=True)
def clock(mocker: MockerFixture) -> Clock:
    """The clock every lock in a test reads, in place of ``time.time``, and whose sleep stands in for ``time.sleep``.

    :param mocker: pytest-mock fixture.
    :returns: the clock, started at :data:`START`.
    """
    fake = Clock()
    mocker.patch.object(time, "time", fake)
    mocker.patch.object(time, "sleep", fake.sleep)
    return fake


def record_in(folder: Path) -> Path:
    """A record in ``folder``; the lock never reads it, so it is not written.

    :param folder: where.
    :returns: its path.
    """
    return folder / "info.rehu"


def lock_of(record: Path, **options: float) -> RecordFileLock:
    """A lock on ``record``.

    :param record: the record.
    :param options: ``ttl`` or ``timeout``, if not the defaults.
    :returns: the lock.
    """
    return RecordFileLock(record, user="alice", **options)


def hold(record: Path, holder: LockHolder | None = OTHER, text: str | None = None) -> Path:
    """Put another process's lock beside ``record``.

    :param record: the record.
    :param holder: who holds it; ignored when ``text`` is given.
    :param text: the lock's content as is, for one that names no holder.
    :returns: the lock file.
    """
    lock = lock_path_for(record)
    lock.write_text(text if text is not None else holder.text() if holder is not None else "", encoding="utf-8")
    return lock


def reading(mocker: MockerFixture, read: Callable[[Path], str]) -> None:
    """Make every read of a lock's content answer ``read``'s text for it.

    :param mocker: pytest-mock fixture.
    :param read: the text read for a path, or an exception it raises.
    """
    mocker.patch(
        "rehuco_core.record_file_lock.shared_read_open",
        side_effect=lambda path: io.BytesIO(read(Path(path)).encode("utf-8")),
    )


def raising(error: OSError) -> Callable[[Path], str]:
    """A read that always fails.

    :param error: what it raises.
    :returns: the read.
    """

    def read(_: Path) -> str:
        """Fail.

        :raises OSError: ``error``.
        """
        raise error

    return read


# region Names


@mark.parametrize(
    ("filename", "expected"),
    [
        param("info.rehu.lock", True, id="a-directory-scoped-record"),
        param("Lesson 1.REHU.LOCK", True, id="a-file-scoped-record-in-any-case"),
        param("info.tc.lock", True, id="a-legacy-record"),
        param("home.rehuco.lock", True, id="a-rehuco"),
        param("info.checksum.lock", True, id="a-checksum-record"),
        param("yarn.lock", False, id="a-tutorial-s-own-lock-file"),
        param("info.lock", False, id="a-record-s-stem-alone"),
        param("info.rehu", False, id="the-record-itself"),
        param("info.rehu.lock.orig", False, id="a-backup-of-one"),
    ],
)
def test_only_a_lock_beside_a_record_s_name_is_one(filename: str, expected: bool) -> None:
    """A lock file is the record's name with ``.lock`` added; any other ``.lock`` is somebody's content.

    **Test steps:**

    * ask whether ``filename`` is a lock
    * verify the answer
    """
    assert is_lock_name(filename) is expected


def test_a_lock_sits_beside_its_record_under_the_record_s_name(tmp_path: Path) -> None:
    """The lock is the record's own name with ``.lock`` added, in the record's folder.

    **Test steps:**

    * ask for the lock of a record, and the path of a lock on it
    * verify both are ``info.rehu.lock`` beside it
    """
    record = record_in(tmp_path)

    assert lock_path_for(record) == tmp_path / "info.rehu.lock"
    assert RecordFileLock(record).path == tmp_path / "info.rehu.lock"


# endregion

# region The holder


def test_a_holder_reads_back_from_its_text() -> None:
    """A lock's content is ``user@host pid app time``, and reads back as the holder that wrote it.

    **Test steps:**

    * write a holder whose user has a space and an ``@`` as text
    * verify its shape, that it parses back equal, and how it is said
    """
    holder = LockHolder("Ann Lee@home", "nas-pc", 17, "rehuco-node", START)

    text = holder.text()

    assert text == "Ann Lee@home@nas-pc 17 rehuco-node 2026-10-19T12:00:00.000+00:00"
    assert LockHolder.parse(text) == holder
    assert str(holder) == "Ann Lee@home@nas-pc (rehuco-node, pid 17) since 2026-10-19 12:00:00 UTC"


@mark.parametrize(
    "text",
    [
        param("", id="empty"),
        param("bob@pc 12 app", id="too-few-parts"),
        param("bob@pc twelve app 2026-10-19T12:00:00+00:00", id="no-pid"),
        param("bob@pc 12 app yesterday", id="no-time"),
        param("bob 12 app 2026-10-19T12:00:00+00:00", id="no-host"),
        param("bob@pc 12 app 2026-10-19T12:00:00", id="a-time-with-no-zone"),
    ],
)
def test_text_that_is_not_a_holder_names_none(text: str) -> None:
    """A lock between its create and its write, or one some other tool wrote, names no holder.

    **Test steps:**

    * parse ``text``
    * verify it names no one
    """
    assert LockHolder.parse(text) is None


def test_this_process_as_a_holder(mocker: MockerFixture) -> None:
    """This process holds a lock as the identity it writes as -- the login name when it has none -- on this host,
    under its pid and its program's name, spaces joined.

    **Test steps:**

    * make the program ``rehuco agent.exe`` and the login name ``carol``
    * verify a holder made with no user, and one made with a user
    * verify an empty program name reads as ``python``, and the holder is this process
    """
    mocker.patch("rehuco_core.record_file_lock.sys.argv", ["C:/apps/rehuco agent.exe"])
    mocker.patch("rehuco_core.record_file_lock.getpass.getuser", return_value="carol")

    anonymous = LockHolder.current(None, START.timestamp())
    named = LockHolder.current("alice", START.timestamp())

    assert anonymous == LockHolder("carol", socket.gethostname(), os.getpid(), "rehuco-agent", START)
    assert named.user == "alice"
    assert anonymous.is_this_process()
    mocker.patch("rehuco_core.record_file_lock.sys.argv", [""])
    assert LockHolder.current(None, START.timestamp()).app == "python"


def test_another_process_is_not_this_one() -> None:
    """A lock taken on another host, or by another process here, is someone else's.

    **Test steps:**

    * verify a holder elsewhere and a holder here under another pid are not this process
    """
    assert not OTHER.is_this_process()
    assert not LockHolder("bob", socket.gethostname(), os.getpid() + 1, "x", START).is_this_process()


# endregion

# region Taking and removing


def test_a_lock_is_there_for_the_write_and_gone_after(tmp_path: Path, clock: Clock) -> None:
    """The lock is the directory entry: created with who holds it, closed at once, and removed once the write is
    done.

    **Test steps:**

    * take a lock on a record
    * verify the lock file names this process as ``alice`` while held
    * verify it is gone once released, and a second release does nothing
    """
    record = record_in(tmp_path)

    with lock_of(record) as lock:
        holder = LockHolder.parse(lock.path.read_text(encoding="utf-8"))
        assert holder is not None
        assert (holder.user, holder.host, holder.pid, holder.time) == (
            "alice",
            socket.gethostname(),
            os.getpid(),
            START,
        )

    assert not lock.path.exists()
    lock.release()
    assert not clock.sleeps


def test_a_write_that_fails_still_removes_the_lock(tmp_path: Path) -> None:
    """A write failing under the lock leaves no lock behind, and its own error is what is raised.

    **Test steps:**

    * raise inside a held lock
    * verify that error comes out and the lock is gone
    """
    record = record_in(tmp_path)

    with raises(RuntimeError, match="write failed"), lock_of(record):
        raise RuntimeError("write failed")

    assert not lock_path_for(record).exists()


def test_a_lock_that_cannot_be_written_is_removed_again(tmp_path: Path, mocker: MockerFixture) -> None:
    """A lock created but not written would read as held by no one until the TTL: it is removed, and the failure
    raised.

    **Test steps:**

    * make writing the lock's content fail
    * verify the error comes out and no lock is left
    """
    record = record_in(tmp_path)
    mocker.patch("rehuco_core.record_file_lock.os.write", side_effect=OSError("disk full"))

    with raises(OSError, match="disk full"):
        lock_of(record).acquire()

    assert not lock_path_for(record).exists()


def test_a_lock_in_a_folder_that_is_gone_fails_as_the_write_would(tmp_path: Path) -> None:
    """A record whose folder is gone fails on its lock the way the write itself would have.

    **Test steps:**

    * take a lock on a record in a folder that does not exist
    * verify a ``FileNotFoundError``, not a lock held by someone
    """
    with raises(FileNotFoundError):
        lock_of(record_in(tmp_path / "gone")).acquire()


# endregion

# region Busy


def test_a_busy_lock_is_waited_out_then_refused_naming_its_holder(tmp_path: Path, clock: Clock) -> None:
    """A fresh lock someone else holds is retried with a random back-off for the timeout, then the write fails with
    the holder named, and the lock is left alone.

    **Test steps:**

    * hold the record's lock as another machine's process, just taken
    * take the lock
    * verify a ``RecordLockedError`` naming that holder, after waiting out the timeout in back-offs of 10-50 ms
    * verify the other lock is untouched
    """
    record = record_in(tmp_path)
    lock = hold(record)

    with raises(RecordLockedError, match="info.rehu is locked by bob@elsewhere") as refused:
        lock_of(record).acquire()

    assert refused.value.holder == OTHER
    assert refused.value.path == record
    assert isinstance(refused.value, OSError)
    assert sum(clock.sleeps) >= DEFAULT_LOCK_TIMEOUT_SECONDS
    assert all(0.01 <= seconds <= 0.05 for seconds in clock.sleeps)
    assert LockHolder.parse(lock.read_text(encoding="utf-8")) == OTHER


def test_a_lock_freed_during_the_back_off_is_taken(tmp_path: Path, mocker: MockerFixture, clock: Clock) -> None:
    """Busy is transient: a lock released while this one backs off is taken on the next try.

    **Test steps:**

    * hold the record's lock as another process, and release it during the first back-off
    * take the lock
    * verify it was taken after one back-off, and names this process
    """
    record = record_in(tmp_path)
    lock = hold(record)

    def release_then_sleep(seconds: float) -> None:
        """The other holder releases while this one waits.

        :param seconds: how long.
        """
        lock.unlink()
        clock.sleep(seconds)

    mocker.patch.object(time, "sleep", release_then_sleep)

    with lock_of(record):
        assert LockHolder.parse(lock.read_text(encoding="utf-8")) != OTHER

    assert len(clock.sleeps) == 1


def test_a_lock_naming_no_one_and_just_made_is_held(tmp_path: Path, clock: Clock) -> None:
    """A lock with no holder in it, made just now, is someone between the create and the write: held, and refused as
    held by someone else.

    **Test steps:**

    * put an empty lock beside the record, its time now
    * take the lock
    * verify a ``RecordLockedError`` naming no one
    """
    record = record_in(tmp_path)
    lock = hold(record, text="")
    os.utime(lock, (clock.now, clock.now))

    with raises(RecordLockedError, match="locked by someone else") as refused:
        lock_of(record).acquire()

    assert refused.value.holder is None


def test_a_lock_that_will_not_read_is_held(tmp_path: Path, mocker: MockerFixture) -> None:
    """A lock that is there but cannot be read -- a Windows client mid-delete -- is held, by no one it can name.

    **Test steps:**

    * hold the record's lock, and make reading it fail
    * take the lock
    * verify a ``RecordLockedError`` naming no one
    """
    record = record_in(tmp_path)
    hold(record)
    reading(mocker, raising(PermissionError("denied")))

    with raises(RecordLockedError) as refused:
        lock_of(record).acquire()

    assert refused.value.holder is None


def test_a_pending_delete_is_busy_until_it_is_gone(tmp_path: Path, mocker: MockerFixture, clock: Clock) -> None:
    """Windows refuses to create a name whose delete is still pending: that is busy, retried like an existing lock.

    **Test steps:**

    * make the first create be refused with a ``PermissionError`` while the name is still listed
    * take the lock
    * verify it was taken after one back-off
    """
    record = record_in(tmp_path)
    mocker.patch("rehuco_core.record_file_lock.os.open", side_effect=iter_open([PermissionError("pending")], os.open))
    listed = iter([True])
    real_exists = Path.exists
    mocker.patch.object(Path, "exists", autospec=True, side_effect=lambda self: next(listed, real_exists(self)))

    with lock_of(record):
        pass

    assert len(clock.sleeps) == 1


def test_a_pending_delete_gone_before_the_look_is_retried_not_blamed_on_the_folder(
    tmp_path: Path, mocker: MockerFixture, clock: Clock
) -> None:
    """A create refused for a delete still pending, with that delete done by the time the name is looked at, finds no
    lock there -- as a folder this process may not write would. One more create tells the two apart: it lands.

    **Test steps:**

    * make the first create be refused with a ``PermissionError``, the name not listed when looked at
    * take the lock
    * verify it was taken, at once, with no back-off
    """
    record = record_in(tmp_path)
    mocker.patch("rehuco_core.record_file_lock.os.open", side_effect=iter_open([PermissionError("pending")], os.open))

    with lock_of(record):
        assert lock_path_for(record).exists()

    assert not clock.sleeps


def test_a_folder_never_writable_fails_as_a_refusal_not_a_lock(
    tmp_path: Path, mocker: MockerFixture, clock: Clock
) -> None:
    """A create refused with no lock there to refuse it is a folder this process may not write: the refusal is raised
    at once, not a lock held by someone after the timeout.

    **Test steps:**

    * make every create be refused with a ``PermissionError``
    * take the lock
    * verify that ``PermissionError`` comes out, with no back-off
    """
    mocker.patch("rehuco_core.record_file_lock.os.open", side_effect=PermissionError("read-only share"))

    with raises(PermissionError, match="read-only share"):
        lock_of(record_in(tmp_path)).acquire()

    assert not clock.sleeps


def test_a_departed_holder_is_not_blamed_for_a_busy_name(tmp_path: Path, mocker: MockerFixture) -> None:
    """A lock seen once and gone since, with the name still answering busy -- a directory cache -- times out naming no
    one, not the holder who left.

    **Test steps:**

    * hold the record's lock as another process; make the create answer busy throughout, and the lock vanish after
      the first look
    * take the lock, with a short timeout
    * verify a ``RecordLockedError`` naming no holder
    """
    record = record_in(tmp_path)
    lock = hold(record)
    looks: list[int] = []

    def read(path: Path) -> str:
        """Answer the holder once, then have the lock gone.

        :param path: the lock.
        :returns: its text.
        :raises FileNotFoundError: from the second look on.
        """
        looks.append(1)
        if len(looks) > 1:
            lock.unlink(missing_ok=True)
            raise FileNotFoundError(path)
        return path.read_text(encoding="utf-8")

    reading(mocker, read)
    mocker.patch("rehuco_core.record_file_lock.os.open", side_effect=FileExistsError("cached"))

    with raises(RecordLockedError, match="someone else") as refused:
        lock_of(record, timeout=0.1).acquire()

    assert refused.value.holder is None


def test_a_lock_that_went_away_is_forgotten_when_the_create_is_still_refused(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """A holder seen once and gone since is not who a later refusal is blamed on: with no lock there, a refused create
    is the folder's own.

    **Test steps:**

    * hold the record's lock as another process; make the create be refused throughout, and the lock vanish after
      the first look
    * take the lock
    * verify the folder's ``PermissionError`` comes out, not a ``RecordLockedError`` naming the departed holder
    """
    record = record_in(tmp_path)
    lock = hold(record)
    looks: list[int] = []

    def read(path: Path) -> str:
        """Answer the holder once, then have the lock gone.

        :param path: the lock.
        :returns: its text.
        :raises FileNotFoundError: from the second look on.
        """
        looks.append(1)
        if len(looks) > 1:
            lock.unlink(missing_ok=True)
            raise FileNotFoundError(path)
        return path.read_text(encoding="utf-8")

    reading(mocker, read)
    mocker.patch("rehuco_core.record_file_lock.os.open", side_effect=PermissionError("read-only share"))

    with raises(PermissionError, match="read-only share"):
        lock_of(record).acquire()


def iter_open(failures: list[OSError], real_open: Callable[[Path, int], int]) -> Callable[[Path, int], int]:
    """A stand-in for ``os.open`` that raises each of ``failures`` once, then opens for real.

    :param failures: what the first calls raise, in order.
    :param real_open: the real ``os.open``.
    :returns: the stand-in.
    """
    pending = list(failures)

    def opener(path: Path, flags: int) -> int:
        """Raise the next failure, or open.

        :param path: what to open.
        :param flags: how.
        :returns: the descriptor.
        """
        if pending:
            raise pending.pop(0)
        return real_open(path, flags)

    return opener


# endregion

# region Stale


def test_a_stale_lock_is_broken_with_a_log_line_and_taken(
    tmp_path: Path, caplog: LogCaptureFixture, clock: Clock
) -> None:
    """A lock older than the TTL by the time it names is abandoned: deleted, verified gone, logged, and taken at once.

    **Test steps:**

    * hold the record's lock as another process, its time older than the TTL
    * take the lock
    * verify it is this process's, with no back-off, and a warning naming the old holder
    """
    record = record_in(tmp_path)
    lock = hold(record)
    clock.now = (START + timedelta(seconds=DEFAULT_LOCK_TTL_SECONDS + 1)).timestamp()
    caplog.set_level(logging.WARNING, logger="rehuco_core.record_file_lock")

    with lock_of(record):
        assert LockHolder.parse(lock.read_text(encoding="utf-8")) != OTHER

    assert not clock.sleeps
    assert f"Broke the stale lock on {record}, left by {OTHER}" in caplog.messages


def test_a_stale_lock_naming_no_one_is_aged_by_its_time_on_disk(
    tmp_path: Path, caplog: LogCaptureFixture, clock: Clock
) -> None:
    """A lock whose holder died between the create and the write names no time: its modification time stands in.

    **Test steps:**

    * put an empty lock beside the record, its modification time older than the TTL
    * take the lock
    * verify it is taken, with a warning that the lock named no holder
    """
    record = record_in(tmp_path)
    lock = hold(record, text="")
    old = clock.now - DEFAULT_LOCK_TTL_SECONDS - 1
    os.utime(lock, (old, old))
    caplog.set_level(logging.WARNING, logger="rehuco_core.record_file_lock")

    with lock_of(record):
        pass

    assert f"Broke the stale lock on {record}, left by a holder it does not name" in caplog.messages


def test_a_stale_lock_that_lingers_is_held(tmp_path: Path, mocker: MockerFixture, clock: Clock) -> None:
    """A stale lock still listed after its delete -- a client's directory cache -- is held and backed off from, never
    spun on.

    **Test steps:**

    * hold a stale lock, and make deleting it leave it listed
    * take the lock
    * verify a ``RecordLockedError`` after the timeout's back-offs
    """
    record = record_in(tmp_path)
    hold(record)
    clock.now = (START + timedelta(seconds=DEFAULT_LOCK_TTL_SECONDS + 1)).timestamp()
    mocker.patch.object(Path, "unlink", autospec=True)

    with raises(RecordLockedError):
        lock_of(record).acquire()

    assert sum(clock.sleeps) >= DEFAULT_LOCK_TIMEOUT_SECONDS


def test_a_stale_lock_that_will_not_delete_is_held(tmp_path: Path, mocker: MockerFixture, clock: Clock) -> None:
    """A stale lock the delete is refused on is held.

    **Test steps:**

    * hold a stale lock, and make deleting it fail
    * take the lock
    * verify a ``RecordLockedError`` naming the old holder
    """
    record = record_in(tmp_path)
    hold(record)
    clock.now = (START + timedelta(seconds=DEFAULT_LOCK_TTL_SECONDS + 1)).timestamp()
    mocker.patch.object(Path, "unlink", autospec=True, side_effect=PermissionError("in use"))

    with raises(RecordLockedError) as refused:
        lock_of(record).acquire()

    assert refused.value.holder == OTHER


def test_a_stale_lock_retaken_before_the_delete_is_left_to_its_new_holder(
    tmp_path: Path, mocker: MockerFixture, clock: Clock
) -> None:
    """A stale lock another writer broke and retook between this one's look and its delete is not deleted: the
    content is read again first, and only the lock judged stale is broken.

    **Test steps:**

    * hold a stale lock, and make every read after the first find a fresh holder's
    * take the lock, with a short timeout
    * verify a ``RecordLockedError`` naming the fresh holder, and its lock still there
    """
    record = record_in(tmp_path)
    lock = hold(record)
    clock.now = (START + timedelta(seconds=DEFAULT_LOCK_TTL_SECONDS + 1)).timestamp()
    fresh = LockHolder("carol", "laptop", 7, "rehuco-agent", datetime.fromtimestamp(clock.now, UTC))
    reads = iter([OTHER.text()])
    reading(mocker, lambda _: next(reads, fresh.text()))

    with raises(RecordLockedError) as refused:
        lock_of(record, timeout=0.1).acquire()

    assert refused.value.holder == fresh
    assert lock.exists()


def test_a_stale_lock_broken_by_another_writer_first_is_taken(
    tmp_path: Path, mocker: MockerFixture, clock: Clock
) -> None:
    """A stale lock someone else deleted between this one's look and its delete is gone either way: taken at once.

    **Test steps:**

    * hold a stale lock, and make the second read find it deleted
    * take the lock
    * verify it is taken with no back-off
    """
    record = record_in(tmp_path)
    lock = hold(record)
    clock.now = (START + timedelta(seconds=DEFAULT_LOCK_TTL_SECONDS + 1)).timestamp()
    calls: list[Path] = []

    def read(path: Path) -> str:
        """Read, but have the other writer delete the lock just before the second read.

        :param path: what is read.
        :returns: its text.
        """
        calls.append(path)
        if len(calls) == 2:
            lock.unlink()
        return path.read_text(encoding="utf-8")

    reading(mocker, read)

    with lock_of(record):
        pass

    assert not clock.sleeps


# endregion

# region Release


def test_a_lock_taken_over_is_left_to_its_new_holder(tmp_path: Path, caplog: LogCaptureFixture) -> None:
    """A lock someone broke as stale and retook while this one held it is not this one's to remove.

    **Test steps:**

    * take the lock, then have another process's lock replace it
    * release
    * verify the other lock is still there, with a warning
    """
    record = record_in(tmp_path)
    caplog.set_level(logging.WARNING, logger="rehuco_core.record_file_lock")

    with lock_of(record):
        lock = hold(record)

    assert LockHolder.parse(lock.read_text(encoding="utf-8")) == OTHER
    assert f"The lock on {record} was taken over before it was released, and is left" in caplog.messages


def test_a_lock_already_gone_at_release_is_logged(tmp_path: Path, caplog: LogCaptureFixture) -> None:
    """A lock deleted by someone else while held is gone; the release says so and carries on.

    **Test steps:**

    * take the lock, then delete it
    * release
    * verify a warning, and no error
    """
    record = record_in(tmp_path)
    caplog.set_level(logging.WARNING, logger="rehuco_core.record_file_lock")

    with lock_of(record) as lock:
        lock.path.unlink()

    assert f"The lock on {record} was gone before it was released" in caplog.messages


def test_a_lock_that_will_not_delete_at_release_is_logged(
    tmp_path: Path, mocker: MockerFixture, caplog: LogCaptureFixture, clock: Clock
) -> None:
    """A release never raises: a delete refused past its retries is logged, and the lock goes stale in time.

    **Test steps:**

    * take the lock, then make deleting it always be refused
    * release
    * verify it was retried after each of the release delays, then a warning naming the refusal
    """
    record = record_in(tmp_path)
    caplog.set_level(logging.WARNING, logger="rehuco_core.record_file_lock")

    with lock_of(record):
        mocker.patch.object(Path, "unlink", autospec=True, side_effect=PermissionError("in use"))

    assert clock.sleeps == list(RELEASE_RETRY_SECONDS)
    assert f"Could not remove the lock on {record}: in use" in caplog.messages


def test_a_release_refused_for_a_moment_is_retried(tmp_path: Path, mocker: MockerFixture, clock: Clock) -> None:
    """A delete refused while a scanner briefly holds the lock open is retried: a lock left behind would cost every
    other writer the TTL.

    **Test steps:**

    * take the lock, then make the first delete be refused
    * release
    * verify one retry, after the first release delay, and the lock gone
    """
    record = record_in(tmp_path)
    real_unlink = Path.unlink
    refusals = [PermissionError("scanned")]

    def unlink(path: Path) -> None:
        """Refuse once, then delete.

        :param path: what to delete.
        :raises PermissionError: the first time.
        """
        if refusals:
            raise refusals.pop()
        real_unlink(path)

    with lock_of(record):
        mocker.patch.object(Path, "unlink", autospec=True, side_effect=unlink)

    assert clock.sleeps == [RELEASE_RETRY_SECONDS[0]]
    assert not lock_path_for(record).exists()


@mark.parametrize(
    ("patched", "error", "message"),
    [
        param("unlink", OSError("device gone"), "Could not remove the lock on {}: device gone", id="a-failed-delete"),
        param(
            "read", PermissionError("device gone"), "Could not remove the lock on {}: device gone", id="a-refused-read"
        ),
        param(
            "unlink", FileNotFoundError("gone"), "The lock on {} was gone before it was released", id="gone-at-delete"
        ),
    ],
)
# pylint: disable-next=too-many-arguments,too-many-positional-arguments
def test_a_release_that_cannot_reach_the_lock_is_logged(
    tmp_path: Path,
    mocker: MockerFixture,
    caplog: LogCaptureFixture,
    patched: str,
    error: OSError,
    message: str,
    clock: Clock,
) -> None:
    """A release that cannot read or delete its lock for a reason a retry will not mend says so, and does not raise --
    a lock deleted by someone else between the read and the delete included.

    **Test steps:**

    * take the lock, then make deleting it fail with ``error``, or reading it be refused
    * release
    * verify the warning, and no retry
    """
    record = record_in(tmp_path)
    caplog.set_level(logging.WARNING, logger="rehuco_core.record_file_lock")

    with lock_of(record):
        if patched == "unlink":
            mocker.patch.object(Path, "unlink", autospec=True, side_effect=error)
        else:
            reading(mocker, raising(error))

    assert not clock.sleeps
    assert message.format(record) in caplog.messages


def test_a_lock_still_listed_after_release_is_noted(
    tmp_path: Path, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """A lock still listed after its delete -- pending while another writer reads it -- is verified and noted, not
    warned about: it reads as held until that read closes, which is what it should.

    **Test steps:**

    * take the lock, then make deleting it leave it listed
    * release
    * verify an info line, and no warning
    """
    record = record_in(tmp_path)
    caplog.set_level(logging.INFO, logger="rehuco_core.record_file_lock")

    with lock_of(record):
        mocker.patch.object(Path, "unlink", autospec=True)

    assert [(entry.levelno, entry.getMessage()) for entry in caplog.records] == [
        (logging.INFO, f"The lock on {record} is still listed after it was removed")
    ]


# endregion

# region A rename's question


def test_a_rename_is_refused_while_another_process_holds_the_lock(tmp_path: Path) -> None:
    """A fresh lock someone else holds refuses a rename, naming the holder.

    **Test steps:**

    * hold the record's lock as another process, just taken
    * verify the question refuses, naming the holder, and leaves the lock
    """
    record = record_in(tmp_path)
    lock = hold(record)

    with raises(RecordLockedError) as refused:
        lock_of(record).refuse_if_held()

    assert refused.value.holder == OTHER
    assert lock.exists()


@mark.parametrize(
    "holder",
    [
        param(None, id="no-lock"),
        param(LockHolder("alice", socket.gethostname(), os.getpid(), "x", START), id="this-process-s-own"),
    ],
)
def test_a_rename_goes_ahead_with_no_one_else_holding_the_lock(tmp_path: Path, holder: LockHolder | None) -> None:
    """No lock, or this process's own, is no reason to refuse.

    **Test steps:**

    * hold the record's lock as ``holder``, or not at all
    * verify the question does not refuse
    """
    record = record_in(tmp_path)
    if holder is not None:
        hold(record, holder)

    lock_of(record).refuse_if_held()


def test_a_rename_breaks_a_stale_lock(tmp_path: Path, caplog: LogCaptureFixture, clock: Clock) -> None:
    """A stale lock is no holder: broken with a log line, and the rename goes ahead.

    **Test steps:**

    * hold a stale lock
    * verify the question does not refuse, the lock is gone, and the break logged
    """
    record = record_in(tmp_path)
    lock = hold(record)
    caplog.set_level(logging.WARNING, logger="rehuco_core.record_file_lock")
    clock.now = (START + timedelta(seconds=DEFAULT_LOCK_TTL_SECONDS + 1)).timestamp()

    lock_of(record).refuse_if_held()

    assert not lock.exists()
    assert f"Broke the stale lock on {record}, left by {OTHER}" in caplog.messages


def test_a_rename_is_refused_by_a_stale_lock_that_lingers(tmp_path: Path, mocker: MockerFixture, clock: Clock) -> None:
    """A stale lock still listed after its break counts as held: the rename refuses rather than moving a record whose
    lock is in doubt.

    **Test steps:**

    * hold a stale lock, and make deleting it leave it listed
    * verify the question refuses, naming the stale holder
    """
    record = record_in(tmp_path)
    hold(record)
    mocker.patch.object(Path, "unlink", autospec=True)
    clock.now = (START + timedelta(seconds=DEFAULT_LOCK_TTL_SECONDS + 1)).timestamp()

    with raises(RecordLockedError) as refused:
        lock_of(record).refuse_if_held()

    assert refused.value.holder == OTHER


def test_a_rename_is_refused_by_a_stale_lock_retaken_meanwhile(
    tmp_path: Path, mocker: MockerFixture, clock: Clock
) -> None:
    """A stale lock another writer broke and retook between the look and the break is that writer's, fresh: the
    rename refuses, naming the new holder.

    **Test steps:**

    * hold a stale lock, and make every read after the first find a fresh holder's
    * verify the question refuses, naming the fresh holder, and leaves the lock
    """
    record = record_in(tmp_path)
    lock = hold(record)
    clock.now = (START + timedelta(seconds=DEFAULT_LOCK_TTL_SECONDS + 1)).timestamp()
    fresh = LockHolder("carol", "laptop", 7, "rehuco-agent", datetime.fromtimestamp(clock.now, UTC))
    reads = iter([OTHER.text()])
    reading(mocker, lambda _: next(reads, fresh.text()))

    with raises(RecordLockedError) as refused:
        lock_of(record).refuse_if_held()

    assert refused.value.holder == fresh
    assert lock.exists()


def test_a_rename_is_refused_by_a_fresh_lock_naming_no_one(tmp_path: Path, clock: Clock) -> None:
    """A fresh lock that names no holder is still held.

    **Test steps:**

    * put an empty lock beside the record, its time now
    * verify the question refuses, naming no one
    """
    record = record_in(tmp_path)
    lock = hold(record, text="")
    os.utime(lock, (clock.now, clock.now))

    with raises(RecordLockedError, match="someone else"):
        lock_of(record).refuse_if_held()


# endregion
