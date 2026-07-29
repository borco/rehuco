# Release Runbook — Cutting a `rehuco-agent` Release

[[[appendices.release-runbook]]]

## Overview

[[[appendices.release-runbook#overview]]]

The step-by-step for shipping a `rehuco-agent` release, written to be followed rather than reasoned about.
Why the workflow has the shape it does — tag-triggered rather than push/PR, version read rather than
hand-typed, build jobs split per platform — is in [[appendices.continuous-integration#release-agent]]; the
artifact formats themselves are in [[appendices.briefcase-packaging#linux-backends]].

> [!NOTE]
> No release has been cut from this repository yet. `release-agent.yml` has so far only been exercised
> through `workflow_dispatch` dry runs, which build every artifact but publish nothing. The `0.0.0` and
> `0.0.1` versions already on PyPI predate the packages themselves — see section 1.

`rehuco-agent` is the only package with installers, so it is the only one with a release workflow. The other
four packages release through PyPI publishing (#18), which is a separate, not-yet-built workflow.

## 1. The version lives in exactly one file

[[[appendices.release-runbook#version-source]]]

`__version__` in `packages/rehuco-agent/src/rehuco_agent/__init__.py`. Nothing else carries it: the workflow
reads that constant, and every artifact name is derived from what it read.

On a tag push the `version` job strips the `rehuco-agent-` prefix off the tag name and **fails the whole run**
if the remainder isn't equal to that constant. That guard is the reason for the step ordering below — the bump
has to be committed *before* the tag is pushed, because the tag is checked against the committed file.

> [!IMPORTANT]
> That check compares the tag against `__version__` and nothing else — it does not know what PyPI already
> holds. `rehuco-core`, `rehuco-node` and `rehuco-agent` each published `0.0.0` and `0.0.1` stubs in June
> 2026 to reserve their names, before this repository had any Python packages in it, so those two versions
> are spent. Reusing one would pass the tag check, publish a GitHub Release that disagrees with the PyPI
> release of the same number, and — once #18 lands and publishes from the same tag — fail outright, because
> PyPI refuses to re-upload a version that exists.

## 2. Dry-run the workflow first

[[[appendices.release-runbook#dry-run]]]

Actions → **Release agent** → **Run workflow**. This is the sanity check: every build job runs and uploads its
artifact, and `Publish GitHub Release` is skipped, because that job is gated on
`startsWith(github.ref, 'refs/tags/')` and a `workflow_dispatch` run never satisfies it. A dry run therefore
cannot create or modify a Release no matter how it goes. The flip side is that a dry run proves nothing about
the `release` job — the changelog section is never extracted, so a missing one surfaces only on the real tag.

What the run proves, per job:

| Job | Builds | Smoke-checked with |
| --- | --- | --- |
| `Determine version` | — | reads `__version__`; on a tag, matches it against the tag |
| `Windows installer` | `Rehuco-*.msi` | the built `Rehuco.exe` starts (see the caveat below) |
| `macOS app` | `Rehuco-*.dmg` | the built `Rehuco.app` starts |
| `Linux AppImage` | `rehuco-agent-x86_64.AppImage` | starts; Qt starts headless in a bare `ubuntu:24.04`; `--register`/`--unregister` |

The artifacts are downloadable from the run summary, so a dry run is also how a maintainer gets a build to try
by hand before committing to a version number.

> [!NOTE]
> The Windows smoke check asserts the process exit code, not its output. A packaged Windows build produces no
> console output at all — see [[appendices.release-runbook#windows-console]].

## 3. The release body comes from the changelog

[[[appendices.release-runbook#release-notes]]]

Changelogs are per package, matching the per-package release tags, so a package's history travels with it
and renders on its own PyPI page. `rehuco-agent`'s lives at `packages/rehuco-agent/CHANGELOG.md`, in
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) form; the root `CHANGELOG.md` is only an index
pointing at it, and the published site includes the same file rather than keeping a second copy.

The `release` job runs `tools/extract_changelog.py` to pull out the `## [X.Y.Z]` section for the version
being released and feeds it to `gh release create --notes-file`. So the release body is text that was
reviewed in a normal commit, not typed at release time.

Two consequences worth knowing before tagging:

- **A missing or empty section fails the job.** That is deliberate — a blank release body looks exactly
  like one nobody got around to writing, and the mistake is only visible after publishing. The build jobs
  all run first, so this fails at the last step, after the artifacts exist but before anything is public.
- **Re-running a tag refreshes the body**, not just the assets, so fixing a changelog entry and
  re-running actually updates what readers see.

## 4. Cut the release

[[[appendices.release-runbook#cut-the-release]]]

1. In `packages/rehuco-agent/CHANGELOG.md`, turn the `## [Unreleased]` entries into a dated section for
   the new version — `## [X.Y.Z] - YYYY-MM-DD` — and leave a fresh empty `## [Unreleased]` above it.
2. Bump `__version__` in `packages/rehuco-agent/src/rehuco_agent/__init__.py`.
3. Commit both. On `master` the message carries no `refs` prefix; `repo:` is the fitting type prefix for a
   release chore.
4. Tag that commit and push the tag:

```sh
git tag rehuco-agent-0.1.0
git push origin rehuco-agent-0.1.0
```

The tag must be `rehuco-agent-X.Y.Z` — the workflow's trigger is `rehuco-agent-*.*.*`, and the same
`<package>-<version>` scheme is what #18 settled for all five packages, so one day this single push is meant to
fire both the installer workflow and PyPI publishing.

## 5. What the tagged run does, and how to redo it

[[[appendices.release-runbook#tagged-run]]]

The same four build jobs run, and then `release` publishes: it downloads every artifact and either creates the
GitHub Release — body included, from the changelog ([[appendices.release-runbook#release-notes]]) — or, if one
already exists for that tag, uploads over it with `--clobber` and rewrites the body. Re-running the same
tag is therefore safe and simply refreshes the assets rather than failing on "already exists".

To redo a release whose *content* was wrong, move the tag rather than inventing a version:

```sh
git tag -d rehuco-agent-0.1.0
git push origin :refs/tags/rehuco-agent-0.1.0
# fix, commit, then re-tag and push as in section 4
```

If the run failed because the tag and `__version__` disagreed, nothing was published — the `version` job fails
before any build starts.

## 6. What a release does not include yet

[[[appendices.release-runbook#gaps]]]

- **Code-signing and notarization** are not done — an unpriced prerequisite
  ([[appendices.open-questions#still-open]]). Downloaders will meet SmartScreen on Windows and Gatekeeper on
  macOS, and have to override both by hand.
- **PyPI publishing** (#18) is a separate workflow that does not exist yet, so a tag today ships installers
  only.
- **No auto-update.** Each release is a fresh download and install.

## 7. Windows packaged builds print nothing

[[[appendices.release-runbook#windows-console]]]

`Rehuco.exe` is a GUI-subsystem binary, which is deliberate — a console-subsystem build would flash a console
window every time a `.rehu` file is opened from Explorer. The consequence is that the packaged Windows build
emits no console output: `Rehuco.exe --version` and `--info` print nothing to a terminal, to a pipe, or into a
redirect, even though both flags run and exit correctly (a bad flag still exits `2`, as argparse intends).

This is specific to the packaged build. From a source checkout the same flags print normally, because the
`rehuco-agent` console script is a console-subsystem executable:

```sh
uv run rehuco-agent --version   # -> version: 0.0.1
```

So on Windows, a packaged build's `--version`/`--info` tell you only whether the app started successfully (exit
code `0`), never what it would have printed; use a source checkout when the printed answer is what's wanted.
