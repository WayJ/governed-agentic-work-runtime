# S10 W1 core integration review — PASS, assembled — 2026-10-15

Independent Orca integration review/assembly of the S10 compensation core,
distinct from the owner's internal fresh-context review recorded in
[the core report](2026-10-15-S10-core-report.md). Reviewer checkout:
`s10-release-control` (control branch `WayJ/s10-release-control`, base
`4a15158` = carrier base). No product file was modified by this review; all
probes and gate replays ran from the labelled `/tmp/s10-integration-2026-10-15/`
extraction of the accepted source (`git archive`, disposable) plus fresh
`/tmp` stores. Verdict: **PASS — no unresolved material finding**; four minor
findings recorded below (Mi-1…Mi-4), none blocking, none requiring a product
fix in the accepted source.

## Scope and source

- Accepted source: `WayJ/s10-compensation-core` tip
  **`4b57468ae555718299530afeaa9ec41cad56b054`** (verified), **12 commits**
  on base `4a15158` (exclusive range, matching the dispatch and the owner's
  commit table).
- Changed files (name-status verified, exactly the 13 allowed): product
  `work_runtime/runtime.py` (+212/−43 hunk lines), `adapters.py`,
  `adapter_contract.py` (+3), `policy.py` (+9); tests `test_compensation.py`
  (new), additive `test_adapter_contract.py`/`adapter_conformance.py`; docs
  `runtime-boundaries.md`, `adapter-contract.md`, `interventions.md`,
  `verification.md`; plan `docs/superpowers/plans/2026-10-15-s10-core.md`;
  report `.agents/notes/2026-10-15-S10-core-report.md`.
- Protected paths byte-identical `4a15158..4b57468` (empty diff):
  `examples/`, `website/`, `work_runtime/web/`, `work_runtime/data/`,
  `inspection.py`, `cli.py`, `demo.py`, `publishing.py`, `file_adapter.py`,
  `ingress.py`, `scripts/verify_install.py`, `scripts/check_docs.py`,
  `scripts/check_site.py`, both READMEs, `AGENTS.md`, `pyproject.toml`,
  `docs/website.md`, `CONTRIBUTING.md`. No UI change → no browser/visual
  claim is made; read-only inspection and byte-equality stand in (per D48).
- Assembly: `git merge --no-ff 4b57468` → control merge commit
  **`03eed8247154cd4c91a5862db04b1ae66e870a10`**; carrier
  `WayJ/sprint-s10-compensation` fast-forwarded to the control tip (exact
  SHA at the end of this note). No main/root merge, no push, no sprint
  state/acceptance/debt/ledger flip — final S10 acceptance waits for W2 and
  a fresh final review (S8 precedent).

## Static review against FULL MASTER §15 D43–D48 (v2.1)

Read in full: AGENTS.md, master §15 (D43–D48), the v2.1 spec (§1–§14 as
amended), E10 roadmap, active S10 sprint plan, the core plan (676 lines),
the core report, and both independent design reviews (F1–F9; A1–A4/C1–C4,
m1–m5). Code read as diff and in full for the four touched modules; docs
read as diff against implemented behavior.

- **D43 admission**: exact payload variant (unpersisted `CommandError`,
  `compensates`-present-or-key triggers misuse handling incl. explicit
  `None`/empty/non-string), authority → window split → revisions/digest →
  link → blockers → pending guard → key precedence matches §14.8 verbatim;
  window gate sits before the business-key branch so **fresh AND re-admission**
  are covered by one gate (F6 fix confirmed in code order); link validation
  (exists/same-work/`confirmed_succeeded`/non-compensation/current pairing)
  returns the immutable `{operation_id, external_id, capability}` snapshot
  on body and `OperationPrepared`/`OperationReadmitted`; key
  `digest([policy.id, capability, target])` with the forward `operation_key`
  never consulted for compensations.
- **D44 opt-in**: `supports_action_context: bool = False` + bool-only
  invariant; dispatch order verified in code: declared-actions preflight →
  **context hold** `ADAPTER_ACTION_CONTEXT_UNSUPPORTED` (zero attempts, fires
  even when `actions` claims withdraw, absent-contract adapters included) →
  attempt persisted → opted-in call
  `execute(key, document, digest, action=capability, compensates=link_or_None)`;
  every other adapter receives **exactly the pre-S10 three positional
  arguments** — no `inspect`, no TypeError fallback anywhere in the diff;
  belt-and-braces `STALE_INTENT` mirror and `_link_still_valid` revalidation
  (all m1 comparison arms present: id/same-work/confirmed/non-compensation/
  snapshot external_id+capability equality/current pairing); re-admission
  never rebinds (returns the stored operation).
