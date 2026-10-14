> **Provenance (added by the copyist, 2026-10-15):** verbatim copy of the independent
> builder-check report from the compensation-design-review checkout at commit
> `00833d8` (branch WayJ/compensation-design-review, clean), copied into this checkout's
> notes as supporting input for the DRAFT v2 revision of
> [the candidate design](../../docs/superpowers/specs/2026-10-15-compensation-execution-design.md).
> Everything below the rule is the reviewer's text, unmodified.

---

# Independent compensation design review (builder-check) — 2026-10-15

## Scope, evidence and verdict

Independent builder-check of the DRAFT
[compensation execution design](../../docs/superpowers/specs/2026-10-15-compensation-execution-design.md)
at candidate `d683429943e7cee1befbf08a6ec2725c116f8c11` (branch
`WayJ/compensation-design`, parent = published main `254c714`, read via `git
show` against this fresh baseline checkout at `254c714`, clean). Master owns
ratification; this note implements nothing, allocates nothing, and mutates no
ledger. Sources read as truth here: `AGENTS.md`, [RFC-001](../../docs/RFC-001-core-semantics.md)
§7 D8/取消, `runtime.py`, `policy.py`, `adapters.py`, `adapter_contract.py`,
`inspection.py`, `demo.py`, `cli.py`, [interventions.md](../../docs/interventions.md),
[runtime-boundaries.md](../../docs/runtime-boundaries.md),
[adapter-contract.md](../../docs/adapter-contract.md),
[verification.md](../../docs/verification.md), the S9 acceptance, the TD-1
design (D38–D42) and the candidate's own
[recon](2026-10-15-compensation-design-recon.md). One throwaway public-API
probe ran twice deterministically (all 22 checks pass both runs) from
`/tmp/compensation-review-2026-10-15/probe_review.py` on fresh `/tmp` stores;
nothing was committed from it.

**Verdict: the runtime-side design (§4.1–§4.7, §4.9–§4.11) is sound and
verified against the code; §4.8 (FakeOA withdrawal action) is not
implementable as written and must be re-decided before ratification.** The
master's critical concern is confirmed by probe: with
`execute(key, document, digest)` receiving no capability and no `compensates`
link (`runtime.py:929`), the design's implied routing ("resolves the original
external_id from its own invoices rows for the document's invoice ids")
cannot select the action and cannot bind the exact original — and in the
duplicate-invoice case it silently converts a business-rejected forward submit
into a real withdrawal. Three bounded alternatives are laid out in §3; two
further material defects (withdrawal accepted-proof falsifying E08; D9
different-key reuse breaking both recovery paths) need amendments under every
alternative. Scope recommendation (expense-only, active-cancellation window,
no saga/auth/fencing claims) is endorsed.

## 1. Prioritized material findings

### F1 — CRITICAL (blocks ratification of §4.8): no action selector, no exact-original binding; implied routing mis-executes

`Adapter.execute` receives `(business_key, document, document_digest)` only
(`runtime.py:929`); the capability is checked against the declared contract
(`runtime.py:916-923`) but never reaches `execute`. The two business keys are
opaque digests of different tuples (forward `digest([id, capability,
document.id, document_revision])` `policy.py:138-140`; compensation
`digest([policy.id, capability, target_operation_id])` §4.3) — an adapter
cannot tell which derivation produced a key, so the hashed key is not an
action selector. §4.8's only offered rule is store-state inference, which
fails four ways (probe P1/P2, real `FakeOA`/`Runtime`/`ExpensePolicy` on
fresh stores):

| case | today | under §4.8 implied routing | probe |
|---|---|---|---|
| duplicate-invoice forward submit (same invoice ids, new key/digest-identical doc) | business-rejected receipt (`adapters.py:51-54`) | **withdraws the earlier acceptance** and returns an accepted `WD-…` receipt → the duplicate submit resolves `confirmed_succeeded` as a withdrawal | P2a vs P2b/P2c |
| compensation linked to op1 after the work document was revised to a second accepted op2's invoices | n/a | binds the **wrong original** (resolves op2's external id; link says op1's) | P1b |
| current document carries never-submitted invoice ids | n/a | resolves nothing → §4.8 "missing original raises" → `outcome_unknown` → `reconcile` lookup `None` → `NO_AUTHORITATIVE_RESULT` `needs_attention`; with D11 (no abandon) finalize is blocked **forever** via the ordinary revise-then-cancel flow | P1c |
| current document spans two acceptances (revision merged invoice sets) | n/a | resolves **two** originals — §4.8's own premise ("all rows of one acceptance share one external id", `adapters.py:56-58`) is per-acceptance true and document-wide false; unspecified | P1d |

