# tools

Scripts that serve the repository: the docs build, the release build, a checksum check, a few probes and one-off
helpers. Plain files, not an installed package: run them from the repository root through `uv`, so they see the
workspace's packages and dev tools.

```text
uv run python tools/<script>.py [arguments]
```

Each script's module docstring is the full account of what it does and why; `--help` lists its options. Tests are in
[tests/](tests/) and run with the rest (`make tests`).

## For using rehuco's data

### verify_checksums.py

Verifies `.checksum` records without the app and without writing anything: no verification date, no adopted file, no
pruned entry, no lock. A share the app is using sees nothing of the run, and a read-only disk can be checked.

```text
uv run python tools/verify_checksums.py PATH [PATH ...]
```

Each `PATH` is a `.checksum` file or a folder; a folder stands for every `.checksum` under it, at any depth.

| Option | Meaning |
| --- | --- |
| `--no-recursive` | only the `.checksum` files directly in a folder |
| `--show-without-checksum` | also list the content files a record does not list |
| `--no-checksum` | hash nothing: only check that each listed file exists |
| `--exclude GLOB` | leave `GLOB` out for this run, besides the app's excluded files |
| `--settings-dir DIR` | read the app's settings from `DIR`, as `rehuco-agent --settings-dir` does |
| `--quiet` / `--verbose` | only records with a finding, or every file named |

The excluded files are the app's current list, read from its settings; the first line printed names the settings
folder and the patterns in use. Exit status: 0 nothing found; 1 a file mismatched, is missing or could not be read (or
`--show-without-checksum` listed one); 2 a path or a record could not be read at all; 130 stopped with Ctrl+C.

## Build and release

These run from the Makefile or the release workflow; run one by hand to try a build step on its own.

| Script | What it does | Use |
| --- | --- | --- |
| `prune_pyside_addons.py` | cuts the PySide6-Addons wheel in a built bundle down to what in-app playback needs | `make agent-dist-build` runs it on the bundle's `app_packages` folder, before `briefcase package` |
| `set_long_path_aware.py` | declares the Windows executable of a build long-path aware | `make agent-dist-build` runs it on the stub after `briefcase build`; by hand: `tools/set_long_path_aware.py <Rehuco.exe>` |
| `fetch_appimage_base.py` | downloads the python-appimage base image and prints its file name | `tools/fetch_appimage_base.py TAG ABI_PLATFORM DIRECTORY`; `GITHUB_TOKEN` authenticates the lookup |
| `extract_changelog.py` | prints one version's section of a Keep a Changelog file, for the GitHub Release notes | `tools/extract_changelog.py CHANGELOG.md 0.5.0`; fails when the section is missing or empty |

## Docs

| Script | What it does | Use |
| --- | --- | --- |
| `check_slug_refs.py` | checks every `[[doc#slug]]` cross-reference resolves to exactly one declaration | `make check-slugs`, part of `make qa` |
| `mkdocs_slug_ref_hook.py` | styles cross-reference tokens on the published site | a `hooks:` entry in `mkdocs.yml`; not run by hand |
| `mkdocs_relative_link_hook.py` | rewrites relative links that leave `docs/` to absolute repository links at build time | a `hooks:` entry in `mkdocs.yml`; not run by hand |
| `clean_window_corners.py` | crops a Windows 11 window screenshot to the window and restores its rounded corners | `tools/clean_window_corners.py IMAGE [IMAGE ...]`; keeps a `.orig` backup unless `-o`; `-r` sets the radius |

## Windows machine setup

PowerShell scripts, run from the repository root.

| Script | What it does | Use |
| --- | --- | --- |
| `add_recycle_bin.ps1` | gives a mapped network drive a Recycle Bin | `.\tools\add_recycle_bin.ps1 T`; one UAC prompt, only when the drive has no definition yet |
| `restart_explorer.ps1` | restarts Explorer so open windows see a shell change | `.\tools\restart_explorer.ps1`; closes every File Explorer window |

## Probes and helpers

| Script | What it does | Use |
| --- | --- | --- |
| `stress_pool_relay.py` | stresses the race between a pool job's answer and the GUI thread deleting its owner | `tools/stress_pool_relay.py relay` must survive; `direct` is expected to crash. Run it after changing a loader's hand-off to the GUI thread |
| `shopping_fab.py` | adds the free Fab listings of a results page to the account's library, one at a time | `python -I tools/shopping_fab.py [--profile PROFILE] [URL]`; needs Firefox and geckodriver, and never buys. Without a `URL` it opens the persona browser to sign in |
