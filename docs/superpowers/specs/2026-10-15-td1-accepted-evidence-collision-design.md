# TD-1 accepted-evidence collision — candidate design (DRAFT)

Status: **DRAFT — pending master ratification.** This is a candidate design
prepared on the next-core-recon checkout at `a90ddc6` (base published main
`635e7b1`). It allocates no epic or sprint id, writes no ADR, mutates no
roadmap ledger, and is **not** an implementation instruction: no product code
changes until the master ratifies a design. Suggestions below are the
designer's recommendations, each paired with the decision the master owns.
Primary evidence: the TD-1
[tracker row](../../../docs/tech-debt-tracker.md), the S8
[design review D-4](../../../.agents/notes/2026-10-14-S8-design-review.md)
finding, the post-S8 [recon](../../../.agents/notes/2026-10-15-next-core-recon.md)
with its public-API probe, and two /tmp spikes for this draft
(`/tmp/next-core-recon-2026-10-15/{probe_td1_compensation_gap,spike_td1_design_scope}.py`,
throwaway, temporary stores, public API only).

## 1. Problem (grounded, with line-level citations)

The evidence table's primary key is `(source, event_id)`
(`work_runtime/runtime.py:107-110`). When an external operation confirms
accepted, `_resolve` INSERTs a runtime-owned `verified` proof of kind
`accepted` with `event_id = operation id` under the operation's work's
current accepted source (`runtime.py:911-921`). `record_evidence` intake
(`_receive`, `runtime.py:657-682`) never consults the operations table, so a
trusted-local actor who is a configured **accepted source** can pre-register
an event whose id equals a stored, not-yet-confirmed operation id. The later
INSERT then raises `sqlite3.IntegrityError: UNIQUE constraint failed:
evidence.source, evidence.event_id` forever: the external acceptance exists
(adapter store has the effect) but can never be recorded; the operation is
stuck `dispatched/in_flight` with attempt `outcome_unknown`; `reconcile`
re-raises identically; `recover()` aborts on that operation every cycle, so
store-wide supervision liveness breaks and every operation stored after the
poisoned row is starved (row-order walk over re-saved rows; recon probe §3).
Signed ingress cannot produce this (`ingress.py:25-27` reserves kind
`accepted`); both directions are trusted-local misuse only.

Spike evidence added for this draft (all assertions held):

- **S1 cross-work**: the accepted-source actor recorded *work W2's* operation
  id as an event id while writing into *work W1*; W2's dispatch then failed
  on the store-global PK. A same-work-only guard is insufficient.
- **S2 kind-literal insufficiency**: with a policy mapping a second,
  ordinary kind (`duplicate_clear`) to the accepted-source actor, the
  colliding row was created **without ever using kind `accepted`**. A
  `kind == "accepted"` guard is insufficient; the danger condition is
  *source equality*, not kind.
- **S3 precedence facts to preserve**: exact resends return the stored
  candidate's current status via the dedup branch; changed content under the
  same `(source, event_id)` is `SOURCE_EVENT_CONFLICT`; a persisted rejected
  intake replays its stored rejected receipt verbatim under a new command id
  while authority holds.

Master motivation (ruling received): the next bounded core slice repairs
TD-1 **before** compensation, because every compensation effect resolution
would ride the same `_resolve`/`recover` path.

## 2. Goals and non-goals

Goals: (a) prevent the collision at intake without disturbing legitimate
accepted-source imports, dedup/resend semantics, or the confirmed-proof
`SOURCE_EVENT_CONFLICT` behavior; (b) give existing poisoned stores a
bounded, durable, honest resolution path so `recover` liveness is restored
without deleting, overwriting, converting or fabricating anything; (c)
document trusted-local limits; (d) repay TD-1 against its written criteria.

Non-goals (master constraints): no schema change (stays `1`); Python ≥3.9,
stdlib only; permanent source/body/fingerprint/old receipts/history/effect
business keys; no authentication, no source-key rotation, no compensation,
no fencing, no new UI; no auto-erase of the conflicting candidate or
operation; no silent conversion of the poisoned proof to `revoked`/`invalid`;
no fake authoritative proof; generic cache/fingerprint/version precedence
unchanged.