The duplicate-submit inversion is the decisive one: the uniqueness contract
§4.8 claims to preserve ("the established adapter rule") is exactly what
state-inferred routing destroys. Any ratified mechanism must make the action
and the original **explicit** — see §3.

### F2 — CRITICAL (design gap feeding F1): the compensation operation's execution document/digest is the *current work state*, not the original's

`_propose` builds the operation body from work state
(`"document": work["document"]`, `runtime.py:657-662`), and §4.1 keeps that.
So the document an adapter may consult for binding is the work's current
document at compensation-proposal time — which may have replaced its invoice
ids after the original's accepted effect (F1 rows 2–4). §4.4 *stores* the
exact binding (`compensates.external_id`, a terminal-fact snapshot) but no
runtime path ever passes it to the adapter — the information exists and is
dropped at the dispatch boundary. Whichever §3 alternative is chosen, the
design must state precisely what document and digest a compensation operation
carries and where each of the four digest touchpoints lands: the admission
scope check (`runtime.py:626-627`), the pending different-digest guard
(`runtime.py:640-643`), the dispatch staleness re-check
(`op["document_digest"] != work["document_digest"]` → `STALE_INTENT`,
`runtime.py:898-905`), and `execute`'s own `digest(document) != content_digest`
check (`adapters.py:40`) plus `receipt_is_valid` (`adapter_contract.py:69-73`).
Note: if the op document is re-bound to the *target's* document (Alternative
A), the dispatch staleness digest comparison **will cancel the compensation**
whenever the work document has moved on — so Alternative A necessarily
 widens §4.5's "exactly one carve-out" claim; see §3.

### F3 — HIGH: withdrawal resolution inserts a kind-`accepted` proof that satisfies E08 for content OA never accepted — false authoritative forward proof

`_resolve` → `_proof_conflict` inserts a runtime-owned `kind: "accepted"`
proof with `data.digest = op["document_digest"]` (`runtime.py:862-866`) for
**any** accepted result. Under the design a withdrawal op carries the current
work digest, and inside the window the document is frozen (P4c;
`runtime.py:381` blocks `revise_document` under an active intent), so the
withdrawal proof's digest equals the work's current digest forever. E08's
`has("accepted")` matches kind + current digest (`policy.py:91-93,124-125`),
so after a withdrawal resolves, E08 reads *satisfied* for the current content
even when OA never accepted that content forward — probe P3 demonstrates the
full flip: forward acceptance at digest1 → revise → E08 pending at digest2 →
withdrawal resolves → E08 **satisfied** at digest2 with
`oa.accepted_count()==1` and no invoice row for the revised content (P3b→P3e,
P3f). In-slice no gate consumes E08 (`action_blockers` excludes E08,
`policy.py:131`; the window blocks submits/completion), so this is
truth-corruption rather than gate-corruption today — but the stored evidence
row is a false authoritative forward claim, it survives S8 revocation of the
original proof (both rows match the digest in the no-revision case), and it
directly violates "no false authoritative forward proof". Amendment needed
under every alternative: compensation resolutions insert a **distinct kind**
(e.g. `"withdrawn"`/`"withdrawal"` — inert to `evaluate`, which reads only
known kinds; S9 reservation already covers all kinds,
`runtime.py:667-682,704-713`) or insert no runtime-owned proof at all (the
operation body, receipt and closure snapshot already carry the truth).
Master decision required (D14 below).

### F4 — HIGH: D9 different-key reuse as written breaks both recovery paths

