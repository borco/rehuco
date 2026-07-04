# §8. Multiplicity: Swarms and Nodes per Machine

[[[multiplicity]]]

## Overview

[[[multiplicity#overview]]]

- **One swarm per node process, always.** A node's identity, config, and data directory are scoped to exactly one swarm.
  This keeps every piece of state (registry, keys, cached catalog) free of an extra "which swarm" dimension that would
  otherwise have to thread through everything.
- **Multiple node processes per machine** are fully supported and require no special design — each is just an ordinary
  node with its own config/data directory, own identity, own port, and own zeroconf service name (to avoid mDNS
  collisions). This covers both "two swarms on one box" and any future case of separating folder groups onto distinct
  processes.
- **Folder-group separation within a single swarm does not need separate node processes.** A single node can watch/serve
  multiple folder roots as plain configuration. Splitting into separate processes is only justified by independent
  restart/update needs, materially different storage reliability per folder set, or future performance scaling — none of
  which apply today.

## §8.1 The single node is the base case, not a special case

[[[multiplicity#single-node-base]]]

Every swarm is single-node at birth (creating a swarm = minting a swarm ID, [[discovery-trust-access#swarm-id]], with no
peers yet), and a swarm may **legitimately stay single-node forever** — someone who just wants the app on one box. This
is a first-class supported mode, not a degraded form of multi-node:

- **A lone node is its own registry authority.** The registry-home model ([[discovery-trust-access#registry-home]])
  degenerates cleanly to one node: *this* node holds the swarm registry, users, access rules, and instance registry, and
  the resolution sequence short-circuits (no preferred authority needed, no peers to chatter with). The agent must not
  hunt the network for an authority and hang when there isn't one.
- **A lone node serves immediately and confidently.** The serve-after-resync gate
  ([[discovery-trust-access#serve-after-resync]]) must treat "I am the registry authority" as instantly satisfied, *not*
  as "I failed to reach peers, falling back." Same outcome, but a one-node install must never pause on a discovery
  timeout waiting for peers that will never answer — that would be a bug born of treating single-node as degraded
  multi-node.
- **Create-swarm and single-node-forever are the same path.** "Single-node forever" is just "created a swarm and never
  invited anyone." Multi-node is the *elaboration*; the base case is one fully-functional node that serves,
  authenticates, and enforces access entirely on its own.
