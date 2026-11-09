"""Tests for the sanitize step a rendered name goes through before it names a file or folder (#322, #577)."""

from pytest import mark, param
from rehuco_core import location_stem, sanitize_name


@mark.parametrize(
    "raw, name",
    [
        param("Intro to Krita", "Intro to Krita", id="kept"),
        param("Ünïcode", "Unicode", id="transliterated"),
        param("What? A/B", "What AB", id="characters-no-name-keeps-dropped"),
        param("  padded  ", "padded", id="trimmed"),
        param("???", None, id="nothing-survives"),
        param("", None, id="empty"),
    ],
)
def test_a_name_is_transliterated_then_sanitized(raw: str, name: str | None) -> None:
    """What no filesystem keeps goes, letters become their ASCII spelling, and a name with nothing left is none.

    **Test steps:**

    * sanitize each name
    * verify the result
    """
    assert sanitize_name(raw) == name


@mark.parametrize(
    "location, stem",
    [
        param("//ryzen-5600/d/__DOWNLOADS/TUTORIALS", "ryzen-5600--d--__DOWNLOADS--TUTORIALS", id="local-drive"),
        param("//nas/data_14t/DATA1/TUTORIALS", "nas--data_14t--DATA1--TUTORIALS", id="share"),
        param("//nas/Ünï: cöde//a", "nas--Uni code--a", id="segments-sanitized-empty-ones-dropped"),
        param("//???/???", None, id="nothing-survives"),
    ],
)
def test_a_location_names_a_file_by_its_segments(location: str, stem: str | None) -> None:
    """A location's segments are sanitized as a name is and joined by ``--``; none surviving is none.

    **Test steps:**

    * name a file for each location
    * verify the stem
    """
    assert location_stem(location) == stem