§4.8: "a different key targeting an already-withdrawn original returns the
existing withdrawal receipt". Two failures (probe P5, real functions):
(1) the existing receipt carries the *first* key's digest, so
`receipt_is_valid(result, requesting op digest)` is false
(`adapter_contract.py:69-73`) → `ADAPTER_RESULT_INVALID` → `needs_attention`
— an "invalid digest loop" the design never resolves; (2) `lookup` is keyed
by `receipts.key` (`adapters.py:69-75`), so `lookup(key2)` returns `None`
→ `NO_AUTHORITATIVE_RESULT` — lost-response recovery fails after a
crash-after-effect even though the withdrawal row exists (under `key1`).
Amendment: separate the surfaces — per-key receipts rows remain the
idempotency/lookup surface (on different-key/same-original, insert a receipts
row under the *requesting* key carrying the *requesting* digest and the
**same** `WD-…` external id), while the `withdrawals` table stays the
per-original effect surface (`UNIQUE(original_external_id)`) that guarantees
exactly one withdrawal effect. Then `execute` returns a digest-valid receipt
and `lookup` stays authoritative-by-key for every legitimate key. (When a
different key can actually arise: cross-runtime stores sharing one external
system; in one runtime+store the D6 key is deterministic per original.)

### F5 — HIGH: `accepted_count()` stops being the forward effect count if withdrawal results ride the receipts table

