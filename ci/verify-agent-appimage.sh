#!/usr/bin/env bash
# Run inside a bare ubuntu:24.04 container, against the already-built AppImage mounted read-only at
# /artifact/rehuco-agent-x86_64.AppImage. Answers this issue's real acceptance criterion: does PySide6
# actually start under QT_QPA_PLATFORM=offscreen on a system that carries nothing but a documented base
# package set -- not just this dev machine's own desktop libraries, and not just qa.yml's own runner
# (ubuntu-latest ships far more preinstalled than a bare `ubuntu:24.04` image does).
#
# The package list below is the *bare-container* floor, found by actually running this script against
# successive ImportErrors rather than assumed from qa.yml's smaller set (libgl1/libegl1/libxkbcommon0,
# [[appendices.continuous-integration#missing-qt-libs]]) -- that set is sufficient on GitHub's
# ubuntu-latest runner only because its much larger preinstalled image already carries glib/fontconfig/
# dbus/krb5 as some other package's transitive dependency, which a genuinely bare container does not.
# Four more libraries were missing here, one import at a time: libglib-2.0.so.0 (QtCore itself),
# libfontconfig.so.1 and libdbus-1.so.3 (both from QtGui), libgssapi_krb5.so.2 (from pyside6-qtads).
#
# --appimage-extract-and-run rather than a FUSE mount: libfuse2 isn't installed by default on Ubuntu
# 24.04+, and a container has no /dev/fuse without extra --device/--cap-add flags a bare-container check
# should not need (docs/specs/packaging-deployment.md, [[packaging-deployment#linux-format]] point 5).
#
# A liveness check, not a clean exit: the app is a single-instance GUI event loop with no ".rehu" to
# open, so there is nothing for it to do but sit in Application.exec() -- confirming it is still running
# a few seconds in (no crash, no segfault) is the same headless-start proof qa.yml's own test suite
# relies on, applied to the packaged artifact instead of the dev venv.
set -euo pipefail

APPIMAGE=/artifact/rehuco-agent-x86_64.AppImage

echo "=== Installing the bare-container headless-Qt floor ==="
apt-get update -qq
apt-get install -y --no-install-recommends \
    libgl1 libegl1 libxkbcommon0 libglib2.0-0 libfontconfig1 libdbus-1-3 libgssapi-krb5-2 >/dev/null
echo

echo "=== Starting under QT_QPA_PLATFORM=offscreen ==="
export QT_QPA_PLATFORM=offscreen
export HOME=/root
"$APPIMAGE" --appimage-extract-and-run &
pid=$!

sleep 5

if kill -0 "$pid" 2>/dev/null; then
    echo "OK: still running 5s after launch (no crash, no missing-library import failure)"
    kill "$pid"
    wait "$pid" 2>/dev/null || true
    exit 0
fi

echo "FAILED: process exited before the liveness check" >&2
wait "$pid"
exit_code=$?
echo "exit code: $exit_code" >&2
exit 1
