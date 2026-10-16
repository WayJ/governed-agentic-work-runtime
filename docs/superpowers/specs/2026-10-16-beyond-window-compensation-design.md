# Beyond-window compensation — candidate design (DRAFT)

Status: **DRAFT — pending master ratification.** Prepared on the S14 design
checkout at `678d7b48e844ee153325239259064eab9b806df3` (published main,
clean tree asserted; baseline battery `Ran 1015 tests … OK (skipped=3)` on
this tree). It allocates no epic or sprint id, writes no ADR, mutates no
roadmap ledger, and is **not** an implementation instruction: no product code
changes until the master ratifies a design after the independent review the
master dispatches next. Primary evidence: the S14
[recon](../../../.agents/notes/2026-10-16-s14-design-recon.md) with its
public-API probe (deterministic, two runs, 21/21 checks each, throwaway
`/tmp` stores), the ratified S10 design
([v1/v2/v2.1, MASTER §15 D43–D48](2026-10-15-compensation-execution-design.md)),
the [S10 acceptance](../acceptances/2026-10-15-S10-acceptance.md) and
[close note](../../../.agents/notes/2026-10-15-S10-close.md),
[roadmap.md](../../../docs/roadmap.md) 0.3, and the actual sources at this
SHA. Everything stays trusted-local: no authentication, tenant, fencing,
distributed exactly-once or production-safety claim is made or implied.

## 1. Problem

Roadmap [0.3](../../../docs/roadmap.md) line 33 leaves open: "compensation
beyond that bounded window (publishing, post-closure, chains), external
fencing of in-flight calls and distributed guarantees remain open". S10
delivered linked expense withdrawal **only** inside the active cancellation
window, expense family only. The S10 handover list
([close note](../../../.agents/notes/2026-10-15-S10-close.md)) carries the
same items. External fencing and distributed guarantees are master-excluded
from this dispatch and stay out. The open compensation item has three named
axes — **family** (publishing), **time** (post-closure), **structure**
(chains) — and this draft's first job is to bound the slice: recommend one
axis-slice, defer the rest with explicit non-goals.

## 2. Grounding findings (F1–F11; full evidence in the [recon](../../../.agents/notes/2026-10-16-s14-design-recon.md))

All citations at `678d7b48e844ee153325239259064eab9b806df3`.

- **F1 — the shipped window machinery.** Forward payloads reject
  `CANCELLATION_ACTIVE` under an active intent; the linked variant
  *requires* the intent (`CANCELLATION_NOT_REQUESTED` otherwise), before the
  business-key branch so fresh and re-admission both split
  (`work_runtime/runtime.py:645-652`); authority is current owner +
  compensating grant (`runtime.py:639-644`).
- **F2 — the window predicate cannot see "closed".** The cancellation
  intent is never popped; it persists in the closed work's JSON
  (`runtime.py:532-538`; probe P-B1). What excludes closed works is the
  `command()` gate — everything except `create_work`/`record_evidence`/
  `revoke_evidence` rejects `WORK_NOT_ACTIONABLE` (`runtime.py:281-286`).
  Relaxing only that gate would let the existing window check **silently
  pass** on closed-cancelled works.
- **F3 — post-closure collisions.** Post-closure linked/forward proposals →
  `WORK_NOT_ACTIONABLE` (P-B2/B3); `dispatch` cancels `STALE_INTENT` for
  closed works (`runtime.py:1011-1018`); `finalize_cancel` can never run
  again; the closure snapshot is written once (`runtime.py:532-538`) — a
  post-closure compensation cannot join `operation_dispositions` without new
  amendment semantics, and no finalize-style block exists to bound it. S8
  precedent for closed-work mutation: `revoke_evidence` records
  `work_was_closed` without reopening (`runtime.py:283-284, 819-883`; P-B4
  shows `record_evidence` likewise admissible).
- **F4 — family-agnosticism is probe-proven, not asserted.** With a
  probe-only paired `PublishingPolicy` subclass and an opted-in probe
  adapter, the **unmodified runtime** runs the entire publishing pipeline:
  admission, immutable snapshot, `digest([policy.id, capability, target])`
  key, replay stability, chain refusal (also `runtime.py:740-743,1087-1093`),
  both adapter holds, explicit kwargs, resolution binding, `adapter_result`,
  `withdrawn` proof at the family accepted source, C04 inertness, exact
  two-id ack, compensation dispositions (P-A2..P-A16).
