"""rehuco-node: the reserved name for a future headless rehuco node.

Nothing is implemented here. The package exists so the name on PyPI is held and the release
plumbing is exercised alongside the others; a node -- a REST service answering for the resources
one machine owns ([[nodes#local-vs-swarm]]) -- is intended, unscheduled, and may never be written.
"""

__version__ = "0.0.1"

__all__ = ["__version__"]
