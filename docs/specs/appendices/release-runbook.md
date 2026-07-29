# Release Runbook — Cutting a Release

[[[appendices.release-runbook]]]

## Overview

[[[appendices.release-runbook#overview]]]

The step-by-step for shipping a release, written to be followed rather than reasoned about. One tag does it:
`<package>-X.Y.Z` publishes that package to PyPI (`publish-packages.yml`), and for `rehuco-agent` — the one
package with installers — the same tag additionally builds the Windows, macOS and Linux artifacts and
attaches them to a GitHub Release (`release-agent.yml`).

Why the workflows have the shape they do — tag-triggered rather than push/PR, version read rather than
hand-typed, build jobs split per platform, TestPyPI ahead of PyPI — is in
[[appendices.continuous-integration#release-agent]] and
[[appendices.continuous-integration#publish-packages]]; the artifact formats themselves are in
[[appendices.briefcase-packaging#linux-backends]].

> [!NOTE]
> One release has been cut so far: `rehuco-agent-0.1.0` on 2026-07-29, which ran `release-agent.yml` to a
> GitHub Release carrying all three installers. `publish-packages.yml` has published nothing yet — it
> arrived after that tag — so what sits on PyPI is still the `0.0.x` name-reservation stubs described in
> section 1.

Both workflows read the same tag, so releasing a package is one push either way; the difference is only how
much a tag produces. `rehuco-agent` is the only package with installers and the only one whose changelog
becomes a GitHub Release body. The other four are PyPI-only: their tags run `publish-packages.yml` alone.

## 1. The version lives in exactly one file

[[[appendices.release-runbook#version-source]]]

`__version__` in the package's own `packages/<package>/src/<module>/__init__.py` — for the agent, that is
`packages/rehuco-agent/src/rehuco_agent/__init__.py`. Nothing else carries it: `pyproject.toml` declares the
version `dynamic` and points hatchling at that file, both workflows read the same constant, and every
artifact name is derived from what they read.

On a tag push each workflow strips the version off the tag name and **fails the whole run** if the remainder
isn't equal to that constant. That guard is the reason for the step ordering below — the bump has to be
committed *before* the tag is pushed, because the tag is checked against the committed file.

> [!IMPORTANT]
> That check compares the tag against `__version__` and nothing else — it does not know what PyPI already
> holds. `rehuco-core`, `rehuco-node` and `rehuco-agent` each published `0.0.0` and `0.0.1` stubs in June
> 2026 to reserve their names, before this repository had any Python packages in it, so those two versions
> are spent, as are `borco-core`'s and `borco-pyside`'s `0.0.1` and `0.0.2`. Reusing one passes the tag
> check, publishes a GitHub Release that disagrees with the PyPI release of the same number, and then fails
> outright at the upload, because PyPI refuses to re-upload a version that exists. Nothing is silently
> replaced — but the GitHub half is public by then, so the answer is always a new version, never a reused
> one ([[appendices.release-runbook#tagged-run]]).

## 2. Dry-run the workflows first

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

Actions → **Publish packages** → **Run workflow** is the same idea for publishing, and it takes the package
name as an input because there is no tag to read it from. It builds that package's sdist and wheel, verifies
the generated Qt modules are inside the wheel, and uploads to **TestPyPI only**: `Publish to PyPI` is gated on
the ref being a tag, so a manual run cannot reach pypi.org. Worth doing for a package whose PyPI publishing
has never run — the trusted-publisher wiring is the part that fails on its first real use, and this is where
that failure is free ([[appendices.release-runbook#pypi-setup]]).

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

The steps are the same for any of the five packages; `rehuco-agent` is used throughout as the example.

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

The tag must be `<package>-X.Y.Z`. `publish-packages.yml` triggers on `*-[0-9]+.[0-9]+.[0-9]+` and reads the
package name out of the tag, so that one form covers all five; `release-agent.yml` triggers on the narrower
`rehuco-agent-*.*.*`, which is why an agent tag fires both workflows and any other package's fires only the
publish.

## 5. What the tagged run does, and how to redo it

[[[appendices.release-runbook#tagged-run]]]

In `publish-packages.yml`: the package is resolved and checked against the tag, its sdist and wheel are built,
and both are uploaded to TestPyPI and then to PyPI. In `release-agent.yml`, for an agent tag: the same four
build jobs as a dry run, and then `release` publishes — it downloads every artifact and either creates the
GitHub Release, body included from the changelog ([[appendices.release-runbook#release-notes]]), or, if one
already exists for that tag, uploads over it with `--clobber` and rewrites the body.

**Re-running an agent tag is safe on the GitHub side and fails on the PyPI side**, by design: the Release is
refreshed rather than duplicated, while PyPI refuses a version it already holds, so the `Publish to PyPI` job
ends red. That is the intended asymmetry — a red job is how a spent version number announces itself
([[appendices.release-runbook#version-source]]) — and nothing is left half-done by it: the packages either
went up on the first run or never did.

To redo a release whose *content* was wrong, move the tag rather than inventing a version:

```sh
git tag -d rehuco-agent-0.1.0
git push origin :refs/tags/rehuco-agent-0.1.0
# fix, commit, then re-tag and push as in section 4
```

If the run failed because the tag and `__version__` disagreed, nothing was published — the `version` job fails
before any build starts.

## 6. PyPI publishing, and the one-time setup it needs

[[[appendices.release-runbook#pypi-setup]]]

`publish-packages.yml` authenticates by **trusted publishing**: the job asks GitHub for a short-lived OIDC
token and PyPI trades it for an upload, so there is no API token in a repository secret or on a maintainer's
machine to rotate or leak. What makes that work is configuration held outside git, in two places, and a tag
whose package has none of it fails at the upload step with an authentication error.

**In this repository** — Settings → Environments → New environment — two environments, named `testpypi` and
`pypi`. No protection rules are needed; they exist so a trusted publisher can be bound to one specific job
rather than to the repository as a whole.

**On each index** — <https://test.pypi.org/manage/account/publishing/> and
<https://pypi.org/manage/account/publishing/> — one publisher per package per index, ten in all:

| Field | Value |
| --- | --- |
| PyPI project name | `borco-core`, `borco-pyside`, `rehuco-core`, `rehuco-node` or `rehuco-agent` |
| Owner | `borco` |
| Repository name | `rehuco` |
| Workflow filename | `publish-packages.yml` |
| Environment name | `testpypi` on TestPyPI, `pypi` on PyPI |

All five projects already exist on pypi.org, so their publishers are added under each project's **Settings →
Publishing** rather than through the pending-publisher form. On TestPyPI they may not exist at all — its
namespace is entirely separate from pypi.org's, and a name held on one is not reserved on the other — so
those go in as *pending* publishers, which create the project on the first successful upload.

Once a package has published, the install is worth a check from a throwaway environment. TestPyPI hosts none
of the dependencies, so it has to be the primary index with real PyPI behind it:

```sh
uv run --no-project --with rehuco-core==X.Y.Z \
  --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ \
  --index-strategy unsafe-best-match \
  python -c "import rehuco_core"
```

`--index-strategy unsafe-best-match` is not optional here, and the reason is worth knowing before it bites:
by default uv considers only the versions on the *first* index that carries a package at all, so that a
lower-priority index cannot answer for a name the primary one owns. Every package in this workspace exists on
real PyPI already, at an older version, so the default lookup finds the name there, fails to find the version
being tested, and stops -- `A compatible version may be available on a subsequent index`. The flag widens the
search to both indexes. Its name is a fair warning in general, but this is a throwaway environment resolving
one pinned version of a package published minutes earlier, which is the case it costs nothing in.

## 7. What a release does not include yet

[[[appendices.release-runbook#gaps]]]

- **Code-signing and notarization** are not done — an unpriced prerequisite
  ([[appendices.open-questions#still-open]]). Downloaders will meet SmartScreen on Windows and Gatekeeper on
  macOS, and have to override both by hand.
- **`make publish` is still there**, and is the bulk-publish path `publish-packages.yml` exists to replace —
  `uv build --all-packages` followed by `uv publish`, which uploads every package whose local version is
  ahead of PyPI. It stays only until the tag-triggered publish has published something for real, so that the
  repository is never left with no publishing path at all
  ([[appendices.continuous-integration#publish-packages]]).
- **No auto-update.** Each release is a fresh download and install.

## 8. Windows packaged builds print nothing

[[[appendices.release-runbook#windows-console]]]

`Rehuco.exe` is a GUI-subsystem binary, which is deliberate — a console-subsystem build would flash a console
window every time a `.rehu` file is opened from Explorer. The consequence is that the packaged Windows build
emits no console output: `Rehuco.exe --version` and `--info` print nothing to a terminal, to a pipe, or into a
redirect, even though both flags run and exit correctly (a bad flag still exits `2`, as argparse intends).

This is specific to the packaged build. From a source checkout the same flags print normally, because the
`rehuco-agent` console script is a console-subsystem executable:

```sh
uv run rehuco-agent --version   # -> version: 0.1.0
```

So on Windows, a packaged build's `--version`/`--info` tell you only whether the app started successfully (exit
code `0`), never what it would have printed; use a source checkout when the printed answer is what's wanted.