- **F5 — today's publishing gap is two policy attributes + one adapter
  opt-in.** `PublishingPolicy` has no `compensation_capabilities`
  (`work_runtime/publishing.py:21-36`) and its `action_blockers` returns
  `CAPABILITY_UNSUPPORTED` off-family (`publishing.py:94-100`) → a linked
  proposal rejects `REQUIREMENT_UNSATISFIED` today (P-D1).
  `FakePublisher` is forward-only, no context opt-in, three-positional
  `execute`, 3-column receipts + immutable `(document_id, digest)`
  publications with same-content dedup (`publishing.py:110-166`).
- **F6 — conformance skips auto-activate.** The opt-in conformance test
  skips adapters without `supports_action_context`
  (`tests/adapter_conformance.py:75-86`); `FakePublisher` opting in turns
  one of S10's two designed skips into an active test with no mixin change.
- **F7 — the withdrawn-proof lifecycle is family-agnostic and closed.** No
  `withdrawn` source mapping anywhere → no imports for any actor
  (`runtime.py:775-777`), admin-only revocation (`runtime.py:805-817`), S9
  reservation covers withdrawal ids at every loaded accepted source
  (`runtime.py:751-797`).
- **F8 — latent migration edge (unreachable today).** `migrate_policy`
  revalidates every verified proof (`runtime.py:602-613`); a `withdrawn`
  proof would fail both the source match and `validate_evidence`
  (`publishing.py:47-58`). Unreachable because a withdrawal implies a
  permanent cancellation intent (blocks migration, `runtime.py:574-575`) or
  a closed work (F3). Any future post-closure design must decide
  withdrawn-proof revalidation explicitly.
- **F9 — publishing-domain specifics.** Forward key is digest-based
  (`publishing.py:102-104`); publications are immutable one-id-per-
  `(document_id, digest)` artifacts; publishing works can also close
  **succeeded** via `request_completion` (`publishing_demo.py:127-130`) —
  retraction of a completed work's artifact is post-closure territory.
- **F10 — name-collision hazard.** S13 shipped `sop.withdraw` (SOP
  authoring family, [sop-authoring.md](../../../docs/sop-authoring.md)); a
  content-family compensation must not add a third confusing "withdraw"
  name.
- **F11 — doc-sync surface.** `publishing.py` is not a `doc_sync_map` row;
  a runtime-byte-unchanged slice fires no mapped row, but
  [runtime-boundaries.md](../../../docs/runtime-boundaries.md):52-53
  ("exists only for the expense family"),
  [interventions.md](../../../docs/interventions.md):122-128 and
  [verification.md](../../../docs/verification.md):572-580 list publishing
  as open — they owe a same-commit truthfulness update anyway.

## 3. Scope recommendation — ONE bounded sub-slice

**Recommended: publishing-family linked compensation inside the active
cancellation window** (`content.unpublish` paired to `content.publish`),
delivered with **zero `runtime.py`/`adapters.py` changes** (F4; the pin
itself is a proposed DoD item, D82).

Honest framing first: this widens the **family** axis of the roadmap's open
item, not the **time** axis. S10 bounded compensation to "expense family +
active window"; the roadmap's parenthetical lists publishing among what is
"beyond that bounded window" because of the family bound. This slice retires
the publishing item *for the in-window case* — the governed retraction path
for a published artifact while the work is still open: publish confirmed →
`request_cancel` → linked `content.unpublish` proposal → one retraction
effect → exact two-id acknowledgement closure. It makes **no** temporal
claim: post-closure compensation (either family), chains, cross-work and
intervener authority remain open exactly as before.

Why this sub-slice and not the others:

| candidate | size | new lifecycle semantics | locally test-gatable | value now | verdict |
|---|---|---|---|---|---|
| **publishing-family, in-window** | smallest: policy + adapter + tests + demo chapter (F5) | **none** — the S10 machinery verbatim (F4) | fully, same gates; conformance skip activates (F6) | proves the family-agnostic claim; second real domain gets the governed retraction path | **recommended** |
| post-closure compensation | large: closed-work admission, dispatch carve-out, closure-amendment semantics, new authority model, new abuse bounds (F2/F3) | many, on the most invariant-laden paths (closure immutability) | yes, but a second design cycle first | highest eventual value (the real "closed it, must still withdraw" case) | deferred (§9, seeds in Q9) |
| chained compensation | largest: compensation-of-compensation admission, saga accounting | the whole structure | partially; no bounded story yet | speculative | deferred (non-goal) |

