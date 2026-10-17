# §6. Discovery, Login and Access

[[[discovery-trust-access]]]

> [!NOTE]
> Until 2026-10-16 this file specified a *swarm*: a swarm ID, pairing between nodes by device ID, a propagated
> membership and user registry, and a serve-after-resync gate. Nodes no longer talk to each other, so none of that
> remains ([[appendices.post-mortem#architecture]]). The sections keep their anchors — code and other specs point at
> them — and say what replaced each.

## §6.1 Two separate questions

[[[discovery-trust-access#separate-gates]]]

- **"Where is a node?"** → answered by **discovery** ([[discovery-trust-access#discovery]]), between the agent and the
  nodes on the LAN.
- **"Who is this person, and what may they see?"** → answered by the **web login**
  ([[discovery-trust-access#user-auth]])
  and **access rules** ([[discovery-trust-access#access-control]]), between a browser and the node serving it.

There is no third question. The agent needs no login to its own files — the operating system already lets the user read
and write them — and a node trusts no other node, because it never asks one for anything.

## §6.2 No swarm, no swarm ID

[[[discovery-trust-access#swarm-id]]]

Retired. A swarm ID gated which announcements a node would answer so that two households' identical installs on one
LAN never saw each other. With no node-to-node traffic there is nothing to gate: an agent lists the nodes it discovers
and the user picks the one to use ([[nodes#node-actions]]); a stranger's node in that list is a name the user does not
pick. Two installs on one LAN need no separation beyond their own ports and mDNS names.

## §6.3 Discovery

[[[discovery-trust-access#discovery]]]

**Zeroconf (mDNS/Bonjour)**, between the **agent and the nodes only**. A node advertises itself under a service name
built from its machine and its user, with its port; the agent's node list (the remote serving node and the borrow
target settings) is read from those announcements, or a node is typed in by address. A browser never browses mDNS:
Safari on an iPad cannot. It gets a plain URL, which the agent shows beside *Open remote node*, and the node's CLI
prints — the `.local` name resolves on every platform that has Bonjour.

## §6.4 Node identity and pairing

[[[discovery-trust-access#node-identity-pairing]]]

Retired. Pairing by device ID, mutual TLS between nodes and trust-on-first-use existed for a network of peers; there
are no peers. What remains is the browser's trust in one node's HTTPS certificate when the web pages come: a
self-signed certificate the node makes itself, accepted once per device, which the iPad's video element honours
([[nodes#web-playback]]). The `NodeKey` the access seam carried for an owning node goes with the teardown
([[nodes#access-seam]]).

## §6.5 Membership model

[[[discovery-trust-access#membership-model]]]

Retired. There is no membership: a machine is part of the household's rehuco by mounting the share, and nothing records
that. Users exist per node, created by that node's CLI ([[discovery-trust-access#user-auth]]).

## §6.6 Registry home

[[[discovery-trust-access#registry-home]]]

Retired. The propagated registry (`.rehusw`: membership, users, hashes, access rules) and the instance registry had to
live somewhere and resync from somewhere; neither exists. The `.rehusw` file is gone from
[[data-model#local-file-trio]]. What a node knows — its users, their sessions, its access rules, its borrow store — is
its own, in its folder under the app folder ([[packaging-deployment#app-folders]]), and is not copied anywhere.

## §6.7 Admin is a web role

[[[discovery-trust-access#admin-portability]]]

The agent holds no identity beyond the OS user running it ([[field-schema#per-user-shared]] names the user's sidecar).
**Admin** is a role on a node's web login, granted when the one-time password is issued
([[discovery-trust-access#user-auth]]): an admin sees every user's jobs and borrows on that node and may return a borrow
for everyone ([[nodes#node-status]], [[borrowing#agent-ui]]). It is per node, like every user: a household member who
is admin on the machine at home is whatever the travelling machine's node says they are there. The open question of a
revocable master identity is void.

## §6.8 User login: a one-time password from the node's CLI

[[[discovery-trust-access#user-auth]]]

A browser user logs in to the web pages, and nothing else needs a login:

- **The agent needs none.** It edits files the OS already lets its user read; the username per-user state is filed
  under is the OS login or the Identity page's setting, not a credential ([[field-schema#per-user-shared]]).
- **The web pages do.** On the node's machine, `rehuco-node otp --user <name> [--admin] --minutes <n>` prints a
  one-time password for that username, good for `n` minutes. The person types it once into the login page on their
  device; the node then issues that **device** a long-lived session (a cookie or token), remembered until it is revoked
  by the CLI or expires. The OTP is per device, once.
- **The username is the sidecar's name.** What the watch page writes — progress, *viewed*, bookmarks — goes into
  `<stem>.user-<name>.rehuser` for that name ([[data-model#single-file]]), through the same lock and merge as the
  agent's
  own writes ([[sync#overview]]). The username of a per-user write comes from the session, never from the request.
- **No password store, nothing propagated.** The node keeps only its issued sessions and their roles; there are no
  hashes to protect and no other node to copy them to.
- **The agent's own node asks nothing of it.** The agent that starts the node hands it a machine-local token for that
  session, so working through one's own machine's node — *Open local node* — asks for nothing; any other machine's
  node takes the login above.

## §6.9 Guests and sharing with others

[[[discovery-trust-access#cross-swarm-sharing]]]

- **A guest** is an ordinary web user: an OTP issued for a name with view-only rules, on a device that becomes a browser
  of this node and nothing more.
- **Sharing content** with someone who runs their own rehuco is a copy: the resource's files and `.rehu`, **stripped of
  every `.rehuser` sidecar, `.lock` and `.borrow`**, which are this household's own bookkeeping. The UUID stays
  (harmless, occasionally useful for a later compare). There is no federation of any kind.

## §6.10 Access control

[[[discovery-trust-access#access-control]]]

Access rules say which **web users** may see which resources. They are the node's own configuration, authored by an
admin on that node's machine, and apply to what that node serves; the files themselves are governed by the share's
permissions, which rehuco neither sets nor overrides.

**Enforcement is at the node, never in the browser.** The web client is a dumb browser
([[borrowing#vacation-topology]]), so the only trustworthy filter is the node answering the request: it knows who the
user is (the session), holds the rules, and **filters the catalog before sending anything back**. The user never
receives a full list with disallowed items merely hidden.

**Grant types** (per [[requirements#overview]]): full access, per-resource, or by-tag. Tag-based grants are **evaluated
dynamically at query time**, not expanded into a static list — a resource retagged later enters or leaves the user's
view with no grant edit.

**The agent is not access-controlled.** Opening a file the OS lets the user read is never gated
([[nodes#local-vs-swarm]]).

## §6.11 Serve-after-resync

[[[discovery-trust-access#serve-after-resync]]]

Retired. The gate kept a node from serving on access rules it might have missed while offline; rules are now the
node's own and never change behind its back. A node serves as soon as it runs.

**What stays of its accepted limitation:** a copy in hand cannot be revoked. A resource borrowed onto a machine stays on
that machine until returned, whatever an admin decides at home meanwhile — the fundamental property of any system that
permits offline use, and an explicit non-goal to defend against at household scale. A borrow is visible to every
agent through its `.borrow` record, and an admin may return it for everyone the next time the machine is reachable
([[borrowing#recording-borrows]]).

## §6.12 Bringing a node up, and what can be configured from where

[[[discovery-trust-access#remote-admin]]]

- **The local node is two checkboxes.** *Settings* > *System Integration* > *Run the local node while rehuco is
  running*, on by default; the agent starts and stops it ([[nodes#two-roles]]). *Open local node* is always present.
  Beneath it, *Allow network access*, off by default: the local node serves this machine, and the node a tablet uses
  is more likely a headless one ([[nodes#node-status]]); ticking it is what opens the firewall
  ([[discovery-trust-access#node-port-firewall]]).
- **Another machine's node is configured on that machine**, by the agent running there. There is no remote
  configuration of nodes: anything that names a program or a script to run (the ffprobe path, the VLC path, scraper
  scripts), folder locations, the borrow store, the users and their rules are that machine's own, and configuring them
  from elsewhere would be remote code execution.
- **Loopback until there is a login.** A node with no user issued listens on loopback only — the default on a fresh
  install, so turning it on exposes nothing by surprise. It opens to the LAN only with *Allow network access* ticked, a
  user issued, and the firewall letting it in ([[discovery-trust-access#node-port-firewall]]).
- **The borrow store lives where the node's machine says.** A folder of that machine's choosing, never the app's own
  folder ([[packaging-deployment#app-folders]]), since one borrow can be many gigabytes ([[borrowing#agent-ui]]).

## §6.13 The node's port and the firewall

[[[discovery-trust-access#node-port-firewall]]]

- [#418: spike: a FastAPI + HTMX + Pico follow-mode page](https://github.com/borco/rehuco/issues/418)
- [#515: feat(node): an HTTP skeleton over the mount — FastAPI app, mDNS advert, the agent's local token](https://github.com/borco/rehuco/issues/515)

**The port is fixed and configurable, never picked.** A browser keys a bookmark, a home-screen web app, its
`localStorage` and a certificate exception by scheme, host and port ([[nodes#web-pages]]), so a port that moved between
runs would break each of them without a word. The node's port is a setting of the user's on that machine, with one
default; a second user on the box sets another once ([[nodes#two-roles]]). A port in use is an error the node reports
in its status, never a reason to move to a free one, which would leave the browsers and the firewall rule behind. The
`.local` name keeps the URL stable across a changed address; the port is what the user keeps stable.

**Opening the firewall takes the administrator once, and the agent asks for it itself.** Measured on Windows (#418):
every way of adding an inbound rule, by program or by port, through `New-NetFirewallRule` or `netsh`, is refused
without elevation. The prompt Windows shows when a program first listens is no better: it writes a rule for the program
on every port, and a cancelled prompt leaves a *Block* rule behind that outranks any later *Allow*, with no further
prompt. So the agent never lets that prompt appear, and the rule follows *Allow network access*
([[discovery-trust-access#remote-admin]]), not the node:

- **The rule wanted** is an enabled *Allow*, inbound, for the agent's own executable *and* the node's port over TCP, on
  the Private profile, from the local subnet only. A *Block* for that executable on the same profile counts as missing,
  since it would win. Reading the rules needs no elevation.
- **Ticking *Allow network access* the first time adds it**: the agent's own prompt says what the node is for, the
  port, and that only private networks and the local subnet are opened; accepting runs the one elevated step, the
  system's UAC prompt, which writes the rule under one named group. A node with network access off never checks or
  asks, so the default start of a fresh install opens nothing and shows no prompt.
- **A start with network access on verifies it**, and a rule found missing — removed by hand, or never accepted —
  brings the same prompt back. Declining leaves the node on loopback, serving this machine, its status saying it is
  not reachable from the network. Loopback until a login still holds on top of this: the node opens to the LAN only
  once a user is issued *and* the rule is in place.
- **Three buttons beside the checkbox**: *Add rule* and *Remove rule*, each one elevated step, and *Verify rule*, which
  needs none and says whether the rule is there, enabled and matching, and whether a *Block* overrides it. A port
  change removes the old rule and asks for the new one; an uninstall removes the group.
- **A Public network stays closed.** On a network Windows calls Public the Private rule does not apply, and the status
  says so rather than widening the rule.

The check and the prompt are Windows'. macOS's application firewall and Linux's `ufw` are off unless the user turned
them on, and are theirs to manage.
