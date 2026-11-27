"""Tests for verifying ``.checksum`` records from a terminal, reading only (#715)."""

import io
from collections.abc import Callable, Iterator
from pathlib import Path

from PySide6.QtCore import QSettings
from pytest import CaptureFixture, MonkeyPatch, fixture, mark
from pytest_mock import MockerFixture
from rehuco_agent.settings.excluded_files_settings import ExcludedFilesSettings, shared_excluded_files_settings
from rehuco_agent.settings.persistent_settings import set_settings_dir
from rehuco_core import RehuDocument, generate_checksums

from tools import verify_checksums
from tools.verify_checksums import human_bytes, main

# region Fixtures / helpers


@fixture(autouse=True)
def fixture_app_settings(tmp_path: Path, monkeypatch) -> Iterator[Path]:  # type: ignore[no-untyped-def]
    """Point every run at an empty settings folder, so none reads the machine's own settings.

    :param tmp_path: pytest fixture.
    :param monkeypatch: pytest fixture.
    :returns: the folder.
    """
    monkeypatch.delenv("REHUCO_AGENT_SETTINGS_DIR", raising=False)
    folder = tmp_path / "default-settings"
    folder.mkdir()
    set_settings_dir(folder)
    shared_excluded_files_settings.cache_clear()
    yield folder
    set_settings_dir(None)
    shared_excluded_files_settings.cache_clear()


def make_record(folder: Path, files: dict[str, bytes]) -> Path:
    """A folder record holding ``files``, checksummed.

    :param folder: the record's folder, created.
    :param files: content by name.
    :returns: the ``info.checksum`` file.
    """
    folder.mkdir(parents=True)
    rehu = folder / "info.rehu"
    document = RehuDocument.new(rehu, username="tester")
    document.title = "A record"
    document.save()
    for name, content in files.items():
        (folder / name).write_bytes(content)
    generate_checksums(rehu)
    return folder / "info.checksum"


@fixture(name="record")
def fixture_record(tmp_path: Path) -> Path:
    """A record of two files that match.

    :param tmp_path: pytest fixture.
    :returns: its ``.checksum`` file.
    """
    return make_record(tmp_path / "asset", {"a.bin": b"alpha", "b.bin": b"bravo"})


def run(capsys: CaptureFixture[str], *arguments: object) -> tuple[int, str]:
    """Run the command and read what it printed.

    :param capsys: pytest fixture.
    :param arguments: the command line.
    :returns: the exit status and the output, error stream included.
    """
    status = main([str(argument) for argument in arguments])
    captured = capsys.readouterr()
    return status, captured.out + captured.err


