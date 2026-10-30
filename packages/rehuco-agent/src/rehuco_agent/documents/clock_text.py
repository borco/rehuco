"""A time spelled as a clock ([[plugins#in-app-player]], [[plugins#video-tree]])."""


def clock_text(milliseconds: int) -> str:
    """Spell a time as ``m:ss``, or ``h:mm:ss`` from an hour on.

    :param milliseconds: the time; a negative one reads as zero.
    :returns: the clock text.
    """
    minutes, seconds = divmod(max(milliseconds, 0) // 1000, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"
