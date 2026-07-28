#! /bin/bash
# Invokes the real `rehuco-agent` console-script entry point pip installs into the AppImage's own
# opt/pythonX.Y/bin/ (not a bare .py path) -- python-appimage substitutes {{ python-executable }} and
# {{ python-version }} from the base runtime it built against. -I: isolated mode, so a host PYTHONPATH
# or other Python env var can never leak into a packaged app ([[appendices.briefcase-packaging#linux-backends]]).
{{ python-executable }} -I "${APPDIR}/opt/python{{ python-version }}/bin/rehuco-agent" "$@"
