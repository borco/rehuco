"""Windows crash-dump retention via HKLM ``LocalDumps`` (#363).

Windows writes a minidump for every native crash and then deletes it unless a per-executable
``LocalDumps`` key exists under ``HKLM\\SOFTWARE\\Microsoft\\Windows\\Windows Error
Reporting\\LocalDumps``. That key lives under ``HKEY_LOCAL_MACHINE``, so writing or removing it needs
elevation; reading it back to report the current status does not.

Windows-only: imports ``winreg`` at module scope, like ``rehuco_agent.windows_registration`` --
only ever imported inside an ``if sys.platform == "win32":`` branch.
"""

import base64
import logging
import subprocess  # nosec B404  # only ever runs an unelevated PowerShell that self-elevates via Start-Process
import winreg
from pathlib import Path
from typing import Final

from .settings.persistent_settings import config_folder

LOG: Final = logging.getLogger(__name__)

LOCAL_DUMPS_KEY: Final = r"SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps"
"""HKLM key holding one sub-key per executable opted into kept crash dumps."""

DUMP_COUNT: Final = 10
"""``DumpCount`` written by :func:`enable` -- how many dumps Windows keeps before deleting the oldest."""

DUMP_TYPE_MINI: Final = 1
"""``DumpType`` written by :func:`enable`: a minidump of a few MB. Never 2, a full dump of hundreds of MB."""

CREATE_NO_WINDOW: Final = 0x08000000
"""Windows process-creation flag so the outer, unelevated PowerShell never flashes a console."""


def dumps_folder() -> Path:
    """Where crash dumps are written -- next to the run log, under this app's own config folder
    (#361, #362). Not created by this call; Windows creates it with the first dump."""
    return config_folder() / "crashdumps"


def dump_files(folder: Path | None = None) -> list[Path]:
    """The ``*.dmp`` files currently in ``folder``, or an empty list while it doesn't exist yet.

    :param folder: the folder to list; defaults to :func:`dumps_folder`.
    """
    folder = dumps_folder() if folder is None else folder
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.dmp"))


def clear_dumps(folder: Path | None = None) -> None:
    """Delete every ``*.dmp`` file in ``folder``, skipping and logging one that can't be deleted.

    Deletes only ``*.dmp`` files, never the folder itself or anything else in it, and needs no
    elevation: dumps of a process the user ran land in the user's own profile, owned by the user.

    :param folder: the folder to clear; defaults to :func:`dumps_folder`.
    """
    for file in dump_files(folder):
        try:
            file.unlink()
        except OSError:
            LOG.warning("Could not delete crash dump %s", file, exc_info=True)


def enable(exe_name: str) -> None:
    """Write ``exe_name``'s ``LocalDumps`` key, through an elevated PowerShell. Idempotent: enabling
    again rewrites the same values.

    :param exe_name: the running executable's file name, e.g. ``"Rehuco.exe"``.
    """
    key_path = rf"HKLM:\{LOCAL_DUMPS_KEY}\{exe_name}"
    folder = str(dumps_folder())
    script = (
        f'New-Item -Path "{key_path}" -Force | Out-Null; '
        f'New-ItemProperty -Path "{key_path}" -Name DumpFolder -Value "{folder}" '
        "-PropertyType ExpandString -Force | Out-Null; "
        f'New-ItemProperty -Path "{key_path}" -Name DumpCount -Value {DUMP_COUNT} '
        "-PropertyType DWord -Force | Out-Null; "
        f'New-ItemProperty -Path "{key_path}" -Name DumpType -Value {DUMP_TYPE_MINI} '
        "-PropertyType DWord -Force | Out-Null"
    )
    run_elevated(script)


def disable(exe_name: str) -> None:
    """Remove ``exe_name``'s ``LocalDumps`` key, through an elevated PowerShell.

    :param exe_name: same as :func:`enable`.
    """
    key_path = rf"HKLM:\{LOCAL_DUMPS_KEY}\{exe_name}"
    script = f'Remove-Item -Path "{key_path}" -Recurse -Force -ErrorAction SilentlyContinue'
    run_elevated(script)


def is_enabled(exe_name: str) -> tuple[bool, Path | None]:
    """Whether ``exe_name`` has a ``LocalDumps`` key, and the folder it points dumps at.

    Reads HKLM directly -- unlike the write, this needs no elevation. The status never comes from a
    subprocess's exit code, so a cancelled UAC prompt on :func:`enable`/:func:`disable` reads as "not
    enabled" here rather than lying about what happened.

    ``DumpFolder`` is a ``REG_EXPAND_SZ``, and ``QueryValueEx`` hands it back unexpanded -- so a key set
    by hand to ``%LOCALAPPDATA%\\CrashDumps`` is expanded here, to the folder Windows itself will write
    into, rather than shown as a literal that exists nowhere.

    :param exe_name: same as :func:`enable`.
    :returns: ``(True, folder)`` when the key exists and names a ``DumpFolder``; ``(False, None)``
        when it doesn't.
    """
    sub_key = rf"{LOCAL_DUMPS_KEY}\{exe_name}"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub_key) as key:
            folder, _ = winreg.QueryValueEx(key, "DumpFolder")
            return True, Path(winreg.ExpandEnvironmentStrings(str(folder)))
    except OSError:
        return False, None


def run_elevated(script: str) -> None:
    """Run ``script`` under one elevated PowerShell, prompting UAC once for the inner process only.

    The outer, unelevated PowerShell relaunches itself elevated through ``Start-Process -Verb RunAs
    -Wait``, handing the real work across as ``-EncodedCommand`` (base64 of UTF-16LE) rather than a
    nested quoted string -- the encoded blob has no spaces or quotes of its own, so the spaces in
    "Windows Error Reporting" never have to survive two levels of shell quoting. Neither process shows
    a window: the outer gets ``CREATE_NO_WINDOW`` and the inner ``-WindowStyle Hidden``.

    :param script: the PowerShell script to run elevated.
    """
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    outer_script = (
        "Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden "
        f"-ArgumentList '-NoProfile','-WindowStyle','Hidden','-EncodedCommand','{encoded}'"
    )
    try:
        subprocess.run(  # nosec B603 B607  # "powershell" resolved off PATH, fixed arguments, never a shell
            ["powershell", "-NoProfile", "-Command", outer_script],
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )
    except OSError:
        LOG.warning("Could not run elevated PowerShell for crash-dump registration", exc_info=True)
