"""How long a tutorial's videos run ([[field-schema#duration-size]], #224).

[[field-schema#duration-size]] defines ``original_duration`` and ``current_duration`` as **measured**
values, and [[field-schema#ms-leak-history]] calls a legacy ``.tc`` duration *advisory until a real scan
overwrites it*. This module is that scan.

Nothing in the dependency tree reads a video container, so the reading is delegated to a **probe**, of
which two ship: :class:`MediaInfoDurationProbe` (the bundled MediaInfo library) and
:class:`FfprobeDurationProbe` (the external executable). Two rather than one because the predecessors
disagree -- tutcatalog and tutcatalogpy3 shell out to ``ffprobe``, tutcatalogpy2 and tc4 link MediaInfo --
and because which one a user can run is a property of their machine, not of this code. The registry
:data:`DURATION_PROBES` and the ``engine`` name selecting one are the same shape the agent's Markdown
renderer already takes.

The counterpart of :mod:`rehuco_core.rehu_content_files`, which answers *which files*: this one answers
*how long they run*, over exactly that set, so a video a size scan counted is a video this measures.
Core-side and GUI-free; the caller supplies the probe and the recognized extensions rather than this
module reading a setting.
"""

import subprocess  # nosec B404  # only ever runs the ffprobe executable the caller named, with fixed flags
from abc import ABC, abstractmethod
from pathlib import Path
from shutil import which
from typing import ClassVar, Final

from pymediainfo import MediaInfo

from .constants import EXCLUDED_FILE_PATTERNS, VIDEO_EXTENSIONS
from .rehu_content_files import enumerate_content_files


class DurationProbeError(RuntimeError):
    """A probe that cannot run at all, raised before any file is read ([[field-schema#duration-size]]).

    Distinct from a file that failed to decode, which costs its own seconds and nothing more. A probe
    with no readable backend behind it -- ``ffprobe`` at a path that holds no executable -- would
    otherwise measure every video as unreadable and total ``0``, which is indistinguishable from a
    tutorial holding no video at all. Reporting it as an error is what keeps a misconfiguration from
    reading as a measurement (#224).
    """


class DurationProbe(ABC):
    """Reads one video file's duration ([[field-schema#duration-size]]).

    Implementations differ only in *what* reads the container; everything about which files are read,
    how they are summed and when the total is rounded belongs to :func:`content_duration`, so a third
    backend is one class and one registry entry.

    **Durations come back in native precision, as fractional seconds.** Rounding is
    :func:`content_duration`'s, applied once to the total: [[field-schema#ms-leak-history]] records
    tc4 rounding per file and accumulating the rounded values, which is the defect that rule exists to
    prevent, and a probe returning whole seconds would reintroduce it one level lower where no caller
    could see it.
    """

    NAME: ClassVar[str]
    """The probe's stable identifier -- the ``engine`` value stored in settings, never the display text.
    Renaming one silently reselects the default on every existing install."""

    LABEL: ClassVar[str]
    """How the probe is named to a user, in the settings page that chooses one (#225)."""

    @abstractmethod
    def unavailable_reason(self) -> str | None:
        """Whether this probe can run here, and if not, why not in words.

        Asked before a scan starts rather than discovered during one, and asked again by the settings
        page (#225) so a misconfiguration is visible before anyone presses Compute.

        :returns: ``None`` when the probe is usable, otherwise a sentence naming what is missing.
        """

    @abstractmethod
    def probe(self, path: Path) -> float | None:
        """Read one video file's duration.

        :param path: the video file.
        :returns: the duration in fractional seconds, or ``None`` when this file carries none that can
            be read -- an unreadable, truncated or undecodable file, which is a property of that file
            rather than of the probe.
        """


