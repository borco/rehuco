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

## §8.2 Node instances on one machine, and one owner per root

[[[multiplicity#instances]]]

- [#409: docs: access seam, owning-node rule, views, node hosting and instances](https://github.com/borco/rehuco/issues/409)

**An instance is a named folder.** Each node process on a machine is an *instance*, with a folder
`nodes/<name>/` under the app's data folder ([[packaging-deployment#app-folders]]) holding:

- a small **node config file** — its swarm, its port and listen address, and which `.rehuco` it serves; the
  `.rehuco` stays the list of roots, so roots are declared in one place;
- its **own data** — identity certificate ([[discovery-trust-access#node-identity-pairing]]), `.rehusw`, `.rehudb`,
  retention store, task queue, change journal.

It starts as `rehuco-node serve --instance <name>`: a systemd template unit (`rehuco-node@<name>`) on Linux; on Windows
a log-on task per instance (no admin rights, and tied to that user's app folder) or a service. The node an agent hosts
([[nodes#two-roles]]) is one instance like any other. **Different users are not a reason for an instance** — users and
access rules are per swarm ([[discovery-trust-access#access-control]]); separate instances are for separate swarms, or
the independent-restart and storage-reliability reasons of the overview.

**Every root folder has exactly one owner** — one node instance (and so one swarm), or, for a root no node serves, the
agent that lists it. Two owners would be two writers ([[data-model#write-integrity]]), so it is refused rather than
handled:

- **The claim lives in the folder.** Adding a root writes a claim beside the fingerprint
  ([[mounts-and-storage#fingerprint-map]]) naming the owner: node, swarm, or agent. Adding a folder someone else
  already claims is refused, naming the owner — the choices are to reach it through that owner, or an explicit,
  admin-only **transfer** that releases the first claim.
- **Roots don't overlap.** A root inside another owner's root, or containing one, is refused, so no file has two
  owners.
- **Outside its owner's swarm, a file is read-only.** An agent opening a `.rehu` under a root claimed by a swarm it is
  not working in opens it read-only and names the owner — it can tell from the claim, so it does not write.
- **One check for processes and machines.** A share mounted by several machines shows every one of them the same
  claim, so the rule that keeps two instances on one box apart also keeps two boxes from both owning a share — the
  double-primary detection of [[mounts-and-storage#folder-add]].
- **Read-only media** (a CD/DVD, a read-only share) can't hold a claim file; the claim goes into a list kept on the
  machine instead, which protects within that machine — enough, since nothing writes to such media.

**An agent works in one swarm at a time** (its single-instance socket is already scoped per swarm,
[[nodes#single-instance]]). Its catalog is what its open `.rehuco` lists — local folders, and references to roots (or
folders under them) that nodes of that swarm serve ([[mounts-and-storage#rehuco-scope]]). A local folder some node of
the swarm owns is reached through that node; any other, directly. Where those nodes run makes no difference: a
resource is addressed by node, root and relative path ([[nodes#access-seam]]), with no host in it, so two instances
on the agent's own machine are reached exactly as two nodes on two boxes are. An instance on the same machine that
belongs to another swarm stays out of view until the agent switches swarm.
