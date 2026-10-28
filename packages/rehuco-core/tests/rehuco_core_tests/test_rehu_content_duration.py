"""Tests for the video-duration scan (#224): the two shipped probes, the per-file ``videos`` map (#410),
and the sum over the same content set the size scan and the checksums read.
"""

# the shipped extension set is spelled out here on purpose -- asserting it against the constant it is
# read from would pass however the constant changed, so the second copy *is* the test
# pylint: disable=duplicate-code

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Final, override
from unittest.mock import Mock

from pytest import approx, mark, param, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    DEFAULT_DURATION_PROBE,
    DURATION_PROBES,
    FFMPEG_TOOL,
    INFO_REHU_FILENAME,
    VIDEO_EXTENSIONS,
    ContentEnumeration,
    ContentUnreachableError,
    DurationProbe,
    DurationProbeError,
    FfprobeDurationProbe,
    MediaInfoDurationProbe,
    ToolCandidate,
    ToolLocator,
    ToolStatus,
    VideoFacts,
    content_duration,
    content_video_files,
    content_videos,
    total_duration,
)
from rehuco_core.external_tools.tool_descriptor import EXECUTABLE_SUFFIX

DIRECTORY: Final = Path("/fake/tutorial")
REHU_PATH: Final = DIRECTORY / INFO_REHU_FILENAME

MODULE: Final = "rehuco_core.rehu_content_duration"


# region Sample probes
class FakeProbe(DurationProbe):
    """A probe that answers from a table the test wrote, recording what it was asked.

    Stands in for a real backend everywhere the question is *how the sum behaves*, which is separate
    from *how a container is read* -- the two shipped probes have their own tests below.

    :param durations: fractional seconds per file name; a name absent from it reads as unreadable. Every
        file answers a 1920x1080 frame.
    :param unavailable: the reason this probe cannot run, or ``None`` when it can.
    """

    NAME = "fake"
    LABEL = "Fake"

    def __init__(self, durations: dict[str, float] | None = None, *, unavailable: str | None = None) -> None:
        self.__durations: Final = durations or {}
        self.__unavailable: Final = unavailable
        self.probed: Final[list[Path]] = []

    @override
    def unavailable_reason(self) -> str | None:
        """Whatever the test declared."""
        return self.__unavailable

    @override
    def probe_video(self, path: Path) -> VideoFacts | None:
        """Record the request and answer from the table."""
        self.probed.append(path)
        duration = self.__durations.get(path.name)
        return VideoFacts(duration, 1920, 1080) if duration is not None else None


def mock_content_files(mocker: MockerFixture, filenames: list[str]) -> None:
    """Make the content enumeration answer with ``filenames`` under :data:`DIRECTORY`.

    The walk itself is `rehuco_core.rehu_content_files`' contract and is tested there; what matters here
    is that the duration scan reads *that* answer rather than walking on its own (#226).

    :param mocker: pytest-mock fixture.
    :param filenames: the content file names to answer with.
    """
    mocker.patch(f"{MODULE}.enumerate_content_files", return_value=readable_enumeration(filenames))


def readable_enumeration(filenames: list[str]) -> ContentEnumeration:
    """A complete walk over ``filenames`` -- every directory listed, nothing unread.

    :param filenames: the content file names, relative to :data:`DIRECTORY`.
    :returns: what the enumeration would have answered.
    """
    return ContentEnumeration(DIRECTORY, [DIRECTORY / name for name in filenames])


# endregion


# region content_duration tests
def test_the_total_is_rounded_once_at_the_end(mocker: MockerFixture) -> None:
    """Native precision is summed and rounded **once**, never per file
    ([[field-schema#ms-leak-history]]) -- the defect tc4 shipped, where ``round(duration / 1000)`` per
    file accumulated the rounded values.

    Three clips of ``0.4`` s total ``1.2`` s, which rounds to ``1``. Rounding each first gives ``0``,
    so the two answers cannot be confused for one another.

    **Test steps:**

    * enumerate three sub-second videos
    * measure and verify the total is the rounded sum, not the sum of the rounded values
    """
    mock_content_files(mocker, ["a.mp4", "b.mp4", "c.mp4"])

    total = content_duration(REHU_PATH, FakeProbe({"a.mp4": 0.4, "b.mp4": 0.4, "c.mp4": 0.4}))

    assert total == 1


