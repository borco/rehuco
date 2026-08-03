"""Tests for LogLevelBand."""

import logging

from borco_pyside.logging.log_level_band import LogLevelBand
from pytest import mark

# region the named levels


@mark.parametrize(
    ("levelno", "band"),
    [
        (logging.DEBUG, LogLevelBand.DEBUGS),
        (logging.INFO, LogLevelBand.INFOS),
        (logging.WARNING, LogLevelBand.WARNINGS),
        (logging.ERROR, LogLevelBand.ERRORS),
        (logging.CRITICAL, LogLevelBand.ERRORS),
    ],
)
def test_each_named_level_lands_in_its_own_band(levelno: int, band: LogLevelBand) -> None:
    """The levels a reader knows by name fall where their names say.

    Critical belongs with the errors: there is no worse band to promote it to, and a reader hiding
    errors is not asking to keep the catastrophes.

    **Test steps:**

    * classify each named level
    * verify the band
    """
    assert LogLevelBand.of(levelno) == band


# endregion


# region the levels between the names


@mark.parametrize(
    ("levelno", "band"),
    [
        (logging.NOTSET, LogLevelBand.DEBUGS),
        (logging.DEBUG - 5, LogLevelBand.DEBUGS),
        (logging.DEBUG + 1, LogLevelBand.INFOS),
        (logging.INFO - 1, LogLevelBand.INFOS),
        (logging.INFO + 1, LogLevelBand.WARNINGS),
        (logging.WARNING - 1, LogLevelBand.WARNINGS),
        (logging.WARNING + 1, LogLevelBand.ERRORS),
        (logging.CRITICAL + 10, LogLevelBand.ERRORS),
    ],
)
def test_a_level_between_two_names_belongs_to_the_band_above_it(levelno: int, band: LogLevelBand) -> None:
    """A level nobody named still belongs somewhere -- the band it is at the top of, or below.

    A library logging at 15 is an ordinary thing; a surface offering one control per named level
    would show it under none of them.

    **Test steps:**

    * classify levels below, between and above the named ones
    * verify each falls in the band covering its range
    """
    assert LogLevelBand.of(levelno) == band


def test_a_negative_level_is_still_a_debug(levelno: int = -100) -> None:
    """Even a level below NOTSET belongs to a band rather than to none.

    **Test steps:**

    * classify a negative level
    * verify it is a debug
    """
    assert LogLevelBand.of(levelno) == LogLevelBand.DEBUGS


# endregion