- **D45 resolution/closure**: `original_external_id` binding check after
  `receipt_is_valid` and **before** the accepted/rejected split (C1);
  quarantine rides the existing idempotent `ADAPTER_RESULT_INVALID` branch;
  full validated receipt stored additively as `op["adapter_result"]`
  (C2/MD-5, ordinary ops never carry it); accepted withdrawal → kind
  **`withdrawn`** proof `{digest, external_id, original_external_id}` at the
  accepted-source identity; no `withdrawn` evidence-source mapping (imports
  denied for every actor, admin-only revoke, ingress unchanged — D23);
  S9 `AcceptanceProofConflict` path verbatim with the actual withdrawal
  result recorded; `finalize_cancel` dispositions add `compensates`/
  `adapter_result` only when present on the operation; ordinary dispositions
  keep the exact three-field shape; ack = original + succeeded withdrawal,
  failed withdrawal excluded.
- **D46 adapter store**: one `BEGIN IMMEDIATE` migration (PRAGMA probe inside
  the transaction; A3), named-column receipts INSERT on every path (A2), new
  forward rows tagged `expense.submit` with legacy `NULL` normalized on read,
  replay validates digest + normalized action + link fingerprint for **both**
  actions (A4, both directions), different-key/same-original inserts a
  requesting-digest/action/link alias reusing the same `WD-…` id with
  authoritative per-key `lookup` (F4), original existence = accepted
  **forward receipt** external id with the invoices table as short-circuit
  (A1/MD-1 — direct zero-invoice acceptances included), known absence stores
  a queryable `ORIGINAL_ABSENT` rejection while a genuine store failure
  raises (D21), one `withdrawals` row per original,
  `accepted_count()` = distinct accepted forward external ids (excludes
  withdrawal/alias rows), `withdrawn_count()` = effect rows (F5). Runtime
  schema stays `1`.
- **D47 tests/docs**: matrix present and named as specified (see counts
  below); same-commit doc pairing verified per commit — see Findings Mi-1
  (c3f103c letter gap) and Mi-2 (64504ac non-mapped row) for the exact
  differences, not hidden.
- **D48 boundaries**: compensation-demo correctly absent (exit 2, unknown
  subcommand until W2); five gates and their command list unchanged; no
  UI/reader feature; installed verifier unchanged; trees/preview (port
  52719, PID 29490) untouched by this review.

## Fresh verification (run on the extracted accepted source = control content)

| item | command | actual result |
|---|---|---|
| tests (gate 2) | `python3 -m unittest discover -s tests` | **Ran 788 tests … OK (skipped=3)** — matches the owner |
| baseline (independent) | same, on extracted `4a15158` | **Ran 726 tests … OK (skipped=1)** — 726+62 arithmetic confirmed |
| contracts (gate 1) | `python3 scripts/check_docs.py` | **90 markdown files, 386 local links, 0 broken** (owner said 101 files — see Mi-3) |
| demo (gate 3) | `python3 -m work_runtime demo` | exit 0 |
| syntax (gate 4) | `python3 -m compileall -q work_runtime tests scripts` | clean |
| site (gate 5) | `python3 scripts/check_site.py` | 2 pages, 0 findings |
| five demos | `publish-demo`, `intervention-demo`, `adoption-demo`, `revocation-demo` (+ `demo` via gate 3) | all exit 0; `compensation-demo` absent as designed |
| rehearsals | `python3 -m unittest discover -s examples/rehearsal` | **Ran 15 tests … OK (skipped=1)** = the 14 pre-existing + the new generic opt-in test, skipped by the queue adapter |
| installed verifier | `python3 scripts/verify_install.py` | **PASS** (serial run; see Mi-4 for one parallel-load flake) — fresh Python 3.9.6 venv, import resolves inside the venv, zero third-party runtime deps, module+console demos with real effect counts, packaged web assets byte-equal |

### Counts and skips (independently identified, not copied)

