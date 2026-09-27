"""Tests for the python-appimage base-image fetcher used by the Linux AppImage build."""

import io
import json
from pathlib import Path

from pytest import mark, raises
from pytest_mock import MockerFixture

from tools import fetch_appimage_base

# region Fixtures / helpers

ABI = "cp314-cp314-manylinux_2_28_x86_64"


def release(*names: str) -> dict:
    """A GitHub release object carrying assets with these names."""
    return {
        "tag_name": "python3.14",
        "assets": [{"name": name, "browser_download_url": f"https://example.invalid/{name}"} for name in names],
    }


def response(payload: bytes) -> io.BytesIO:
    """A stand-in for ``urlopen``'s context-manager response."""
    return io.BytesIO(payload)


# endregion

# region find_asset tests


def test_find_asset_picks_the_one_matching_asset_whatever_its_patch_version() -> None:
    """The free-threaded build and other architectures sit in the same release and must not match."""
    found = fetch_appimage_base.find_asset(
        release(
            "python3.14.7-cp314-cp314t-manylinux_2_28_x86_64.AppImage",
            f"python3.14.7-{ABI}.AppImage",
            "python3.14.7-cp314-cp314-manylinux_2_28_aarch64.AppImage",
        ),
        ABI,
    )
    assert found["name"] == f"python3.14.7-{ABI}.AppImage"


@mark.parametrize(
    "names",
    [
        (),
        (f"python3.14.6-{ABI}.AppImage", f"python3.14.7-{ABI}.AppImage"),
    ],
    ids=["none", "two"],
)
def test_find_asset_refuses_anything_but_exactly_one_match(names: tuple[str, ...]) -> None:
    """Guessing between two candidates would silently change the runtime the AppImage ships."""
    with raises(LookupError):
        fetch_appimage_base.find_asset(release(*names), ABI)


# endregion

# region fetch_release tests


@mark.parametrize("token", ["secret", None])
def test_fetch_release_authenticates_only_when_given_a_token(mocker: MockerFixture, token: str | None) -> None:
    """A local build has no token and still works, within the unauthenticated rate limit."""
    urlopen = mocker.patch.object(
        fetch_appimage_base.urllib.request, "urlopen", return_value=response(json.dumps(release()).encode())
    )
    assert fetch_appimage_base.fetch_release("python3.14", token) == release()
    request = urlopen.call_args.args[0]
    assert request.full_url == fetch_appimage_base.RELEASES_API + "python3.14"
    assert request.get_header("Authorization") == (f"Bearer {token}" if token else None)


# endregion

# region main tests


def run_main(mocker: MockerFixture, *, exists: bool, token: str | None = None) -> tuple[int, dict]:
    """Run ``main()`` against a mocked API and filesystem; return the exit code and the mocks."""
    name = f"python3.14.7-{ABI}.AppImage"
    if token is None:
        mocker.patch.dict(fetch_appimage_base.os.environ, clear=True)
    else:
        mocker.patch.dict(fetch_appimage_base.os.environ, {"GITHUB_TOKEN": token}, clear=True)
    mocks = {
        "fetch": mocker.patch.object(fetch_appimage_base, "fetch_release", return_value=release(name)),
        "download": mocker.patch.object(fetch_appimage_base, "download"),
        "mkdir": mocker.patch.object(Path, "mkdir"),
    }
    mocker.patch.object(Path, "exists", return_value=exists)
    code = fetch_appimage_base.main(["python3.14", ABI, "out"])
    return code, mocks


def test_main_downloads_a_missing_base_image_and_prints_its_bare_name(mocker: MockerFixture, capsys) -> None:
    """The bare name is what python-appimage can parse a version out of; a path or URL is not."""
    code, mocks = run_main(mocker, exists=False, token="secret")
    name = f"python3.14.7-{ABI}.AppImage"
    assert code == 0
    mocks["fetch"].assert_called_once_with("python3.14", "secret")
    mocks["download"].assert_called_once_with(f"https://example.invalid/{name}", Path("out") / name)
    assert capsys.readouterr().out == f"{name}\n"


def test_main_reuses_a_base_image_already_downloaded(mocker: MockerFixture, capsys) -> None:
    """A local rebuild skips the ~50 MB download; with no token the lookup goes out unauthenticated."""
    code, mocks = run_main(mocker, exists=True)
    assert code == 0
    mocks["fetch"].assert_called_once_with("python3.14", None)
    mocks["download"].assert_not_called()
    mocks["mkdir"].assert_not_called()
    assert capsys.readouterr().out == f"python3.14.7-{ABI}.AppImage\n"


def test_main_fails_when_the_release_has_no_matching_asset(mocker: MockerFixture, capsys) -> None:
    """Failing names the problem on stderr and downloads nothing."""
    mocker.patch.object(fetch_appimage_base, "fetch_release", return_value=release())
    download = mocker.patch.object(fetch_appimage_base, "download")
    assert fetch_appimage_base.main(["python3.14", ABI, "out"]) == 1
    download.assert_not_called()
    assert "found none" in capsys.readouterr().err


# endregion

# region download tests


def test_download_writes_the_bytes_and_marks_the_file_executable(mocker: MockerFixture) -> None:
    """python-appimage runs the base image to extract it, so it has to be executable."""
    mocker.patch.object(fetch_appimage_base.urllib.request, "urlopen", return_value=response(b"ELF"))
    write_bytes = mocker.patch.object(Path, "write_bytes")
    chmod = mocker.patch.object(Path, "chmod")
    fetch_appimage_base.download("https://example.invalid/base.AppImage", Path("out/base.AppImage"))
    write_bytes.assert_called_once_with(b"ELF")
    chmod.assert_called_once_with(0o755)


# endregion