## 3. Part A — intake reservation (prevention)

### A1 Predicate (recommendation: registry-union source equality)

Reject a `record_evidence` when **both** hold:

1. `event_id` exactly matches a stored operation id (indexed PK lookup
   `SELECT 1 FROM operations WHERE id=?`), and
2. the actor is the configured accepted source of **any** policy version in
   the loaded registry — `actor ∈ {p.evidence_sources.get("accepted") for p
   in self.policies.values()}`, precomputed once at `Runtime.__init__`.

Why the union is sound and complete: `_resolve` INSERTs only under
`self._accepted_source(work_of_op)`, which resolves to the accepted source of
a **loaded** registry policy (a work whose pinned version is missing fails
closed and can never resolve). Every possible INSERT source is therefore in
the union, so the guard blocks every actor who could ever create a colliding
row, and blocks no one else (unrelated sources and unrelated kinds are free —
they cannot collide by construction). It also needs no cross-work policy
resolution, avoiding a new fail-closed edge. Cost: one indexed lookup per
intake, plus a conservative over-block in the exotic case where the matched
operation belongs to a work whose accepted source is a *different* actor than
the writer (rejected import of an operation id — dubious content anyway; the
rejection receipt says why).

Alternative considered (exact op-work policy): resolve the matched
operation's own work and compare against *that* policy's accepted source.
Exact, but it loads another work inside `_receive`, must define behavior when
that work's pinned version is not loaded, and saves nothing the union does
not already guarantee. Not recommended.

Future ids need no reservation: operation ids are runtime-generated `uuid4`
hex stored in the same transaction that creates them
(`runtime.py:647-654`), so an id absent from `operations` cannot later appear
except by 2^-122 coincidence — stated, not handled. Reservation never
expires (operations rows are permanent); accepted sources therefore can never
import an event id that aliases a stored operation, which is the invariant's
point. Legitimate imports are unaffected in practice because real external
event ids are externally generated and never runtime `uuid4` hex (recon
probe: fresh-id import accepted).

### A2 Precedence inside `_receive` (unchanged order, one new step)

```text
shape/identity checks (unchanged)
→ source+kind authority (unchanged)
→ existing-row branch (unchanged): fingerprint match → dedup resend with
   current status; mismatch → SOURCE_EVENT_CONFLICT
→ NEW reservation check (A1) → rejected OPERATION_ID_RESERVED
→ insert pending candidate (unchanged)
```

Existing dedup and the confirmed-proof conflict behavior therefore remain
exactly as spiked (S3): an *exact resend* of a pre-fix accepted poisoning
command still replays its stored accepted receipt with the candidate's
current status; a post-confirmation record under the same id is still
`SOURCE_EVENT_CONFLICT` (the runtime-written proof row exists). The
reservation only governs the no-existing-row path.

### A3 Rejection code and receipt (recommendation)

New code **`OPERATION_ID_RESERVED`** (a distinct admission fact — not a
fingerprint conflict, not an authority failure). Receipt:
`{"decision": "rejected", "code": "OPERATION_ID_RESERVED",
"observed_state_version": v, "blockers": [<matched operation id>]}`,
persisted like any rejected receipt; replays verbatim while current
source+kind authority holds (the `record_evidence` replay branch is
unchanged). Alternatives: `SOURCE_EVENT_ID_RESERVED`, or reusing
`SOURCE_EVENT_CONFLICT` (rejected — different meaning, would corrupt the
S3-pinned semantics). `CommandError` is wrong: this is a persisted business
rejection, not API misuse.

### A4 Retirement and migration semantics

The union is computed from the **currently loaded registry**, so it travels
with configuration: after `migrate_policy` renames the accepted source (V1
`oa` → V2 `oa2`), a runtime serving both versions reserves both actors —
correct, because V1-pinned works still resolve under `oa`. If V1 is not
loaded, V1 works are unreadable (fail closed), their operations can never
resolve, and no INSERT can occur under `oa` — the shrunken union stays sound.
The guard neither extends nor reduces authority: a retired accepted source is
already denied at the authority step for its kinds; a stored
`OPERATION_ID_RESERVED` receipt stays rejected on replay (verbatim stored
receipt), consistent with every other rejected receipt. S8 retirement rules
(old-source pending proofs never re-verify; revoked permanent) are untouched.