class MediaInfoDurationProbe(DurationProbe):
    """Reads durations through the **MediaInfo** library, bundled with the app.

    The backend that ships working: ``pymediainfo``'s wheels carry ``libmediainfo`` for Windows, macOS
    and Linux alike, so the three installers ([[packaging-deployment#linux-format]]) gain a probe
    without gaining an external tool the user has to find first. It reads the container's declared
    duration rather than decoding frames, so a scan costs a header read per file -- which matters on a
    tutorial of hundreds of videos on an SMB mount ([[packaging-deployment#ts230-as-nas]]).

    MediaInfo reports durations in **milliseconds** ([[field-schema#ms-leak-history]]), and the
    conversion to seconds happens here, once, without rounding -- the historical 1000x inflation was a
    build that omitted this division, and the second half of that lesson is that the value stays
    fractional until :func:`content_duration` totals it.
    """

    NAME = "mediainfo"
    LABEL = "MediaInfo (bundled)"

    def unavailable_reason(self) -> str | None:
        """Whether the bundled MediaInfo library loads.

        :returns: ``None`` when it does, otherwise a sentence saying it could not be loaded. Normally
            unreachable in a packaged build, and reachable in a source install that deliberately took
            ``pymediainfo`` without its bundled library (``--no-binary``) on a host that has none.
        """
        if not MediaInfo.can_parse():
            return "The MediaInfo library could not be loaded."
        return None

    def probe(self, path: Path) -> float | None:
        """Read ``path``'s duration out of its General track.

        The General track is the *container's* duration, which is what a player shows and what the sum
        of a tutorial's files should total -- deliberately not the video track's, which may be shorter
        than the file that holds it.

        :param path: the video file.
        :returns: the duration in fractional seconds, or ``None`` when the file carries none.
        """
        try:
            media_info = MediaInfo.parse(path)
        except Exception:  # pylint: disable=broad-exception-caught
            # pymediainfo raises whatever the library and the ctypes layer under it raise -- a
            # truncated file, a filename the C API cannot represent, an OSError from the mount. Every
            # one of them means the same thing to a scan: this file contributes nothing.
            return None
        for track in media_info.tracks:
            if track.track_type == "General" and track.duration is not None:
                return float(track.duration) / 1000.0
        return None


class FfprobeDurationProbe(DurationProbe):
    """Reads durations by running **ffprobe**, an executable the user supplies.

    The backend for whoever already has FFmpeg installed and would rather the app use it than carry a
    second media library: the same ``-show_entries format=duration`` call
    ``tutcatalogpy3`` made, with the executable's location a setting (#225) because a system FFmpeg
    lives wherever that system put it.

    :param executable: the ``ffprobe`` executable's path, or ``None`` to look it up on ``PATH``.
    """

    NAME = "ffprobe"
    LABEL = "ffprobe (external)"

    __ARGUMENTS: Final = (
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
    )
    """Print the container's duration and nothing else: no banner, no key, no wrapper -- so the whole
    of stdout is the number, and a parse failure means the call failed rather than that the format
    moved."""

    __TIMEOUT_SECONDS: Final = 30.0
    """How long one file may take before it is given up on. A header read is milliseconds even over a
    mount; a call still running after this is one that will not return (a named pipe, a device node
    that answered the extension test), and a scan of hundreds of files must not hang on it."""

    def __init__(self, executable: str | None = None) -> None:
        self.__executable: Final = executable or ""

    def unavailable_reason(self) -> str | None:
        """Whether an ``ffprobe`` executable can be found.

        :returns: ``None`` when one resolves, otherwise a sentence naming what is missing -- an unset
            path with nothing on ``PATH`` to fall back to, or a configured path that holds no runnable
            executable.
        """
        if self.__resolved_executable() is not None:
            return None
        if self.__executable:
            return f"No runnable ffprobe at {self.__executable}."
        return "ffprobe was not found on PATH, and no path is configured."

    def probe(self, path: Path) -> float | None:
        """Run ``ffprobe`` over ``path`` and read the duration off its stdout.

        :param path: the video file.
        :returns: the duration in fractional seconds, or ``None`` when the call failed, timed out, or
            printed something that is not a number -- every one of which means this file contributes
            nothing.
        :raises DurationProbeError: if no executable resolves; a scan cannot silently total ``0``
            because the tool it was told to use is not there.
        """
        executable = self.__resolved_executable()
        if executable is None:
            raise DurationProbeError(self.unavailable_reason())
        try:
            completed = subprocess.run(  # nosec B603  # a resolved executable and fixed flags, never a shell
                [executable, *self.__ARGUMENTS, str(path)],
                capture_output=True,
                text=True,
                timeout=self.__TIMEOUT_SECONDS,
                check=False,
            )
        except OSError, subprocess.SubprocessError:
            return None
        try:
            return float(completed.stdout.strip())
        except ValueError:
            # ffprobe prints nothing for a file it could not open, and "N/A" for a container carrying
            # no duration at all -- both are this file contributing nothing, not a failed scan
            return None

    def __resolved_executable(self) -> str | None:
        """Locate the executable to run.

        :func:`shutil.which` for both cases rather than only the ``PATH`` one: given a configured path
        it also answers *is this actually runnable*, and on Windows it is what supplies the ``.exe``
        the user's path may well omit.

        :returns: the executable's path, or ``None`` when none resolves.
        """
        if self.__executable:
            return which(self.__executable)
        return which("ffprobe")