def test_only_the_recognized_video_extensions_are_probed(mocker: MockerFixture) -> None:
    """A non-video content file is skipped rather than probed -- a reference PDF beside the videos costs
    no call and contributes no seconds.

    **Test steps:**

    * enumerate a mix of videos and other files
    * measure and verify only the videos were probed
    """
    mock_content_files(mocker, ["lesson.mp4", "notes.pdf", "project.zip", "clip.mkv"])
    probe = FakeProbe({"lesson.mp4": 10.0, "clip.mkv": 5.0})

    total = content_duration(REHU_PATH, probe)

    assert [path.name for path in probe.probed] == ["lesson.mp4", "clip.mkv"]
    assert total == 15


def test_extensions_match_case_insensitively(mocker: MockerFixture) -> None:
    """An SMB or macOS listing hands back casings Windows never wrote, so a ``.MP4`` is the same video.

    **Test steps:**

    * enumerate an upper-cased video extension
    * measure and verify it was probed
    """
    mock_content_files(mocker, ["LESSON.MP4"])

    assert content_duration(REHU_PATH, FakeProbe({"LESSON.MP4": 12.0})) == 12


def test_a_custom_extension_set_changes_what_is_summed(mocker: MockerFixture) -> None:
    """The recognized set is injected rather than baked in, so a user's list (#225) is what a scan
    measures -- a format the shipped set omits is a preference change, not a rebuild.

    **Test steps:**

    * enumerate a ``.webm``, which the shipped set does not name
    * verify it is skipped by default and measured once the set names it
    """
    mock_content_files(mocker, ["lesson.webm"])
    durations = {"lesson.webm": 30.0}

    assert content_duration(REHU_PATH, FakeProbe(durations)) == 0
    assert content_duration(REHU_PATH, FakeProbe(durations), video_extensions=(".webm",)) == 30


def test_a_tutorial_with_no_video_measures_zero(mocker: MockerFixture) -> None:
    """No video is a genuine ``0``, not an error -- a resource may hold none. An unreachable resource is
    a different answer, and refuses rather than totalling one (#245).

    **Test steps:**

    * enumerate content holding no video at all
    * verify the total is ``0``
    """
    mock_content_files(mocker, ["notes.pdf"])

    assert content_duration(REHU_PATH, FakeProbe()) == 0


def test_a_resource_that_will_not_read_in_full_is_refused_rather_than_totalled(mocker: MockerFixture) -> None:
    """A runtime summed over the branches that happened to answer is not this tutorial's runtime, and it
    reads exactly like one -- the same refusal the size scan makes over the same walk (#245).

    **Test steps:**

    * make the enumeration answer with one video and a branch it could not list
    * measure
    * verify it refused, naming the branch, rather than totalling the video alone
    """
    mocker.patch(
        f"{MODULE}.enumerate_content_files",
        return_value=ContentEnumeration(DIRECTORY, [DIRECTORY / "a.mp4"], (DIRECTORY / "offline",)),
    )

    with raises(ContentUnreachableError, match="offline"):
        content_duration(REHU_PATH, FakeProbe({"a.mp4": 10.0}))


