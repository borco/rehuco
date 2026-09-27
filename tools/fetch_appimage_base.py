"""Download the python-appimage base image the Linux AppImage build starts from, and print its file name.

python-appimage can resolve its own base image (``build app -p 3.14``), but it does so by calling the
GitHub API with no credentials and no way to pass any, so under CI it runs into the unauthenticated rate
limit. Nor can a fixed URL be pinned instead: each ``python3.X`` release is a rolling tag whose assets are
replaced in place on every CPython patch release, so yesterday's URL is gone tomorrow. This does the
lookup itself -- authenticated when ``GITHUB_TOKEN`` is set -- and hands python-appimage a local file.

The file is written under its own asset name, and the bare name is what gets printed: python-appimage
parses the Python version out of the ``--base-image`` string itself, which a full URL or a path with
``python`` in a directory name would throw off.
"""

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

RELEASES_API = "https://api.github.com/repos/niess/python-appimage/releases/tags/"
"""Where a base-image release's metadata is read from; the release tag is appended."""


def asset_pattern(abi_platform: str) -> re.Pattern[str]:
    """The asset names a release may carry for one ABI/platform tag, whatever its CPython patch version.

    :param abi_platform: e.g. ``cp314-cp314-manylinux_2_28_x86_64``.
    """
    return re.compile(rf"^python\d+\.\d+\.\d+-{re.escape(abi_platform)}\.AppImage$")


def find_asset(release: dict, abi_platform: str) -> dict:
    """Return the one asset of ``release`` built for ``abi_platform``.

    :param release: a release object as the GitHub API returns it.
    :param abi_platform: e.g. ``cp314-cp314-manylinux_2_28_x86_64``.
    :raises LookupError: when no asset, or more than one, matches.
    """
    pattern = asset_pattern(abi_platform)
    matches = [asset for asset in release["assets"] if pattern.match(asset["name"])]
    if len(matches) != 1:
        names = ", ".join(asset["name"] for asset in matches) or "none"
        raise LookupError(f"expected one {abi_platform} asset in {release['tag_name']}, found {names}")
    return matches[0]


def fetch_release(tag: str, token: str | None) -> dict:
    """Read one release's metadata from the GitHub API.

    :param tag: the release tag, e.g. ``python3.14``.
    :param token: a GitHub token, or ``None`` for an unauthenticated (rate-limited) request.
    """
    request = urllib.request.Request(RELEASES_API + tag, headers={"Accept": "application/vnd.github+json"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request) as response:  # nosec B310  # fixed https:// API URL
        return json.load(response)


def download(url: str, destination: Path) -> None:
    """Write ``url``'s content to ``destination`` and make it executable."""
    with urllib.request.urlopen(url) as response:  # nosec B310  # an https:// asset URL from the API
        destination.write_bytes(response.read())
    destination.chmod(0o755)


def main(argv: list[str] | None = None) -> int:
    """Make sure the current base image is in the output directory, and print its file name.

    :param argv: command-line arguments; ``None`` reads them from ``sys.argv``.
    :returns: process exit code.
    """
    parser = argparse.ArgumentParser(
        prog="fetch_appimage_base",
        description="Download the current python-appimage base image for one ABI/platform tag.",
    )
    parser.add_argument("tag", help="python-appimage release tag, e.g. python3.14")
    parser.add_argument("abi_platform", help="ABI and platform tag, e.g. cp314-cp314-manylinux_2_28_x86_64")
    parser.add_argument("directory", type=Path, help="directory to download the base image into")
    args = parser.parse_args(argv)

    try:
        asset = find_asset(fetch_release(args.tag, os.environ.get("GITHUB_TOKEN")), args.abi_platform)
    except LookupError as error:
        print(error, file=sys.stderr)
        return 1

    destination = args.directory / asset["name"]
    if not destination.exists():
        args.directory.mkdir(parents=True, exist_ok=True)
        download(asset["browser_download_url"], destination)
    print(asset["name"])
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
