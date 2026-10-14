# Independent SECOND compensation design review (DRAFT v2 builder-check) — 2026-10-15

## Scope, evidence and verdict

Independent second builder-check of the amended DRAFT
[compensation execution design §14 (DRAFT v2)](../../docs/superpowers/specs/2026-10-15-compensation-execution-design.md)
at candidate `e25d17050a16fb3f928be00e3c2053a02f26af35` (branch
`WayJ/compensation-design`; §14 v2 supersedes conflicting v1 text per §14.14;
revision note read alongside). This review checkout is the existing
`compensation-design-review` worktree, clean at baseline `254c714` with the
first review (`00833d8`) preserved as its own commit. Candidate product code
equals this baseline: `git diff 254c714 d683429 -- work_runtime tests scripts
website examples pyproject.toml` is empty, so every source citation was checked
in-place against this checkout. Sources read as truth: `AGENTS.md`, `runtime.py`,
`policy.py`, `adapters.py`, `adapter_contract.py`, `ingress.py`,
`inspection.py`, `demo.py`, `tests/adapter_conformance.py`,
`tests/test_adapter_contract.py`, `tests/test_file_adapter.py`,
`docs/interventions.md`, plus the candidate's v1 §4/§6/§7/§10–§13 text and
revision note (read via `git show`). Three throwaway, labelled probes ran from
`/tmp/compensation-review2-2026-10-15/` (real `FakeOA`/`AdapterContract` on
fresh `/tmp` stores; SQLite migration race via threads; nothing committed);
the candidate tree was additionally extracted to a labelled `/tmp` copy via
`git archive` to run `scripts/check_docs.py` (87 files, 358 local links,
0 broken) and to byte-compare the copied first review (identical below its
provenance block, modulo the separator blank line). The 726-test battery was
re-run once on this baseline to ground the "existing battery verbatim" pin:
`Ran 726 tests … OK (skipped=1)`.

**Verdict: PASS with bounded findings.** The B mechanism and the runtime-side
v2 contract (§14.1–§14.3, §14.5–§14.7) genuinely resolve F1–F8 — every claim
I attacked reproduced against source, including the four F1 failure rows
being unreachable by construction, the `withdrawn` proof's inertness, and the
window/re-admission exemption. The defects found are concentrated in §14.4
(the new adapter-store algorithm) and its §14.5/§14.6/§14.12 edges: **four
material amendments (A1–A4)** — the invoices-only original-existence probe
fabricates known absence on an existing accepted receipt; the "byte-identical
forward path" is unimplementable after the drafted migration (positional
INSERT breaks); the open-time migration races under concurrent first-open;
the idempotency/link-fingerprint guard is missing on the forward side — plus
**four material clarifications (C1–C4)** and five minor ones. None reopens
the mechanism choice (D15=B stands), F1–F3, or the scope; all have concrete
pinned fixes. Ratification should follow a docs-only v2.1 fold of A1–A4 and
C1–C4; W1 must not dispatch against §14.4 as currently worded.

## 1. F1–F8 resolution verification (checked against source, not the draft's own words)