def test_an_unreadable_file_costs_its_own_seconds_and_no_more(mocker: MockerFixture) -> None:
    """A truncated or undecodable video does not abort the scan or corrupt the total -- the same way an
    unreadable file costs only its own bytes in the size scan.

    **Test steps:**

    * enumerate three videos, one of which the probe cannot read
    * verify the scan still ran to the end and totalled the two it could read
    """
    mock_content_files(mocker, ["a.mp4", "broken.mp4", "c.mp4"])
    probe = FakeProbe({"a.mp4": 10.0, "c.mp4": 5.0})

    total = content_duration(REHU_PATH, probe)

    assert [path.name for path in probe.probed] == ["a.mp4", "broken.mp4", "c.mp4"]
    assert total == 15


def test_an_unavailable_probe_is_reported_rather_than_measured_as_zero(mocker: MockerFixture) -> None:
    """A backend that cannot run raises, and does so *before* anything is enumerated: a silent ``0``
    would be indistinguishable from a tutorial holding no video (#224).

    **Test steps:**

    * measure with a probe that declares itself unavailable
    * verify it raises carrying the reason, and that nothing was probed
    """
    mock_content_files(mocker, ["a.mp4"])
    probe = FakeProbe({"a.mp4": 10.0}, unavailable="ffprobe was not found on PATH, and no path is configured.")

    with raises(DurationProbeError, match="not found on PATH"):
        content_duration(REHU_PATH, probe)

    assert not probe.probed


def test_the_excluded_patterns_reach_the_shared_enumeration(mocker: MockerFixture) -> None:
    """The junk list is passed straight through, so a file the size scan skipped is one this never sees
    -- the point of computing the content set once (#226).

    **Test steps:**

    * measure with a custom pattern list
    * verify the enumeration was called with that list and the resource's path
    """
    enumerate_content_files = mocker.patch(f"{MODULE}.enumerate_content_files", return_value=readable_enumeration([]))

    content_duration(REHU_PATH, FakeProbe(), excluded_patterns=("*.tmp",))

    enumerate_content_files.assert_called_once_with(REHU_PATH, ("*.tmp",))


def test_the_default_probe_is_used_when_none_is_given(mocker: MockerFixture) -> None:
    """Omitting the probe selects the shipped default rather than refusing -- what a caller with no
    settings yet (#224 before #225) gets.

    **Test steps:**

    * measure with no probe over content holding no video
    * verify the default backend was constructed and asked whether it could run
    """
    mock_content_files(mocker, [])
    unavailable_reason = mocker.patch.object(MediaInfoDurationProbe, "unavailable_reason", return_value=None)

    assert content_duration(REHU_PATH) == 0
    unavailable_reason.assert_called_once_with()


# endregion


# region Registry tests
def test_the_registry_names_both_shipped_probes() -> None:
    """Both backends ship, selectable by name -- the shape the settings page (#225) reads.

    **Test steps:**

    * verify the registry maps each probe's ``NAME`` to its class
    """
    assert DURATION_PROBES == {
        MediaInfoDurationProbe.NAME: MediaInfoDurationProbe,
        FfprobeDurationProbe.NAME: FfprobeDurationProbe,
    }


def test_the_default_probe_is_the_bundled_one() -> None:
    """The default is the backend that works on a fresh install with nothing configured; ``ffprobe`` is
    the deliberate alternative, never the fallback.

    **Test steps:**

    * verify the default names the MediaInfo probe, and that it is registered
    """
    assert DEFAULT_DURATION_PROBE == MediaInfoDurationProbe.NAME
    assert DURATION_PROBES[DEFAULT_DURATION_PROBE] is MediaInfoDurationProbe


def test_the_shipped_video_extensions_carry_tc4s_set() -> None:
    """The default set is tc4's, carried across unchanged, and every entry is a lower-cased dotted
    suffix -- the shape :func:`content_duration` compares against.

    **Test steps:**

    * verify the shipped set and its spelling
    """
    assert VIDEO_EXTENSIONS == (
        ".asf",
        ".avi",
        ".flv",
        ".m4v",
        ".mkv",
        ".mov",
        ".mp4",
        ".mpeg",
        ".mpg",
        ".ts",
        ".vob",
    )
    assert all(extension == extension.lower() and extension.startswith(".") for extension in VIDEO_EXTENSIONS)


