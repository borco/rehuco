# §8. Multiplicity: Machines, Users and Nodes

[[[multiplicity]]]

## Overview

[[[multiplicity#overview]]]

- **Any number of machines, one share.** Every machine mounts the share and runs its own agent over its own `.rehudb`;
  nothing coordinates them but the filesystem ([[sync#overview]]) and the SMB server's change notifications
  ([[mounts-and-storage#out-of-band]]). A machine without the share mounted is an agent with offline roots.
- **One node per machine and user**, hosted by that user's agent ([[nodes#two-roles]]). A second user on the same
  machine runs their own agent and so their own node, on another port and under another mDNS name, only while logged
  in. There are no node *instances*, no `nodes/<name>/` folders and no `--instance` flag: the node's files sit under
  `node/` in the folder it shares with the agent ([[packaging-deployment#app-folders]]).
- **Folder-group separation needs no process.** One `.rehuco` lists many roots as plain configuration, and one node
  serves whichever of them its machine reaches.

## §8.1 No node is the base case

[[[multiplicity#single-node-base]]]

An agent with the share mounted and the node switched off is a complete rehuco: it edits, scans, browses, saves under
the lock and follows the notifier. The node adds web pages, long jobs and a borrow store ([[nodes#overview]]), and an
agent that never turns it on loses nothing else. Nothing hunts the network for an authority, because there is none: a
single-machine install must never pause on a discovery timeout waiting for peers that will never answer.

## §8.2 No owners, no claims

[[[multiplicity#instances]]]

The earlier design gave every root folder exactly one owner — a node, a swarm, or an agent — recorded as a claim file
beside a fingerprint, refused a second owner, and made a file read-only outside its owner's swarm. All of that existed
to keep a single writer true, and is gone with it:

- Any machine that can reach a folder may edit under it; the lock and the compare-and-swap keep writers apart
  ([[sync#lock-file]]), on one machine and across machines alike.
- **Roots still do not overlap** within one `.rehuco`, for the cache's sake, not for ownership: a root inside another,
  or containing one, would scan a record twice and give it two rows (#498). The agent refuses the add and says which
  root encloses which. It compares the folders as spelled, and again through their links (`os.path.realpath`) on a
  worker, since following a mapped drive can wait out a network timeout. The two forms are never compared with each
  other, and the root is stored as spelled, never resolved. A root the cache holds unreachable is compared as spelled
  only. A file that already nests opens as it is, and the main window's banner says which roots overlap; the scan
  never enters another root ([[data-model#cache-schema]]), so each record keeps one row meanwhile.
- A share several machines mount is the same folder to all of them; each has its own mapping to it
  ([[mounts-and-storage#rehuco-scope]]) and its own cache of it.
- Read-only media (a CD/DVD, a read-only share) hold no lock file and take no save; their records open read-only with
  the reason, and their per-user state lives on the retained copy ([[mounts-and-storage#durable-retention]]).