| finding | resolved? | evidence |
|---|---|---|
| F1 action selector / exact-original binding | **yes** | §14.2 call rule passes `action=op["capability"]` + runtime-validated immutable `compensates` snapshot; no document-field selection; dispatch decision reads the declared contract only (`_declared_contract` `runtime.py:31-45`, preflight `runtime.py:916-923`, execute call `runtime.py:929`); legacy adapters never receive kwargs — no introspection/TypeError probing; context hold before the attempt persists (zero attempts/effects, `needs_attention` not set — the held pattern pinned at `tests/test_adapter_contract.py:342-366`). Wrong-original/missing/ambiguous/duplicate-inversion are unreachable: binding travels only in `compensates.external_id`. |
| F2 document/digest identity | **yes** | Op body is current work state (`runtime.py:657-662`); in-window freeze verified (`runtime.py:380-381`, revise at `402-412`; `migrate_policy` window-dead `runtime.py:561`); all four digest touchpoints unchanged (admission `runtime.py:626-629`, pending guard `637-641`, dispatch staleness `898-905`, `adapters.py:40` + `adapter_contract.py:62-73`). |
| F3 false forward proof | **yes** | `has(kind)` matches kind literals + digest (`policy.py:91-93`), E08 reads `has("accepted")` (`policy.py:124-125`) — `withdrawn` never satisfies it; no `withdrawn` source mapping ⇒ `_receive` authority check denies imports for every actor (`runtime.py:691-692`); revocation of a withdrawn proof admin-only (`_revoke_authority`, `runtime.py:721-733`: kind lookup yields None → only `_is_admin`); signed ingress forwards non-`accepted` kinds and is denied at `record_evidence` (`ingress.py:25,177-190`); S9 reservation is kind-agnostic over operation ids (`runtime.py:697-713`); the conflict path records the actual result and inserts no proof of any kind (`_proof_conflict`, `runtime.py:848-875`). |
| F4 different-key reuse / recovery | **yes** | Alias receipts rows under the requesting key with the requesting digest and the same `WD-…` id keep `receipt_is_valid` true and `lookup` authoritative-by-key (`adapters.py:69-75`); `withdrawals(original_external_id PK)` gives exactly one effect per original; crash-after-effect under key1 → `lookup(key1)` digest-valid → reconcile confirms once (`runtime.py:946-968`). |
| F5 honest counters | **yes** | `accepted_count()` redefined as distinct forward-accepted external ids (action-tag filter excludes withdrawal/alias rows; legacy NULL rows included); `withdrawn_count()` = effect rows; zero-invoice edge handled for the counter (receipts-based — but see A1 for the inconsistent existence probe). |
| F6 window + re-admission | **yes** | The `CANCELLATION_ACTIVE` gate (`runtime.py:620`) provably sits before the re-admission branch (`runtime.py:643-658`), so the variant-conditional gate covers fresh **and** re-admission; in-window freezing keeps `OPERATION_CONTENT_CONFLICT` unreachable from drift; `interventions.md:64-66` confirmed to owe the same-commit sentence. |
| F7 reconcile preflight | **yes (for B)** | Documented caller responsibility — the first review's own sanctioned alternative under a single two-action adapter; D18 dropped consistently. |
| F8 caller surfaces | **yes (for B)** | `run_worker` hardwires `FakeOA` (`demo.py:107-112`); worker/CLI/`recover` (`runtime.py:1008-1022`) unchanged; per-capability wiring only under A/C (not adopted). |

Also re-verified while here: `receipt_is_valid` accepts the extra
`original_external_id` field unchanged (`adapter_contract.py:62-73`); the
trailing defaulted contract field is backward compatible — every in-repo
construction is keyword-form (`adapters.py:16-21`, `publishing.py:117-122`,
`file_adapter.py:213-218`, `tests/test_adapter_contract.py:21-23,68`,
`tests/test_file_adapter.py:345-351`) and a defaulted field leaves
`valid_contract`/frozen semantics intact (probe: keyword construction with
defaulted field + `valid_contract` True; `isinstance(1, bool)` is False so a
bool invariant rejects ints); the E01 admission gate keeps runtime-proposed
expense submits invoice-carrying (`policy.py:128-133`); legacy receipts rows
read back `NULL/NULL` after the drafted ALTER (probe); re-admission cannot
re-bind a link (same key ⇒ same target ⇒ same stored snapshot; the branch
mutates actor/plan/contract revisions only, `runtime.py:648-653`).

## 2. Material amendments (fold into §14 before ratification; W1 blocking)

### A1 — HIGH (§14.4 step 3, D21): the invoices-only original-existence probe fabricates known absence for an existing accepted forward receipt