# endregion


# region MediaInfoDurationProbe tests
def fake_media_info(tracks: list[SimpleNamespace]) -> SimpleNamespace:
    """Build what ``MediaInfo.parse`` returns: an object carrying the parsed tracks.

    :param tracks: the tracks to answer with.
    :returns: the stand-in.
    """
    return SimpleNamespace(tracks=tracks)


def test_mediainfo_reads_the_general_tracks_milliseconds_as_seconds(mocker: MockerFixture) -> None:
    """MediaInfo reports milliseconds and the division to seconds happens once, here, unrounded --
    the historical 1000x inflation was a build that omitted it ([[field-schema#ms-leak-history]]).

    **Test steps:**

    * parse a file whose General track reports ``2500`` ms
    * verify the probe answers ``2.5`` fractional seconds
    """
    mocker.patch(
        f"{MODULE}.MediaInfo.parse",
        return_value=fake_media_info([SimpleNamespace(track_type="General", duration=2500)]),
    )

    assert MediaInfoDurationProbe().probe(Path("a.mp4")) == approx(2.5)


def test_mediainfo_ignores_a_track_that_is_not_the_container(mocker: MockerFixture) -> None:
    """The General track is the *container's* duration -- what a player shows -- and a video track that
    stops earlier than the file holding it must not be what a tutorial's total is built from.

    **Test steps:**

    * parse a file whose Video track is shorter than its General track
    * verify the General track's duration is what comes back
    """
    mocker.patch(
        f"{MODULE}.MediaInfo.parse",
        return_value=fake_media_info(
            [
                SimpleNamespace(track_type="Video", duration=1000),
                SimpleNamespace(track_type="General", duration=2500),
            ]
        ),
    )

    assert MediaInfoDurationProbe().probe(Path("a.mp4")) == approx(2.5)


@mark.parametrize(
    "tracks",
    [
        param([], id="no-tracks-at-all"),
        param([SimpleNamespace(track_type="Video", duration=1000)], id="no-general-track"),
        param([SimpleNamespace(track_type="General", duration=None)], id="general-track-carries-no-duration"),
    ],
)
def test_mediainfo_answers_nothing_for_a_file_carrying_no_container_duration(
    mocker: MockerFixture, tracks: list[SimpleNamespace]
) -> None:
    """A file with no readable container duration contributes nothing rather than zero seconds.

    **Test steps:**

    * parse a file whose tracks carry no General duration
    * verify the probe answers ``None``
    """
    mocker.patch(f"{MODULE}.MediaInfo.parse", return_value=fake_media_info(tracks))

    assert MediaInfoDurationProbe().probe(Path("a.mp4")) is None


def test_mediainfo_reads_the_first_video_tracks_size(mocker: MockerFixture) -> None:
    """The ``videos`` map records each file's frame size beside its length (#410): the duration is still
    the container's, the size the first Video track's.

    **Test steps:**

    * parse a file with a General track and two Video tracks
    * verify the facts carry the General duration and the first Video track's size
    """
    mocker.patch(
        f"{MODULE}.MediaInfo.parse",
        return_value=fake_media_info(
            [
                SimpleNamespace(track_type="General", duration=2500),
                SimpleNamespace(track_type="Video", duration=1000, width=1920, height=1080),
                SimpleNamespace(track_type="Video", duration=1000, width=640, height=360),
            ]
        ),
    )

    assert MediaInfoDurationProbe().probe_video(Path("a.mp4")) == VideoFacts(2.5, 1920, 1080)


def test_mediainfo_reads_a_file_with_no_video_track_as_length_only(mocker: MockerFixture) -> None:
    """An audio-only file under a video extension keeps its length and has no size.

    **Test steps:**

    * parse a file with a General and an Audio track only
    * verify the facts carry the duration and no size
    """
    mocker.patch(
        f"{MODULE}.MediaInfo.parse",
        return_value=fake_media_info(
            [SimpleNamespace(track_type="General", duration=4000), SimpleNamespace(track_type="Audio", duration=4000)]
        ),
    )

    assert MediaInfoDurationProbe().probe_video(Path("a.mp4")) == VideoFacts(4.0, None, None)