DURATION_PROBES: Final[dict[str, type[DurationProbe]]] = {
    probe.NAME: probe for probe in (MediaInfoDurationProbe, FfprobeDurationProbe)
}
"""The probes this build ships, by :attr:`DurationProbe.NAME` -- what an ``engine`` setting selects from
(#225). Classes rather than instances: :class:`FfprobeDurationProbe` is constructed with the executable
path its own settings hold, so the registry names the backends and the caller builds the one it wants,
the way `MarkdownRenderingSettings` keeps each engine's settings side by side."""

DEFAULT_DURATION_PROBE: Final = MediaInfoDurationProbe.NAME
"""The probe used when nothing has chosen one -- the bundled library, because it is the one that works
on a fresh install with nothing configured. ``ffprobe`` is the deliberate alternative for a machine that
already has FFmpeg, never the fallback for a machine that has neither."""


def content_duration(
    rehu_path: Path,
    probe: DurationProbe | None = None,
    *,
    video_extensions: tuple[str, ...] = VIDEO_EXTENSIONS,
    excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS,
) -> int:
    """Sum how long ``rehu_path``'s videos run ([[field-schema#duration-size]], #224).

    A probe per video over :func:`~rehuco_core.rehu_content_files.enumerate_content_files`, deliberately
    not a walk of its own: the files a duration covers, the bytes a size counts and the hashes a
    manifest records are one set, decided once (#226).

    **Summed in native precision and rounded once, at the end.** [[field-schema#ms-leak-history]] states
    this as a rule because tc4 broke it -- ``round(duration / 1000)`` per file, accumulated -- which
    loses up to half a second per video and, on a tutorial of two hundred clips, minutes off the total.

    :param rehu_path: the resource's ``.rehu`` file.
    :param probe: reads one file's duration; the default backend
        (:data:`DEFAULT_DURATION_PROBE`) when omitted.
    :param video_extensions: the file extensions to measure, matched case-insensitively -- injected
        rather than read from a setting (:data:`~rehuco_core.constants.VIDEO_EXTENSIONS` by default), so
        a user's list (#225) reaches this without core learning what a settings page is.
    :param excluded_patterns: filename globs to leave out of the walk, passed straight through to
        :func:`~rehuco_core.rehu_content_files.enumerate_content_files`.
    :returns: the total duration in whole seconds; ``0`` when the resource holds no video at all. A file
        that cannot be *probed* costs its own seconds and nothing more.
    :raises DurationProbeError: if ``probe`` cannot run here at all. Deliberately not a ``0``: a
        misconfigured backend and a tutorial with no video would otherwise be the same answer.
    :raises ContentUnreachableError: some directory under the resource would not list (#245) -- the same
        refusal for the same reason, one step earlier: a total over the branches that happened to answer
        is not this resource's runtime.
    """
    probe = probe if probe is not None else DURATION_PROBES[DEFAULT_DURATION_PROBE]()
    unavailable = probe.unavailable_reason()
    if unavailable is not None:
        raise DurationProbeError(unavailable)
    suffixes = tuple(extension.lower() for extension in video_extensions)
    enumeration = enumerate_content_files(rehu_path, excluded_patterns)
    enumeration.require_complete()
    total = 0.0
    for path in enumeration.files:
        if path.suffix.lower() not in suffixes:
            continue
        duration = probe.probe(path)
        if duration is not None:
            total += duration
    return round(total)
