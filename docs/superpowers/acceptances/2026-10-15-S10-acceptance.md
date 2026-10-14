# Acceptance record — sprint S10, 2026-10-15

Independent Orca final acceptance of the assembled S10 expense-compensation
release: core `WayJ/s10-compensation-core` tip `4b57468ae555718299530afeaa9ec41cad56b054`
(12 commits on carrier base `4a15158`) assembled into control via merge
`03eed8247154cd4c91a5862db04b1ae66e870a10` (W1 integration review pass), then
demo `WayJ/s10-compensation-demo` tip `421bf70554c16b294d676e2c0f302de515cb22d0`
(5 commits on `3996b83dc873c62f4bfe5346952d8cf422518003`) assembled by this
review as merge `037e8b3f515a93233b5d4c416937b4bee3ddac61` (no-ff, no conflict
by construction). Evaluation environment: the **actual assembled carrier tree**
(per dispatch) — control `WayJ/s10-release-control` and the sprint's own carrier
`WayJ/sprint-s10-compensation` were both at `037e8b3` (fast-forwarded before the
scenarios ran; verified), not a tmp or stale tree; every scenario below ran
there, fresh. Base main `254c714fdeafacc8a15c8ce9a2cda7c92f617a52`
(local==remote, CI `38616203004` verified at S10 open). Python 3.9.6; zero
runtime dependencies; runtime store schema stays `1`. Review inputs read in
full: AGENTS.md, MASTER §15 D43–D48 (v2.1 spec
[§1–§15](../specs/2026-10-15-compensation-execution-design.md)), E10 roadmap,
the active S10 sprint plan, the scoped core and demo plans, the
[W1 core report](../../../.agents/notes/2026-10-15-S10-core-report.md), the
[W1 core integration review](../../../.agents/notes/2026-10-15-S10-core-integration-review.md)
and the [W2 demo report](../../../.agents/notes/2026-10-15-S10-demo-report.md).

## Verdict

pass — all five scenarios green on fresh runs in the actual assembled tree;
every DoD item checked with evidence; the one doc-sync arrears on a triggered
row (the `c3f103c` same-commit letter gap, W1 review Mi-1) is **paid inside
this acceptance act** by the coordinator-sanctioned pre-merge carrier
consolation described below (runtime/adapters now share their commit with
`docs/runtime-boundaries.md` in the release history); no UI/reader/browser
asset changed (byte-equality verified vs main), so no browser sweep is
claimed. Owner reports were not edited; the `c3f103c` gap is disclosed here
as it actually happened, and the repair is the consolidation, not a
retroactive claim.

## Pre-merge carrier consolidation (sanctioned; executed before this record)

Master ruling (this dispatch): the final release must pay D47's same-commit
runtime/adapters boundary-doc rule in the release history; the W1 Mi-1 gap
(`c3f103c` changed `runtime.py` with `interventions.md`/`verification.md`
only) is not waived as minor. Executed transformation, all provenance
preserved:

- Preservation first: branch `WayJ/s10-release-control-assembled` and tag
  `s10-assembled-037e8b3` point at the full assembled history (core merge
  `03eed82`, review note `3996b83`, demo merge `037e8b3`); owner branches
  `WayJ/s10-compensation-core` (`4b57468`) and `WayJ/s10-compensation-demo`
  (`421bf70`) are untouched; nothing torn down.
- `WayJ/s10-release-control` was soft-reset to actual main `254c714` and
  rebuilt as three scoped combined commits regrouping the same content by
  wave: `bf7899c` (design v2.1 + E10 roadmap + sprint materialization, the
  `254c714..4a15158` docs), `c7491d1` (the whole core wave
  `4a15158..4b57468` plus the W1 review note — **all** runtime/adapters/
  contract/policy changes, the three core test files, and
  `docs/runtime-boundaries.md` in this one commit, with
  adapter-contract/interventions/verification at core-tip content), `3554a5b`
  (the demo wave `3996b83..421bf70`, including the three docs' W2 additions,
  READMEs, CLI, demo module, installer proof and demo tests).
