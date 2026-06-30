#!/usr/bin/env bash
# Run inside quay.io/pypa/manylinux2014_aarch64.
# Creates a non-root user and re-execs as them so uv and the package install
# match the real deployment scenario ($HOME/.local/bin/uv, user-owned venv).
# A missing manylinux2014_aarch64 wheel or a glibc-version mismatch exits non-zero.
set -euo pipefail

# The manylinux container runs as root by default, but on the real TS-230 uv is
# installed as a normal user.  Re-exec as a dedicated user so paths and permissions
# mirror the actual deployment ($HOME/.local/bin/uv, user-owned venv).
if [ "$(id -u)" = "0" ]; then
    useradd -m canary
    SCRIPT="$(readlink -f "$0")"
    exec su -s /bin/bash - canary -c "exec bash \"$SCRIPT\""
fi

echo "=== Running as: $(id) ==="
echo "=== glibc: $(ldd --version | head -1) ==="
echo "=== arch:  $(uname -m) ==="
echo

echo "=== Installing uv ==="
# The uv installer extracts to a temp directory before moving the binary into place.
# On the TS-230, /tmp is a 64 MB RAM disk shared with system processes — exhausting it
# stops the RAM disk and requires a reboot to recover.  Always redirect TMPDIR to a
# persistent location before invoking the installer.  Normal uv operation (venv
# creation, package install) does not use TMPDIR, so this only applies here.
mkdir -p ~/tmp
export TMPDIR=~/tmp
curl -LsSf https://astral.sh/uv/install.sh | sh
unset TMPDIR
export PATH="$HOME/.local/bin:$PATH"
echo "uv $(uv --version)"
echo

VENV="$HOME/canary-venv"

echo "=== Creating venv (Python 3.13) ==="
uv venv --python 3.13 "$VENV"
echo "Python: $("$VENV/bin/python" --version)"
echo

echo "=== Installing direct dependencies ==="
uv pip install --python "$VENV/bin/python" \
    fastapi \
    "uvicorn[standard]" \
    zeroconf \
    cryptography \
    pydantic

echo "=== Installed versions ==="
uv pip list --python "$VENV/bin/python"
echo

echo "=== Smoke imports ==="
"$VENV/bin/python" - <<'EOF'
from importlib.metadata import version

import fastapi
import uvicorn
import zeroconf
import cryptography
import pydantic
import pydantic_core
import starlette
import anyio

print(f"  fastapi        {version('fastapi')}")
print(f"  uvicorn        {version('uvicorn')}")
print(f"  zeroconf       {version('zeroconf')}")
print(f"  cryptography   {version('cryptography')}")
print(f"  pydantic       {version('pydantic')}")
print(f"  pydantic-core  {version('pydantic-core')}")
print(f"  starlette      {version('starlette')}")
print(f"  anyio          {version('anyio')}")
print()
print("All imports OK")
EOF