@mark.parametrize("raw", ["n/a", "", "0", -5, True])
def test_a_frame_size_reported_as_no_positive_number_reads_as_unknown(mocker: MockerFixture, raw: object) -> None:
    """A backend may spell a dimension as text it could not measure, zero, or a flag; none of those is a size.

    **Test steps:**

    * parse a file whose Video track reports ``raw`` for both dimensions
    * verify the facts keep the duration and have no size
    """
    mocker.patch(
        f"{MODULE}.MediaInfo.parse",
        return_value=fake_media_info(
            [
                SimpleNamespace(track_type="General", duration=4000),
                SimpleNamespace(track_type="Video", duration=4000, width=raw, height=raw),
            ]
        ),
    )

    assert MediaInfoDurationProbe().probe_video(Path("a.mp4")) == VideoFacts(4.0, None, None)


def test_mediainfo_treats_a_parse_failure_as_an_unreadable_file(mocker: MockerFixture) -> None:
    """Whatever the library and the ctypes layer under it raise -- a truncated file, a name the C API
    cannot represent, a mount that went away -- means the same thing to a scan.

    **Test steps:**

    * make the parse raise
    * verify the probe answers ``None`` rather than propagating
    """
    mocker.patch(f"{MODULE}.MediaInfo.parse", side_effect=RuntimeError("boom"))

    assert MediaInfoDurationProbe().probe(Path("a.mp4")) is None


def test_mediainfo_is_available_when_its_bundled_library_loads(mocker: MockerFixture) -> None:
    """Availability is the library loading, asked before a scan rather than discovered during one.

    **Test steps:**

    * verify a loadable library reports no reason
    * verify an unloadable one reports one in words
    """
    can_parse = mocker.patch(f"{MODULE}.MediaInfo.can_parse", return_value=True)
    assert MediaInfoDurationProbe().unavailable_reason() is None

    can_parse.return_value = False
    assert MediaInfoDurationProbe().unavailable_reason() == "The MediaInfo library could not be loaded."


# endregion


# region FfprobeDurationProbe tests
FFMPEG_FOLDER: Final = Path("/opt/ffmpeg/bin")
FOUND_EARLIER: Final = ToolCandidate(Path("/found"), "PATH", ToolStatus.USABLE, (6, 0))


def locator_resolving(mocker: MockerFixture, candidate: ToolCandidate | None) -> Mock:
    """Build a locator that answers every ``resolve`` with one candidate.

    :param mocker: the fixture patching nothing here, only building the mock.
    :param candidate: what it resolves to.
    :returns: the mock locator.
    """
    locator = mocker.Mock(spec=ToolLocator)
    locator.resolve.return_value = candidate
    return locator


def usable_locator(mocker: MockerFixture) -> Mock:
    """Build a locator whose FFmpeg is usable.

    :param mocker: the pytest-mock fixture.
    :returns: the mock locator.
    """
    return locator_resolving(mocker, ToolCandidate(FFMPEG_FOLDER, "PATH", ToolStatus.USABLE, (7, 1)))


def test_ffprobe_asks_the_locator_for_the_chosen_install_once(mocker: MockerFixture) -> None:
    """The chosen path is what the locator is asked about, empty meaning *Automatic*, and a probe asks only once.

    **Test steps:**

    * ask a probe holding a chosen path twice whether it can run
    * verify the locator was asked once, about that path
    * verify one holding none asks about the empty path
    """
    locator = usable_locator(mocker)
    probe = FfprobeDurationProbe("/opt/ffmpeg", [FOUND_EARLIER], locator)

    assert probe.unavailable_reason() is None
    assert probe.unavailable_reason() is None
    locator.resolve.assert_called_once_with(FFMPEG_TOOL, "/opt/ffmpeg", (FOUND_EARLIER,))

    automatic = usable_locator(mocker)
    assert FfprobeDurationProbe(locator=automatic).unavailable_reason() is None
    automatic.resolve.assert_called_once_with(FFMPEG_TOOL, "", ())


