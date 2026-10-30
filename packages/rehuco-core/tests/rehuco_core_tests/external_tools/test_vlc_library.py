"""Tests for the proxy around python-vlc: it never fails without VLC, and imports only by full path
([[appendices.vlc#python-vlc]], #319)."""

import importlib
import json
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Final

from pytest import MonkeyPatch, mark, param
from pytest_mock import MockerFixture
from rehuco_core import LIBRARY_PATH_VARIABLE, ToolStatus, VlcLibrary, probe_libvlc

MODULE: Final = "rehuco_core.external_tools.vlc_library"


def fake_vlc(bound: str, version: bytes = b"3.0.23 Vetinari") -> ModuleType:
    """A ``vlc`` module as python-vlc leaves it after a successful import.

    :param bound: the library path its ``dll`` carries.
    :param version: what ``libvlc_get_version`` answers.
    :returns: the module.
    """
    module = ModuleType("vlc")
    setattr(module, "dll", SimpleNamespace(_name=bound))  # noqa: B010
    setattr(module, "libvlc_get_version", lambda: version)  # noqa: B010
    setattr(  # noqa: B010
        module,
        "Instance",
        lambda *options: (
            None if any("bad" in option for option in options) else SimpleNamespace(media_player_new=lambda: "player")
        ),
    )
    return module


def test_importing_the_package_does_not_import_python_vlc() -> None:
    """Nothing imports ``vlc`` at module load: that import searches for and loads libvlc, and can exit the process.

    **Test steps:**

    * import the package, which this test already has
    * verify ``vlc`` is not among the loaded modules
    """
    assert "vlc" not in sys.modules


def test_no_library_is_unavailable_with_a_reason_and_nothing_is_imported(mocker: MockerFixture) -> None:
    """**Test steps:**

    * load with no library
    * verify it is unavailable, says VLC is not set up, and never imported anything
    """
    import_module = mocker.patch(f"{MODULE}.importlib.import_module")

    loaded = VlcLibrary.load(None)

    assert not loaded.available
    assert loaded.reason == "No VLC is set up on the Tools page."
    assert loaded.module is None
    assert loaded.version is None
    assert loaded.instance() is None
    assert loaded.media_player(None) is None
    import_module.assert_not_called()


