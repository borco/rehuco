"""Tests for RootLayoutTemplatesSettings: the library of root path templates and its Try-it sample (#637)."""

from pytest import mark
from rehuco_agent.settings.location_templates_settings import DEFAULT_SAMPLE, SAMPLE_FIELDS
from rehuco_agent.settings.root_layout_templates_settings import (
    DEFAULT_ROOT_LAYOUT_TEMPLATES,
    RootLayoutTemplatesSettings,
    normalize_root_layout_templates,
)

from rehuco_agent_tests.conftest import FakeSettings


def test_the_shipped_library_is_empty_and_the_shipped_sample_is_the_locations_one() -> None:
    """A fresh object offers no template, and the sample starts as the Locations pages' (#637).

    **Test steps:**

    * build the settings and read both fields
    * verify no templates and the shared default sample
    """
    settings = RootLayoutTemplatesSettings()

    assert settings.templates == DEFAULT_ROOT_LAYOUT_TEMPLATES
    assert not settings.templates
    assert settings.sample == DEFAULT_SAMPLE


@mark.parametrize(
    ("stored", "expected"),
    [
        (["{title}", " {title} ", "", "  ", "*", "{authors}/{title}"], ("{title}", "*", "{authors}/{title}")),
        (["{author}"], ("{author}",)),
        ("{title}", ("{title}",)),
        (None, ()),
        (7, ()),
    ],
)
def test_normalizing_trims_and_drops_blanks_and_repeats_but_keeps_an_invalid_row_and_star(
    stored: object, expected: tuple[str, ...]
) -> None:
    """Saving never costs a typo or a ``*`` its row, which the page flags, but a blank and a repeat are no rows (#637).

    **Test steps:**

    * normalize a list of repeats, blanks, ``*`` and a valid template; a typo; one string; nothing; a non-list
    * verify the trimmed templates in first-seen order, ``*`` and the typo kept, and none for the last two
    """
    assert normalize_root_layout_templates(stored) == expected


def test_the_library_and_the_sample_round_trip_through_storage() -> None:
    """What is saved is what loads, the sample field by field so ``authors``' comma survives (#637).

    **Test steps:**

    * save a library of two templates and a sample whose authors hold a comma
    * load them into a new settings object
    * verify both are read back, and that the sample is stored one key per field
    """
    store = FakeSettings()
    sample = ("A Title", "A Publisher", "Jane Doe, John Roe", "1999", "12")
    saved = RootLayoutTemplatesSettings()
    saved.templates = ("{authors}/{title}", "{publisher}/{title}")
    saved.sample = sample
    saved.save(store)  # type: ignore[arg-type]

    loaded = RootLayoutTemplatesSettings()
    loaded.load(store)  # type: ignore[arg-type]

    assert loaded.templates == saved.templates
    assert loaded.sample == sample
    store.beginGroup("root_layout_try_it")
    assert [store.value(field) for field in SAMPLE_FIELDS] == list(sample)


def test_loading_nothing_gives_the_shipped_values() -> None:
    """A never-saved store reads as the shipped library and sample (#637).

    **Test steps:**

    * load an empty store over changed values
    * verify the shipped ones are back
    """
    settings = RootLayoutTemplatesSettings()
    settings.templates = ("{title}",)
    settings.sample = ("x",) * len(SAMPLE_FIELDS)

    settings.load(FakeSettings())  # type: ignore[arg-type]

    assert not settings.templates
    assert settings.sample == DEFAULT_SAMPLE