def snapshot(folder: Path) -> dict[str, tuple[bytes, int]]:
    """Every file under a folder with its bytes and modification time.

    :param folder: the folder.
    :returns: by relative path.
    """
    return {
        path.relative_to(folder).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


# endregion


def test_a_record_that_matches_exits_zero(capsys: CaptureFixture[str], record: Path) -> None:
    """Nothing found is a clean exit, and the record's line says what matched.

    **Test steps:**

    * run the command on a record whose files are unchanged
    * check the exit status is 0 and the output counts two matched files
    """
    status, output = run(capsys, record)

    assert status == 0
    assert f"{record}: 2 matched" in output


def test_the_first_line_names_the_settings_and_the_patterns(capsys: CaptureFixture[str], record: Path) -> None:
    """A wrong list of excluded files is seen at once.

    **Test steps:**

    * run the command with ``--exclude`` and the settings folder the fixture set
    * check the first line names the folder, the app's patterns and the added one
    """
    _, output = run(capsys, record, "--exclude", "*.mine")

    first = output.splitlines()[0]
    assert "default-settings" in first
    assert ".DS_Store" in first
    assert "*.mine" in first


def test_a_changed_file_is_named_and_exits_one(capsys: CaptureFixture[str], record: Path) -> None:
    """A mismatch is the finding the exit status exists for.

    **Test steps:**

    * change a listed file and run the command
    * check the exit status is 1 and the file is named as mismatched
    """
    (record.parent / "a.bin").write_bytes(b"changed")

    status, output = run(capsys, record)

    assert status == 1
    assert "mismatched: a.bin" in output
    assert "b.bin" not in output


def test_a_missing_file_is_named_and_exits_one(capsys: CaptureFixture[str], record: Path) -> None:
    """A listed file that is gone is a finding too.

    **Test steps:**

    * delete a listed file and run the command
    * check the exit status is 1 and the file is named as missing
    """
    (record.parent / "b.bin").unlink()

    status, output = run(capsys, record)

    assert status == 1
    assert "missing: b.bin" in output


def test_a_file_without_a_checksum_is_named_only_when_asked(capsys: CaptureFixture[str], record: Path) -> None:
    """The record's own files and the junk are never among the files without a checksum.

    **Test steps:**

    * add an unlisted content file, a screenshot and a ``.DS_Store`` beside the record
    * run the command: the exit status is 0 and the file is not named
    * run it with ``--show-without-checksum``: the exit status is 1 and only the content file is named
    """
    (record.parent / "extra.bin").write_bytes(b"new")
    (record.parent / "info01.jpg").write_bytes(b"screenshot")
    (record.parent / ".DS_Store").write_bytes(b"junk")

    plain_status, plain = run(capsys, record)
    status, shown = run(capsys, record, "--show-without-checksum")

    assert plain_status == 0
    assert "extra.bin" not in plain
    assert status == 1
    assert "no checksum: extra.bin" in shown
    for name in ("info.rehu", "info.checksum", "info01.jpg", ".DS_Store", "a.bin"):
        assert f"no checksum: {name}" not in shown


def test_no_checksum_hashes_nothing_and_names_a_missing_file(
    mocker: MockerFixture, capsys: CaptureFixture[str], record: Path
) -> None:
    """Existence alone: a changed file passes, a missing one is shown, and no byte is read.

    **Test steps:**

    * make the hashing fail the test if it is called
    * change one listed file and delete the other
    * run the command with ``--no-checksum``
    * check the exit status is 1, the deleted file is named, the changed one is not and one file is present
    """
    mocker.patch("rehuco_core.checksum_inspection.digest_content", side_effect=AssertionError("hashed"))
    (record.parent / "a.bin").write_bytes(b"changed")
    (record.parent / "b.bin").unlink()

    status, output = run(capsys, record, "--no-checksum")

    assert status == 1
    assert "missing: b.bin" in output
    assert "mismatched" not in output
    assert "1 present, 1 missing" in output


def test_a_pattern_in_the_settings_folder_takes_a_file_out_of_the_list(
    capsys: CaptureFixture[str], tmp_path: Path, record: Path
) -> None:
    """``--settings-dir`` reads the app's settings, the pattern list among them.

    **Test steps:**

    * store a pattern for ``*.skip`` in a settings folder and add an unlisted ``x.skip`` beside the record
    * run with ``--show-without-checksum`` and that folder: the file is not named
    * run again with an empty settings folder: it is
    """
    stored = tmp_path / "stored-settings"
    stored.mkdir()
    settings = QSettings(str(stored / "rehuco-agent.ini"), QSettings.Format.IniFormat)
    ExcludedFilesSettings(patterns=("*.skip",)).save(settings)
    settings.sync()
    (record.parent / "x.skip").write_bytes(b"x")
    empty = tmp_path / "empty-settings"
    empty.mkdir()

    _, excluded = run(capsys, record, "--show-without-checksum", "--settings-dir", stored)
    shared_excluded_files_settings.cache_clear()
    _, listed = run(capsys, record, "--show-without-checksum", "--settings-dir", empty)

    assert "no checksum: x.skip" not in excluded
    assert "no checksum: x.skip" in listed


def test_a_settings_path_that_is_not_a_folder_is_refused(tmp_path: Path, record: Path) -> None:
    """The app's own refusal.

    **Test steps:**

    * run the command with a file for ``--settings-dir``
    * check the parser exits with its usage error
    """
    not_a_folder = tmp_path / "file.txt"
    not_a_folder.write_text("x", encoding="utf-8")

    try:
        main([str(record), "--settings-dir", str(not_a_folder)])
    except SystemExit as stop:
        assert stop.code == 2
    else:
        raise AssertionError("the path was accepted")


def test_a_folder_stands_for_every_record_under_it(capsys: CaptureFixture[str], tmp_path: Path) -> None:
    """At any depth by default, in the order of the paths, and only the top with ``--no-recursive``.

    **Test steps:**

    * make a folder holding a record and, in a sub-folder, another
    * run the command on the folder: both records are verified, the top one first
    * run it with ``--no-recursive``: only the top one is
    """
    top = make_record(tmp_path / "root", {"a.bin": b"alpha"})
    below = make_record(tmp_path / "root" / "sub", {"c.bin": b"charlie"})

    status, every = run(capsys, tmp_path / "root")
    _, shallow = run(capsys, tmp_path / "root", "--no-recursive")

    assert status == 0
    assert every.index(str(top)) < every.index(str(below))
    assert "Total: 2 records" in every
    assert str(below) not in shallow
    assert "Total: 1 record:" in shallow


def test_a_folder_with_no_record_exits_two(capsys: CaptureFixture[str], tmp_path: Path) -> None:
    """A mistyped path must not pass in silence.

    **Test steps:**

    * run the command on an empty folder
    * check the exit status is 2 and the folder is named
    """
    (tmp_path / "empty").mkdir()

    status, output = run(capsys, tmp_path / "empty")

    assert status == 2
    assert "empty: no .checksum file found" in output


def test_a_path_that_is_no_record_exits_two(capsys: CaptureFixture[str], tmp_path: Path) -> None:
    """A missing path, a file that is no ``.checksum`` and a record that is not JSON are all unreadable.

    **Test steps:**

    * run the command on a path that does not exist, a text file and a ``.checksum`` holding no JSON
    * check each exits 2 with its own reason
    """
    text = tmp_path / "notes.txt"
    text.write_text("x", encoding="utf-8")
    broken = tmp_path / "broken.checksum"
    broken.write_text("not json", encoding="utf-8")

    missing_status, missing = run(capsys, tmp_path / "nowhere")
    text_status, not_a_record = run(capsys, text)
    broken_status, malformed = run(capsys, broken)

    assert (missing_status, text_status, broken_status) == (2, 2, 2)
    assert "not found" in missing
    assert "not a .checksum file" in not_a_record
    assert "broken.checksum" in malformed


def test_a_run_changes_no_byte_and_no_time(capsys: CaptureFixture[str], tmp_path: Path) -> None:
    """Reading only, whatever the findings: the files, the record and the folder are as they were.

    **Test steps:**

    * make a record with a changed file, an unlisted one and a missing one
    * run the command with ``--show-without-checksum``
    * check every file's bytes and modification time, and the list of files, are unchanged
    """
    record = make_record(tmp_path / "asset", {"a.bin": b"alpha", "b.bin": b"bravo", "c.bin": b"charlie"})
    (record.parent / "a.bin").write_bytes(b"changed")
    (record.parent / "b.bin").unlink()
    (record.parent / "new.bin").write_bytes(b"new")
    before = snapshot(tmp_path / "asset")

    status, _ = run(capsys, record, "--show-without-checksum")

    assert status == 1
    assert snapshot(tmp_path / "asset") == before


def test_quiet_leaves_out_a_record_with_nothing_found_and_verbose_names_every_file(
    capsys: CaptureFixture[str], tmp_path: Path
) -> None:
    """The two volumes.

    **Test steps:**

    * make a record that matches and one with a changed file, under one folder
    * run with ``--quiet``: only the changed record's line and the total are shown
    * run with ``--verbose`` on the matching one: its files are named
    """
    good = make_record(tmp_path / "root" / "good", {"a.bin": b"alpha"})
    bad = make_record(tmp_path / "root" / "bad", {"b.bin": b"bravo"})
    (bad.parent / "b.bin").write_bytes(b"changed")

    _, quiet = run(capsys, tmp_path / "root", "--quiet")
    _, verbose = run(capsys, good, "--verbose")

    assert str(bad) in quiet
    assert str(good) not in quiet
    assert "Total: 2 records" in quiet
    assert "matched: a.bin" in verbose


def test_the_progress_line_is_drawn_on_a_terminal_only(
    mocker: MockerFixture, capsys: CaptureFixture[str], record: Path
) -> None:
    """A piped run prints no rewritten line; a terminal gets one that is erased before the result.

    **Test steps:**

    * run the command piped: the output holds no carriage return
    * run it with the output reporting a terminal: the output holds one
    """
    _, piped = run(capsys, record)
    mocker.patch.object(verify_checksums.sys.stdout, "isatty", return_value=True, create=True)
    mocker.patch("tools.verify_checksums.shutil.get_terminal_size", return_value=mocker.Mock(columns=60))
    _, terminal = run(capsys, record)

    assert "\r" not in piped
    assert "\r" in terminal


@mark.parametrize(
    ("size", "text"),
    [(5, "5 B"), (2048, "2.0 KiB"), (3 * 1024**3, "3.0 GiB"), (5 * 1024**4, "5.0 TiB")],
)
def test_a_byte_count_is_read_in_its_largest_unit(size: int, text: str) -> None:
    """Progress is for a person.

    **Test steps:**

    * format a byte count in each unit
    * check the text
    """
    assert human_bytes(size) == text


def test_a_record_reached_twice_is_verified_once(capsys: CaptureFixture[str], record: Path) -> None:
    """A folder and a file inside it name one record.

    **Test steps:**

    * run the command on a record's file and on its folder
    * check one record was verified
    """
    _, output = run(capsys, record, record.parent)

    assert "Total: 1 record:" in output


def test_an_unreadable_file_and_a_file_without_a_checksum_reach_the_total(
    capsys: CaptureFixture[str], record: Path
) -> None:
    """Both are counted in the last line.

    **Test steps:**

    * replace a listed file with a directory and add an unlisted file
    * run the command with ``--show-without-checksum``
    * check the total counts one unreadable and one without a checksum, and the exit status is 1
    """
    (record.parent / "a.bin").unlink()
    (record.parent / "a.bin").mkdir()
    (record.parent / "extra.bin").write_bytes(b"new")

    status, output = run(capsys, record, "--show-without-checksum")

    assert status == 1
    assert "unreadable: a.bin" in output
    assert "1 unreadable, 1 without a checksum" in output.splitlines()[-1]


def test_a_folder_that_will_not_list_is_unreadable(
    mocker: MockerFixture, capsys: CaptureFixture[str], tmp_path: Path
) -> None:
    """The walk's own failure is named, not passed over in silence.

    **Test steps:**

    * make the walk of a folder report a permission failure
    * run the command on the folder
    * check the exit status is 2 and the folder is named
    """
    (tmp_path / "root").mkdir()

    def walk(_: Path, onerror: Callable[[OSError], None]) -> Iterator[tuple[str, list[str], list[str]]]:
        """A walk that fails at once.

        :param _: the folder.
        :param onerror: told of the failure.
        :returns: nothing.
        """
        onerror(OSError(13, "Permission denied", str(tmp_path / "root")))
        return iter(())

    mocker.patch("tools.verify_checksums.os.walk", side_effect=walk)

    status, output = run(capsys, tmp_path / "root")

    assert status == 2
    assert "Permission denied" in output


def test_ctrl_c_prints_what_was_verified_so_far(
    mocker: MockerFixture, capsys: CaptureFixture[str], record: Path
) -> None:
    """The run stops and says how far it got.

    **Test steps:**

    * make the check raise a keyboard interrupt
    * run the command
    * check the exit status is 130 and the output says it was interrupted
    """
    mocker.patch("tools.verify_checksums.inspect_checksums", side_effect=KeyboardInterrupt)

    status, output = run(capsys, record)

    assert status == 130
    assert "Interrupted. Total: 0 records" in output


def test_no_checksum_draws_no_progress_line_on_a_terminal(
    mocker: MockerFixture, capsys: CaptureFixture[str], record: Path
) -> None:
    """Nothing is hashed, so there is no progress to show.

    **Test steps:**

    * make the output report a terminal
    * run the command with ``--no-checksum``
    * check the output holds no carriage return
    """
    mocker.patch.object(verify_checksums.sys.stdout, "isatty", return_value=True, create=True)
    mocker.patch("tools.verify_checksums.shutil.get_terminal_size", return_value=mocker.Mock(columns=60))

    _, output = run(capsys, record, "--no-checksum")

    assert "\r" not in output


def test_a_piped_run_names_a_file_the_code_page_cannot_spell(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """A piped stream on Windows is the ANSI code page's; the run writes UTF-8 instead of failing on a name.

    **Test steps:**

    * make a record whose changed file has a name outside cp1252
    * run the command with the output a cp1252 pipe
    * check the exit status is 1 and the output, read as UTF-8, names the file
    """
    name = "日本語.bin"
    record = make_record(tmp_path / "asset", {name: b"alpha"})
    (record.parent / name).write_bytes(b"changed")
    piped = io.BytesIO()
    monkeypatch.setattr(verify_checksums.sys, "stdout", io.TextIOWrapper(piped, encoding="cp1252"))

    status = main([str(record)])
    verify_checksums.sys.stdout.flush()

    assert status == 1
    assert f"mismatched: {name}" in piped.getvalue().decode("utf-8")


def test_a_folder_holding_two_records_verifies_each_over_its_own_files(
    capsys: CaptureFixture[str], record: Path
) -> None:
    """A folder record and a file-scoped one beside it are two records, each with its own ``.checksum``.

    **Test steps:**

    * add a file-scoped record with one file beside a folder record, and checksum it
    * add a second file of its stem, unlisted
    * run the command on the folder with ``--show-without-checksum``
    * check both records are verified, in the order of their paths, and the unlisted file is the file-scoped one's
    """
    clip = record.parent / "clip.rehu"
    document = RehuDocument.new(clip, username="tester")
    document.title = "A clip"
    document.save()
    (record.parent / "clip.mp4").write_bytes(b"video")
    generate_checksums(clip)
    (record.parent / "clip.srt").write_bytes(b"subtitles")

    status, output = run(capsys, record.parent, "--show-without-checksum")

    lines = output.splitlines()
    assert status == 1
    assert lines[1] == f"{clip.with_suffix('.checksum')}: 1 matched, 1 without a checksum"
    assert lines[2] == "  no checksum: clip.srt"
    assert lines[3] == f"{record}: 2 matched"
    assert "Total: 2 records" in lines[-1]
