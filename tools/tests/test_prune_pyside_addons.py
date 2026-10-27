"""Tests for the pruning of the PySide6-Addons wheel in a built bundle down to what in-app playback needs (#317)."""

from pathlib import Path
from typing import Final

from pytest import CaptureFixture, mark, param, raises
from pytest_mock import MockerFixture

from tools import prune_pyside_addons
from tools.prune_pyside_addons import KEEP_PATTERNS, find_record, plan_prune, platform_of, prune, read_record

# region Fixtures / helpers

ADDONS_INFO: Final = "pyside6_addons-6.11.1.dist-info"
ESSENTIALS_INFO: Final = "pyside6_essentials-6.11.1.dist-info"

SHARED: Final = (
    "PySide6/__init__.py",
    "PySide6/_config.py",
    "PySide6/py.typed",
    "PySide6/QtCore.pyi",
    "PySide6/QtMultimedia.pyi",
)
"""What both wheels install -- 64 files in the real ones, which Essentials needs."""

WINDOWS_KEPT: Final = (
    "PySide6/QtMultimedia.pyd",
    "PySide6/QtMultimediaWidgets.pyd",
    "PySide6/Qt6Multimedia.dll",
    "PySide6/Qt6MultimediaWidgets.dll",
    "PySide6/plugins/multimedia/ffmpegmediaplugin.dll",
    "PySide6/avcodec-61.dll",
    "PySide6/avformat-61.dll",
    "PySide6/avutil-59.dll",
    "PySide6/swresample-5.dll",
    "PySide6/swscale-8.dll",
)
"""What playback needs of the Windows wheel of PySide6 6.11.1."""

WINDOWS_REMOVED: Final = (
    "PySide6/QtWebEngineCore.pyd",
    "PySide6/Qt6WebEngineCore.dll",
    "PySide6/Qt6MultimediaQuick.dll",
    "PySide6/QtMultimediaQuick.pyd",
    "PySide6/plugins/multimedia/windowsmediaplugin.dll",
    "PySide6/qml/QtMultimedia/plugins.qmltypes",
    "PySide6/translations/qtmultimedia_de.qm",
    "PySide6/Qt3DCore.pyd",
)
"""What it does not: other modules, the Windows backend and everything that is only about Qt Quick."""


FFMPEG_MAJORS: Final = {"avcodec": 63, "avformat": 63, "avutil": 61, "swresample": 7, "swscale": 10}
"""PySide6 6.12's FFmpeg libraries and their majors."""


def write_wheel(site_packages: Path, dist_info: str, files: tuple[str, ...]) -> None:
    """Install a wheel as far as pruning can tell: its files, and a ``RECORD`` naming them and its own metadata.

    :param site_packages: where wheels are installed.
    :param dist_info: the wheel's ``.dist-info`` folder.
    :param files: the files it installs, relative to ``site_packages``.
    """
    for name in (*files, f"{dist_info}/METADATA"):
        path = site_packages / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * 10)
    lines = [f"{name},sha256=abc,10" for name in (*files, f"{dist_info}/METADATA")]
    (site_packages / dist_info / "RECORD").write_text("\n".join([*lines, f"{dist_info}/RECORD,,"]), encoding="utf-8")


def install(site_packages: Path, addons: tuple[str, ...], essentials: tuple[str, ...] = SHARED) -> None:
    """Install both wheels, as pip does into a bundle.

    :param site_packages: where wheels are installed.
    :param addons: what the Addons wheel installs; the shared files are added.
    :param essentials: what the Essentials wheel installs.
    """
    write_wheel(site_packages, ESSENTIALS_INFO, essentials)
    write_wheel(site_packages, ADDONS_INFO, (*addons, *SHARED))


def existing(site_packages: Path, names: tuple[str, ...]) -> list[str]:
    """Which of some files are still installed.

    :param site_packages: where wheels are installed.
    :param names: the files.
    :returns: those that exist.
    """
    return [name for name in names if (site_packages / name).exists()]


# endregion

# region The plan


def test_the_plan_keeps_the_keep_list_and_what_essentials_owns_and_removes_the_rest() -> None:
    """**Test steps:**

    * plan a prune of a wheel holding kept, shared, removable and metadata files
    * verify the keep list, the shared files and the wheel's own metadata stay, and the rest goes
    """
    addons = (*WINDOWS_KEPT, *WINDOWS_REMOVED, *SHARED, f"{ADDONS_INFO}/METADATA")

    plan = plan_prune(addons, SHARED, KEEP_PATTERNS["windows"], ADDONS_INFO)

    assert set(plan.keep) == {*WINDOWS_KEPT, *SHARED, f"{ADDONS_INFO}/METADATA"}
    assert set(plan.remove) == set(WINDOWS_REMOVED)


