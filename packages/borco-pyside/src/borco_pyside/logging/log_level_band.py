"""The four bands a log level falls into, which is what a reader filters and paints by."""

import logging
from enum import IntEnum, unique


@unique
class LogLevelBand(IntEnum):
    """One of the four groups every log level belongs to, named for what a reader calls them.

    `logging` levels are **numbers, not four constants**: `logging.DEBUG` and friends are landmarks in
    a continuous range, and a library is free to log at 15, at 5, or at `logging.CRITICAL` + 10. A
    surface offering one control per named level would silently show nothing for any of those, so each
    band here is a *range* -- every level belongs to exactly one, and no level belongs to none.

    Each member's value is the level at the **top** of its band, except :attr:`ERRORS`, which is open
    at the top because there is nothing worse to promote a record to.
    """

    DEBUGS = logging.DEBUG
    """Anything at debug level or below, including `logging.NOTSET` and a library's own finer levels."""

    INFOS = logging.INFO
    """Above debug, up to and including info."""

    WARNINGS = logging.WARNING
    """Above info, up to and including warning."""

    ERRORS = logging.ERROR
    """Anything above warning -- errors, criticals, and whatever a caller invented past them."""

    @classmethod
    def of(cls, levelno: int) -> LogLevelBand:
        """Say which band a level falls into.

        :param levelno: a `logging` level number, named or not.
        :returns: the band it belongs to.
        """
        for band in (cls.DEBUGS, cls.INFOS, cls.WARNINGS):
            if levelno <= band:
                return band
        return cls.ERRORS
