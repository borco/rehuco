"""How this agent is run, so a child can be run the same way ([[nodes#two-roles]])."""

import sys
from pathlib import Path


def own_program() -> list[str]:
    """The command that runs this agent again.

    The packaged exe, the dev launcher and the console script run as themselves; only ``python -m rehuco_agent``
    (``argv[0]`` a ``.py`` file) has to go back through the interpreter.

    :returns: the program, to which a flag is appended.
    """
    launched = Path(sys.argv[0])
    return [sys.executable, "-m", "rehuco_agent"] if launched.suffix == ".py" else [str(launched.resolve())]