@mark.parametrize(
    ("candidate", "expected"),
    [
        param(None, "No FFmpeg was found, and none is set up.", id="nothing-found"),
        param(
            ToolCandidate(Path("/x"), "Custom", ToolStatus.MISSING, reason="No FFmpeg at /x."),
            "No FFmpeg at /x.",
            id="chosen-path-holds-nothing",
        ),
        param(
            ToolCandidate(Path("/x"), "Custom", ToolStatus.TOO_OLD, (3, 4), "Version 4.0 or newer is needed."),
            "Version 4.0 or newer is needed.",
            id="too-old",
        ),
    ],
)
def test_ffprobe_says_why_it_cannot_run(mocker: MockerFixture, candidate: ToolCandidate | None, expected: str) -> None:
    """The reason is the candidate's own, since the fix differs: install FFmpeg, point at a real one, or update it.

    **Test steps:**

    * resolve to an unusable candidate, or to none
    * verify the reason says which
    """
    assert FfprobeDurationProbe(locator=locator_resolving(mocker, candidate)).unavailable_reason() == expected


def test_ffprobe_reads_the_duration_off_stdout(mocker: MockerFixture) -> None:
    """The call prints the container's duration and nothing else, so the whole of stdout is the number.

    **Test steps:**

    * run the probe over a file
    * verify the executable and flags it ran, and the fractional seconds it read back
    """
    locator = usable_locator(mocker)
    run = mocker.patch(f"{MODULE}.subprocess.run", return_value=SimpleNamespace(stdout=ffprobe_output("2.500000")))

    assert FfprobeDurationProbe(locator=locator).probe(Path("/fake/a.mp4")) == approx(2.5)

    command = run.call_args.args[0]
    assert command[0] == str(FFMPEG_FOLDER / f"ffprobe{EXECUTABLE_SUFFIX}")
    assert "format=duration:stream=width,height" in command
    assert command[-1] == str(Path("/fake/a.mp4"))


def test_ffprobe_reads_the_first_video_streams_size(mocker: MockerFixture) -> None:
    """The ``videos`` map records each file's frame size beside its length (#410), read from the first
    video stream the call selected.

    **Test steps:**

    * run the probe over a file whose output carries a stream size
    * verify the facts carry the duration, width and height
    """
    locator = usable_locator(mocker)
    mocker.patch(
        f"{MODULE}.subprocess.run",
        return_value=SimpleNamespace(stdout=ffprobe_output("2.500000", {"width": 1280, "height": 720})),
    )

    assert FfprobeDurationProbe(locator=locator).probe_video(Path("/fake/a.mp4")) == VideoFacts(2.5, 1280, 720)


def test_ffprobe_reads_a_file_with_no_video_stream_as_length_only(mocker: MockerFixture) -> None:
    """An audio-only file under a video extension still has a length worth counting; it just has no
    frame size.

    **Test steps:**

    * run the probe over a file whose output lists no stream
    * verify the facts carry the duration and no size
    """
    locator = usable_locator(mocker)
    mocker.patch(f"{MODULE}.subprocess.run", return_value=SimpleNamespace(stdout=ffprobe_output("3.0")))

    assert FfprobeDurationProbe(locator=locator).probe_video(Path("/fake/a.mp4")) == VideoFacts(3.0, None, None)


