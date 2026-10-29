"""Tests for the rules that let an external FFmpeg's libraries stand in for Qt's: which files, which major, which
order (#580)."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Final
from unittest.mock import Mock, call

from pytest import mark, param, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    LibrariesUnusableError,
    ToolStatus,
    bundled_library_names,
    free_libraries,
    library_files,
    load_libraries,
    probe,
)
from rehuco_core.external_tools import ffmpeg_libraries

MODULE: Final = "rehuco_core.external_tools.ffmpeg_libraries"

QT_611: Final = ("avcodec-61.dll", "avformat-61.dll", "avutil-59.dll", "swresample-5.dll", "swscale-8.dll")
"""The libraries PySide6 6.11 bundles."""

QT_612: Final = ("avcodec-63.dll", "avformat-63.dll", "avutil-61.dll", "swresample-7.dll", "swscale-10.dll")
"""The libraries PySide6 6.12 bundles."""

LOAD_ORDER_611: Final = ("avutil-59.dll", "swresample-5.dll", "swscale-8.dll", "avcodec-61.dll", "avformat-61.dll")
"""``QT_611`` in the order they must be loaded."""


def make_files(folder: Path, names: tuple[str, ...]) -> Path:
    """Put empty files in a folder.

    :param folder: the folder, created when absent.
    :param names: the file names.
    :returns: the folder.
    """
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"")
    return folder


@mark.parametrize("bundled", [param(QT_611, id="6.11"), param(QT_612, id="6.12")])
def test_the_bundled_names_are_read_from_qts_own_folder(tmp_path: Path, bundled: tuple[str, ...]) -> None:
    """No version is written into the code: whatever major PySide6 carries is what is asked for.

    **Test steps:**

    * make a PySide6 folder with one set of libraries and files that are not FFmpeg's
    * read the names
    * verify each library maps to the file the folder holds
    """
    qt_folder = make_files(tmp_path / "PySide6", (*bundled, "Qt6Core.dll", "opengl32sw.dll"))

    names = bundled_library_names(qt_folder)

    assert sorted(names.values()) == sorted(bundled)
    assert set(names) == {"avutil", "swresample", "swscale", "avcodec", "avformat"}


def test_a_qt_with_no_ffmpeg_names_nothing(tmp_path: Path) -> None:
    """**Test steps:**

    * read the names of a folder holding none
    * verify there are none
    """
    assert not bundled_library_names(make_files(tmp_path / "PySide6", ("Qt6Core.dll",)))


def test_a_build_of_the_right_major_gives_its_files_in_load_order(tmp_path: Path) -> None:
    """The order is each library after those it depends on, whatever order the folder lists them in.

    **Test steps:**

    * make a build holding the five libraries and a program
    * ask for its files
    * verify the full paths, ``avutil`` first and ``avformat`` last
    """
    names = bundled_library_names(make_files(tmp_path / "qt", QT_611))
    build = make_files(tmp_path / "build", (*QT_611, "ffmpeg.exe"))

    assert library_files(build, names) == [build / name for name in LOAD_ORDER_611]


@mark.parametrize(
    ("present", "status", "words"),
    [
        param(("ffmpeg.exe", "ffprobe.exe"), ToolStatus.NO_LIBRARIES, "static", id="static"),
        param(QT_612, ToolStatus.WRONG_MAJOR, "avcodec-63.dll", id="another-major"),
        param(QT_611[:3], ToolStatus.INCOMPLETE, "swscale-8.dll", id="a-library-missing"),
    ],
)
def test_a_build_that_cannot_stand_in_says_which_way(
    tmp_path: Path, present: tuple[str, ...], status: ToolStatus, words: str
) -> None:
    """A static build, another major and a partial set are each their own status, with a reason that names the files.

    **Test steps:**

    * make a build that is static, of another major, or short of libraries
    * ask for its files
    * verify the refusal carries the status and a reason naming what is wrong
    """
    names = bundled_library_names(make_files(tmp_path / "qt", QT_611))

    with raises(LibrariesUnusableError) as caught:
        library_files(make_files(tmp_path / "build", present), names)

    assert caught.value.status is status
    assert words in caught.value.reason
    assert not status.is_usable


def test_another_major_names_the_files_wanted_too(tmp_path: Path) -> None:
    """**Test steps:**

    * make a build of the other major
    * verify the reason says what this app needs
    """
    names = bundled_library_names(make_files(tmp_path / "qt", QT_611))

    with raises(LibrariesUnusableError) as caught:
        library_files(make_files(tmp_path / "build", QT_612), names)

    assert "avcodec-61.dll" in caught.value.reason


def test_a_qt_bundling_nothing_refuses_every_build(tmp_path: Path) -> None:
    """**Test steps:**

    * ask for the files of a build against no bundled names
    * verify it is refused as not runnable here
    """
    with raises(LibrariesUnusableError) as caught:
        library_files(make_files(tmp_path, QT_611), {})

    assert caught.value.status is ToolStatus.NOT_RUNNABLE


def test_libraries_are_loaded_by_full_path_in_the_order_given(mocker: MockerFixture, tmp_path: Path) -> None:
    """**Test steps:**

    * load three files with the loader mocked
    * verify each was loaded by its full path, in order, and the loaded ones come back in order
    """
    loader = mocker.patch(f"{MODULE}.ctypes.CDLL", side_effect=lambda path: Mock(path=path))
    files = [tmp_path / "avutil-59.dll", tmp_path / "swresample-5.dll", tmp_path / "swscale-8.dll"]

    loaded = load_libraries(files)

    assert loader.call_args_list == [call(str(file)) for file in files]
    assert [library.path for library in loaded] == [str(file) for file in files]


def test_a_library_that_fails_frees_those_loaded_before_it(mocker: MockerFixture, tmp_path: Path) -> None:
    """None stays loaded from a build that cannot be used, and they leave in the reverse of the order they came.

    **Test steps:**

    * load three files, the third failing
    * verify the refusal, and that the first two were freed last first
    """
    first, second = Mock(_handle=11), Mock(_handle=22)
    mocker.patch(f"{MODULE}.ctypes.CDLL", side_effect=[first, second, OSError("no")])
    freed = Mock()
    mocker.patch(f"{MODULE}.sys", SimpleNamespace(platform="win32"))
    mocker.patch.dict(sys.modules, {"_ctypes": SimpleNamespace(FreeLibrary=freed)})

    with raises(LibrariesUnusableError) as caught:
        load_libraries([tmp_path / "a.dll", tmp_path / "b.dll", tmp_path / "c.dll"])

    assert caught.value.status is ToolStatus.NOT_RUNNABLE
    assert "c.dll" in caught.value.reason
    assert freed.call_args_list == [call(22), call(11)]


def test_a_library_built_for_another_processor_is_its_own_status(mocker: MockerFixture, tmp_path: Path) -> None:
    """Windows reports it as *bad image format*, error 193, which is not a version failure.

    **Test steps:**

    * load a file whose load fails with that error
    * verify the status is the wrong architecture
    """
    error = OSError("bad image")
    error.winerror = 193  # type: ignore[attr-defined]
    mocker.patch(f"{MODULE}.ctypes.CDLL", side_effect=error)

    with raises(LibrariesUnusableError) as caught:
        load_libraries([tmp_path / "avutil-59.dll"])

    assert caught.value.status is ToolStatus.WRONG_ARCHITECTURE


def test_nothing_is_freed_off_windows(mocker: MockerFixture) -> None:
    """**Test steps:**

    * free a library on a platform that is not Windows
    * verify nothing was asked of ``_ctypes``
    """
    mocker.patch(f"{MODULE}.sys", SimpleNamespace(platform="linux"))
    freed = Mock()
    mocker.patch.dict(sys.modules, {"_ctypes": SimpleNamespace(FreeLibrary=freed)})

    free_libraries([Mock(_handle=1)])

    freed.assert_not_called()


@mark.parametrize(
    ("reported", "version"),
    [
        param(b"n7.1.5-12-g1fdbca85aa-20260731", (7, 1, 5), id="release"),
        param(b"7.1.1-essentials_build-www.gyan.dev", (7, 1, 1), id="release-with-suffix"),
        param(b"N-118000-g1a2b3c", None, id="git-build"),
        param(None, None, id="nothing"),
    ],
)
def test_the_version_is_asked_of_the_loaded_avutil(reported: bytes | None, version: tuple[int, ...] | None) -> None:
    """A release reports its numbers and a git build a commit.

    **Test steps:**

    * ask a loaded ``avutil`` for its version
    * verify the numbers, or none for a build that reports a commit
    """
    avutil = Mock()
    avutil.av_version_info.return_value = reported

    assert ffmpeg_libraries.read_loaded_version([avutil]) == version


def test_the_probe_writes_what_the_build_is(mocker: MockerFixture, tmp_path: Path) -> None:
    """The child's whole answer is a file: the packaged app prints nowhere.

    **Test steps:**

    * probe a build of the right major with the loader mocked
    * verify the answer file says usable with the build's version
    """
    avutil = Mock()
    avutil.av_version_info.return_value = b"n7.1.5-12-gabc"
    mocker.patch(f"{MODULE}.ctypes.CDLL", return_value=avutil)
    qt_folder = make_files(tmp_path / "qt", QT_611)
    output = tmp_path / "answer.json"

    code = probe(make_files(tmp_path / "build", QT_611), qt_folder, output)

    assert code == 0
    assert json.loads(output.read_text(encoding="utf-8")) == {"status": "usable", "version": [7, 1, 5], "reason": ""}


def test_a_probed_build_with_no_readable_version_is_untested(mocker: MockerFixture, tmp_path: Path) -> None:
    """A git build loads, so it can be used, and it is not refused for printing no number.

    **Test steps:**

    * probe a build whose avutil reports a commit
    * verify the answer is untested with no version
    """
    avutil = Mock()
    avutil.av_version_info.return_value = b"N-118000-gabc"
    mocker.patch(f"{MODULE}.ctypes.CDLL", return_value=avutil)
    output = tmp_path / "answer.json"

    probe(make_files(tmp_path / "build", QT_611), make_files(tmp_path / "qt", QT_611), output)

    answer = json.loads(output.read_text(encoding="utf-8"))
    assert answer["status"] == "untested"
    assert answer["version"] == []


def test_a_probed_build_that_cannot_stand_in_writes_why(tmp_path: Path) -> None:
    """**Test steps:**

    * probe a static build
    * verify the exit is still 0 and the answer carries the status and reason
    """
    output = tmp_path / "answer.json"

    code = probe(make_files(tmp_path / "build", ("ffmpeg.exe",)), make_files(tmp_path / "qt", QT_611), output)

    answer = json.loads(output.read_text(encoding="utf-8"))
    assert code == 0
    assert answer["status"] == ToolStatus.NO_LIBRARIES.value
    assert "static" in answer["reason"]