The S10 design itself carried post-closure as "a second design cycle"
(v1 §3/§12); nothing in the current code makes it cheaper than that (F2/F3).
Chains are refused at two independent points today (F4) with no demonstrated
need. Picking the publishing slice follows the working agreement's
smallest-explainable-promise discipline and immediately validates — under a
second real domain — every D43–D48 guarantee the runtime already gives.

## 4. Design (recommended slice)

### 4.1 Public surface — reuse the S10 linked variant verbatim

`propose_action` with payload `{capability, contract_revision, plan_revision,
document_digest, compensates}` where `capability == "content.unpublish"` and
`compensates` is the confirmed publish operation id. No new command, no new
payload fields, no runtime change: the exact-key shape check, CAS/dedup/
replay, and the whole admission chain apply as shipped
(`runtime.py:625-716`). Receipt shapes unchanged. The slice's product surface
is `work_runtime/publishing.py` (policy + adapter) plus tests/demo/docs.

### 4.2 Authority, admission and abuse bounds (what "widened admission" means here)

- **Authority**: the current owner holding `content.unpublish` in grants —
  the ordinary S10 rule (`runtime.py:639-644`); replay re-checks the same
  way. Demo grants gain `content.unpublish` for the owning agent
  (trusted-local configuration; no tenant-auth claim).
- **Evidence**: the immutable link snapshot
  `{operation_id, external_id, capability}` taken from the terminal target at
  proposal (`runtime.py:728-749`) — reused verbatim, never re-derived from
  the current document. Target must be `confirmed_succeeded`, same work, not
  itself a compensation, paired by the current policy
  (`runtime.py:740-746`).
- **Window**: the active cancellation intent only (`runtime.py:648-652`).
  This slice adds **no** new temporal reach: closed works keep
  `WORK_NOT_ACTIONABLE` (F2/F3), dispatch keeps the closed→`STALE_INTENT`
  branch, and the belt-and-braces no-intent→`STALE_INTENT` mirror
  (`runtime.py:996-1003`) stands.
- **Abuse bounds** (unchanged from S10, restated): the window requirement +
  permanent intent; one compensation per original via the store-global
  `business_key UNIQUE` (D6 rule, `runtime.py:681-685`); unresolved
  compensations block `finalize_cancel` (`runtime.py:504-510`); dispatch
  re-runs authority/grant/blocker/link revalidation
  (`runtime.py:1004-1048`); the adapter receives the link only through the
  explicit kwargs path — nothing in a document can select the action.

### 4.3 Replay, conflict and business key — identical to S10

Compensation key `digest([policy.id, "content.unpublish", target_op_id])`,
structurally distinct from the publishing forward key (digest-based on
document content, `publishing.py:102-104`) and from every expense key.
Re-proposal re-admits the same operation; re-admission never rebinds the
link; `OPERATION_CONTENT_CONFLICT` semantics unchanged (in-window document
freezing keeps it unreachable from drift, `runtime.py:380-381`). Probe-pinned
(P-A4/P-A5).

### 4.4 Adapter — FakePublisher gains the paired action (D46 pattern)

Mirror the S10 `FakeOA` withdrawal design on the publishing store:

- contract: `actions=("content.publish", "content.unpublish")`,
  `uniqueness=("document.id+content_digest",
  "retraction.original_external_id")`, `supports_action_context=True`
  (`work_runtime/adapter_contract.py:14-49` untouched).
- additive migration under one `BEGIN IMMEDIATE` with in-transaction PRAGMA
  probe: `receipts` gains nullable `action`/`link_digest`; new
  `retractions(original_external_id PRIMARY KEY, external_id, key, digest)`
  table. Original receipts/publications rows never deleted or rewritten.