- +62 = **57** new `tests/test_compensation.py` tests (counted by name:
  PolicyPairing 2, store migration 3, forward/counters 4, withdrawal
  execution 7, admission 13, dispatch 5, resolution 7, closure 4, recovery
  8, pins 4) + **2** `AdapterContractTests` field tests + the **1** generic
  mixin test discovered through **3** in-suite adopters (`FakeOA` pass;
  `FilePublisherConformanceTests` and `FakePublisherConformanceTests`
  skip `'adapter does not opt into action/link execution context'`).
- Third suite skip is the pre-existing
  `test_ui_cli.AbsentBackendTests.test_absent_backend_is_a_bounded_startup_error`
  (`'backend assembled: absent-install path unreachable'`). The rehearsal
  skip is the same mixin test on the fourth adopter (queue adapter). These
  are the designed C4 opt-in skips, not coverage loss — the FakeOA leg of
  the same test passes in-suite.

## Independent probes (my own; public API only; SQLite row equality + real counters)

`python3 /tmp/s10-integration-2026-10-15/probe.py` → **19 checks, 19 passed,
0 failed — three deterministic runs.** My own probe harness had 13 bugs
across the first iterations (wrong event key, callable/dict mixup in a child
script, re-admission/transfer/CAS envelope mechanics, inspector shapes,
one mistaken count assert); every failure reproduced as probe-side and no
product behavior changed any finding. Coverage:

- Happy path end-to-end: snapshot equals target terminal facts; events carry
  the additive `compensates`; full `adapter_result` stored and
  `receipt_is_valid`; `withdrawn` proof data exact at `(oa, withdrawal op
  id)`; **real counters** `accepted_count()==1`/`withdrawn_count()==1`;
  receipts rows tagged (`expense.withdraw` + `link_digest == digest(link)`;
  forward `expense.submit`/NULL); `withdrawals` exactly one row; invoices
  untouched; finalize exact two-id ack; ordinary disposition exactly three
  keys, compensation disposition carries link + adapter result.
- Refusal truth: adapter-level `ORIGINAL_ABSENT` (queryable rejected receipt,
  zero effect rows); runtime-level rejection → `confirmed_failed`,
  `needs_attention`, finalize ack original only, disposition records the
  refusal reason; mismatched ack → `OUTCOME_UNRESOLVED`.
- Window/admission: `CANCELLATION_NOT_REQUESTED` without an intent; forward
  `CANCELLATION_ACTIVE` unchanged; exact-shape misuse unpersisted (no
  command row, no version bump); cross-work/unknown/failed/chained targets →
  `COMPENSATION_TARGET_INVALID` with `[target]` blockers; unpaired
  capability (grant held) degrades `CAPABILITY_UNSUPPORTED` →
  `REQUIREMENT_UNSATISFIED`.
- Authority/replay: stored receipt replays verbatim under the original
  command id/version; grant loss → fresh unpersisted `AUTHORITY_DENIED`;
  dispatch grant-loss **held** with zero attempts then succeeds on restore;
  re-admission returns the same operation id; admin-run transfer invalidates
  the prepared compensation `OWNERSHIP_TRANSFERRED`; former owner denied;
  new owner without grant denied; with grant re-admitted
  (`OperationReadmitted` carries the unchanged snapshot) and dispatches;
  post-closure fresh proposal `WORK_NOT_ACTIONABLE`.
- Dispatch/opt-in: contract-less recorder receives exactly three positional
  args on forward dispatch; false-marker contract (withdraw declared,
  opt-in `False`) → held `ADAPTER_ACTION_CONTEXT_UNSUPPORTED`, zero
  attempts, work out of `needs_attention`, re-dispatch succeeds; opted-in
  wrapper receives `action="expense.submit", compensates=None` forward and
  `action="expense.withdraw"` + snapshot for compensation.
- Adapter store: pre-S10 3-column store migrates (columns once, legacy row
  `NULL/NULL`, legacy three-positional replay works); new forward rows
  tagged; cross-action key replay conflicts **both directions**; same key +
  different link conflicts at equal digest; 4-thread concurrent first-open
  race-free; zero-invoice direct acceptance is **present** for withdrawal
  (receipts-side, A1); alias under a different key returns the same `WD-…`
  id with the requesting digest, `receipt_is_valid` true, `lookup(key2)`
  authoritative, still one effect row; `timeout_after_commit` lost-response
  leaves `lookup` authoritative; duplicate-invoice forward still
  business-rejected with a populated withdrawal store; counters exclude
  withdrawal/alias receipts.
