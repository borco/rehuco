# Packages

rehuco is published as three separate packages on PyPI.

| Package | Description | PyPI |
| --- | --- | --- |
| [rehuco-agent](https://pypi.org/project/rehuco-agent/) | PySide6 desktop GUI | [![PyPI](https://img.shields.io/pypi/v/rehuco-agent)](https://pypi.org/project/rehuco-agent/) |
| [rehuco-core](https://pypi.org/project/rehuco-core/) | Shared library: models, `.rehu` I/O, sync primitives | [![PyPI](https://img.shields.io/pypi/v/rehuco-core)](https://pypi.org/project/rehuco-core/) |
| [rehuco-node](https://pypi.org/project/rehuco-node/) | Headless REST node | [![PyPI](https://img.shields.io/pypi/v/rehuco-node)](https://pypi.org/project/rehuco-node/) |

## Generic libraries (temporarily hosted)

Two generic, reusable libraries under the author's `borco` namespace live in this monorepo for now. They are
**not rehuco-specific** and are scheduled to move to their own repository once their APIs settle — do not rely on
their location here. Not yet published to PyPI.

| Package | Description |
| --- | --- |
| `borco-core` | Generic reusable classes with no GUI dependency |
| `borco-pyside` | Generic reusable PySide6/Qt classes (e.g. `ApplicationSingleton`) |