def test_a_file_both_wheels_install_is_never_removed() -> None:
    """Removing what Essentials owns would break the app: ``PySide6/__init__.py`` is in both wheels.

    **Test steps:**

    * plan a prune of a wheel that holds only shared files besides the keep list
    * verify none of the shared files is removed
    """
    plan = plan_prune((*WINDOWS_KEPT, *SHARED), SHARED, KEEP_PATTERNS["windows"], ADDONS_INFO)

    assert plan.remove == ()


def test_a_module_a_later_release_adds_is_removed_without_being_listed() -> None:
    """The point of a keep list over a remove list.

    **Test steps:**

    * plan a prune of a wheel holding a module nobody has heard of
    * verify it is removed
    """
    plan = plan_prune((*WINDOWS_KEPT, "PySide6/QtBrandNew.pyd"), SHARED, KEEP_PATTERNS["windows"], ADDONS_INFO)

    assert plan.remove == ("PySide6/QtBrandNew.pyd",)


@mark.parametrize(
    "ffmpeg",
    [
        param(("avcodec-61", "avformat-61", "avutil-59", "swresample-5", "swscale-8"), id="PySide6 6.11"),
        param(("avcodec-63", "avformat-63", "avutil-61", "swresample-7", "swscale-10"), id="PySide6 6.12"),
    ],
)
def test_the_ffmpeg_libraries_are_kept_whatever_their_major_version(ffmpeg: tuple[str, ...]) -> None:
    """The majors move with PySide6, so the keep list names none of them.

    **Test steps:**

    * plan a prune of a wheel whose FFmpeg libraries carry one release's majors
    * verify all five are kept
    """
    libraries = tuple(f"PySide6/{name}.dll" for name in ffmpeg)
    base = tuple(path for path in WINDOWS_KEPT if "/av" not in path and "/sw" not in path)

    plan = plan_prune((*base, *libraries), SHARED, KEEP_PATTERNS["windows"], ADDONS_INFO)

    assert plan.remove == ()
    assert set(libraries) <= set(plan.keep)


def test_a_pattern_that_matches_nothing_is_an_error() -> None:
    """A release that moved a file playback needs would otherwise build a bundle that cannot play.

    **Test steps:**

    * plan a prune of a wheel without the FFmpeg plugin
    * verify it is refused, naming the pattern
    """
    addons = tuple(path for path in WINDOWS_KEPT if "ffmpegmediaplugin" not in path)

    with raises(LookupError, match="ffmpegmediaplugin"):
        plan_prune(addons, SHARED, KEEP_PATTERNS["windows"], ADDONS_INFO)


@mark.parametrize("platform", sorted(KEEP_PATTERNS))
def test_every_platform_keeps_the_modules_the_backend_and_ffmpeg(platform: str) -> None:
    """**Test steps:**

    * read the keep list of a platform
    * verify it names both Python modules, the multimedia libraries, the FFmpeg plugin and the five FFmpeg libraries
    """
    patterns = " ".join(KEEP_PATTERNS[platform])

    for needed in ("QtMultimedia", "QtMultimediaWidgets", "ffmpegmediaplugin"):
        assert needed in patterns
    for library in ("avcodec", "avformat", "avutil", "swresample", "swscale"):
        assert library in patterns


MACOS_WHEEL: Final = {
    "kept": (
        "PySide6/QtMultimedia.abi3.so",
        "PySide6/QtMultimediaWidgets.abi3.so",
        "PySide6/Qt/lib/QtMultimedia.framework/Versions/A/QtMultimedia",
        "PySide6/Qt/lib/QtMultimedia.framework/Resources/Info.plist",
        "PySide6/Qt/lib/QtMultimediaWidgets.framework/Versions/A/QtMultimediaWidgets",
        "PySide6/Qt/plugins/multimedia/libffmpegmediaplugin.dylib",
        *(f"PySide6/Qt/lib/lib{library}.{major}.dylib" for library, major in FFMPEG_MAJORS.items()),
    ),
    "removed": (
        "PySide6/Qt/plugins/multimedia/libdarwinmediaplugin.dylib",
        "PySide6/Qt/lib/QtWebEngineCore.framework/Versions/A/QtWebEngineCore",
        *(f"PySide6/Qt/lib/lib{library}.{major}.1.101.dylib" for library, major in FFMPEG_MAJORS.items()),
    ),
}
"""A macOS wheel as far as the keep list can tell: the frameworks, the FFmpeg backend alone, and each FFmpeg library
under its SONAME and again under its full version."""

