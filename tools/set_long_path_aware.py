"""Declare a built Windows executable long-path aware (#628).

A Windows process gets paths past the old 260-character ``MAX_PATH`` only when its executable's manifest declares
``longPathAware`` (and the system allows it: ``LongPathsEnabled = 1``). The Briefcase build ships a prebuilt stub,
``Rehuco.exe``, whose manifest does not, so every path of 260 characters or more fails with ``WinError 3`` in the
installed app while Explorer and ``python.exe`` open the same file.

The dev launcher declares it in its own manifest (``launcher.manifest``); this tool does the same for the stub, by
rewriting its manifest resource in place -- under every language it is stored under (the linker's is 1033; 0 is
neutral), so no copy of it says otherwise whichever the loader prefers. Run it on the stub after ``briefcase build`` and
before ``briefcase package``. It changes nothing in an executable whose every manifest already declares it.
"""

import argparse
import ctypes
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Final

LONG_PATH_AWARE: Final = (
    '<application xmlns="urn:schemas-microsoft-com:asm.v3"><windowsSettings>'
    '<longPathAware xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">true</longPathAware>'
    "</windowsSettings></application>"
)
"""The manifest element that declares it."""

RT_MANIFEST: Final = 24
"""The resource type of an embedded manifest."""

MANIFEST_ID: Final = 1
"""The resource id Windows reads an executable's manifest from."""

LOAD_LIBRARY_AS_DATAFILE: Final = 0x2


def with_long_path_aware(manifest: str) -> str:
    """Add the long-path declaration to a manifest.

    :param manifest: the manifest's XML, with or without a byte order mark.
    :returns: the manifest, unchanged when it already declares it.
    :raises ValueError: the text has no ``assembly`` element to add it to.
    """
    if "longPathAware" in manifest:
        return manifest
    end = manifest.rfind("</assembly>")
    if end < 0:
        raise ValueError("the manifest has no </assembly> to add the declaration to")
    return f"{manifest[:end]}{LONG_PATH_AWARE}{manifest[end:]}"


def read_manifests(executable: Path) -> dict[int, str]:  # pragma: no cover -- the Windows resource API, tried live
    """Read the manifests embedded in an executable.

    :param executable: the executable.
    :returns: each manifest's XML by the language it is stored under.
    :raises OSError: the executable cannot be loaded or has no manifest.
    """
    # Built here, not at module level: ``WINFUNCTYPE`` exists only on Windows, and the module is imported everywhere.
    enum_languages = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p, wintypes.WORD, ctypes.c_void_p
    )
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LoadLibraryExW.restype = wintypes.HMODULE
    kernel.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
    kernel.EnumResourceLanguagesW.argtypes = [
        wintypes.HMODULE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        enum_languages,
        ctypes.c_void_p,
    ]
    kernel.FindResourceExW.restype = wintypes.HANDLE
    kernel.FindResourceExW.argtypes = [wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p, wintypes.WORD]
    kernel.LoadResource.restype = wintypes.HANDLE
    kernel.LoadResource.argtypes = [wintypes.HMODULE, wintypes.HANDLE]
    kernel.LockResource.restype = ctypes.c_void_p
    kernel.LockResource.argtypes = [wintypes.HANDLE]
    kernel.SizeofResource.restype = wintypes.DWORD
    kernel.SizeofResource.argtypes = [wintypes.HMODULE, wintypes.HANDLE]
    kernel.FreeLibrary.argtypes = [wintypes.HMODULE]
    module = kernel.LoadLibraryExW(str(executable), None, LOAD_LIBRARY_AS_DATAFILE)
    if not module:
        raise ctypes.WinError(ctypes.get_last_error())
    languages: list[int] = []
    manifests: dict[int, str] = {}
    try:
        kernel.EnumResourceLanguagesW(
            module, RT_MANIFEST, MANIFEST_ID, enum_languages(lambda *args: languages.append(args[3]) or True), None
        )
        if not languages:
            raise ctypes.WinError(ctypes.get_last_error())
        for language in languages:
            resource = kernel.FindResourceExW(module, RT_MANIFEST, MANIFEST_ID, language)
            if not resource:
                raise ctypes.WinError(ctypes.get_last_error())
            data = ctypes.string_at(
                kernel.LockResource(kernel.LoadResource(module, resource)), kernel.SizeofResource(module, resource)
            )
            manifests[language] = data.decode("utf-8-sig")
    finally:
        kernel.FreeLibrary(module)
    return manifests


def write_manifests(executable: Path, manifests: dict[int, str]) -> None:  # pragma: no cover -- the resource API
    """Replace manifests embedded in an executable.

    :param executable: the executable.
    :param manifests: each manifest's XML by the language to store it under.
    :raises OSError: the resources cannot be updated.
    """
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.BeginUpdateResourceW.restype = wintypes.HANDLE
    kernel.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    kernel.UpdateResourceW.restype = wintypes.BOOL
    kernel.UpdateResourceW.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.WORD,
        ctypes.c_char_p,
        wintypes.DWORD,
    ]
    kernel.EndUpdateResourceW.restype = wintypes.BOOL
    kernel.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]
    handle = kernel.BeginUpdateResourceW(str(executable), False)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    error = None
    for language, manifest in manifests.items():
        data = manifest.encode("utf-8")
        if not kernel.UpdateResourceW(handle, RT_MANIFEST, MANIFEST_ID, language, data, len(data)):
            error = ctypes.WinError(ctypes.get_last_error())
            break
    if not kernel.EndUpdateResourceW(handle, error is not None) and error is None:
        error = ctypes.WinError(ctypes.get_last_error())
    if error is not None:
        raise error


def main(argv: list[str] | None = None) -> int:
    """Declare the executable named on the command line long-path aware.

    :param argv: command-line arguments; ``None`` reads them from ``sys.argv``.
    :returns: the exit status: 0 on success, 1 when the executable could not be changed.
    """
    parser = argparse.ArgumentParser(
        prog="set_long_path_aware", description="Declare a built Windows executable long-path aware."
    )
    parser.add_argument("executable", type=Path, help="the executable to change")
    arguments = parser.parse_args(argv)
    try:
        manifests = read_manifests(arguments.executable)
        changed = {
            language: aware
            for language, manifest in manifests.items()
            if (aware := with_long_path_aware(manifest)) != manifest
        }
        if changed:
            write_manifests(arguments.executable, changed)
    except (OSError, ValueError) as error:
        print(f"Not changed: {error}", file=sys.stderr)
        return 1
    print(f"{arguments.executable.name} is long-path aware")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