`accepted_count()` counts receipts rows with `status == "accepted"`
(`adapters.py:77-82`) and is pinned as the honest forward count across the
suite (e.g. `tests/test_adapter_contract.py:236,259,366`;
`tests/test_accepted_evidence_collision.py:346-506`). §4.8's withdrawal
receipt has `status: "accepted"` and its idempotency language ("same key+digest
→ same receipt") implies receipts-table storage — after one submit + one
withdrawal, `accepted_count()` returns 2, contradicting the design's own
assertion `accepted_count()==1` (§7) and the truthful-accounting goal (§2b).
Amendment (composes with F4): receipts rows are the per-key call surface;
**effect counters count effect tables** — forward count = acceptances (e.g.
`COUNT(DISTINCT external_id) FROM invoices`), withdrawal count = `withdrawals`
rows. State it in §4.8 and pin both counts in TDD.

### F6 — MEDIUM: the window carve-out must explicitly cover re-admission, and `interventions.md` owes the matching amendment

The cancellation gate in `_propose` (`runtime.py:620-621`) sits **before**
the business-key re-admission branch (`runtime.py:643-658`): inside the window
every re-proposal — including re-admission of an existing intent — is
`CANCELLATION_ACTIVE` today (P4b, P4f). §4.5's "the new owner re-proposes
through the unchanged re-admission path" therefore only works if the
compensation variant's gate exemption covers **both** the fresh-proposal and
re-admission paths (outside the window re-admission works and re-prepares to
`ready` with the actor updated — P4e). `interventions.md` currently states
"new waits, proposals **and re-admission** … are rejected `CANCELLATION_ACTIVE`"
— the same-commit interventions.md amendment (§8 row already exists) must
state the compensation-variant exception precisely. Verified bounded while
here: document/plan/contract/migration are frozen in-window (`runtime.py:381`,
P4c), so the re-admission digest guard (`OPERATION_CONTENT_CONFLICT`,
`runtime.py:646-647`) cannot fire from document drift inside the window —
the key-dedup story (one store-global `business_key UNIQUE` row per (family,
capability, original); re-proposal re-admits; a *different target* is a
different key and legitimately a second withdrawal) holds as designed.
`request_cancel` ordering is safe (it runs before any compensation can exist
and cancels only what exists); `transfer_owner` invalidates prepared
compensations uniformly (`runtime.py:546` → `_cancel_prepared` 444-452, P4d);
a new owner without the withdraw grant simply cannot re-propose, and the work
later closes with the effect acknowledged-unwithdrawn — honest, and already
carried by D11's residual.

### F7 — MEDIUM: `reconcile` performs no declared-actions preflight

The actions preflight exists only in `dispatch` (`runtime.py:916-923`;
documented dispatch-only in [adapter-contract.md](../../docs/adapter-contract.md)).
`reconcile` calls `adapter.lookup` directly (`runtime.py:952`). With a single
two-action adapter this is invisible; under per-capability adapters (§3 A/C)
a wrong-adapter reconcile yields `None` → `NO_AUTHORITATIVE_RESULT` — a
caller wiring error misreported as an authoritative absence (and the effect
may exist in the other adapter's store). If A or C is ratified, add the same
preflight to `reconcile` (fresh rejection, nothing persisted) or document the
caller's exclusive responsibility. Cheap; keeps "wrong adapter held before
effects" symmetric for the recovery path.

### F8 — LOW/MEDIUM (depends on §3 choice): caller surfaces in mixed-capability stores must be explicit per operation

`dispatch`/`reconcile` take one adapter (`runtime.py:883,946`);
`recover(adapter)` sweeps **all** operations with that single adapter
(`runtime.py:1008-1022`); `run_worker` hard-wires `FakeOA`
(`demo.py:107-112`). With one two-action adapter all callers stay unchanged
(the design's implicit appeal — viable only if F1 is solved without splitting
adapters). With per-capability adapters, worker/CLI/demo/recover must select
by operation capability explicitly, and `recover` needs a per-capability
mapping (or per-op resolution). The safety net already exists and is
house-tested: a wrong adapter is **held** `ADAPTER_ACTION_UNSUPPORTED` with
zero attempts/effects and the op re-dispatches with a compatible adapter
(`tests/test_adapter_contract.py:342-366`, the `ExportCapableOA` shared-store
precedent) — that behavior must be preserved and pinned for withdrawals.
§7's "dispatch is link-agnostic" is true only for the two-action adapter and
must be restated per ratified alternative. No untrusted-document flag bypass:
under every alternative the `compensates` link is runtime-validated at
admission (§4.2 chain) and never adapter-supplied; forward admission is
untouched.

### F9 — verified-sound list (claims checked against code, no finding)

Command protocol dedup/CAS/replay with authority recheck
(`runtime.py:257-338`; `propose_action` replay = owner + capability,
`runtime.py:326-328`); closed works reject fresh proposals before `_apply`
(`WORK_NOT_ACTIONABLE`) and dispatch stale-checks closed works (probe 5 of
the recon; `runtime.py:898-905`); exact-shape payloads raise unpersisted
`CommandError` (house style, consistent with §4.1); precedence
authority → window → contract/plan/digest → link → blockers → pending guard →
key matches the code shape modulo the variant re-ordering §4.2 intends;
attempt persisted before the external call and exception → `outcome_unknown`
(`runtime.py:924-931`); reconcile-by-key escalation and idempotent recovery
(`runtime.py:946-968`); `finalize_cancel` exact-ack and unresolved gates need
zero changes and already include a confirmed withdrawal in the ack set
(`runtime.py:506-524`); S9 reservation covers compensating operation ids
across kinds (`runtime.py:667-682,704-713`); `policy.id` is family-shared
(`"expense-submit"`, `policy.py:37`) and inherited by `ExpensePolicyV2`
(`policy.py:143`), so the D6 key is version-stable as claimed; the forward
key tuple shape differs from the compensation tuple, and the store-global
`business_key UNIQUE` gives at-most-one compensation per (family, capability,
original); additive JSON on operation/event bodies renders generically
(`inspection.py`) and schema stays `1`; `PublishingPolicy` untouched keeps
the publishing family out via `CAPABILITY_UNSUPPORTED`; `migrate_policy` is
window-dead (`runtime.py:562,381`). The recon's five gaps and "machinery is
link-agnostic" conclusions all reproduced.

## 2. Answers to the master's specific questions

- **HOW select action and bind exact original_external_id?** As drafted: it
  cannot — F1/F2. The design must adopt one of §3's explicit mechanisms.
- **Hashed business key as selector?** No — opaque digests of different
  tuples; not decodable, not an action selector (F1).
- **Current document changed invoice ids after the accepted effect?** P1b/P1c/P1d
  — wrong-original, missing-original (closure deadlock via D11) and
  ambiguous-original are all reachable through the ordinary
  revise-then-cancel flow.
- **Multi-invoice original / duplicate invoice / revoked proof / immutable
  binding?** A confirmed_succeeded original's *own* document invoice ids all
  map to its external id (invariant P1a: acceptance inserts them atomically;
  no earlier acceptance can hold any of them or it would have been
  duplicate-rejected; the PK prevents later overwrite) — that invariant, or
  the §4.4 snapshot id, gives the exact binding; duplicate-invoice is the
  P2 inversion; revoked proofs: F3 (withdrawal proof survives revocation of
  the original and re-satisfies E08's digest).
- **Different-key existing withdrawal receipt?** Must serve lookup **alias
  for that key** AND the **correct requested digest**, else exactly the two
  failures P5 demonstrates; fix in F4.
- **accepted_count with withdrawals in receipts?** F5 — must remain the
  forward effect count; count effect tables, not receipts.
- **Dispatch revalidation/cancellation hidden gates?** F6: exactly two
  proposal/dispatch gates exist (`runtime.py:620-621`, `891-897`), both
  before staleness/authority/contract re-checks, which then still run
  (`898-923`); no third hidden gate for `propose_action` (it routes ahead of
  the `_apply` management gate, `runtime.py:376-377`). The carve-out must
  cover re-admission too. `recover` inherits through `dispatch` but passes
  one adapter (F8).
- **Key dedup vs different link/execution content?** F6 — sound in-slice;
  content conflict unreachable in-window.
- **transfer-owner invalidation / finalize prepared-cancelled semantics?**
  P4d/P4e/P4f + F6; cancelled ops don't block finalize; held/prepared ones
  do (`runtime.py:506-510`) — D11 carried.
- **Authority/exact-shape/closed/version precedence?** F9 — verified.
- **`_resolve` writes kind accepted for withdrawal — false forward proof?**
  Yes — F3; amend the proof kind (D14).

## 3. Alternatives (bounded; master decision D15)

All three fix F1/F2 by making action and original explicit; all three
require the F3 (proof kind), F4 (per-key receipts + per-original withdrawals),
F5 (effect counters) and F6 (re-admission exemption + interventions.md)
amendments regardless.

**A — dedicated withdrawal adapter over the same external store + immutable
target-derived execution document/link/digest.** A `WithdrawOA` (or `FakeOA`
subclass) declaring `actions=("expense.withdraw",`) sharing the OA SQLite
store; `FakeOA` keeps `actions=("expense.submit",)` byte-identical — no
routing inference anywhere, duplicate-invoice semantics intact. The
compensation op's `document`/`document_digest` := the **target operation's**
(immutable by the P1a invariant; binding is exact by construction), with the
§4.4 snapshot as recorded cross-check. Cost: §4.5's "one carve-out" widens —
the admission scope check, the pending different-digest guard and the
dispatch staleness digest comparison each need an explicit variant rule
(target-digest-based, or staleness skips the digest arm for compensations
while keeping closed/plan/contract checks); caller surfaces become
per-capability (F8: worker flag, demo wiring, recover mapping); reconcile
preflight (F7) recommended. Protocol stays frozen; per-capability adapters
are a house-tested pattern (`ExportCapableOA` shared-store precedent, held
then compatible-dispatch).

**B — backwards-compatible protocol extension: pass action/link to
`execute`.** `execute(key, document, content_digest, *, action=None,
compensates=None)`, passed only to adapters that opt in via a marker the
runtime checks before the call (legacy adapters are never invoked with the
kwargs, so no `TypeError` → no phantom `outcome_unknown`). The withdrawal
path binds on `compensates.original_external_id` directly — no invoice
inference at all; the op document may stay the current work document, so
**§4.5's single carve-out and all digest touchpoints stay exactly as
drafted**, and every caller (worker/CLI/demo/recover, one adapter) is
unchanged. §10's rejection of this option ("breaks every existing adapter
signature") is factually wrong for keyword-with-default extensions and the
rejection should be withdrawn. Cost: the Adapter protocol surface grows by an
opt-in; the conformance mixin gains action/link coverage.

**C — dispatcher-side per-capability resolution (registry/wrapper).** The
runtime accepts an optional capability→adapter registry used by
`dispatch`/`reconcile`/`recover` when a single adapter isn't supplied;
adapters stay single-action as in A, but callers hand over one registry and
`recover` resolves per op (answers F8's sweep without caller loops). C is a
**delivery** mechanism, not a binding mechanism — it composes with A (A's
adapter split + C's registry) but does not by itself tell `execute` the
action or the original; on its own it still needs A's immutable document or
B's kwargs. Cost: `Runtime` public API grows; widest blast radius of the
three.

**Recommendation: B for this slice** (smallest runtime delta — the drafted
§4.5 single carve-out survives verbatim; explicit binding from the immutable
snapshot; callers and `recover` unchanged), with **A as the fully viable
protocol-purist alternative** if the master refuses any Adapter-surface
growth (accepting the widened digest-rule surface and per-capability caller
wiring, optionally composed with C for `recover`). Both keep the wrong
adapter held before effects (existing actions preflight) and neither
introduces any untrusted-document flag around forward admission.

## 4. Master decisions requested (amendments to the D-table)

| id | decision | recommendation |
|---|---|---|
| D14 | withdrawal accepted-proof kind | **distinct kind (e.g. `withdrawn`) for compensation resolutions** (F3); alternative: no runtime-owned proof for compensations. Either way: no kind-`accepted` row whose digest can satisfy E08 forward |
| D15 | §4.8 mechanism | **B (opt-in `action`/`compensates` kwargs)**; alternative A (+C optional). §10's adapter-signature rejection withdrawn as factually incorrect |
| D16 | receipts vs effects accounting | per-key receipts rows + per-original `withdrawals` table; different-key reuse inserts a requesting-digest receipts row reusing the same WD id; effect counters count effect tables (`accepted_count` stays forward-only) — F4/F5 |
| D17 | re-admission inside the window | compensation variant exempt from `CANCELLATION_ACTIVE` for fresh **and** re-admission paths; `interventions.md` sentence amended same-commit — F6 |
| D18 (conditional) | if A/C ratified: reconcile actions preflight + per-capability caller wiring (worker/CLI/demo/recover mapping) | adopt; else drop |
| D6/D7/D8/D9/D10/D11/D12/D13 | as drafted | confirmed sound (D9's mechanics replaced by D16; D11 residual sharpened by F1-row-3: without an abandon path a missing-original withdrawal deadlocks closure — note in §12) |

## 5. TDD and ownership requirements for the implementation wave(s)

Keep §6's fifteen RED/GREEN tests and add, per finding (all public API, real
stores, both determinism runs): duplicate-invoice forward submit still
business-rejected with the withdrawal-capable store present (P2 pin under the
ratified mechanism — the regression F1 guards); the revision matrix P1b–P1d
as tests — the withdrawn original is always the linked one, never the
current-document resolution; withdrawal proof kind never satisfies E08 at any
digest (P3 pin, including after S8 revocation of the original proof);
different-key reuse returns a digest-valid receipt and `lookup(requesting
key)` is authoritative (P5 pin); end-to-end counts `accepted_count()==1` and
`withdrawn_count()==1` asserted from the SQLite stores after the real
child-crash demo (`os._exit` idiom, one withdrawal row, attempts length 1,
reconcile confirms once); compensation re-admission inside the window
(P4f flip) and transfer-owner invalidation → new-owner re-propose (P4d/P4e);
if A/C: wrong-adapter dispatch held with zero effects then compatible
re-dispatch (existing pattern extended), and reconcile preflight behavior.
Forward regressions: the existing 726-test battery verbatim, publishing
family byte-unchanged, five gates unchanged, new demo not a global gate
(D12). Ownership per §9 W1/W2 with `adapter-contract.md` joining the
same-commit docs when the Adapter surface changes (B) — the doc_sync_map row
for `adapters.py`/`runtime.py` → `runtime-boundaries.md` continues to apply.

## 6. Scope confirmation and limits

Expense-only + active-cancellation-window is the right bounded slice (§3 of
the recon, verified: post-closure paths reject `WORK_NOT_ACTIONABLE`/
`STALE_INTENT` and need their own design cycle; publishing is semantically
distinct). Future work carried, not pre-decided: post-closure compensation,
publishing-family compensation, public abandon of prepared intents (F1-row-3
makes this more than cosmetic), compensation chains, cross-work,
intervener-initiated compensation, any viewer surface. No saga orchestration,
authentication, fencing, distributed exactly-once or production-safety claim
is made or implied by anything above; every principal remains trusted-local
configuration. This review implemented nothing; the probe suite is throwaway
under `/tmp/compensation-review-2026-10-15/` and committed nothing.