LINUX_WHEEL: Final = {
    "kept": (
        "PySide6/QtMultimedia.abi3.so",
        "PySide6/QtMultimediaWidgets.abi3.so",
        "PySide6/Qt/lib/libQt6Multimedia.so.6",
        "PySide6/Qt/lib/libQt6MultimediaWidgets.so.6",
        "PySide6/Qt/lib/libQt6FFmpegStub-ssl.so.3",
        "PySide6/Qt/lib/libQt6FFmpegStub-va-drm.so.2",
        "PySide6/Qt/lib/libQt6FFmpegStub-va-x11.so.2",
        "PySide6/Qt/plugins/multimedia/libffmpegmediaplugin.so",
        *(f"PySide6/Qt/lib/lib{library}.so.{major}" for library, major in FFMPEG_MAJORS.items()),
    ),
    "removed": (
        "PySide6/Qt/lib/libQt6MultimediaQuick.so.6",
        "PySide6/Qt/lib/libQt6WebEngineCore.so.6",
        *(f"PySide6/Qt/lib/lib{library}.so" for library in FFMPEG_MAJORS),
        *(f"PySide6/Qt/lib/lib{library}.so.{major}.1.101" for library, major in FFMPEG_MAJORS.items()),
    ),
}
"""A Linux wheel the same way: each FFmpeg library three times over, flattened out of its symlinks."""


@mark.parametrize(
    ("platform", "wheel"),
    [param("macos", MACOS_WHEEL, id="macOS"), param("linux", LINUX_WHEEL, id="Linux")],
)
def test_an_ffmpeg_library_is_kept_under_its_soname_alone(platform: str, wheel: dict[str, tuple[str, ...]]) -> None:
    """The wheels hold each FFmpeg library two or three times, at 15 MB for the biggest, and the backend asks for one
    name; the rest are what would make the keep list three times the 20 MB the spike measured.

    **Test steps:**

    * plan a prune of a wheel holding each FFmpeg library under every name
    * verify the modules, the frameworks or libraries, the FFmpeg plugin and each SONAME are kept
    * verify the other names, the other backend and the other modules are removed
    """
    plan = plan_prune((*wheel["kept"], *wheel["removed"]), SHARED, KEEP_PATTERNS[platform], ADDONS_INFO)

    assert set(plan.keep) == set(wheel["kept"])
    assert set(plan.remove) == set(wheel["removed"])


@mark.parametrize(
    ("sys_platform", "expected"),
    [("win32", "windows"), ("darwin", "macos"), ("linux", "linux"), ("freebsd14", "linux")],
)
def test_the_keep_list_follows_the_python_platform(sys_platform: str, expected: str) -> None:
    """**Test steps:**

    * ask for the keep list of several ``sys.platform`` values
    * verify each answers its own, and anything but Windows and macOS is Linux
    """
    assert platform_of(sys_platform) == expected


# endregion

# region The bundle


def test_pruning_removes_what_the_plan_removes_and_leaves_the_rest(tmp_path: Path) -> None:
    """**Test steps:**

    * install an Essentials and an Addons wheel into a folder
    * prune it for Windows
    * verify the kept and shared files and the metadata remain, the rest is gone, and the counts say so
    """
    install(tmp_path, (*WINDOWS_KEPT, *WINDOWS_REMOVED))

    removed, removed_bytes, kept, kept_bytes = prune(tmp_path, "windows")

    assert existing(tmp_path, WINDOWS_KEPT) == list(WINDOWS_KEPT)
    assert existing(tmp_path, SHARED) == list(SHARED)
    assert existing(tmp_path, WINDOWS_REMOVED) == []
    assert (tmp_path / ADDONS_INFO / "METADATA").exists()
    assert (removed, removed_bytes) == (len(WINDOWS_REMOVED), 10 * len(WINDOWS_REMOVED))
    # the kept files, the wheel's METADATA, and its RECORD, which is the one file of another size
    files = len(WINDOWS_KEPT) + len(SHARED) + 1
    assert (kept, kept_bytes) == (files + 1, 10 * files + (tmp_path / ADDONS_INFO / "RECORD").stat().st_size)


def test_pruning_removes_the_folders_it_empties_and_only_those(tmp_path: Path) -> None:
    """**Test steps:**

    * install wheels whose removable files fill one folder, with a kept file in the one beside it
    * prune
    * verify the emptied folders are gone, a folder holding a kept file is not, and neither is the install folder
    """
    install(tmp_path, (*WINDOWS_KEPT, *WINDOWS_REMOVED))

    prune(tmp_path, "windows")

    assert not (tmp_path / "PySide6" / "qml").exists()
    assert not (tmp_path / "PySide6" / "translations").exists()
    assert (tmp_path / "PySide6" / "plugins" / "multimedia").is_dir()
    assert tmp_path.is_dir()