- Resolution/quarantine: digest-valid receipts naming a wrong
  `original_external_id` quarantine `ADAPTER_RESULT_INVALID` for accepted
  **and** rejected statuses (no proof, no `adapter_result`, work
  `needs_attention`); repeated reconcile idempotent (work version and event
  count frozen).
- Proofs/E08/S9: `withdrawn` proof leaves E08 pending at the new digest and
  **still pending after admin revocation of the original accepted proof**;
  `record_evidence` kind `withdrawn` denied for every actor; withdrawn-proof
  revoke denied for a non-admin `evidence.revoke`-less actor and accepted
  for admin; S9 poison at `(oa, withdrawal op id)` → op confirms with the
  actual `WD-…` result + `proof_conflict` snapshot +
  `AcceptanceProofConflict` event, no proof inserted, poisoned row
  byte-identical.
- Recovery: **real child death** (`os._exit(73)` after the withdrawal
  commits, subprocess) → restart `recover` confirms once, **attempts length
  1**, one original + one withdrawal effect, finalize exact two-id ack with
  full closure snapshot; execute exception → `outcome_unknown`/`RuntimeError`,
  reconcile → `NO_AUTHORITATIVE_RESULT` `needs_attention`, unresolved
  compensation blocks finalize, a later operation on another work stays
  live; `ReadOnlyInspector` summary/list/events/detail over the
  compensation store with **byte-identical store files** before/after.

### RED validation (representative replays, committed tests vs parent commits)

- Task 5 (`4769574` admission tests on parent `1e66ac5`): **30 tests, 17
  failures + 2 errors** — meaningful RED (`CANCELLATION_ACTIVE`/lenient
  drop/wrong codes).
- Task 7 (`0fd3ecb` resolution tests on parent `f61abc8`): **42 tests, 1
  failure + 3 errors** — meaningful RED (binding check/`adapter_result`/
  `withdrawn` kind absent). The owner's disclosed preservation pins
  (already-GREEN legs) were not re-demanded as fake RED, per the dispatch.

## Findings (all minor; none material; no product change made)

- **Mi-1 (report accuracy + same-commit letter gap, c3f103c).** The owner
  report claims "Every commit touching `runtime.py`/`adapters.py` (aaf2e7b,
  1e66ac5, 4769574, f61abc8, 0fd3ecb, c3f103c) updated
  `docs/runtime-boundaries.md` in the same commit" — **false for
  `c3f103c`**: that commit (closure dispositions) changed `runtime.py` with
  `interventions.md` + `verification.md` only; its own audit-table row omits
  the boundary file. The other five pairings are verified true. Substance:
  the closure behavior is finalization wording owned by `interventions.md`
  (updated same-commit), `runtime-boundaries.md` already delegates
  finalization to it, and the branch-tip boundary doc is current — there is
  no drift at `4b57468`. Under the mechanical AGENTS `doc_sync_map` row and
  D47's "runtime AND adapters boundary docs SAME code commit" this is a
  letter violation for that one commit, now recorded here; routing to the
  owner/master as disclosure (history rewrite is not proposed; the accepted
  source stands as reviewed).
- **Mi-2 (non-mapped row, 64504ac).** The policy-pairing commit carried no
  docs. `policy.py` is **not** in the AGENTS `doc_sync_map`, and master D47
  pairs only runtime/adapters boundary docs, so nothing enforced was owed;
  the design §8 draft table does name policy docs same-commit, and they
  landed one commit later inside `4769574` with the admission that exercises
  the pairing. The owner's internal review disclosed this; recorded as the
  exact difference rather than hidden.
- **Mi-3 (gate count provenance).** `check_docs.py` on the committed
  accepted tree: **90 files / 386 links / 0 broken**; the owner's report
  says 101 files / 386 / 0. Their worktree is clean now, but the
  `.superpowers` SDD ledger (untracked local working files, deleted after
  their final review) was present at gate time: reconstructing 11 ledger
  `.md` files reproduces exactly `101 files, 386 links, 0 broken`. Same
  reconciliation class as S8's 78-vs-79; links and broken counts identical.