§14.4 step 3 verifies an original by `SELECT 1 FROM invoices WHERE
external_id = …` on the no-effect path and, on absence, stores the
**authoritative** business rejection `ORIGINAL_ABSENT`. But `invoices` rows
exist only for accepted effects **that carried invoices** (`adapters.py:51-58`);
a direct adapter call with a zero-invoice document is accepted with no
invoices rows. Probe (real `FakeOA`, fresh `/tmp` store): a zero-invoice
forward call returns `accepted` with `external_id OA-b56…`, `accepted_count()
== 1`; the §14.4 invoices probe for that id returns **ABSENT** while a
receipts-side probe returns **PRESENT**. The design would then store a
known-absence rejection for an original whose accepted forward receipt exists
in the same store — exactly the "fake known absence" class the v2 principle
("known absence is authoritative, unavailability is not") forbids. v2 itself
acknowledges this identical edge for the counter ("the counter is
receipts-based, not invoices-based") but not for the existence probe — an
internal inconsistency. In-slice reachability is bounded (runtime-admitted
expense targets always carry invoices via E01 + in-window freeze + dispatch
digest re-check; the misfire needs a custom policy without an E01-like
blocker, or a store mixing direct adapter acceptances with runtime
withdrawals for the same original id), but §14.4 pins this probe as the
binding backstop at the adapter's public surface. **Amendment:** existence =
an accepted **forward receipt** in `receipts` for that `external_id`
(action-tag filter as in the counter; a scan of the same table the counter
already scans), with the invoices query at most a short-circuit. If the
master prefers invoices-only, the restriction must be documented and the
zero-invoice receipt case explicitly classified — but receipts-side is
strictly more truthful at equal cost. (MD-1.)

### A2 — HIGH (§14.4 step 4, §14.9, D24): "forward path byte-identical to today" is unimplementable after the drafted migration

`adapters.py:55` writes receipts with a **positional** `INSERT INTO receipts
VALUES (?,?,?)`. After the drafted `ALTER TABLE receipts ADD COLUMN action
TEXT; ADD COLUMN link_digest TEXT`, SQLite rejects it — probe:
`table receipts has 5 columns but 3 values were supplied`; the named-column
form `INSERT INTO receipts (key,digest,result) VALUES (?,?,?)` works and the
legacy row reads back `NULL/NULL`. An implementer transcribing "byte-identical
to today" literally produces a store whose first forward submit after
migration crashes. (The `invoices` positional INSERT at `adapters.py:58` is
unaffected — that table is unchanged.) **Amendment:** restate step 4 as
*behavior*-identical with the forward INSERT switched to named columns, and
pin what new forward rows store in `action`: recommend the explicit forward
action string (`"expense.submit"`), keeping `NULL` reserved for legacy rows
(the §14.4 schema comment already says "NULL = legacy forward row"), with
replay comparison normalizing `NULL`/`None` → the forward action (this
normalization is FakeOA-side policy for its own legacy direct callers, not a
protocol rule). (MD-2.)

### A3 — HIGH (§14.4 migration clause, §14.10 test 26): the open-time migration races under concurrent first-open

"Added on open when missing (PRAGMA table_info probe)" crashes when two
processes first-open the same store: both probe, both ALTER, the loser gets
`sqlite3.OperationalError: duplicate column name: action` / `link_digest`
(probe, threaded first-open). Multi-process access to one OA store is the
supported pattern (runtime SQLite locking; the crash demo's worker child).
Probe also confirms the fix: probe+ALTER serialized under `BEGIN IMMEDIATE`
is race-free across the same race. **Amendment:** the migration runs inside
`BEGIN IMMEDIATE` (or catches duplicate-column-name `OperationalError` and
re-probes); test 26 gains a concurrent-first-open leg and a
reopen-idempotency leg ("added exactly once" already implies the latter —
make it explicit). (MD-3.)

### A4 — HIGH (§14.4 step 2/step 4 boundary, §14.9): the idempotency/link-fingerprint guard is drafted only for the withdrawal path — the forward side can replay a cross-action receipt

Step 2's link-fingerprint idempotency (same key must match digest **and**
action **and** `link_digest`) is specified for withdrawals only; step 4 says
the forward path is byte-identical to today, i.e. replay on (key, digest)
alone (`adapters.py:45-49`). After v2 widens `receipts` to two actions, a
forward `execute` under a key holding a withdrawal or alias row with equal
digest returns the `WD-…` receipt as a forward result — cross-action key
reuse, which the "established adapter rule" (`ValueError`, zero effects)
exists to prevent. Runtime business keys cannot collide across the
forward/compensation tuples (`policy.py:138-140` vs §4.3), so this is
reachable only through direct adapter calls — but that surface is exactly
what the conformance mixin and the stand-in's own contract advertise.
**Amendment:** the forward replay check compares action (normalized per A2)
and `link_digest` NULL-ness and raises `ValueError` on mismatch with zero
new effects — the same guard class §14.2 applies to withdrawals, mirrored;
extend §14.10 test 20 (or add a test) to pin the forward-side conflict.
(MD-4.)

## 3. Material clarifications (wording owed same-commit; no mechanism change)

### C1 — §14.5: state the binding check covers accepted **and** rejected receipts

As drafted, "a malformed or mismatched target receipt is quarantined" does
not say the check runs before the status split. A digest-valid **rejected**
receipt naming the wrong `original_external_id` must quarantine
(`ADAPTER_RESULT_INVALID`, idempotent via the existing same-reason branch,
`runtime.py:977-982`) rather than confirm a failure against the wrong
original — false confirmation of failure is still false confirmation. Pin
the wording and have §14.10 test 23 include a rejected-mismatch leg.

### C2 — §14.5/§14.6/§14.9: the failed-withdrawal "reason rides the stored adapter result" has no current basis — name the additive storage

`_resolve` persists only `external_id` for rejected results
(`runtime.py:986-994`); no full adapter receipt is stored in the runtime,
`OperationResolved` carries `{operation_id, status}` and the closure
disposition carries `{operation_id, status, dispatch_state}`
(`runtime.py:511-524`). So neither `ORIGINAL_ABSENT` nor any refusal reason
is runtime-queryable as drafted, and §14.6's closure-description claim
("attempted, refused, effect stands") does not hold without a change.
**Amendment:** name the storage — recommend additive
`op["adapter_result"] = result` for compensation resolutions (generic
rendering verified: `inspection.py:190-194`; additive-JSON rule), optionally
plus the reason in the closure disposition; the alternative (weaken to
"queryable via `lookup(business_key)` from the adapter store") splits stored
truth across two stores and still owes precise §14.6 wording. (MD-5.)

### C3 — §14.12 D11 + §14.14 item 8: the "only genuinely unavailable lookups" residual is wrong

The sharpened D11 residual ("the permanent-block residual survives only for
genuinely unavailable lookups") contradicts §14.6's own sentence that
prepared/held/`outcome_unknown` compensations keep blocking finalize
`OUTCOME_UNRESOLVED` (`runtime.py:506-510`): a held
`ADAPTER_ACTION_CONTEXT_UNSUPPORTED` compensation with no opted-in adapter
ever wired, a prepared-never-dispatched compensation, or an `outcome_unknown`
from a non-lookup failure each blocks closure indefinitely with no abandon
path — independent of lookup availability. `ORIGINAL_ABSENT` removes only
the missing-original sub-case. Amend D11/§14.14: the residual is **any
unresolved compensation** (prepared/held/outcome_unknown), of which
unavailable lookup is one cause.

### C4 — §14.10 test 27 / §14.2: the generic mixin coverage must not assume `expense.submit`

`AdapterConformanceMixin` is shared by three domains today
(`tests/test_publishing.py`, `tests/test_file_adapter.py`,
`tests/test_adapter_contract.py`; declared actions include
`content.publish`). Pin: the opt-in mixin test derives the action from the
adapter's own `contract.actions[0]` (forward context, `compensates=None`)
or a fixture hook, and skips when the opt-in is absent — no hardcoded
expense capability in generic conformance code. v2 does not hardcode it,
but does not pin the derivation either.

## 4. Minor clarifications (fold at ratification)

- **m1 (§14.6 dispatch link re-validation):** enumerate the comparisons —
  stored snapshot vs stored target body: `operation_id` exists,
  `external_id` equality, `capability` equality, status
  `confirmed_succeeded`, `work_id` equality, target not itself carrying
  `compensates`, current-policy pairing. The drafted
  "not confirmed_succeeded/same-work/non-compensation/pairing" omits the
  snapshot-vs-target `external_id`/`capability` equality arms (by
  construction at admission; belt-and-braces at dispatch should state them).
- **m2 (re-admission alias semantics):** state that re-admission returns the
  existing operation with its original immutable `compensates` snapshot
  (verified: no wrong-link path exists), so re-admission aliases forward the
  existing key and can never re-bind.
- **m3 (quarantine hygiene):** the §14.5 quarantine inherits `_resolve`'s
  idempotent same-reason branch and is unreachable on closed works (finalize
  cannot close past unresolved ops; `_resolve` early-returns on confirmed
  statuses) — the S9 closed-work custom-state preservation is unaffected; no
  new case. Test 23 should add a repeated-reconcile leg.
- **m4 (§14.2 normalization scope):** `action=None` ⇒ forward is FakeOA-side
  policy for its legacy direct callers, not a protocol rule (the protocol
  rule: legacy adapters are simply never called with kwargs). One sentence.
- **m5 (candidate-local references):** v2's relative links and the revision
  note's references (e.g. to `2026-10-15-compensation-design-recon.md`,
  which exists only on the candidate branch) resolve inside the candidate
  tree — verified only via the labelled `/tmp` `git archive` extraction and
  `check_docs.py` (0 broken) — and are absent from this review checkout, so
  this review claims no in-place validation of candidate-only paths; final
  link validation belongs to assembly/acceptance.

## 5. Master decisions requested (amendments to the v2 decision set)

| id | decision | recommendation |
|---|---|---|
| MD-1 | original-existence probe (A1) | **receipts-side accepted-forward-receipt query** (invoices at most a short-circuit); alternative: keep invoices-only with the zero-invoice restriction documented and classified — not recommended |
| MD-2 | forward write after migration (A2) | named-column INSERT + explicit forward action on new rows (`NULL` = legacy, normalized comparison); "byte-identical" restated behavior-identical |
| MD-3 | migration concurrency (A3) | probe+ALTER under `BEGIN IMMEDIATE` (probe-verified race-free) or duplicate-column catch + re-probe; test 26 concurrency/reopen legs |
| MD-4 | forward-side replay guard (A4) | action/link compare on forward replay, `ValueError` + zero effects on mismatch; test pin |
| MD-5 | failed-withdrawal reason storage (C2) | additive `op["adapter_result"]` for compensation resolutions (+ optional closure-disposition reason); alternative: adapter-store-only with weakened §14.6 wording |
| D19–D24 | local names/choices | confirmed sound **as amended**: D19 field/invariant verified compatible; D20 hold code/ordering verified against the held pattern; D21 semantics stand with MD-1's probe change; D22 stands with C1's accepted+rejected wording; D23 all four consequences verified in source; D24 stands with MD-2/MD-3/MD-4. D11 wording corrected per C3. |

## 6. TDD, ownership and release constraints (coherence check)

The §14.10 matrix (tests 16–27 + GREEN pins) is coherent with the
amendments: 16–19 and 21–25 map one-to-one onto the F1–F6 pins; test 20
extends to the forward side under MD-4; test 26 gains the A3 legs; test 27
takes the C4 pin; test 22's store-exception leg correctly keeps true
unavailability `outcome_unknown`. W1/W2 ownership (§14.11) is coherent with
the AGENTS doc_sync_map (`runtime.py`/`adapters.py` → `runtime-boundaries.md`
same-commit; `adapter-contract.md`/`interventions.md`/`verification.md`
listed same-commit for the surface changes) and with single-core W1 + W2
demo, independent assembly before integration-owned merge/non-force push.
Release constraints hold: runtime schema stays `1`
(`runtime.py:128-134`, `inspection.py` `_require_schema1`), the 726-test
battery is the untouched baseline (re-run green here, `OK (skipped=1)`), the
new demo is not a global gate (D12), no UI change (D13), publishing family
byte-unchanged, five AGENTS gates unaltered. Nothing in v2 authorizes
implementation before final ratification — consistent with the master's
"no product implementation yet".

## 7. Scope and limits

This review implemented nothing, mutated no ledger, and touched no candidate
file; ownership is this note only. All probes are throwaway under
`/tmp/compensation-review2-2026-10-15/` (labelled), including the extracted
candidate tree used for `check_docs.py` and the copy byte-comparison.
Findings are bounded to the dispatched second builder-check questions; this
is not a blanket endorsement — unlisted v1/v2 text stands only as re-verified
in §1, and candidate-internal link validation is deferred to assembly (m5).
No saga/auth/fencing/distributed-exactly-once claim is made or implied;
every principal remains trusted-local configuration.
