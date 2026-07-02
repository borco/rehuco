"""Coverage configurer plugin: on non-Windows, drop rehuco's Windows-only code from the report.

Runner-independent, unlike env vars set in the Makefile or conftest (those depend on *how* pytest
was launched, and pytest-cov reads the coverage config before conftest runs): coverage calls the
configurer at its own initialization, so this applies uniformly to ``make cov``, a bare
``pytest --cov``, and the VSCode / IDE test runner. On Windows nothing is dropped -- the Windows
test set measures that code on its own runner.

Registered via ``[tool.coverage.run] plugins`` in ``pyproject.toml``; importable because
``[tool.pytest.ini_options] pythonpath`` puts the repo root on ``sys.path``.
"""

import sys
from typing import Any

WINDOWS_ONLY_OMIT = "*/platforms/windows/*"
"""Glob for the wholly-Windows package to omit from the report off Windows."""

WINDOWS_ONLY_EXCLUDE = r'if sys\.platform == "win32":'
"""Regex matching the ``__main__`` win32 guard lines, whose blocks are excluded off Windows."""


class PlatformCoverageConfigurer:
    """Omits/excludes rehuco's Windows-only code from coverage when not running on Windows."""

    def configure(self, config: Any) -> None:
        """Append the Windows-only omit/exclude rules unless running on Windows.

        Appends to ``report:exclude_lines`` -- not ``report:exclude_also`` -- because coverage has
        already folded ``exclude_also`` into ``exclude_lines`` by the time the configurer runs;
        ``exclude_lines`` is the list actually matched against source.

        :param config: the coverage configuration to mutate in place.
        """
        if sys.platform == "win32":
            return

        omit = list(config.get_option("run:omit") or [])
        omit.append(WINDOWS_ONLY_OMIT)
        config.set_option("run:omit", omit)

        exclude = list(config.get_option("report:exclude_lines") or [])
        exclude.append(WINDOWS_ONLY_EXCLUDE)
        config.set_option("report:exclude_lines", exclude)


def coverage_init(reg: Any, options: Any) -> None:
    """Coverage plugin entry point: register the configurer.

    :param reg: the coverage plugin registration object.
    :param options: plugin options from the coverage config (unused).
    """
    reg.add_configurer(PlatformCoverageConfigurer())
