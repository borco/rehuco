"""rehuco-node: the local node, a process the agent runs beside itself for as long as it runs (#506).

Today the node keeps a heartbeat file and a log under the folder it shares with the agent, and stops when the
agent does. The agent's System Integration page turns it on and off and shows whether it runs. What the node will
serve on top of that lifecycle is design, not code ([[nodes]]).
"""

__version__ = "0.0.1"

__all__ = ["__version__"]
