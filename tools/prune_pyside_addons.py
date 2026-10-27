"""Cut the PySide6-Addons wheel in a built bundle down to the files in-app playback needs ([[plugins#in-app-player]],
[[packaging-deployment#qt-multimedia]], #317).

The agent plays video through Qt Multimedia, which lives in ``PySide6-Addons``: a wheel of 100 MB to 440 MB, nearly all
of it modules nothing here imports. Playback needs about 20 MB of it, and the Briefcase build keeps just that.

**A keep list, never a remove list.** What goes is every file the Addons wheel's ``RECORD`` names, bar the keep list and
bar what ``PySide6-Essentials`` owns too -- the two wheels share 64 files, ``PySide6/__init__.py`` among them, which
Essentials needs. So a module a later Addons release adds is removed without anyone listing it, which Briefcase's own
``cleanup_paths`` could not do: it can only name what to remove. The keep list is regular expressions, because the
FFmpeg libraries carry their major version in their names and it moves with PySide6 (``avcodec-61`` in 6.11,
``avcodec-63`` in 6.12).

A pattern that matches nothing is an error, not a shrug: it means a release moved or renamed a file playback needs, and
a bundle without it would build, install and then fail to play.

Run it on the ``app_packages`` folder of a bundle after ``briefcase build`` and before ``briefcase package``.
"""

import argparse
import csv
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

FFMPEG_LIBRARIES: Final = ("avcodec", "avformat", "avutil", "swresample", "swscale")
"""The five FFmpeg libraries Qt's FFmpeg backend binds."""

MODULES: Final = (r"PySide6/QtMultimedia\..*", r"PySide6/QtMultimediaWidgets\..*")
"""The two Python modules, in whatever form the platform builds them (``.pyd``, ``.abi3.so``, ``.pyi``)."""

KEEP_PATTERNS: Final = {
    "windows": (
        *MODULES,
        r"PySide6/Qt6Multimedia\.dll",
        r"PySide6/Qt6MultimediaWidgets\.dll",
        r"PySide6/plugins/multimedia/ffmpegmediaplugin\.dll",
        *(rf"PySide6/{library}-\d+\.dll" for library in FFMPEG_LIBRARIES),
    ),
    "macos": (
        *MODULES,
        r"PySide6/Qt/lib/QtMultimedia\.framework/.*",
        r"PySide6/Qt/lib/QtMultimediaWidgets\.framework/.*",
        r"PySide6/Qt/plugins/multimedia/libffmpegmediaplugin\.dylib",
        *(rf"PySide6/Qt/lib/lib{library}\.\d+\.dylib" for library in FFMPEG_LIBRARIES),
    ),
    "linux": (
        *MODULES,
        r"PySide6/Qt/lib/libQt6Multimedia\.so\.\d+",
        r"PySide6/Qt/lib/libQt6MultimediaWidgets\.so\.\d+",
        r"PySide6/Qt/lib/libQt6FFmpegStub-[a-z0-9-]+\.so\.\d+",
        r"PySide6/Qt/plugins/multimedia/libffmpegmediaplugin\.so",
        *(rf"PySide6/Qt/lib/lib{library}\.so\.\d+" for library in FFMPEG_LIBRARIES),
    ),
}
"""What playback needs of the Addons wheel, per platform, as regular expressions each matched in full against the paths
in its ``RECORD`` (forward slashes, relative to the folder the wheel installs into).

An FFmpeg library is kept under its SONAME only -- ``libavcodec.so.63``, ``libavcodec.63.dylib`` -- which is the name
the backend asks for. The wheels hold each of them two or three times over, flattened out of their symlinks
(``libavcodec.so``, ``libavcodec.so.63`` and ``libavcodec.so.63.1.101``, 15 MB apiece), and nothing loads the others.
macOS keeps the FFmpeg backend only, as Windows does, so which plugin Qt loads never depends on the order it tries."""

ADDONS_DIST: Final = "pyside6_addons"
ESSENTIALS_DIST: Final = "pyside6_essentials"


@dataclass(frozen=True)
class PrunePlan:
    """What pruning an Addons wheel keeps and removes."""

    keep: tuple[str, ...]
    """The Addons files that stay: the keep list's, and the ones Essentials owns too."""

    remove: tuple[str, ...]
    """The Addons files that go."""


def platform_of(sys_platform: str) -> str:
    """The keep list a Python platform uses.

    :param sys_platform: :data:`sys.platform`.
    :returns: ``windows``, ``macos`` or ``linux``.
    """
    if sys_platform == "win32":
        return "windows"
    return "macos" if sys_platform == "darwin" else "linux"