## 4. Part B — existing poisoned stores (undecided by master; options compared)

Prevention cannot heal a store already poisoned: the conflicting row exists,
the operation is `dispatched`, the external effect is already committed. The
master asked for a comparison; three candidate behaviors:

### B-option P1 — prevention-only, honest residual rollback loop

Leave `_resolve` as is. Poisoned stores keep the IntegrityError loop and the
`recover` abort, documented as a trusted-local residual. Smallest diff; but
it leaves the slice's own motivation (deterministic `_resolve`/`recover`
failure with retained external effect) unfixed for every existing store, and
TD-1's repayment could then only be claimed *partially* (the master's
explicit caveat). There is also no manual remedy inside the public API: rows
are permanent, so no command sequence clears the collision. Not recommended.

### B-option P2b — mark the operation `outcome_unknown` + `needs_attention`

On conflict, set the op `outcome_unknown` (reason `EVIDENCE_RESERVED_CONFLICT`),
work `needs_attention`, durable event; `recover` proceeds past it. But the
adapter's authoritative answer says *accepted* — parking a known-accepted
external effect as "unknown" misrepresents stored external truth, and it
blocks `finalize_cancel`/`request_completion` forever via
`OUTCOME_UNRESOLVED` with no exit except direct store surgery. Rejected.

### B-option P2a — record the real acceptance on the operation; surface the proof conflict (recommended)

In `_resolve`'s accepted branch, before the INSERT, pre-check
`SELECT body FROM evidence WHERE source=? AND event_id=?` with
`(accepted_source, op id)` (exact PK probe — deterministic; no
exception-control-flow). If a row exists, in the **same transaction** as all
other resolution writes:

- operation: `status = "confirmed_succeeded"`, `dispatch_state = "finished"`,
  `external_id = result["external_id"]`, `attempts[-1]["status"] =
  "confirmed_succeeded"` (the external acceptance is real and authoritative;
  this records it, it does not fabricate a proof), plus one additive JSON
  field `proof_conflict = {"source", "event_id", "evidence_id",
  "evidence_kind", "evidence_status", "external_id", "digest"}` snapshotting
  the conflicting row **verbatim at resolution time** (its status may since
  have changed via `verify_pending` — pending/verified/invalid/revoked are
  all possible and all recorded; the row itself is never mutated here);
- work: `status = "needs_attention"` (sticky under `_evaluate`,
  `runtime.py:197-199`), requirements recomputed honestly from the actual
  stored evidence — E08 is satisfied only if the conflicting row is
  `verified` with a matching digest, which is the pre-existing trusted-local
  boundary, now made visible;
