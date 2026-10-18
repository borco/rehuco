"""A path made absolute and tidy, spelled as the user reached it (#511).

**Not :meth:`pathlib.Path.resolve`.** On Windows ``resolve`` follows a mapped drive to the share behind it --
``T:\\DATA2`` becomes ``\\\\Nas\\data_14t\\DATA2`` -- and the two spellings are not the same place to the rest of the
system: a root listed under the letter no longer contains the file, a Recycle Bin registered for the letter does not
cover it, and a file written through one spelling right after the other can be refused (measured on a Samba share).
It also asks the server, which blocks for the network's timeout when the server is off. This asks nothing: it joins a
relative path to the working directory and folds ``.`` and ``..``, and keeps the drive letter as typed.
"""

import os
from pathlib import Path


def absolute_path(path: Path | str) -> Path:
    """``path`` made absolute against the working directory, with ``.`` and ``..`` folded -- never resolved.

    :param path: any path.
    :returns: the absolute path, its drive or share as given.
    """
    return Path(os.path.normpath(Path(path).absolute()))