def find_record(site_packages: Path, dist: str) -> Path:
    """Find the ``RECORD`` of an installed wheel.

    :param site_packages: the folder the wheels are installed into.
    :param dist: the wheel's normalized distribution name, such as ``pyside6_addons``.
    :returns: its ``RECORD``.
    :raises FileNotFoundError: no such wheel is installed, or more than one version is.
    """
    records = sorted(site_packages.glob(f"{dist}-*.dist-info/RECORD"))
    if len(records) != 1:
        raise FileNotFoundError(f"expected one {dist} wheel in {site_packages}, found {len(records)}")
    return records[0]


def read_record(record: Path) -> list[str]:
    """Read the files a wheel installed.

    :param record: the wheel's ``RECORD``.
    :returns: the paths, as written there: forward slashes, relative to the install folder.
    """
    with record.open(newline="", encoding="utf-8") as stream:
        return [row[0] for row in csv.reader(stream) if row]


def plan_prune(
    addons: Iterable[str], essentials: Iterable[str], keep_patterns: Iterable[str], dist_info: str
) -> PrunePlan:
    """Decide what of the Addons wheel stays.

    :param addons: every path of the Addons wheel's ``RECORD``.
    :param essentials: every path of the Essentials wheel's ``RECORD``; what it owns is never removed.
    :param keep_patterns: the files playback needs, as regular expressions (:data:`KEEP_PATTERNS`).
    :param dist_info: the Addons wheel's ``.dist-info`` folder, whose metadata is left as it is.
    :returns: the plan.
    :raises LookupError: a keep pattern matches no file of the wheel.
    """
    owned = set(essentials)
    patterns = tuple(keep_patterns)
    paths = tuple(addons)
    unmatched = [pattern for pattern in patterns if not any(re.fullmatch(pattern, path) for path in paths)]
    if unmatched:
        raise LookupError(f"nothing in the Addons wheel matches {', '.join(unmatched)}")
    keep: list[str] = []
    remove: list[str] = []
    for path in paths:
        if (
            path in owned
            or path.startswith(f"{dist_info}/")
            or any(re.fullmatch(pattern, path) for pattern in patterns)
        ):
            keep.append(path)
        else:
            remove.append(path)
    return PrunePlan(tuple(keep), tuple(remove))


def prune(site_packages: Path, platform: str) -> tuple[int, int, int, int]:
    """Remove from an installed ``PySide6-Addons`` everything playback does not need.

    Files only, then the folders that were left empty: a file the bundle does not hold (a wheel's ``RECORD`` names
    ``.pyc`` files and folders it never wrote) is passed over.

    :param site_packages: the folder the wheels are installed into.
    :param platform: whose keep list: ``windows``, ``macos`` or ``linux``.
    :returns: the number of files removed and their bytes, and the number of files kept and their bytes.
    :raises FileNotFoundError: the Addons or the Essentials wheel is not installed there.
    :raises LookupError: a keep pattern matches no file.
    """
    addons_record = find_record(site_packages, ADDONS_DIST)
    plan = plan_prune(
        read_record(addons_record),
        read_record(find_record(site_packages, ESSENTIALS_DIST)),
        KEEP_PATTERNS[platform],
        addons_record.parent.name,
    )
    removed = removed_bytes = 0
    for path in plan.remove:
        target = site_packages / path
        if target.is_file() or target.is_symlink():
            removed_bytes += target.stat().st_size if target.is_file() else 0
            target.unlink()
            removed += 1
    folders = {parent for name in plan.remove for parent in (site_packages / name).parents}
    for folder in sorted(folders, reverse=True):
        if folder != site_packages and folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    kept = [site_packages / name for name in plan.keep if (site_packages / name).is_file()]
    return removed, removed_bytes, len(kept), sum(file.stat().st_size for file in kept)


def main(argv: list[str] | None = None) -> int:
    """Prune the Addons wheel of the bundle named on the command line and say what that came to.

    :param argv: command-line arguments; ``None`` reads them from ``sys.argv``.
    :returns: the exit status: 0 on success, 1 when the bundle could not be pruned.
    """
    parser = argparse.ArgumentParser(
        prog="prune_pyside_addons",
        description="Cut the PySide6-Addons wheel in a built bundle down to what in-app playback needs.",
    )
    parser.add_argument("site_packages", type=Path, help="the bundle's app_packages folder")
    parser.add_argument("--platform", choices=sorted(KEEP_PATTERNS), default=platform_of(sys.platform))
    arguments = parser.parse_args(argv)
    try:
        removed, removed_bytes, kept, kept_bytes = prune(arguments.site_packages, arguments.platform)
    except (FileNotFoundError, LookupError) as error:
        print(f"Not pruned: {error}", file=sys.stderr)
        return 1
    megabyte = 1024 * 1024
    print(
        f"Pruned PySide6-Addons for {arguments.platform}: "
        f"removed {removed} files ({removed_bytes / megabyte:.1f} MiB), kept {kept} ({kept_bytes / megabyte:.1f} MiB)"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
