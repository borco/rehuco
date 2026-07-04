# §6. Discovery, Swarm Identity, and Trust

## §6.1 Two separate questions

[[discovery-trust-access#separate-gates]]

- **"Is this node even part of my network?"** → answered by **swarm identity**.
- **"Do I trust this specific node?"** → answered by **pairing/approval**.

These must be separate gates. Without the first, the second alone would let any installation of the same software (a neighbor's, a stranger's, even another household's identical setup) discover and attempt to pair with the user's nodes, since zeroconf advertises to anything listening.

## §6.2 Swarm ID

[[discovery-trust-access#swarm-id]]

- Generated once, randomly, when the very first node is created ("create new swarm" vs. "join existing swarm" at first run).
- Carried in every zeroconf announcement. Nodes ignore announcements with a non-matching swarm ID outright — a foreign node never even becomes a pairing candidate.
- This also directly enables **running multiple independent swarms** on the same LAN (e.g. a real household swarm and a separate test/dev swarm), since they simply never see each other's traffic.

## §6.3 Discovery

[[discovery-trust-access#discovery]]

**Zeroconf (mDNS/Bonjour)** for finding nodes on the LAN — the right tool for zero-config local discovery, and lightweight enough for the QNAP.

## §6.4 Node identity and pairing (Syncthing-style, trust-on-first-use)

[[discovery-trust-access#node-identity-pairing]]

Node identity follows the Syncthing model, which is cleaner than a separate pairing-secret scheme because the human-visible identity and the cryptographic identity are the *same object*:

- **A node's identity is the hash of its own self-signed TLS certificate's public key** (a "device ID"). The identity *is* the key — self-certifying, no certificate authority needed. All later traffic is mutual TLS in which each side verifies the other's presented cert hashes to the expected device ID.
- **Pairing is mutual approval of device IDs.** A new node announces (over zeroconf, gated by swarm ID §6.2) its device ID. The admin app shows the join request and its device ID; the user **independently verifies** it against the device ID shown on the node's own console/log (the side-channel check that defeats a rogue device claiming a fake identity — the same trust model as confirming an SSH host key). On approval, the node's device ID is recorded as trusted.
- Because identity is just the cert hash, there is **no separate long-lived secret to store or rotate** — the keypair *is* the standing credential, and "compare the fingerprint" reduces to "compare the device ID," with nothing else to get wrong.
- For headless boxes (QNAP), the device ID is surfaced the same way a fingerprint was: printed to console where there's a screen, written to a log readable over SSH as the guaranteed fallback, and echoed in the admin app's join request for side-channel comparison.

(This supersedes an earlier design that used a short-lived randomly-generated pairing secret exchanged for a long-lived credential. The cert-hash identity achieves the same trust-on-first-use property more simply, and the swarm-ID gate of §6.2 still sits in front of it.)

## §6.5 Membership model: hub-and-spoke, not full mesh

[[discovery-trust-access#membership-model]]

The **admin is the sole authority for swarm membership**. When the admin approves a new node:

- The admin records the new node's public identity in its registry.
- The admin **pushes the updated membership list to all other already-known nodes**, so every node trusts the new member without having to independently re-verify it.
- Any node only ever needs to trust one thing: the admin's say on who belongs. This avoids O(N²) pairing dances as the swarm grows, at a scale where a privileged admin role already exists naturally.
- A node that's offline when a new member joins picks up the update next time it reconnects.

This is the same pattern Syncthing calls an **introducer** — a trusted device that vouches for others to its peers — which independently validates the hub-and-spoke choice. The admin is the introducer; ordinary nodes trust the admin's vouching rather than re-verifying each new member themselves.

## §6.6 Registry home: preferred authority with chatter fallback (decided)

[[discovery-trust-access#registry-home]]

> [!NOTE]
> **Implement the registry-resolution and serve-after-resync logic (§6.6 + §6.11) with Opus, not the auto-switched Sonnet.** The startup sequence (preferred-authority → chatter-for-highest-version → last-known), the version-marker comparison, and the "serve only after catching up, unless nothing newer is reachable" gate have several edge cases (single node, cold start, partial power-up, vacation laptop) where a wrong default either deadlocks startup or serves stale access rules. Override to `/model opus` for both sections.

The propagated swarm registry (`.rehusw`, §4.8 — membership, users, hashes, access rules) and the instance registry (§10.2) are global state that isn't derivable from any single `.rehu`, so they need a defined place to resync *from*. The model is a **preferred authority with a chatter fallback**:

- A swarm may designate a **preferred authority** — the most reliably always-on box (e.g. the QNAP or the always-on Linux node). When reachable, it is the canonical resync source: a node that has caught up to it *knows* it is current.
- If **no preferred authority is defined**, or it is **unreachable**, or the node is **away from the swarm** (vacation laptop), nodes fall back to **chatter** — gossip with whatever peers are reachable, take the highest registry version-marker (§6.11), and serve on that. This is "current among who's reachable," accepting it may transiently lag until a higher-versioned holder appears.
- The **single node** is the degenerate case (§8.1): no peers, no authority needed — it is trivially current and serves immediately, never waiting on a discovery timeout.

So startup registry resolution is a simple sequence: **try the preferred authority → else chatter with reachable peers, take highest version → else serve last-known `.rehusw`.** Certainty when the authority is up; functional (if briefly-stale) when it isn't; no distributed consensus needed, because swarm config has a single writer (the admin, §6.5) and ordering is by version-marker, not agreement. The concrete lookup *sequence* above is the design; only its wire-level details are implementation.

## §6.7 Admin app portability

[[discovery-trust-access#admin-portability]]

The agent must run identically on any machine — it holds no unique local state beyond a cached session token (§6.8):

- The **authoritative registry lives on the preferred authority node** (above), not on whichever machine the agent last ran on. The agent resolves and pulls the current registry on launch via the sequence above.
- The agent's user identity travels as a session token in the OS secure store (§6.8), not tied to one machine's disk.
- **Open question, still unresolved:** should the *admin* identity be a permanent "master key," or revocable/replaceable like an ordinary node identity, in case it's lost or compromised? (This is distinct from registry home, which is now decided.)

## §6.8 User authentication (distinct from node trust)

[[discovery-trust-access#user-auth]]

§6.1–6.6 authenticate *nodes* to each other. Authenticating *humans* is separate and necessary because any node can act as an HTTPS server a user logs into (including the thin tablet's server, §11.5):

- **Passwords are never stored, transmitted, or propagated — only salted slow-hashes are.** Each user record holds `hash = Argon2id(password + per-user salt)` (bcrypt/scrypt acceptable). A node authenticates a login by re-running the KDF on what the user typed and comparing. The plaintext password exists only momentarily at the login.
- **The user list (usernames + salted hashes + permissions) is shared swarm state**, propagated to every node the same way membership is (§6.5). Every node caches it because every node may be the server a user logs into — there is no central auth bottleneck, and offline login works on any node (e.g. the vacation laptop).
- **Accepted trade-off:** every node therefore holds all users' hashes, so a compromised node exposes them to offline cracking. At household scale (family + occasional lost laptop, not a determined adversary) this is acceptable, and it's bounded by the fact that **only nodes ever hold hashes, and visitors never become nodes** (§6.9).
- **The thin tablet logs in via a session** against whatever node serves it (which holds the hash and issues a session token/cookie). No credential is stored on the tablet.
- **The desktop agent caches a session token, never the password.** On login the serving node issues a session token (the same kind the tablet gets); the agent persists *that token* in the OS secure store (Keychain / Windows Credential Manager / Secret Service), so the user isn't re-prompted every launch. The plaintext password and any hash never touch the client. An expired or revoked token simply fails on next use and re-prompts — which is also how user-deletion/revocation reaches the agent, with no special-casing. Logout discards the token (and ideally invalidates it server-side). Login/logout are explicit menu actions in the agent.

## §6.9 Visitors and cross-swarm sharing (no federation)

[[discovery-trust-access#cross-swarm-sharing]]

A visitor is never allowed to join the swarm as a node. Two clean paths instead:

- **Guest account** — a normal user record (username + hash + view-only permissions), propagated like any user. The visitor logs into *your* node's web UI as a dumb browser client (same as the tablet); their device never becomes a node and never holds hashes or swarm state.
- **Export / import** — the way to share content with someone who has *their own* swarm. Copy resources to a disk, **stripped of swarm-bookkeeping**, and the visitor imports them into their own swarm. There is deliberately **no cross-swarm federation or trust** — that would be a large complexity tax for no household benefit; sharing is a deliberate, manual, identity-scrubbing copy.
  - An exported resource **keeps its UUID** (harmless, occasionally useful for later re-import/compare) but is **stripped of the version vector, activity log, per-user state, and instance-registry entries** — those are the originating swarm's private bookkeeping and would leak usage or corrupt ordering in the destination swarm. Export = resource content + `.rehu` metadata + screenshots, scrubbed of all swarm bookkeeping.

## §6.10 Access control

[[discovery-trust-access#access-control]]

Access rules (which users may see which resources) are **swarm-wide config**, authored by the admin and propagated to every node exactly like membership (§6.5) and the user list (§6.8).

**Important separation from `.rehuco`.** Although it's tempting to put access rules in `.rehuco`, that file is deliberately *per-machine* (§9.3) — it holds mounts and ownership flags that legitimately differ box to box. Access rules, the user list, and hashes are the opposite: **swarm-identical, must be the same on every node**. So they do *not* ride in the per-machine `.rehuco`; they belong with the propagated swarm registry (the same data and propagation path as membership/users, §6.5–6.7), whether implemented as a registry section or a clearly-marked propagated sibling file. Putting machine-specific and swarm-identical data in one propagation bucket would force the system to either wrongly propagate mounts or wrongly fail to propagate grants. Concrete consequence: because grants propagate like membership, a node offline when a grant is made catches up on reconnect — so access is consistent regardless of which node a user logs into.

**Enforcement is server-side, at the serving node — never client-side.** Because the web client is a dumb browser (§11.5) and the Qt app is just a node client (§5.1), the only trustworthy filter is the node answering the request: it knows who the user is (authenticated session, §6.8), holds the propagated access rules, and **filters the catalog before sending anything back**. The user never receives a full list with disallowed items merely hidden in the UI — the node simply never returns what the user isn't entitled to. This is precisely why the user+access data must live on *every* node: each node enforces locally for whoever it serves.

**Grant types** (per §14): full access, per-resource, or by-tag. Tag-based grants are **evaluated dynamically at query time**, not expanded into a static list — if a user is granted "everything tagged `blender`" and a resource is later retagged, that resource automatically enters or leaves the user's view with no explicit grant edit. This is the one part of access that is *computed* rather than a static lookup, and it makes grant-by-category cheap and self-maintaining.

## §6.11 Serve-after-resync (startup gating on swarm info)

[[discovery-trust-access#serve-after-resync]]

A node that was offline while users/permissions changed must not serve on stale access rules — it could grant access that was revoked, or deny access that was granted. So a node gates serving user-facing requests on first bringing its `.rehusw` (§4.8) up to date. The rule must be stated carefully, because taken literally ("don't serve until resynced with the rest of the swarm") it would make the swarm un-startable:

- **The vacation laptop** boots as the only node in reach — there is *no one* to resync with. An unconditional rule would mean it never serves, destroying the core offline use case.
- **Cold start at home** (e.g. after a power cut) boots every node at once; if each refuses to serve until it has resynced with the others — who are also all refusing — you get a startup deadlock or a fragile race.

So the correct rule is **"catch up to the most-current swarm-info source you can reach, then serve; if no more-current source is reachable, serve on last-known `.rehusw`":**

- On startup, the node attempts to resync `.rehusw` from the registry home (§6.6) or any reachable peer.
- If it reaches a **more-current** source, it must finish pulling the updated users/access **before** serving — the strict rule, intact, for the normal "briefly-offline node rejoins a running swarm" case.
- If it **cannot reach anyone**, it falls back to its durable last-known `.rehusw` and serves on that basis. For the vacation laptop this is correct and safe: it's *your* device, *your* account, on a network you control — the same LAN-local trust posture the whole design assumes — and refusing to serve would simply be useless.

**Deciding "more current" requires a version marker on `.rehusw`.** The admin is the sole writer of swarm config (§6.5), so a simple monotonic admin-side counter (or the same version-vector machinery as §7) suffices: a node compares its `.rehusw` version N against a reachable source's version M; if M > N, pull and apply before serving; otherwise serve immediately (so a node that missed nothing is never delayed). This makes the gate block *only* when there's genuinely something to catch up on.

**Resync source:** the place to resync *from* is resolved by the preferred-authority-with-chatter model (§6.6) — preferred authority if reachable, else chatter for the highest version, else last-known.

**Accepted limitation — offline revocation cannot reach a copy already in hand.** A consequence of allowing offline access: if you borrow a resource onto a laptop and go offline, and the admin then revokes your access or deletes your account, your laptop keeps serving that resource to you for as long as it never rejoins the swarm — and you could even export it (§6.9) out of the admin's reach. This is a *fundamental* property of any system permitting offline use, not a flaw specific to this design; the only "fixes" are time-bombed DRM-style local copies (fighting the device's own owner) or server-held decryption keys (which turn every offline access back into an online checkout, killing the offline use case). Both trade away the core capability the design exists to provide, to defend against a threat that barely exists at household scale — the "attacker" is a household member who already had legitimate access and kept a complete local copy. So this is a **deliberate, accepted boundary**: revocation is effective for future swarm access but cannot reach an already-held complete local copy; the design trusts swarm members, and defending against a member who kept a copy is an explicit non-goal. **Partial mitigation, free from §6.11:** revocation *does* take effect the instant that laptop rejoins the swarm (its `.rehusw` resync pulls the updated rules and it enforces from then on) — the hole is specifically a copy that *never reconnects*; any node that ever comes back online closes its own hole on next sync.
