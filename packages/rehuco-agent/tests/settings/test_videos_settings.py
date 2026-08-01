"""Tests for VideosSettings: what a tutorial's duration scan is run with (#225).

Uses a hand-rolled in-memory stand-in for ``QSettings`` (see ``test_main_window_settings.py`` for
the same rationale) rather than a real one or ``tmp_path``.
"""

from collections.abc import Iterator
from typing import Any

from pytest import fixture, mark
from pytest_mock import MockerFixture
from rehuco_agent.settings import videos_settings
from rehuco_agent.settings.videos_settings import (
    VideosSettings,
    normalize_extensions,
    read_engine,
    shared_videos_settings,
)
from rehuco_core import (
    DEFAULT_DURATION_PROBE,
    VIDEO_EXTENSIONS,
    FfprobeDurationProbe,
    MediaInfoDurationProbe,
)

MISSING_FFPROBE = "/nowhere/ffprobe"
"""A path holding no executable, so :meth:`FfprobeDurationProbe.unavailable_reason` names it back --
which is how a test observes *which* executable the probe was built with, without reaching inside it."""


# region fixtures
# Mirrors every other settings test's FakeSettings exactly -- kept as a separate copy rather than a
# shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API.

    Method names and the ``type=`` parameter deliberately mirror ``QSettings``'s own C++-derived
    API, since :meth:`VideosSettings.load`/:meth:`~VideosSettings.save` call them by name.
    """

    def __init__(self) -> None:
        self.__data: dict[str, Any] = {}
        self.__group = ""

    def beginGroup(self, name: str) -> None:  # noqa: N802
        self.__group = f"{name}/"

    def endGroup(self) -> None:  # noqa: N802
        self.__group = ""

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802
        self.__data[self.__group + key] = value

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002, N802
        del type
        return self.__data.get(self.__group + key, default)


@fixture
def settings() -> FakeSettings:
    """A fresh in-memory settings stand-in."""
    return FakeSettings()


# pylint: enable=duplicate-code


@fixture(autouse=True)
def clear_shared_instance_cache() -> Iterator[None]:
    """Clear the ``lru_cache``-backed singleton before and after every test (see
    ``test_markdown_rendering_settings.py`` for the full rationale)."""
    shared_videos_settings.cache_clear()
    yield
    shared_videos_settings.cache_clear()


# endregion

# region normalize_extensions


def test_normalizes_case_dots_blanks_and_duplicates() -> None:
    """Every spelling of one format is one entry, dot-prefixed and lower-cased, in the order first seen.

    **Test steps:**

    * normalize a list mixing casings, a missing dot, padding, a blank and a repeat
    * verify the result is the distinct normalized extensions in their original order
    """
    assert normalize_extensions(["MP4", "  .mkv ", "", "mp4"]) == (".mp4", ".mkv")


def test_a_bare_string_reads_as_a_one_element_list() -> None:
    """The ``QSettings`` ini backend hands a single-element list back as a plain string, not as garbage.

    **Test steps:**

    * normalize the bare string ``"mp4"``
    * verify it became a one-element tuple rather than falling back to the shipped set
    """
    assert normalize_extensions("mp4") == (".mp4",)


@mark.parametrize(
    "value",
    [None, [], (), "", "   ", [".", " . "], 42, {"extensions": [".mp4"]}],
    ids=["absent", "empty-list", "empty-tuple", "empty-string", "blank-string", "bare-dots", "int", "dict"],
)
def test_a_value_naming_no_extension_falls_back_to_the_shipped_set(value: object) -> None:
    """Absent, empty and garbage all yield the shipped formats, never *no video formats at all* (#225).

    A list resolving to nothing would measure every tutorial as zero seconds, which is exactly the
    silent-zero [[field-schema#duration-size]] refuses.

    **Test steps:**

    * normalize each value that names no usable extension
    * verify the shipped set came back
    """
    assert normalize_extensions(value) == VIDEO_EXTENSIONS


# endregion

# region read_engine


def test_a_known_engine_is_kept() -> None:
    """A stored name this build ships is the selection, unchanged.

    **Test steps:**

    * read back both shipped probe names
    * verify each resolves to itself
    """
    assert read_engine(MediaInfoDurationProbe.NAME) == MediaInfoDurationProbe.NAME
    assert read_engine(FfprobeDurationProbe.NAME) == FfprobeDurationProbe.NAME


@mark.parametrize(
    "value",
    [None, "", "gstreamer", 42, ["ffprobe"]],
    ids=["absent", "empty", "unknown-name", "int", "list"],
)
def test_an_engine_this_build_lacks_falls_back_to_the_default(value: object) -> None:
    """An ``.ini`` written by a newer version selects the default instead of raising (#225).

    **Test steps:**

    * read back each value naming no shipped probe
    * verify the default backend came out
    """
    assert read_engine(value) == DEFAULT_DURATION_PROBE


# endregion

# region the effective values


def test_a_fresh_instance_measures_with_the_bundled_backend_over_the_shipped_formats() -> None:
    """Nothing configured means the backend that works on a fresh install, and every shipped format.

    **Test steps:**

    * build a settings object without loading anything
    * verify its probe is the bundled one and its extension set is the shipped one
    """
    settings = VideosSettings()

    assert isinstance(settings.create_probe(), MediaInfoDurationProbe)
    assert settings.video_extensions == VIDEO_EXTENSIONS


def test_stored_extensions_replace_the_shipped_set_entirely() -> None:
    """A custom list is the whole answer, not an addition to the shipped one.

    **Test steps:**

    * build a settings object holding one extension
    * verify its effective set is exactly that extension
    """
    assert VideosSettings(extensions=("mp4",)).video_extensions == (".mp4",)


def test_the_ffprobe_probe_is_built_with_the_configured_executable() -> None:
    """Selecting ffprobe hands it the path this section keeps for it, not a bare ``PATH`` lookup (#225).

    **Test steps:**

    * build a settings object selecting ffprobe with an executable that does not exist
    * verify the probe is an ffprobe one, and reports that very path as missing
    """
    settings = VideosSettings(engine=FfprobeDurationProbe.NAME, ffprobe_executable=MISSING_FFPROBE)

    probe = settings.create_probe()

    assert isinstance(probe, FfprobeDurationProbe)
    assert probe.unavailable_reason() == f"No runnable ffprobe at {MISSING_FFPROBE}."


def test_an_engine_this_build_lacks_still_yields_a_usable_probe() -> None:
    """A settings object naming an unknown backend measures with the default rather than raising.

    **Test steps:**

    * build a settings object naming a backend this build does not ship
    * verify its probe is the default one
    """
    assert isinstance(VideosSettings(engine="gstreamer").create_probe(), MediaInfoDurationProbe)


# endregion

# region persistence


def test_load_falls_back_to_the_defaults_on_a_fresh_install(settings: FakeSettings) -> None:
    """With nothing persisted, loading yields the bundled backend and the shipped formats.

    **Test steps:**

    * load a settings object from empty storage
    * verify the default engine, no executable and the shipped extension set
    """
    loaded = VideosSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.engine == DEFAULT_DURATION_PROBE
    assert loaded.ffprobe_executable == ""
    assert loaded.video_extensions == VIDEO_EXTENSIONS


def test_every_value_round_trips_through_storage(settings: FakeSettings) -> None:
    """What was saved is what loads back: the backend, its executable, and the list in order (#225).

    **Test steps:**

    * save a settings object holding all three
    * load a second object from the same storage
    * verify it holds the same three
    """
    saved = VideosSettings(
        engine=FfprobeDurationProbe.NAME,
        ffprobe_executable=MISSING_FFPROBE,
        extensions=(".mp4", ".mkv"),
    )
    saved.save(settings)  # type: ignore[arg-type]

    loaded = VideosSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.engine == FfprobeDurationProbe.NAME
    assert loaded.ffprobe_executable == MISSING_FFPROBE
    assert loaded.extensions == (".mp4", ".mkv")


def test_extensions_are_saved_as_a_list(settings: FakeSettings) -> None:
    """Stored as a list, which is what the ``QSettings`` ini backend can round-trip.

    **Test steps:**

    * save a settings object holding two extensions
    * verify the raw stored value is a ``list``, not a tuple
    """
    VideosSettings(extensions=(".mp4", ".mkv")).save(settings)  # type: ignore[arg-type]

    assert settings.value("videos/extensions") == [".mp4", ".mkv"]


def test_each_backends_settings_survive_switching_to_the_other_and_back(settings: FakeSettings) -> None:
    """The executable is kept whether or not ffprobe is selected, so a switch loses nothing (#225).

    That is the whole reason the two backends' settings sit side by side rather than under one
    "probe settings" key, the same arrangement ``markdown_css``/``mistletoe_css`` already takes.

    **Test steps:**

    * save ffprobe selected with an executable path
    * save again with the bundled backend selected, keeping the path as loaded
    * load afresh and select ffprobe again
    * verify the executable is still the one configured
    """
    configured = VideosSettings(engine=FfprobeDurationProbe.NAME, ffprobe_executable=MISSING_FFPROBE)
    configured.save(settings)  # type: ignore[arg-type]

    switched = VideosSettings()
    switched.load(settings)  # type: ignore[arg-type]
    switched.engine = MediaInfoDurationProbe.NAME
    switched.save(settings)  # type: ignore[arg-type]

    switched_back = VideosSettings()
    switched_back.load(settings)  # type: ignore[arg-type]
    switched_back.engine = FfprobeDurationProbe.NAME

    assert switched_back.ffprobe_executable == MISSING_FFPROBE
    assert switched_back.create_probe().unavailable_reason() == f"No runnable ffprobe at {MISSING_FFPROBE}."


def test_load_repairs_an_engine_this_build_lacks(settings: FakeSettings) -> None:
    """A stored backend name this build does not ship loads as the default rather than raising (#225).

    **Test steps:**

    * seed storage with an unknown engine name
    * load a settings object from it
    * verify the default backend came back
    """
    settings.setValue("videos/engine", "gstreamer")

    loaded = VideosSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.engine == DEFAULT_DURATION_PROBE


def test_load_repairs_an_unusable_stored_extension_value(settings: FakeSettings) -> None:
    """A stored value a list was never written as yields the shipped formats rather than propagating.

    **Test steps:**

    * seed storage with a number under the extensions key
    * load a settings object from it
    * verify the shipped set is what a scan would be handed
    """
    settings.setValue("videos/extensions", 42)

    loaded = VideosSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.video_extensions == VIDEO_EXTENSIONS


# endregion

# region the shared instance


def test_the_shared_instance_is_loaded_once(mocker: MockerFixture, settings: FakeSettings) -> None:
    """The singleton reads persistent storage on first call and hands the same object back after.

    **Test steps:**

    * seed storage with one extension and patch ``persistent_settings`` to return it
    * call the shared accessor twice
    * verify both calls returned the same object, holding the seeded extension
    """
    settings.setValue("videos/extensions", [".mp4"])
    mocker.patch.object(videos_settings, "persistent_settings", return_value=settings)

    first = shared_videos_settings()
    second = shared_videos_settings()

    assert first is second
    assert first.video_extensions == (".mp4",)


# endregion