- one durable event `AcceptanceProofConflict` with the same body; exactly one
  version bump (single `_save`, mirroring `_revoke`'s pattern).

Nothing is deleted, overwritten, converted to `revoked`/`invalid`, or
revived; no authoritative proof is synthesized; the actual external
acceptance and the conflicting import remain distinguishable in public
stored truth (operation carries `external_id` + `proof_conflict`; the
imported row keeps its own identity and can still be revoked/inspected
through existing commands if a human decides so).

Replay/idempotence: after the first conflict resolution the op is
`confirmed_succeeded`, so `_resolve`'s terminal early-return
(`runtime.py:901-902`) and `reconcile`'s status guard make every subsequent
`reconcile`/`recover` a no-op for it — zero writes, zero adapter calls, and
`recover` reaches all other operations (liveness restored; bounded work per
cycle). Crash atomicity: the whole transition is one `_transaction`; a crash
between the external effect and this block rolls back to `dispatched`, and
the next `reconcile` redoes it deterministically (lookup is a read; the
adapter never re-executes a dispatched operation). Exactly-one external
effect and attempts count are asserted in tests by adapter counters.

Requirements/closure behavior (explicitly, as the master asked): a
`confirmed_succeeded` operation without an automatic proof does not satisfy
any requirement by itself — `request_completion` still demands satisfied
requirements plus no unresolved operations, so if the conflicting row never
verifies, completion stays blocked; if it *did* verify (shape-valid synthetic
acceptance), completion becomes possible citing that proof — this is exactly
the capability the trusted-local boundary already grants today with no
dispatch at all (recon probe §3.3), and the durable conflict event plus
`needs_attention` surface it rather than hide it. `finalize_cancel`
acknowledgement semantics need no change: the conflicted op is
`confirmed_succeeded`, its effect is real, and the ack set (exactly the
succeeded ids) remains truthful. **Whether `request_completion` should
additionally block while any operation carries an unresolved `proof_conflict`
is a master decision** (§D6) — recommended *no new blocker* for the minimal
slice, because the acceptance is real and the conflict is visible; the
stronger gate is a one-check addition if the master prefers it.

Rejected-result operations never INSERT a proof and cannot collide; their
path is unchanged. Closed works cannot host a poisoned dispatched operation
by construction (both closure paths require all operations resolved), so no
closed-history case exists to handle.

### B-fixture — "real existing prevention-bypassed store" (recommendation)

Post-fix, the poisoning intake is rejected, so tests must construct the
pre-fix state directly: a fixture that INSERTs the evidence row with exactly
the legacy canonical shape `_receive` wrote — same five columns, fingerprint
`digest([work_id, payload])`, candidate body `{"id", "source", "event_id",
"kind", "data", "status": "pending_verification"}` — using the **accepted
original inputs** (the same payloads/receipts the recon probe recorded),
labelled as a legacy-store fixture. Additive JSON only: readers must treat a
missing `proof_conflict` as absent. A test-only escape hatch in the product
guard is explicitly rejected (it would weaken the invariant the slice
exists to restore).

## 5. Authority and trusted-source boundary (unchanged surface)

The reservation adds no authority: it fires only after the existing
source+kind admission, it is computed from the same trusted-local registry
the runtime already trusts, and it never grants a write. The
synthetic-acceptance fact (a trusted accepted source can satisfy
`accepted`-kind requirements by shape without any external effect) is the
documented trusted-local boundary, unchanged by this design — Part B only
makes its collision consequence visible and recoverable. No authentication,
tenant, or key-rotation claim is made or implied.

## 6. Public stored truth summary (proposed)

| surface | addition |
|---|---|
| rejection code | `OPERATION_ID_RESERVED` (persisted receipt, blockers `[op id]`) |
| operation JSON | additive `proof_conflict` object (absent on legacy rows) |
| event type | `AcceptanceProofConflict` (body = the `proof_conflict` object) |
| work status | `needs_attention` on conflict resolution (existing status, sticky) |
| inspection/GUI | zero code change: `inspection.py` renders events generically (`events()` `type` passthrough, `runtime` `inspection.py:243-257`) and `event_types` is a GROUP BY (`inspection.py:204-205`); web assets whitelist no event names (verified by source scan) |

Precedence (final): identity/shape → authority → dedup resend →
`SOURCE_EVENT_CONFLICT` → **`OPERATION_ID_RESERVED`** → insert. Command
CAS/fingerprint/version mechanics untouched.

## 7. Proposed tests (RED → GREEN; named, public API where possible)

RED (fail on current `a90ddc6` runtime):

1. `test_accepted_source_cannot_reserve_operation_id` — fresh-id import
   accepted, then op-id import rejected `OPERATION_ID_RESERVED` (today:
   accepted).
2. `test_reservation_is_global_across_works` — S1 shape: op of W2, import
   into W1 → rejected (today: accepted, W2 dispatch raises).
3. `test_reservation_is_source_scoped_not_kind_scoped` — S2 shape:
   overlapping-mapping policy, non-`accepted` kind → rejected; and
   `invoice-service` may still record any event id (no false block).
4. `test_legacy_poisoned_store_resolves_with_proof_conflict` — B-fixture →
   dispatch/reconcile → `confirmed_succeeded` + `proof_conflict` +
   `AcceptanceProofConflict` + `needs_attention`, exactly one external
   effect (`FakeOA.accepted_count() == 1`), attempts length 1 (today:
   IntegrityError).
5. `test_recover_liveness_after_conflict` — fixture with poisoned op plus a
   second ready op → `recover()` completes without raising, second op
   dispatched/confirmed, poisoned op no-op on repeat, adapter call counts
   bounded (today: raises, second op starved).
6. `test_conflict_resolution_is_crash_atomic` — `fault` injection before the
   resolution transaction + real `os._exit` child per the repo's crash
   standard (`tests/test_runtime.py:266,278` idioms) → rolled back to
   `dispatched`, redone identically on retry.

GREEN (preservation, pinned): dedup resend with current status (S3);
`SOURCE_EVENT_CONFLICT` on changed content and post-confirmation; replay of
the new rejection verbatim; legit fresh-id imports for both families;
`verify_pending` may still flip the conflicting row's status before/after
resolution and the event snapshot reflects the status at resolution;
conflicting row already `revoked` at resolution → conflict still handled, row
untouched; migration with renamed accepted source reserves both actors;
retired source cannot import anyway (authority first); publishing family
(`FakePublisher`) mirror of 1/4/5; request_completion/finalize_cancel
behavior per §D6 ruling.

Extent: the 702-test baseline, five AGENTS gates, five demos, 14 rehearsal
tests and `verify_install.py` remain green with no UI change and no new
dependency; skip disclosure unchanged (the single S5/S6-inherited skip).

## 8. Documentation, acceptance and release requirements

- `docs/runtime-boundaries.md` updated in the **same commit** as
  `runtime.py` (doc_sync_map row): reservation precedence, the new code,
  conflict-resolution semantics, trusted-local limits.
- `docs/verification.md` and `docs/interventions.md` TD-1-deferred mentions
  updated; `docs/evidence-revocation.md` TD-1 note updated.
- TD-1 tracker repayment citing the merge commit hash. With P2a the written
  criteria are met in full (intake rejection + meaningful tests of legitimate
  imports and actual accepted-effect reconciliation); with P1 the master
  must explicitly restate the criteria as partial — another reason P2a is
  recommended.
- Independent acceptance precedes integration-owned merge/non-force push;
  remote equality and exact-SHA CI per house standard. Epic/sprint/ADR
  allocation is the master's; this draft claims none.

## 9. Unresolved master decisions (each with recommendation)

| id | decision | recommendation |
|---|---|---|
| D1 | Poisoned-store behavior: P1 vs P2a vs P2b | **P2a** (liveness + honest external truth; §4) |
| D2 | Predicate variant: registry-union vs exact op-work policy | **registry-union** (sound, complete, no new fail-closed edge; §A1) |
| D3 | Rejection code name | **`OPERATION_ID_RESERVED`**, blockers `[op id]` (§A3) |
| D4 | Reservation receipt replay | unchanged protocol (stored verbatim) — no new ruling needed unless master objects |
| D5 | Retirement/migration | union from loaded registry (§A4) — confirm |
| D6 | `request_completion` blocker while `proof_conflict` present | **no new blocker** (minimal slice; visible via event + needs_attention); stronger gate is the alternative |
| D7 | Poisoned-store fixture approach | direct legacy-shape row insert from accepted original inputs (§B-fixture) |
| D8 | Whether the synthetic-acceptance boundary gets an explicit doc note in this slice | recommended yes, one paragraph in runtime-boundaries |
| D9 | Event/field naming (`AcceptanceProofConflict`, `proof_conflict`) | confirm or rename |
| D10 | Repayment criteria statement (full vs partial) follows D1 | with P2a: **full**; with P1: partial, explicitly restated |

## 10. Alternatives considered (summary)

Prevention-only (P1): minimal diff, leaves recover broken for existing
stores, forces a partial repayment claim. Parking as outcome_unknown (P2b):
misrepresents a known-accepted effect and permanently blocks closure.
Exact per-operation policy predicate: correct but heavier and adds an
unloadable-policy edge inside intake. Reusing `SOURCE_EVENT_CONFLICT`:
corrupts pinned semantics. Test-only guard bypass for fixtures: weakens the
invariant. Reservation scoped to kind `accepted` or to same-work: both
disproved by S1/S2. Erasing/converting the conflicting row or regenerating
proofs for confirmed ops: forbidden by the master's permanence constraints
and S8 D36 discipline.

## MASTER ratification — 2026-10-15, D38–D42 (before implementation)

This section supersedes all conflicting DRAFT suggestions above. Master owns
these choices under the user's explicit autonomous supervision authorization.
Independent builder check: [report](../../../.agents/notes/2026-10-15-TD1-independent-design-review.md), source b8bba84. Draft source90e980b retained as history.

- **D38 / draft D1,D10:** P2a prevention AND existing-poison resolution; TD-1 stays open until both are independently proven and published. Compensation follows separately. No deletion, replacement, conversion or regeneration of an existing evidence row.
- **D39 / D2–D5:** reservation after unchanged authority and existing-row dedup/conflict branches; OPERATION_ID_RESERVED persisted normal rejection with blockers [operation_id]. Compute accepted-source union from currently loaded policies **per intake**, filtering only nonempty string accepted sources. Never assume an accepted-source fallback or policy-object immutability. Any stored operation id is reserved for every source in that union, across works and across proof kinds, permanently; conservative over-block on different accepted-source operations is explicit. Unrelated sources and legitimate fresh-event imports remain valid. Cache/version/fingerprint precedence and source replay authority remain unchanged. Missing registry versions still fail closed through existing rules; no source authority broadened.
- **D40 / D7,D9,F1,F2:** conflict lookup returns SQL work_id/fingerprint and parsed evidence body. Operation gains proof_conflict with exactly nine fields: source, event_id, evidence_id, evidence_work_id, evidence_kind, evidence_status, evidence_fingerprint, external_id, document_digest. source/event_id are the collision PK; evidence_work_id and evidence_fingerprint are the existing SQL columns; evidence_id/kind/status are nonempty body strings else null. external_id and document_digest are the actual validated adapter result and operation digest, **not** candidate data.digest. Do not include ambiguous digest or coerce candidate values. Valid JSON object with malformed/missing fields degrades as above; general corrupted-store/invalid JSON repair is out of scope. Stored candidate raw/body/fingerprint/identity remains byte-identical.
- **D41 / D6,D8,F3,F4:** on a valid accepted external result colliding with any existing candidate (any kind/status/work), persist actual operation confirmed_succeeded/finished/external_id and existing attempt terminal state; never execute again. Set work needs_attention only when it was not closed. Closed status/outcome/completion remain unchanged, even in custom legacy fixtures. Single atomic resolution transaction, one work version bump, one event AcceptanceProofConflict with the nine proof_conflict fields plus operation_id and work_was_closed (eleven fields); conflict event replaces ordinary OperationResolved for this resolution, normal resolution remains unchanged. Subsequent terminal-op reconcile/recover makes no writes to **that operation or its conflict-resolution event**, no new external execute or lookup for that settled op; recover may verify/expire other records and must reach other operations. No new completion blocker: trusted-local accepted imports already can satisfy requirements independently, and completion still requires normal requirements/no unresolved ops. A conflict does not silently revoke proof authority. Admin/source may explicitly revoke through S8; replacement new-event proof remains available through current source; cancellation acknowledges the real confirmed effect. No automatic proof repair or historical rewrite. Document general trusted-source boundary, not authentication or distributed safety.
- **D42 / tests/release:** meaningful prevention and legacy-fixture RED/GREEN in both families, real accepted effect count/keys and later-operation liveness, exception/real process-death rollback then bounded reconciliation; full row preservation, normal rejection/replay/import preservation and custom closed/malformed-id tests. Direct legacy canonical-row fixtures clearly labelled accepted pre-fix inputs; no product bypass. Runtime and boundary docs in SAME implementation commit. Generic inspector exposes raw operation plus conflict event, no reader/UI changes. Fresh 702 baseline+new/full5gates/5demos/14rehearsal/install; independent integration accepts and publishes exact final SHA/CI. Scope never expands to compensation/auth/fencing/UI.

All draft D1–D10 and independent F1–F4 are resolved by these choices; no implementation question or approval UI remains. Existing policy/source mutation is read per call only for reservation, not a new live-policy mutation contract.