- **TREE byte-equality before/after:** consolidated `3554a5b^{tree}` ==
  assembled `037e8b3^{tree}` ==
  `a2d2bf38ed747443fb25e11e25794eae8f2fbdac` (exact `git rev-parse ^{tree}`
  equality); worktree clean after the rebuild; no product semantic change.
- **Mapped same-commit rule evidence (operational check, whole release
  range):** the only commit in `254c714..3554a5b` touching
  `work_runtime/runtime.py` or `work_runtime/adapters.py` is `c7491d1`, and it
  carries `docs/runtime-boundaries.md` (per-commit file lists verified by
  script). The other mapped rows owe nothing (`scripts/check_docs.py` and
  `scripts/check_site.py` unchanged this sprint).
- **Fresh carrier verification after consolidation** (identical to the
  assembled-tree runs, as byte-equality requires): battery `Ran 809 tests …
  OK (skipped=3)`; contracts `checked 91 markdown files, 393 local links, 0
  broken`; `demo` exit 0; `compileall` clean; site `checked 2 pages, 0
  findings`; rehearsals `Ran 15 tests … OK (skipped=1)`; all six demos exit 0.
- Owner reports and the W1 review text were **not** edited to claim pairing;
  the actual gap and this repair are disclosed here and in the close note.

## Scenario Results