def ffprobe_output(duration: str | None, stream: dict[str, object] | None = None) -> str:
    """Build what ``ffprobe -of json`` prints for one file.

    :param duration: the container's duration as ffprobe spells it, or ``None`` for a container with none.
    :param stream: the first video stream's entries, or ``None`` for a file with no video stream.
    :returns: the JSON text.
    """
    payload: dict[str, object] = {"format": {} if duration is None else {"duration": duration}}
    if stream is not None:
        payload["streams"] = [stream]
    return json.dumps(payload)


@mark.parametrize(
    "stdout",
    [
        param("", id="nothing-printed-for-a-file-it-could-not-open"),
        param('{"format": {"duration": "N/A"}}', id="container-carrying-no-duration"),
        param('{"format": {}}', id="container-reporting-no-duration-at-all"),
        param("[]", id="not-an-object"),
    ],
)
def test_ffprobe_treats_unparseable_output_as_an_unreadable_file(mocker: MockerFixture, stdout: str) -> None:
    """Both of ``ffprobe``'s ways of saying *no duration here* mean this file contributes nothing.

    **Test steps:**

    * run the probe over a file the call answers for with no number
    * verify it answers ``None``
    """
    locator = usable_locator(mocker)
    mocker.patch(f"{MODULE}.subprocess.run", return_value=SimpleNamespace(stdout=stdout))

    assert FfprobeDurationProbe(locator=locator).probe(Path("/fake/a.mp4")) is None


@mark.parametrize(
    "error",
    [
        param(OSError("not executable"), id="the-executable-would-not-start"),
        param(subprocess.TimeoutExpired("ffprobe", 30.0), id="the-call-never-returned"),
    ],
)
def test_ffprobe_treats_a_failed_call_as_an_unreadable_file(mocker: MockerFixture, error: Exception) -> None:
    """One file that hangs or refuses to start must not take a scan of hundreds down with it.

    **Test steps:**

    * make the call raise
    * verify the probe answers ``None`` rather than propagating
    """
    locator = usable_locator(mocker)
    mocker.patch(f"{MODULE}.subprocess.run", side_effect=error)

    assert FfprobeDurationProbe(locator=locator).probe(Path("/fake/a.mp4")) is None


def test_ffprobe_refuses_to_probe_with_nothing_to_run(mocker: MockerFixture) -> None:
    """Probing without a resolvable executable raises rather than answering ``None`` per file, which
    would total ``0`` and read as a tutorial with no video.

    **Test steps:**

    * probe with nothing resolvable
    * verify it raises
    """
    locator = locator_resolving(mocker, None)

    with raises(DurationProbeError):
        FfprobeDurationProbe(locator=locator).probe(Path("/fake/a.mp4"))


# endregion


# region content_videos tests
def test_the_videos_map_keys_each_probed_file_relative_to_its_folder(mocker: MockerFixture) -> None:
    """A directory-scoped record keys its videos by their POSIX path under its folder, the key its users'
    progress entries share ([[field-schema#watch-progress]], #410). A file the probe cannot read has no
    length to record and is left out; a non-video is never probed.

    **Test steps:**

    * enumerate nested videos, an unreadable one and a PDF
    * verify the map's keys, values and order
    """
    mock_content_files(mocker, ["01 Basics/a.mp4", "01 Basics/broken.mp4", "notes.pdf", "b.mkv"])

    videos = content_videos(REHU_PATH, FakeProbe({"a.mp4": 2.5, "b.mkv": 4.0}))

    assert videos == {"01 Basics/a.mp4": VideoFacts(2.5, 1920, 1080), "b.mkv": VideoFacts(4.0, 1920, 1080)}


def test_a_standalone_records_video_is_keyed_without_its_stem(mocker: MockerFixture) -> None:
    """A standalone ``<stem>.rehu`` describes one media file, keyed by its name with the stem removed, so
    renaming the stem keeps the key ([[field-schema#watch-progress]]).

    **Test steps:**

    * enumerate a standalone record's one video
    * verify it is keyed by its extension alone
    """
    mocker.patch(
        f"{MODULE}.enumerate_content_files",
        return_value=ContentEnumeration(DIRECTORY, [DIRECTORY / "Lesson.MP4"]),
    )

    videos = content_videos(DIRECTORY / "lesson.rehu", FakeProbe({"Lesson.MP4": 7.0}))

    assert videos == {".MP4": VideoFacts(7.0, 1920, 1080)}