def test_a_file_the_bundle_does_not_hold_is_passed_over(tmp_path: Path) -> None:
    """A ``RECORD`` names files a bundle may have dropped already, such as ``.pyc`` files.

    **Test steps:**

    * install wheels, delete one removable file by hand, and prune
    * verify it neither raised nor was counted
    """
    install(tmp_path, (*WINDOWS_KEPT, *WINDOWS_REMOVED))
    (tmp_path / WINDOWS_REMOVED[0]).unlink()

    removed, _removed_bytes, _kept, _kept_bytes = prune(tmp_path, "windows")

    assert removed == len(WINDOWS_REMOVED) - 1


def test_pruning_twice_changes_nothing_the_second_time(tmp_path: Path) -> None:
    """**Test steps:**

    * prune a bundle twice
    * verify the second removed nothing and kept what the first kept
    """
    install(tmp_path, (*WINDOWS_KEPT, *WINDOWS_REMOVED))
    first = prune(tmp_path, "windows")

    second = prune(tmp_path, "windows")

    assert second[0] == 0
    assert second[2:] == first[2:]


def test_a_bundle_without_the_addons_wheel_is_refused(tmp_path: Path) -> None:
    """**Test steps:**

    * install only the Essentials wheel
    * verify pruning is refused, naming the wheel it did not find
    """
    write_wheel(tmp_path, ESSENTIALS_INFO, SHARED)

    with raises(FileNotFoundError, match="pyside6_addons"):
        prune(tmp_path, "windows")


def test_a_bundle_without_the_essentials_wheel_is_refused(tmp_path: Path) -> None:
    """Without it nothing says which files are shared, and pruning could remove what the app imports.

    **Test steps:**

    * install only the Addons wheel
    * verify pruning is refused, naming the wheel it did not find, and nothing was removed
    """
    write_wheel(tmp_path, ADDONS_INFO, (*WINDOWS_KEPT, *WINDOWS_REMOVED))

    with raises(FileNotFoundError, match="pyside6_essentials"):
        prune(tmp_path, "windows")

    assert existing(tmp_path, WINDOWS_REMOVED) == list(WINDOWS_REMOVED)


def test_two_versions_of_a_wheel_are_refused(tmp_path: Path) -> None:
    """**Test steps:**

    * install Addons wheels of two versions
    * verify pruning is refused rather than guessing which is the bundle's
    """
    install(tmp_path, WINDOWS_KEPT)
    write_wheel(tmp_path, "pyside6_addons-6.12.0.dist-info", WINDOWS_KEPT)

    with raises(FileNotFoundError, match="found 2"):
        find_record(tmp_path, "pyside6_addons")


def test_a_record_is_read_as_the_paths_it_names(tmp_path: Path) -> None:
    """A path with a comma is quoted in a ``RECORD``.

    **Test steps:**

    * read a ``RECORD`` with a plain row, a quoted row with a comma, and a blank line
    * verify the paths come back whole
    """
    record = tmp_path / "RECORD"
    record.write_text('a/b.py,sha256=x,1\n"c/d, e.py",sha256=y,2\n\n', encoding="utf-8")

    assert read_record(record) == ["a/b.py", "c/d, e.py"]


# endregion

# region The command line


def test_the_command_prints_what_it_pruned(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """**Test steps:**

    * run the command on an installed bundle for Windows
    * verify it exited 0 and said how many files went and stayed
    """
    install(tmp_path, (*WINDOWS_KEPT, *WINDOWS_REMOVED))

    status = prune_pyside_addons.main([str(tmp_path), "--platform", "windows"])

    assert status == 0
    assert f"removed {len(WINDOWS_REMOVED)} files" in capsys.readouterr().out


def test_the_command_fails_with_a_reason_when_it_cannot_prune(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """A build that pruned nothing must stop, not ship 440 MB.

    **Test steps:**

    * run the command on a folder with no wheels
    * verify it exited 1 and said why on stderr
    """
    status = prune_pyside_addons.main([str(tmp_path), "--platform", "windows"])

    assert status == 1
    assert "Not pruned" in capsys.readouterr().err


def test_the_command_defaults_to_the_keep_list_of_the_platform_it_runs_on(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * run the command with no platform on a pretend macOS, with the pruning itself patched
    * verify it pruned the folder it was given with the macOS keep list
    """
    mocker.patch.object(prune_pyside_addons.sys, "platform", "darwin")
    pruned = mocker.patch.object(prune_pyside_addons, "prune", return_value=(0, 0, 0, 0))

    assert prune_pyside_addons.main([str(tmp_path)]) == 0

    pruned.assert_called_once_with(tmp_path, "macos")


# endregion