- `execute(key, document, content_digest, *, action=None, compensates=None)`
  with the S10 guards (unknown action; withdraw without a valid three-field
  link; forward with a link — `ValueError` before any write); replay requires
  digest + normalized action + link fingerprint to match; different-key/
  same-original inserts a requesting-digest alias receipt reusing the same
  retraction id; original existence is decided from an accepted **forward**
  receipt scan (publications short-circuit), known absence stores the
  authoritative `ORIGINAL_ABSENT` rejection, real store failure stays
  `outcome_unknown`. Rejection receipts use a `RTR-…` id prefix (final
  naming Q2-adjacent, builder's local choice within the pinned shapes).
- counters: `published_count()` **unchanged** (publication rows; effects are
  never counted away) plus `retracted_count()` (retraction rows).
- **forward path byte-unchanged** (`publishing.py:141-175` today), including
  same-content dedup reusing the publication id: no withdraw-by-store-state
  branch. The external-model limit this leaves — a re-publish of identical
  `(document id, digest)` after a retraction reuses the retracted artifact's
  id, and the retraction row remains the truthful historical record — is
  documented, not "fixed" (Q4).
- `FilePublisher` untouched: forward-only contract → a linked retraction
  holds `ADAPTER_ACTION_UNSUPPORTED` at the actions preflight
  (`runtime.py:1029-1036`); its conformance opt-in skip stays a skip (Q6).

### 4.5 Proof kind — reuse `withdrawn`, no new kind

Accepted retraction resolves with the runtime-owned **`withdrawn`** proof at
the publishing family's accepted source `"publisher"`, data
`{digest, external_id, original_external_id}` (`runtime.py:946-960`; P-A12).
Never a forward `accepted` proof; C04 stays keyed on the forward proof
(kind-literal `has()`, `publishing.py:65-68,90-91`; P-A13). No `withdrawn`
source mapping → no imports, admin-only revoke, S9 reservation — all
verbatim S10 semantics (F7). Resolution binding check
(`original_external_id` equality before the accepted/rejected split,
quarantine on mismatch) applies unchanged (`runtime.py:1137-1149`).

### 4.6 Closure and finalize — unchanged machinery (probe-pinned)

Unresolved retraction blocks finalize (`OUTCOME_UNRESOLVED`); the ack must
list exactly the publish + retraction ids; the compensation disposition adds
`compensates` + `adapter_result` while ordinary dispositions keep the
three-field shape; refused retraction is recorded ("attempted, refused,
effect stands"), never reversed (P-A14..P-A16; `runtime.py:494-539`). A
completed-then-closed publishing work (succeeded closure) gains nothing here
— that is the deferred post-closure case (F9).

### 4.7 Post-closure and chains — explicitly untouched

Nothing in this slice relaxes any closed-work gate, adds any closed-work
dispatch path, or amends closure snapshots. Chains stay refused at admission
and dispatch revalidation (F4). The F2 landmine (window predicate blind to
"closed") and the F3 collision list are recorded here and in the recon as
the seed inventory for the post-closure design cycle the master may
commission later (Q9).

### 4.8 Policy layer

`PublishingPolicy` gains
`compensation_capabilities = {"content.unpublish": "content.publish"}` and
the paired-capability `action_blockers` branch (the exact
`policy.py:133-139` shape; paired → empty blockers, off-family keeps
`CAPABILITY_UNSUPPORTED`). No new policy version — the attribute is a family
declaration inherited by any future versions (S10 D10 reasoning; Q7).
Custom/old policies without the attribute degrade unchanged (P-D1 behavior).

### 4.9 Store, schema and compatibility

Runtime schema stays `1`; no runtime-code or runtime-store change at all.
The FakePublisher store migration is additive and idempotent on reopen (the
S10 concurrent-first-open pattern). Old stores open unchanged; readers treat
absent fields as absent.

### 4.10 Demo and visibility (no UI)

A **retraction chapter in `publish-demo`** (S13's `publication-demo`
withdrawal-chapter precedent, D77): publish → cancel → linked retraction →
real crash-after-commit recovery (reuse the `worker`/timeout machinery) →
exact two-id closure, counts asserted from the SQLite stores
(`published_count()==1`, `retracted_count()==1`), printed `inspect` command
runs verbatim. Q3 carries the alternative (a new top-level demo); no reader/
GUI change and therefore no browser claim (S10 D13 pattern). Installer gains
a matching module+console stage; the five AGENTS gates and their command
list stay exactly as configured (S10 D48 pattern).

## 5. Alternatives considered (rejected for this slice)

| alternative | why rejected |
|---|---|
| post-closure compensation first | highest eventual value but a genuine second design cycle: closed-work admission, dispatch carve-out, closure-amendment semantics, a new authority and abuse-bound model (F2/F3) — not the smallest coherent slice; deferred with seeds (Q9) |
| chained compensation / sagas | no bounded story; refused at two independent points today (F4); speculative semantics for compensation-of-compensation accounting |
| both families widened at once | expense already shipped; "both" adds nothing the publishing slice does not already prove (family-agnosticism is one-or-many) |
| a new `compensate_action` command for publishing | re-litigates ratified D2 for zero new guarantee; the linked variant already works verbatim (P-A2) |
| a new proof kind (`retracted`) | re-litigates D45/D14; `withdrawn` is family-agnostic by construction and its closed lifecycle (F7) carries over unchanged |
| `published_count()` excluding retracted artifacts | counts an effect away — violates the never-erase/never-count-away truthfulness rule; add `retracted_count()` instead (Q5) |
| FilePublisher retraction support | immutable hash-named artifacts are its documented model; the graceful hold (`ADAPTER_ACTION_UNSUPPORTED`) is the boundary; a file-domain retraction story would be its own design |
| automatic unpublish of retracted content on forward dedup | forward path must stay byte-unchanged (P2-class pin from S10); external-model limit documented instead (Q4) |
| new policy version gating the pairing | delays the capability for existing works for no safety gain (S10 D10) |

## 6. Open questions (each with a default recommendation)

| id | question | default |
|---|---|---|
| Q1 | confirm the sub-slice: publishing in-window now, post-closure and chains deferred | **yes — as §3**; master may overrule toward post-closure, accepting the larger cycle |
| Q2 | capability name | **`content.unpublish`** (domain-natural; avoids a third "withdraw" name colliding with `sop.withdraw`, F10); alternatives `content.withdraw` (symmetry) / `content.retract` |
| Q3 | demo shape | **retraction chapter inside `publish-demo`** (S13 D77 precedent); alternative a new top-level demo — heavier, no extra proof |
| Q4 | forward dedup × retraction interplay | **forward behavior byte-unchanged**; document the re-publish-after-retraction external-model limit; alternative: forward rejection of retracted content (rejected — changes forward semantics and re-opens P2-class risks) |
| Q5 | counters | **`published_count()` unchanged + `retracted_count()` added**; never count effects away |
| Q6 | FilePublisher | **untouched, forward-only**; its conformance opt-in skip remains a designed skip |
| Q7 | policy surface | **pairing attribute on the family, no new version** (D10 reasoning) |
| Q8 | pin `runtime.py`/`adapters.py` byte-unchanged as a DoD acceptance check | **yes** — it is the proof of the family-agnostic claim; any discovered runtime need escalates to the master rather than silently widening the slice |
| Q9 | (post-closure seeds, no default implementation) if/when post-closure is commissioned: explicit closed-cancelled predicate instead of gate relaxation (F2); amendment-not-rewrite of closure truth (F3); authority model (owner vs intervener/admin); the bound that replaces finalize-blocking; withdrawn-proof revalidation under any migratable state (F8) | recorded for that cycle; **not** decided here |

## 7. Proposed decisions (D80+, pending master ratification)

| id | decision (recommendation) |
|---|---|
| D80 | scope: publishing-family linked compensation inside the active cancellation window; post-closure, chains, cross-work, intervener authority remain deferred non-goals |
| D81 | capability `content.unpublish` paired to `content.publish` (Q2 default) |
| D82 | surface: reuse the S10 linked `propose_action` variant verbatim; `work_runtime/runtime.py` and `work_runtime/adapters.py` **byte-unchanged**, pinned at acceptance (Q8) |
| D83 | authority: current owner + `content.unpublish` grant (ordinary rule; demo grants updated) |
| D84 | business key/replay/conflict: identical D6 rule and re-admission semantics; no new codes |
| D85 | proof kind: reuse `withdrawn`; no new kind, no source mapping (F7 lifecycle verbatim) |
| D86 | FakePublisher: opt-in + paired action + additive store migration (receipts `action`/`link_digest`, `retractions` table), alias receipts, `ORIGINAL_ABSENT`, forward-receipt original-existence scan — the D46 pattern |
| D87 | forward path byte-unchanged incl. same-content dedup; retraction append-only; external-model limit documented (Q4) |
| D88 | FilePublisher untouched (holds at the actions preflight) |
| D89 | policy: pairing attribute on `PublishingPolicy`, no new version (Q7) |
| D90 | demo: `publish-demo` retraction chapter + installer stage; not a gate; no UI/no browser claim |
| D91 | docs: same-commit truthfulness updates to `runtime-boundaries.md` (family sentence), `interventions.md`, `verification.md`, `adapter-contract.md`/`file-adapter.md` as needed — no `doc_sync_map` row fires (F11), the update is owed for truth, not by the map |

## 8. Proposed bounded sprint shape (design input only)

Baseline `678d7b48…` (1015 tests, 3 named skips, five gates green per S13
close). Two waves, S10/S13 precedent:

- **W1 core** (single core developer): `publishing.py` (pairing + blockers
  branch; FakePublisher action/opt-in/store/counters),
  `tests/test_publishing.py` additions or a sibling
  `tests/test_publishing_compensation.py`, same-commit doc updates (D91).
  Meaningful RED first (the §9 list), minimal implementation, GREEN pins
  after; real crash + store-count assertions mandatory (S8/S10 lesson).
- **W2 demo**: `publishing_demo.py` retraction chapter, demo tests, README/
  README.zh entries, `scripts/verify_install.py` stage; gates' command list
  unchanged.
- **Independent acceptance precedes integration's ordinary merge/non-force
  push**: fresh battery with exact counts/skips, five gates verbatim, all
  demos, rehearsals, installer, byte-equality of untouched assets **plus the
  runtime.py/adapters.py byte-unchanged pin (D82)**, doc-sync audit, exact
  final remote SHA/CI (S9/S10 standard).

**Acceptance scenario sketch**: S1 admission matrix (pairing, window split
both variants, target matrix incl. chain refusal, key stability, replay,
authority/transfer re-admission) on the public API; S2 adapter store
(migration incl. concurrent first-open, alias, link fingerprint,
`ORIGINAL_ABSENT`, forward-unchanged pins, counters from raw SQLite); S3
resolution/proofs (binding-mismatch quarantine, `withdrawn` inertness for
C04, no imports, admin-only revoke, `adapter_result`, exact two-id ack +
dispositions, refusal-not-reversal); S4 recovery (real child death after the
retraction commits, recover confirms once, one publication + one retraction
effect, read-only inspector zero-write); S5 gates/demos/rehearsals/installer/
doc-sync + the D82 pin + protected-asset diff empty.

## 9. TDD-shaped test implications (list only — no tests written here)

RED (fail on current `678d7b48…`): paired admission inside the window
(today `REQUIREMENT_UNSATISFIED`/`CAPABILITY_UNSUPPORTED`, P-D1);
`CANCELLATION_NOT_REQUESTED` without an intent; forward payloads keep
`CANCELLATION_ACTIVE`; target matrix (confirmed-only, same-work,
non-compensation, pairing match, unknown/cross-work/failed targets); key
stability + distinctness + one store row; replay under a new command id;
holds with zero attempts (`ADAPTER_ACTION_UNSUPPORTED` on the current
contract; `ADAPTER_ACTION_CONTEXT_UNSUPPORTED` on an
action-without-opt-in contract); retraction execution (one effect per
original, alias receipt reusing the id, link fingerprint conflict,
`ORIGINAL_ABSENT` stored rejection, forward still dedup-identical); binding
mismatch quarantine; `withdrawn` proof shape at source `publisher`, C04
inertness, import denial, admin-only revoke; exact two-id ack and
compensation dispositions; unresolved retraction blocks finalize; real
child crash after commit → recover once; old-store additive migration
(concurrent first-open, idempotent reopen); conformance opt-in test
activates for `FakePublisher`.

GREEN pins: `runtime.py` + `adapters.py` byte-unchanged (D82); the entire
expense compensation suite unchanged; `FilePublisher` forward-only and its
skip intact; ordinary publishing flow byte-identical; expense/publishing
forward counters unchanged; runtime schema `1`; zero runtime dependencies;
Python ≥3.9.

## 10. Honest limits

- This draft designs nothing into existence: no code, test, UI or store
  change was made; the probe policy/adapters exist only in the throwaway
  probe script; nothing here is claimed shipped.
- The recommended slice makes **no temporal claim**: post-closure
  compensation, chains, cross-work compensation, intervener compensation
  authority and a public abandon command remain unimplemented and
  undecided; the seeds are Q9, the collisions F2/F3/F8.
- Everything remains trusted-local: principal names are configuration, not
  authentication; no tenant model; no external fencing of in-flight calls;
  no distributed leases or exactly-once; single coordinator; the publisher
  remains the local fake stand-in — no real publishing integration is
  claimed. The adapter's declared contract is local configuration, never a
  remotely verified guarantee.
- Naming hazard (F10): `content.unpublish` (this design, content family)
  must never be conflated with S13's `sop.withdraw` (SOP authoring family)
  in docs, demos or claims.
- The re-publish-after-retraction external-model limit (Q4 default) is a
  documented modeling choice of the fake store, not a guarantee about any
  real system.
- Ratification, epic/sprint attachment and any amendment of D80–D91 are the
  master's; this draft does not self-ratify and expects an independent
  design review before any implementation dispatch.

## MASTER ratification - 2026-10-16 D80-D91 (before implementation)

Ratified on the independent design review
[cf70b05](../../../.agents/notes/2026-10-16-s14-independent-design-review.md)
(verdict: implementable with amendments; 50-check family-agnosticism probe
re-proved; baseline 1015/3 reconfirmed). The DRAFT body above is ratified
**as amended** by this section; where they differ, this section governs.

- **D80–D86, D88, D89, D91** ratified **as drafted** (scope =
  publishing-family linked compensation inside the active cancellation window,
  post-closure/chains/cross-work/intervener deferred as non-goals;
  `content.unpublish` paired capability; S10 `propose_action` variant reused
  verbatim; current-owner authority; identical D6 business-key/replay rules
  with no new codes; `withdrawn` proof kind reused; FakePublisher D46-pattern
  additive migration; FilePublisher untouched; `PublishingPolicy` pairing
  attribute with no new version; same-commit truthfulness docs with no
  doc_sync_map row firing), with two additions: **D86+MD-2** — the
  `FakePublisher` contract keeps `"content.publish"` FIRST in `actions`
  (the conformance mixin derives forward context from `actions[0]`), and the
  retraction receipt id prefix is pinned deterministically at implementation
  and documented; **D91+MD-4** — `roadmap.md` 0.3 (the beyond-window
  compensation sentence) joins the master-owned close-out doc set.
- **D82+MD-5** — the `runtime.py`/`adapters.py` **byte-unchanged pin stays as
  a DoD acceptance check** with the escalation rule: any implementation that
  believes a runtime/adapters edit is unavoidable stops and asks the master
  via Orca rather than editing.
- **D87 (AMENDED per RF1/MD-1 — replaces the drafted byte-level pin)** — the
  forward path is pinned at **behavior level**: no withdraw-by-store-state
  branch in the forward path; same-content forward dedup still returns the
  same receipt with identical dispositions and store state (result/store-state
  identity); retraction remains append-only. The single mechanical
  column-naming edit to the receipts INSERT is **allowed and must be
  disclosed** in the report. The re-publish-after-retraction external-model
  limit is documented **with the RF4 reachability note**: through the governed
  runtime the interplay is unreachable (permanent-intent `CANCELLATION_ACTIVE`
  refusal same-work; store-global forward business key collision
  `OPERATION_CONTENT_CONFLICT` cross-work) — the limit binds the adapter
  model, not the governed flow.
- **D90 (SETTLED per RF2/MD-1)** — the demo structure is pinned to
  **alternative (b), additive**: `publish-demo` KEEPS its existing
  succeeded-completion story on the first work and APPENDS a second work
  demonstrating cancellation + linked retraction + the exact two-id closure;
  asserted counts are `published_count == 2, retracted_count == 1` (the
  drafted (1,1) implied silently dropping the succeeded-completion path and
  is rejected). The installer's existing publish-demo stage assertions
  (publications/final line) are updated in the SAME commit, and a NEW console
  stage is added — disclosed as new coverage (the current stage is
  module-only), extending rather than matching the publication-demo
  module+console precedent. Not a gate; no UI/browser claim.
- **Q1–Q9 defaults ratified as drafted**, with Q4 sharpened by the RF4
  reachability note above.

No external fencing, no distributed guarantees, no chain/universal
compensation, no tenant authentication, no history rewrite. Trusted-local
principals are not identities; the S10/S12/S13 accepted boundaries carry
over unchanged.
