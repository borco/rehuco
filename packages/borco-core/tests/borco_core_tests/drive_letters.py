"""Which drive letter a Windows test may treat as having nothing behind it (#501).

A letter whose root does not exist is not enough: a remembered network drive that is disconnected -- a NAS switched off
-- has no reachable root yet is still mapped, and the system answers for it as a network drive. So a letter counts as
unused only when the system lists no drive at it, mapped ones included, and no mapping is remembered for it either.

Windows-only in what it calls; importable anywhere, since it loads the Windows modules only when asked.
"""

import string

import pytest


def letters_in_use() -> set[str]:
    """Every drive letter Windows lists or remembers a mapping for.

    :returns: the letters, upper case, without colons.
    """
    import ctypes  # pylint: disable=import-outside-toplevel  # Windows-only below: kept off other platforms
    import winreg  # pylint: disable=import-outside-toplevel

    mask = ctypes.WinDLL("kernel32").GetLogicalDrives()
    used = {letter for position, letter in enumerate(string.ascii_uppercase) if mask >> position & 1}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Network") as remembered:
            count = winreg.QueryInfoKey(remembered)[0]
            used.update(winreg.EnumKey(remembered, index).upper() for index in range(count))
    except FileNotFoundError:
        pass
    return used


def unused_drive() -> str:
    """A drive letter, with its colon, that nothing on this machine is mounted or mapped at -- skipping the test when
    every letter is taken.

    :returns: for example ``"Z:"``.
    """
    used = letters_in_use()
    free = next((letter for letter in reversed(string.ascii_uppercase[3:]) if letter not in used), None)
    if free is None:
        pytest.skip("every drive letter is in use")
    return f"{free}:"
