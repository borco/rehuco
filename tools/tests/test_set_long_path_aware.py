"""Tests for declaring the Windows executables long-path aware (#628)."""

from pathlib import Path
from typing import Final

from pytest import CaptureFixture, mark, param, raises
from pytest_mock import MockerFixture

from tools import set_long_path_aware
from tools.set_long_path_aware import LONG_PATH_AWARE, main, with_long_path_aware

# region Fixtures / helpers

LAUNCHER_MANIFEST: Final = Path(__file__).parents[2] / "packages" / "rehuco-agent" / "launcher" / "launcher.manifest"

BOM: Final = chr(0xFEFF)
"""A byte order mark."""

STUB_MANIFEST: Final = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">'
    '<trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges>'
    '<requestedExecutionLevel level="asInvoker" uiAccess="false"></requestedExecutionLevel>'
    "</requestedPrivileges></security></trustInfo></assembly>"
)
"""The manifest of Briefcase's Windows stub, shortened."""

ENGLISH: Final = 1033
NEUTRAL: Final = 0

# endregion


# region with_long_path_aware


@mark.parametrize("bom", [param("", id="plain"), param(BOM, id="with-a-byte-order-mark")])
def test_with_long_path_aware_adds_the_declaration_inside_the_assembly(bom: str) -> None:
    """
    Test steps:
    1. Give a manifest that lacks the declaration, with and without a byte order mark.
    2. Check the declaration closes the assembly and everything else is kept.
    """
    manifest = bom + STUB_MANIFEST

    changed = with_long_path_aware(manifest)

    assert changed == manifest.replace("</assembly>", f"{LONG_PATH_AWARE}</assembly>")


def test_with_long_path_aware_leaves_a_manifest_that_declares_it() -> None:
    """
    Test steps:
    1. Give a manifest the function already changed.
    2. Check it comes back as it is.
    """
    once = with_long_path_aware(STUB_MANIFEST)

    assert with_long_path_aware(once) == once


def test_with_long_path_aware_refuses_text_without_an_assembly() -> None:
    """
    Test steps:
    1. Give text that is no manifest.
    2. Check the function raises.
    """
    with raises(ValueError, match="assembly"):
        with_long_path_aware("not a manifest")


# endregion


# region main


def test_main_writes_only_the_manifests_that_lack_the_declaration(
    mocker: MockerFixture, capsys: CaptureFixture[str]
) -> None:
    """
    Test steps:
    1. Give an executable with a neutral manifest that declares it and an English one that does not.
    2. Check only the English one is written, changed, and the run says so.
    """
    aware = with_long_path_aware(STUB_MANIFEST)
    mocker.patch.object(set_long_path_aware, "read_manifests", return_value={NEUTRAL: aware, ENGLISH: STUB_MANIFEST})
    write = mocker.patch.object(set_long_path_aware, "write_manifests")

    assert main(["build/Rehuco.exe"]) == 0

    write.assert_called_once_with(Path("build/Rehuco.exe"), {ENGLISH: aware})
    assert capsys.readouterr().out == "Rehuco.exe is long-path aware\n"


def test_main_writes_nothing_when_every_manifest_declares_it(mocker: MockerFixture) -> None:
    """
    Test steps:
    1. Give an executable whose only manifest already declares it.
    2. Check nothing is written and the run succeeds.
    """
    mocker.patch.object(
        set_long_path_aware, "read_manifests", return_value={ENGLISH: with_long_path_aware(STUB_MANIFEST)}
    )
    write = mocker.patch.object(set_long_path_aware, "write_manifests")

    assert main(["Rehuco.exe"]) == 0

    write.assert_not_called()


@mark.parametrize(
    "error", [param(OSError("no manifest"), id="unreadable"), param(ValueError("no assembly"), id="not-a-manifest")]
)
def test_main_fails_when_the_executable_cannot_be_changed(
    mocker: MockerFixture, capsys: CaptureFixture[str], error: Exception
) -> None:
    """
    Test steps:
    1. Make reading the manifests raise what the resource API or the edit raise.
    2. Check the run fails and says why on stderr.
    """
    mocker.patch.object(set_long_path_aware, "read_manifests", side_effect=error)

    assert main(["Rehuco.exe"]) == 1

    assert capsys.readouterr().err == f"Not changed: {error}\n"


# endregion


# region The launcher's manifest


def test_the_launcher_manifest_declares_long_path_aware() -> None:
    """
    Test steps:
    1. Read the manifest the dev launcher is linked with.
    2. Check it declares long-path awareness as true.
    """
    manifest = LAUNCHER_MANIFEST.read_text(encoding="utf-8")

    assert "<longPathAware" in manifest
    assert ">true</longPathAware>" in manifest


# endregion
