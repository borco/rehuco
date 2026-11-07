"""Tests for the sanitize step a rendered name goes through before it names a file or folder (#322, #577)."""

from pytest import mark, param
from rehuco_core import sanitize_name


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