- **Mi-4 (environment flake, not product).** The first `verify_install.py`
  run FAILED at "module ui-demo did not exit after the interrupt" while I
  ran the baseline battery concurrently; a serial re-run **PASSed** all
  stages, and the verifier is byte-unchanged (`git diff` empty). W2/final
  acceptance should run the installer without parallel load.

### Owner's 9 deferred minors — load-bearing assessment

None is load-bearing and none warrants new tests or cosmetic fixes from this
review: the two tautological assertions sit beside real load-bearing legs in
the same tests (my probes independently cover inspector zero-write and kwargs
delivery); the no-new-dependencies pin's skip of absolute imports is covered
by my real venv install (zero third-party deps); the unsent-command-id probe
leg is cosmetic (the version/event-count legs carry it); the RED table
provenance and plan Step-2 overstatement are documentation nuance with RED
independently reproduced here; Mi-2 above; the transient `verification.md`
mixin-test naming was one commit ahead of `8f17ba7` with a truthful final
state; the plan's Review-Focus test-name mismatches have coverage present.
No unnecessary test was added and no cosmetic fix applied, per the dispatch.

## W2 stable API (verified empirically, for the demo owner)

- **The shipped `worker` CLI cannot perform the withdrawal**: `run_worker`
  constructs the runtime with `demo_grants()` (no `expense.withdraw`), so
  dispatching a prepared withdrawal through
  `python3 -m work_runtime worker …` **holds** it `AUTHORITY_DENIED` with
  zero attempts and zero effects (verified by real subprocess). A
  grants-carrying subprocess (test-local child or any public-API process
  with the withdraw grant) completes it with exactly one effect — the W2
  demo must use a local child with compensation grants or a public
  subprocess; no fake CLI capability claim.
- Stable public surface at the assembled SHA: `propose_action` compensation
  variant (exact five-key payload incl. `compensates`); codes
  `COMPENSATION_TARGET_INVALID` (blockers `[target]`),
  `CANCELLATION_NOT_REQUESTED`, hold reasons
  `ADAPTER_ACTION_CONTEXT_UNSUPPORTED`/`COMPENSATION_TARGET_INVALID`,
  receipt reason `ORIGINAL_ABSENT`, proof kind `withdrawn`
  (`{digest, external_id, original_external_id}`), op fields `compensates`/
  `adapter_result`, compensation dispositions in the closure snapshot,
  `FakeOA.execute(..., action=, compensates=)` opt-in call,
  `withdrawn_count()`/`accepted_count()` semantics, additive adapter-store
  migration. The `compensation-demo` subcommand, installer stage and README
  entries are W2 additions on top of this SHA.

## Assembly record

- Control `WayJ/s10-release-control`: merge commit
  `03eed8247154cd4c91a5862db04b1ae66e870a10` (`merge: assemble S10
  compensation core 4b57468 into release control`), then this note committed
  on top. Post-assembly gates re-run on the control tree: full battery
  **788 OK (skipped=3)**, `check_docs.py` **90 files / 386 links / 0 broken**
  (this note lives under `.agents/`, excluded from the scan), `compileall`
  clean, `check_site.py` 0 findings, `demo` exit 0 — identical to the
  accepted-source runs.
- Carrier `WayJ/sprint-s10-compensation`: fast-forwarded to the control tip —
  i.e. this note's own commit (a commit cannot contain its own hash; the
  exact SHA is recorded in the worker report to the coordinator and equals
  `git rev-parse` of this file's commit; contains `4b57468` + merge + this
  note). W2 builds on that exact SHA.
- No main/root merge, no push, no sprint `state` flip, no acceptance record,
  no debt/ledger change. All worktrees and the preview server
  (127.0.0.1:52719, PID 29490) preserved.

## Risks / limits (unchanged, truthful)

No public abandon for prepared/held/`outcome_unknown` compensations (any
unresolved compensation blocks finalize; lookup unavailability is one cause);
reconcile stays caller-trusted under the single two-action adapter;
belt-and-braces dispatch branches are unreachable via the public API and
pinned only through crafted stores; `adapter_result` grows operation bodies
(additive JSON, schema 1); expense family + active-cancellation window only
— publishing, post-closure, chains, cross-work, intervener authority, viewer
surfaces, auth/fencing/distributed exactly-once/key rotation remain
unimplemented and unclaimed.