| id | command | expected | actual | pass |
|---|---|---|---|---|
| S1 | full battery on the assembled tree (twice: assembled and consolidated): `python3 -m unittest discover -s tests`; skips enumerated by `-v`; independent probes `/tmp/s10-final-acceptance/probes/core_probes.py` P2; baseline arithmetic on extracted committed `4a15158` | Linked admission/window/replay: exact codes, immutable target/key, forward cancellation unchanged | `Ran 809 tests … OK (skipped=3)` both trees. Probe P2 PASS: stale `plan_revision` → rejected `PLAN_REVISION_MISMATCH` (command row persisted as a receipt, operations count unchanged); unknown target → `COMPENSATION_TARGET_INVALID` with `blockers == [requested id]`; same payload under a new command id replays to the **same operation id** (stable compensation key); dispatch-time grant loss → held `AUTHORITY_DENIED`, `attempts == []`, zero effects, then succeeds on restore. Window split (`CANCELLATION_ACTIVE` forward unchanged, `CANCELLATION_NOT_REQUESTED` without intent) and the full grants/version/shape/crosswork/chaining/re-admission/transfer matrix are pinned by `tests/test_compensation.py` (57 tests, green; W1 review verified them against D43 §14.8 and independently replayed Task-5 RED: 30 tests, 17 failures + 2 errors on parent). Baseline independently confirmed: extracted `4a15158` → `Ran 726 tests … OK (skipped=1)`; 726+62+21=809 with 62 = 57 `test_compensation.py` + 2 `test_adapter_contract.py` field tests + 3 in-suite mixin-test adopters (counted by name, not copied) | yes |
| S2 | same battery; probes P3–P7 (real adapters/stores, raw SQLite); installer's independent proof re-verified by mutation testing | Legacy zero-kwargs/false-marker hold, revision matrix, duplicate invoice, zero-invoice receipt presence, concurrent migration, aliases/action/link replay | Probes PASS: false-marker contract (withdraw declared, opt-in `False`) → held `ADAPTER_ACTION_CONTEXT_UNSUPPORTED`, zero execute calls, zero effect rows, work stays out of `needs_attention`, re-dispatch succeeds; a contract-less legacy adapter receives **exactly three positional arguments** on forward dispatch (recorded); different-key/same-original withdrawal returns the **same WD id** with authoritative `lookup(key2)`, still exactly one effect row; cross-action replay rejected **both directions** with `ValueError` and zero writes; a zero-invoice accepted forward receipt makes the original **present** for withdrawal (receipts-side, not invoices-only) while a store that never saw it stores a queryable `ORIGINAL_ABSENT` rejection; 4-thread barrier first-open on a pre-S10 3-column store migrates once (columns present, legacy row `NULL/NULL`, `withdrawals` created), reopen idempotent. Duplicate-invoice forward still business-rejected with a populated withdrawal store (suite pin, green). Concurrency/serialization pins green in-suite | yes |
| S3 | same battery; probes P1/P8/P9; demo-effect probe `/tmp/s10-final-acceptance/probes/demo_effect_probe.py` | Accepted/rejected binding mismatch, withdrawn E08 inertness/admin revoke/noimports, stored adapter_result and exact ack/dispositions; no false submit/reversal, failed explicit, unresolved blocks, original history intact | Probes PASS: end-to-end positive path — immutable `{operation_id, external_id, capability}` snapshot, separate stable key `digest([family, capability, original id])`, `adapter_result` bound to the original, exactly two tagged receipts (withdrawal receipt `link_digest == digest(compensates)`, recomputed), one `withdrawals` row, invoices unchanged, counts recomputed from rows (1/1), exact two-id closure ack, ordinary disposition exactly 3 keys / compensation disposition 5 keys; a digest-valid result naming a wrong `original_external_id` quarantines `ADAPTER_RESULT_INVALID` (op `outcome_unknown`, work `needs_attention`, no proof, no `adapter_result`, repeat idempotent with version/event count frozen); `withdrawn`-kind proof never satisfies E08 (still `satisfied` by the forward proof; after admin-revoking the forward accepted proof E08 is `pending`); withdrawn-kind import rejected for every actor incl. a configured writer; withdrawn-proof revoke denied for a configured source holding `evidence.revoke` (no `withdrawn` source mapping exists) and accepted for admin. Pre/post-withdrawal row comparison: forward receipt, invoices, forward proof and all prior events byte-identical — history appended, never rewritten. Refusal store (demo scenario B): `confirmed_failed` with stored `ORIGINAL_ABSENT` `adapter_result`, no withdrawn proof, single-id ack, refusal disposition, refusing store exactly one queryable rejection with zero effects — **documented boundary**: this demonstrates authoritative absence in THAT store under caller-trusted wiring; it is not a claim that the actual forward store refused an ordinary withdrawal or that the original effect disappeared (the original store keeps its accepted receipt and counts) | yes |
| S4 | probe P10 (real child `os._exit(73)`); probe P12 (read-only inspector); suite recovery/visibility pins; `ReadOnlyInspector` over real stores | Actual loss/process-death/retry/one-effect counts, S9 conflict path, generic inspect raw/events/full-table no-write | P10 PASS: real grants-carrying child dies with **exit code 73**; verified **pre-recover** store state — external `WD-…` effect and `withdrawals` row COMMITTED in `oa.sqlite` while the runtime operation is still `dispatched/in_flight` with an `outcome_unknown` attempt (the effect genuinely precedes the outcome store); restart `recover()` confirms **once** (`attempts` length 1), one original + one withdrawal effect, counts (1,1). P12 PASS: `ReadOnlyInspector` summary/list/events/work_detail with the runtime DB **byte-identical before/after** (zero writes); `OperationPrepared` for the withdrawal carries the additive `compensates` snapshot; inspector operation ids equal the raw table ids. S9 conflict-over-withdrawal-identity, execute-exception → `outcome_unknown` → reconcile `NO_AUTHORITATIVE_RESULT`, unresolved-compensation-blocks-finalize and later-work liveness are suite pins (green; W1 review's probe history additionally exercised them live — cited, not re-run here: 19/19 W1 probes on the same core SHA) | yes |
| S5 | five AGENTS gates verbatim; six demos explicit (not a gate); rehearsals; `python3 scripts/verify_install.py` serial (no concurrent load, Mi-4 respected); doc-sync audit; pinned-W2 diff review; this record precedes the merge | Exact counts/skips/docs/scope; actual remote==final main and exact CI success (close act) | Gates: contracts `checked 91 markdown files, 393 local links, 0 broken`; tests 809 OK (skipped=3); `demo` exit 0; `compileall` clean; site `2 pages, 0 findings` — command list unchanged (AGENTS untouched). Six demos all exit 0 (`demo`, `publish-demo`, `intervention-demo`, `adoption-demo`, `revocation-demo`, `compensation-demo`). Rehearsals `Ran 15 tests … OK (skipped=1)` — the 14 pre-existing rehearsal tests pass; the skip is the new generic opt-in conformance test on the queue adapter. The three suite skips, independently named: `Opt-in action/link execution: explicit forward context replays.` on `FilePublisherConformanceTests` and `FakePublisherConformanceTests` (`'adapter does not opt into action/link execution context'`) and `test_ui_cli.AbsentBackendTests.test_absent_backend_is_a_bounded_startup_error` (`'backend assembled: absent-install path unreachable'`). Installer `=== PASS ===`, serial, **zero SKIPPED lines**, 19 printed stage sections (the documented 18 stages, venv-creation and install printed separately) incl. module and console `compensation-demo` **outside the checkout** with the independent two-store proof, and installed UI over real HTTP with byte-equal packaged assets and unchanged store tables. Pinned-W2 review: `git diff 3996b83..421bf70` = exactly the 11 owned files; protected paths (runtime/adapters/contract/policy/demo/inspection/publishing/file_adapter/ingress modules, `web/`, `data/`, `website/`, `examples/`, gate scripts, AGENTS, pyproject, README-adjacent protected set, sprints/roadmaps/acceptances/tracker, runtime-boundaries) byte-identical; vs main `254c714..037e8b3` the protected-asset diff is empty. W2 RED independently reproduced: the final demo test file on extracted pre-W2 `3996b83` → `Ran 21 tests … FAILED (failures=1, errors=20)` (20 × `ImportError: cannot import name 'compensation_demo'`; 1 CLI failure unknown-subcommand). Release remote equality and exact-SHA CI are the close act's items, recorded in `.agents/notes/2026-10-15-S10-close.md` at push time (S7–S9 precedent: acceptance precedes the merge by design) | yes |

## Independent mutation testing of the installed-proof

`/tmp/s10-final-acceptance/probes/mutation_probe.py` — restore-pristine →
tamper → `require_compensation_proof` must reject; **8 meaningful mutations,
8 rejected, 0 undetected; pristine control accepted**: fabricated second
withdrawal effect row (false WD); withdrawal id changed in the store while
the op body is kept; mutated `compensates` snapshot (wrong linked target);
swapped `link_digest` on the withdrawal receipt; forged extra accepted
forward receipt (accepted-count inflation); flipped proof kind
`withdrawn`→`accepted` **with the fingerprint recomputed** (a coherent
forgery, not a corrupt row); deleted withdrawal receipt row; withdrawal
effect inserted into the refusal scenario's absent store. Every rejection
named the violated invariant. The proof never trusts demo stdout, counters
or narration; keys/fingerprints are recomputed with the standard library.

## DoD Checklist

- [x] Authorized version-bound linked compensation and dispatch revalidation permit expense withdrawal only during active cancellation, preserve ordinary admission/replay/ownership, and reuse immutable original links with separate stable keys — S1 evidence: probes P1/P2 (exact codes `PLAN_REVISION_MISMATCH`/`COMPENSATION_TARGET_INVALID`+blockers, replay to the same operation id, grant-loss hold then restore), suite matrix green (both policy versions, window split covering fresh AND re-admission, cross-work/unknown/failed/chained targets, transfer re-admission with unchanged snapshot), W1 review's live authority/replay probes cited on the same core SHA
- [x] Explicit opt-in action/link execution preserves legacy calls and forward behavior; additive adapter migration, per-key receipts and per-original withdrawal effects remain race-safe, queryable and idempotent with truthful counts — S2 evidence: probes P3 (false-marker hold with zero calls/effects; legacy 3-positional args), P4 (alias same-WD-id, authoritative per-key lookup, one effect row), P5 (cross-action replay both directions, zero writes), P6 (zero-invoice presence; stored absence), P7 (4-thread concurrent migration, idempotent reopen); counters recomputed from rows in P1 and the demo probe
- [x] Actual results bind original effects, use withdrawn proof semantics and preserve original history; stored adapter results and cancellation dispositions expose refusal without false reversal or forward acceptance — S3 evidence: probes P1 (byte-identical pre/post rows), P8 (mismatch quarantine idempotent), P9 (withdrawn never satisfies E08; no imports; admin-only revoke); demo refusal store verified raw (`confirmed_failed`, stored reason, single-id ack, zero effects, original retained)
- [x] Meaningful RED/GREEN, lost-response/process-death, revision/link/alias/legacy/concurrency tests and readonly inspection prove one retained original and withdrawal effect; generic assets and publishing remain valid without UI changes — RED: W1 review independently replayed core Task-5 (30 tests: 17F+2E) and Task-7 (42 tests: 1F+3E) RED on parents; this run independently reproduced the W2 RED (21 tests: 1F+20E on pre-W2 tree) and re-confirmed the 726 baseline on committed `4a15158`; process death proven live pre-recover (P10); read-only zero-write proven by bytes (P12); protected assets byte-equal vs main (empty diff) — no UI change, no browser claim
- [x] A no-credentials compensation-demo and installed module plus console trials prove actual stored links/effects/closure; Python>=3.9/schema1/zero dependencies, full tests, five gates, six demos, fourteen rehearsal tests and installed verification pass with exact counts/skips — demo-effect probe 4/4 from raw SQLite (keys recomputed, snapshots, external ids, evidence fingerprints, event kinds, closure truth; the printed `inspect` command executed with `"outcome": "cancelled"`); installer PASS serial with module+console compensation stages outside the checkout; counts/skips exactly as enumerated in S5 (809/3, 15/1, 91/393/0, six demos); Python 3.9.6 venv install with zero third-party dependencies; schema 1 (runtime) with additive adapter migration
- [x] Independent acceptance precedes integration ordinary main merge/non-force push with same-commit runtime/adapter boundary docs, truthful bounded compensation coverage and exact final remote equality/CI; unimplemented family/window/auth/fencing guarantees remain unclaimed — this record and the sprint-doc state flip precede the merge (ordering honored); the same-commit boundary-doc rule is paid in the release history by the sanctioned consolidation above (`c7491d1` is the only runtime/adapters commit and carries `docs/runtime-boundaries.md`, with the assembled tree preserved byte-equal on `WayJ/s10-release-control-assembled`); public docs/README claim only the bounded expense active-cancellation window (publishing/post-closure/chains/auth/fencing/distributed-exactly-once/key-rotation explicitly open — verified in README/README.zh/verification.md diffs); final remote equality and exact-SHA CI (3.9/3.12/3.13) are recorded at push time in the close note per the S7–S9 precedent

## Obstacles (verbatim)

- 2026-10-15 — first core-probe run reported 5 FAILs (P2 `KeyError('reason')`,
  P3 `CommandError('Adapter contract descriptor is malformed: NoneType')`,
  P8 expected `dispatch_state == 'needs_attention'`, P9 expected
  `CommandError` from a revoke that actually returns a rejected **dict**, P12
  read the inspector's operation list with the wrong key). All five diagnosed
  probe-side against the documented API shapes before any product conclusion:
  rejections are receipt dicts keyed `code` (with `blockers` carrying the
  requested target id); a `contract = None` attribute is malformed by design
  (only an **absent** descriptor is legacy); quarantine parks the *work* in
  `needs_attention` while the op stays `outcome_unknown`; revoke denials are
  `AUTHORITY_DENIED` dicts; `work_detail` operations use `id`. Probes
  corrected; re-run **11/11 PASS**. No product change — same class as the W1
  reviewer's 13 probe-side iterations.
- 2026-10-15 — demo-probe inspect replay failed `Unknown work: expense`:
  the printed `--db "/path"` token was split naively so the quotes reached
  SQLite as part of the filename (opening a fresh empty DB). The installer's
  own replay uses `shlex.split`; probe corrected to match. Re-run 4/4 PASS.
- 2026-10-15 — mutation-probe first iteration terminated at M1 because the
  verifier signals rejection via `SystemExit` (`FAILED: …`), which
  `except Exception` does not catch; corrected to `except BaseException`
  (KeyboardInterrupt excluded by control flow). 8/8 mutations then detected,
  control PASS.
- 2026-10-15 — reconciliation, recorded not rewritten: W1 owner report said
  "101 files"; W1 review measured 90/386/0 on the committed core tree; W2
  owner saw 95→96 during their session with untracked SDD briefs (committed
  91). This run's clean tracked counts on the assembled/consolidated tree:
  **91 files / 393 links / 0 broken** (the +1 file vs W1 is the W2 demo plan;
  +7 links are the W2 docs/plan additions). No worktree-local markdown was
  present during this run's gates.
- 2026-10-15 — recorded scope note (not a failure): no browser-based UI sweep
  was run because S10 changed no UI/reader/browser asset — protected diff vs
  main empty. GUI evidence is the installer's installed-UI-over-real-HTTP
  stage (byte-equal packaged assets, seeded works, unchanged store tables)
  plus the preview check recorded in the close note; no visual change is
  claimed.

## Doc-Drift Audit

| map row (change, owes) | matched this sprint | doc state | detail |
|---|---|---|---|
| work_runtime/runtime.py → docs/runtime-boundaries.md | yes — runtime.py changed (core wave) | current; same-commit rule **paid via consolidation** | In the owner branch 5 of 6 runtime commits paired natively; `c3f103c` did not (W1 Mi-1, disclosed). The release history now carries ALL runtime/adapters changes in `c7491d1` together with `docs/runtime-boundaries.md` (final content); per-commit audit over `254c714..carrier` shows `c7491d1: PAIRED` and no other commit touching the mapped code. Branch-tip content was already current (W1 review verified; re-read this run) |
| work_runtime/adapters.py → docs/runtime-boundaries.md | yes — adapters.py changed (core wave) | current; same commit `c7491d1` | as above; store-compatibility/migration/withdrawal sections reviewed against observed probe behavior |
| scripts/check_docs.py → CONTRIBUTING.md | no — check_docs.py unchanged | n/a | row owes nothing |
| scripts/check_site.py → docs/website.md | no — check_site.py unchanged | n/a | row owes nothing |

Beyond the map (recorded, not enforced): `policy.py` (`64504ac`, W1 Mi-2) is
**not** a mapped row; the design §8 draft table names policy docs same-commit
and they landed same-branch in `4769574` with the admission that exercises
the pairing — content current at tip (pairing section re-read); per the
coordinator ruling this stands as a disclosed caveat with no further claims.
`docs/adapter-contract.md`, `docs/interventions.md`, `docs/verification.md`
(not mapped) were updated by both waves and verified truthful against
observed behavior this run; `docs/roadmap.md` 0.3 release-time note is the
close act's sanctioned integration update (spec §8).

## W2 deferred-minor assessment (no cosmetic patches, per dispatch)

1. Demo step 4 prints the `(WD-…)` placeholder rather than the concrete id —
   cosmetic print; the id is asserted in-store and inspectable (demo-effect
   probe reads it from SQLite). Not patched; disclosed.
2. Refusal-store OA check reuses the unfiltered accepted-forward helper —
   correct in this scenario because the withdrawal receipt lives in
   `absent.sqlite`; verified by raw row counts in the demo-effect probe.
   Not patched.
3. Compensation API example EN-only — consistent with the zh README's
   pre-existing "英文首页提供 Python 使用示例" deferral pattern; the zh
   additions make no bilingual-example claim. Not patched; no false scope.

All three are confidence-neutral cosmetics; none affects stored truth,
proofs or counts (mutation testing above covers the load-bearing invariants).
