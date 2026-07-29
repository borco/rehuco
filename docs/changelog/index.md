# Changelog

Every package keeps its own changelog, matching the per-package release tags (`<package>-X.Y.Z`) this
monorepo releases with — so a package's history travels with it, and renders on its own PyPI page. The
pages below include those files verbatim; the copy in the repository stays the only one there is.

| Package | What it is | Released |
| --- | --- | --- |
| [rehuco-agent](rehuco-agent.md) | The desktop editor — the only runnable program here | [![PyPI](https://img.shields.io/pypi/v/rehuco-agent)](https://pypi.org/project/rehuco-agent/) |
| [rehuco-core](rehuco-core.md) | Shared library: models, `.rehu` I/O, legacy `.tc` reading | [![PyPI](https://img.shields.io/pypi/v/rehuco-core)](https://pypi.org/project/rehuco-core/) |
| [rehuco-node](rehuco-node.md) | A reserved name; no service written yet | [![PyPI](https://img.shields.io/pypi/v/rehuco-node)](https://pypi.org/project/rehuco-node/) |
| [borco-core](borco-core.md) | Generic reusable classes with no GUI dependency | [![PyPI](https://img.shields.io/pypi/v/borco-core)](https://pypi.org/project/borco-core/) |
| [borco-pyside](borco-pyside.md) | Generic reusable PySide6/Qt classes and widgets | [![PyPI](https://img.shields.io/pypi/v/borco-pyside)](https://pypi.org/project/borco-pyside/) |

The two `borco-*` libraries are not rehuco-specific. They are developed in this monorepo for now and
will later move to their own repository, taking their changelogs with them.

Entries follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and each package follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). For `rehuco-agent`, a version's section is
also what a reader sees on its
[GitHub Release](https://github.com/borco/rehuco/releases) — the release body is built from the
changelog rather than written twice.
