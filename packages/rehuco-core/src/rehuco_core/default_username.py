"""The username a fresh install files its own edits under ([[field-schema#per-user-shared]], #412)."""

import getpass

from .plugins import DEFAULT_CURRENT_USERNAME


def default_username() -> str:
    """The default **current** username: the OS login name, or :data:`~rehuco_core.DEFAULT_CURRENT_USERNAME`
    (``admin``) when the platform can't produce one.

    :returns: the current username an install with nothing persisted yet starts with.
    """
    try:
        return getpass.getuser()
    except OSError:
        return DEFAULT_CURRENT_USERNAME