def test_a_library_is_imported_by_full_path_and_bound(
    mocker: MockerFixture, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """The import is made with ``PYTHON_VLC_LIB_PATH`` set to the full path, so python-vlc searches for nothing.

    **Test steps:**

    * make the import answer a module bound to the library asked for
    * verify the variable named it, the proxy is available, and the version, the instance and the player come through
    """
    monkeypatch.delenv(LIBRARY_PATH_VARIABLE, raising=False)
    library = tmp_path / "libvlc.dll"
    mocker.patch(f"{MODULE}.importlib.import_module", return_value=fake_vlc(str(library)))
    mocker.patch.dict(sys.modules, {}, clear=False)
    sys.modules.pop("vlc", None)

    loaded = VlcLibrary.load(library)

    assert os.environ[LIBRARY_PATH_VARIABLE] == str(library)
    assert loaded.available
    assert loaded.reason is None
    assert loaded.library == library
    assert loaded.version == (3, 0, 23)
    instance = loaded.instance("--no-video")
    assert instance is not None
    assert loaded.media_player(instance) == "player"
    assert loaded.instance("--bad-option") is None


@mark.parametrize(
    ("raised", "said"),
    [
        param(SystemExit(1), "it exited with 1", id="sys.exit from a bad path"),
        param(FileNotFoundError("Could not find module"), "FileNotFoundError: Could not find module", id="no VLC"),
        param(KeyError("ProgramFiles"), "KeyError: 'ProgramFiles'", id="no ProgramFiles"),
        param(OSError("not a valid Win32 application"), "OSError: not a valid", id="wrong bitness"),
    ],
)
def test_whatever_the_import_raises_becomes_a_reason(
    mocker: MockerFixture, tmp_path: Path, raised: BaseException, said: str
) -> None:
    """Each thing ``import vlc`` was measured to raise, ``SystemExit`` included, leaves the proxy unavailable.

    **Test steps:**

    * make the import raise it
    * verify nothing escapes, the proxy is unavailable, and the reason names the library and what happened
    """
    mocker.patch(f"{MODULE}.importlib.import_module", side_effect=raised)
    sys.modules.pop("vlc", None)
    library = tmp_path / "libvlc.dll"

    loaded = VlcLibrary.load(library)

    assert not loaded.available
    assert loaded.reason is not None
    assert str(library) in loaded.reason
    assert said in loaded.reason
    assert loaded.instance() is None


def test_a_module_already_bound_to_another_library_asks_for_a_restart(mocker: MockerFixture, tmp_path: Path) -> None:
    """python-vlc cannot be rebound, so a path changed after the first load waits for the next start.

    **Test steps:**

    * have ``vlc`` already imported, bound to one library, and load another
    * verify the proxy is unavailable and the reason names both and says to restart
    """
    mocker.patch.dict(sys.modules, {"vlc": fake_vlc(str(tmp_path / "old" / "libvlc.dll"))})
    import_module = mocker.patch(f"{MODULE}.importlib.import_module")

    loaded = VlcLibrary.load(tmp_path / "new" / "libvlc.dll")

    assert not loaded.available
    assert loaded.reason is not None
    assert "old" in loaded.reason and "new" in loaded.reason and "restart" in loaded.reason
    import_module.assert_not_called()


def test_a_module_already_bound_to_the_same_library_is_reused(mocker: MockerFixture, tmp_path: Path) -> None:
    """**Test steps:**

    * have ``vlc`` already imported, bound to the library asked for
    * verify the proxy is available over it, with no second import
    """
    library = tmp_path / "libvlc.dll"
    mocker.patch.dict(sys.modules, {"vlc": fake_vlc(str(library))})
    import_module = mocker.patch(f"{MODULE}.importlib.import_module")

    loaded = VlcLibrary.load(library)

    assert loaded.available
    import_module.assert_not_called()


def test_an_instance_libvlc_raises_for_is_none_and_logged(mocker: MockerFixture, tmp_path: Path) -> None:
    """**Test steps:**

    * have the module's ``Instance`` raise
    * verify ``None`` comes back and a warning was logged
    """
    module = fake_vlc(str(tmp_path / "libvlc.dll"))
    setattr(module, "Instance", mocker.Mock(side_effect=RuntimeError("boom")))  # noqa: B010
    mocker.patch.dict(sys.modules, {"vlc": module})
    warning = mocker.patch(f"{MODULE}.LOG.warning")

    assert VlcLibrary.load(tmp_path / "libvlc.dll").instance() is None
    warning.assert_called_once()


@mark.parametrize("version", [b"nightly", "3.0.23 Vetinari"], ids=["unreadable", "text not bytes"])
def test_a_version_is_read_from_bytes_or_text_or_not_at_all(
    mocker: MockerFixture, tmp_path: Path, version: bytes | str
) -> None:
    """**Test steps:**

    * bind a module whose version is a nightly's, then one answering text
    * verify ``None`` for the first and the numbers for the second
    """
    library = tmp_path / "libvlc.dll"
    mocker.patch.dict(sys.modules, {"vlc": fake_vlc(str(library), version)})  # type: ignore[arg-type]

    assert VlcLibrary.load(library).version == (None if version == b"nightly" else (3, 0, 23))


def test_the_probe_writes_what_the_child_found(mocker: MockerFixture, tmp_path: Path) -> None:
    """**Test steps:**

    * probe with a module that binds, then with one whose instance is refused, then with an import that exits
    * verify each answer file: usable with the version and the bound path; not runnable with its reason
    """
    library = tmp_path / "libvlc.dll"
    output = tmp_path / "answer.json"
    good = fake_vlc(str(library))
    mocker.patch.dict(sys.modules, {"vlc": good})
    assert probe_libvlc(library, output) == 0
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "status": ToolStatus.USABLE.value,
        "version": [3, 0, 23],
        "reason": "",
        "library": str(library),
    }

    setattr(good, "Instance", lambda *options: None)  # noqa: B010
    probe_libvlc(library, output)
    answer = json.loads(output.read_text(encoding="utf-8"))
    assert answer["status"] == ToolStatus.NOT_RUNNABLE.value
    assert "no instance" in answer["reason"]

    sys.modules.pop("vlc")
    mocker.patch(f"{MODULE}.importlib.import_module", side_effect=SystemExit(1))
    probe_libvlc(library, output)
    answer = json.loads(output.read_text(encoding="utf-8"))
    assert answer["status"] == ToolStatus.NOT_RUNNABLE.value
    assert answer["library"] == ""
    assert "exited with 1" in answer["reason"]


def test_importlib_is_what_the_proxy_imports_with() -> None:
    """The import goes through ``importlib`` so a test can stand in for it; a plain ``import vlc`` would run at module
    load.

    **Test steps:**

    * read the proxy's module source
    * verify it has no ``import vlc`` statement
    """
    source = Path(importlib.import_module(MODULE).__file__ or "").read_text(encoding="utf-8")

    assert "import vlc\n" not in source
    assert "from vlc" not in source