def test_the_total_is_the_rounded_sum_of_the_videos_map(mocker: MockerFixture) -> None:
    """``content_duration`` is :func:`content_videos` summed and rounded once -- the two can never
    disagree about which files a tutorial holds.

    **Test steps:**

    * enumerate three videos
    * verify the total equals the rounded sum of the map's durations
    """
    mock_content_files(mocker, ["a.mp4", "b.mp4", "c.mp4"])
    probe = FakeProbe({"a.mp4": 1.4, "b.mp4": 1.4, "c.mp4": 0.0})

    videos = content_videos(REHU_PATH, probe)

    assert content_duration(REHU_PATH, probe) == round(sum(facts.duration for facts in videos.values())) == 3


def test_listing_the_video_files_probes_nothing(mocker: MockerFixture) -> None:
    """The auto-viewed rule needs only which videos are on disk, never their lengths (#410).

    **Test steps:**

    * enumerate videos and a non-video
    * verify the listing holds the videos only
    """
    mock_content_files(mocker, ["a.mp4", "notes.pdf", "b.MKV"])

    assert content_video_files(REHU_PATH) == [DIRECTORY / "a.mp4", DIRECTORY / "b.MKV"]


def test_an_unavailable_probe_refuses_the_videos_map_too(mocker: MockerFixture) -> None:
    """A misconfigured backend must not read as a tutorial with no video, per file any more than in total.

    **Test steps:**

    * build the map with a probe that cannot run
    * verify it raises before anything is probed
    """
    mock_content_files(mocker, ["a.mp4"])
    probe = FakeProbe({"a.mp4": 1.0}, unavailable="Nothing to run.")

    with raises(DurationProbeError, match="Nothing to run."):
        content_videos(REHU_PATH, probe)
    assert not probe.probed


def test_the_total_is_summed_natively_and_rounded_once() -> None:
    """Three clips of 0.4 s are a second, not the zero that rounding each would give
    ([[field-schema#ms-leak-history]]); no video is zero.

    **Test steps:**

    * total three 0.4 s videos, and none
    * verify 1 and 0
    """
    assert total_duration({key: VideoFacts(0.4) for key in ("a", "b", "c")}) == 1
    assert total_duration({}) == 0


# endregion


# region Cross-backend tests
def test_both_backends_total_the_same_tree_identically(mocker: MockerFixture) -> None:
    """Selecting the other backend changes which code path ran and nothing else -- the durations are a
    property of the files, not of what read them.

    **Test steps:**

    * enumerate the same two videos for both probes, each answering the same durations
    * verify the two totals agree
    """
    mock_content_files(mocker, ["a.mp4", "b.mkv"])
    mocker.patch(f"{MODULE}.MediaInfo.can_parse", return_value=True)
    mocker.patch(
        f"{MODULE}.MediaInfo.parse",
        side_effect=lambda path: fake_media_info(
            [SimpleNamespace(track_type="General", duration=2500 if Path(path).name == "a.mp4" else 2600)]
        ),
    )
    locator = usable_locator(mocker)
    mocker.patch(
        f"{MODULE}.subprocess.run",
        side_effect=lambda command, **_kwargs: SimpleNamespace(
            stdout=ffprobe_output("2.500000" if command[-1].endswith("a.mp4") else "2.600000")
        ),
    )

    mediainfo_total = content_duration(REHU_PATH, MediaInfoDurationProbe())
    ffprobe_total = content_duration(REHU_PATH, FfprobeDurationProbe(locator=locator))

    assert mediainfo_total == ffprobe_total == 5


# endregion
