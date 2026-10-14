# Acceptance record — sprint S9, 2026-10-15

Independent Orca integration acceptance on the accepted source: core
`WayJ/s9-evidence-collision-core` tip `dc1ea1165f8bceeb4f18d443ec96d9358fe9e6c3`
(5 commits on sprint base/carrier `bcce865`, itself 4 commits on published
main `635e7b1` — local==remote equality and exact-SHA CI run `38603764253`
success re-verified this run: jobs `test (3.9)`/`test (3.12)`/`test (3.13)`
all green). Ordered-after-verdict merges: control `WayJ/s9-release-control`
and carrier `WayJ/sprint-s9-evidence-collision` were fast-forwarded to the
accepted source **after** the scenarios below ran, so the evaluation
environment was a detached scratch worktree at the exact source SHA (tree
`9a976eb6d6d14ac72dccdf857491fa9a91bb061c`, byte-identical to the
post-verdict carrier/control assembly, `git rev-parse ^{tree}` equality on
all three). Independent public-API probes ran from `/tmp/s9-integration-probe`
(outside any checkout, throwaway stores); RED reproduction ran in a detached
scratch worktree at unmodified base `bcce865` plus the new test file.
Python 3.9.6; zero runtime dependencies; schema stays `1`. Review inputs:
ratified D38–D42 design (MASTER section supersedes all draft text), S9
sprint/E9 roadmap, RFC-001/003, the scoped core plan
`cd07042`, the owner report
[2026-10-15-S9-core-report.md](../../../.agents/notes/2026-10-15-S9-core-report.md)
and the independent design review
[2026-10-15-TD1-independent-design-review.md](../../../.agents/notes/2026-10-15-TD1-independent-design-review.md).

## Verdict

pass — all four scenarios green on fresh runs in the source environment;
every DoD item checked with evidence; no unpaid doc-sync drift on triggered
rows (the runtime.py→runtime-boundaries.md same-commit rule is satisfied
natively by the owner's commits `267e1d3` and `1063542` — no consolidation
was needed this sprint); no UI/reader/browser asset changed (byte-equality
verified), so no browser sweep is claimed.

## Scenario Results

| id | command | expected | actual | pass |
|---|---|---|---|---|
| S1 | `python3 -m unittest tests.test_accepted_evidence_collision -v` (fresh, source env); independent probes `/tmp/s9-integration-probe/probe.py` P1 (public API, outside checkout); independent RED: new tests on unmodified base `bcce865` | Both-family authority/version/malformed/dedup/newcode/crosswork/source-overlap/registry-change behavior; `OPERATION_ID_RESERVED` only for new eligible collisions; legitimate imports and old receipts intact | Module 24/24 OK. Probes: fresh-id import accepted; op-id intake rejected `OPERATION_ID_RESERVED` with `blockers==[op]` and current `observed_state_version`; cross-work (op of W2 imported into W1) rejected; overlapping-mapping kind rejected while `invoice-service` records the same id accepted (no false block); registry union spans loaded V1/V2 and follows live policy-object mutation (`oa3`); publishing mirror; stored rejection replays verbatim, fresh `AUTHORITY_DENIED` on authority loss, verbatim again on restore. Suite pins: exact resend of a pre-fix poisoning payload dedups with the candidate's current status; changed content stays `SOURCE_EVENT_CONFLICT`; post-confirmation import stays `SOURCE_EVENT_CONFLICT`. RED reproduced: 6 prevention tests fail `'accepted' != 'rejected'`/`KeyError: 'code'` on base | yes |
| S2 | same module run; probes P2/P4 (real `FakeOA` counters, sqlite row equality, `ReadOnlyInspector`); RED on base | Actual confirmed result; exact nine-field op snapshot and eleven-field event; candidate/closed history unchanged | Probes: `confirmed_succeeded`/`finished`/truthy `external_id`/existing attempt terminal status, attempts length 1, `accepted_count()==1`; snapshot set == exactly the nine fields, sourced PK/body-strings/SQL-columns/adapter-`external_id`/op-`document_digest` (suite additionally pins `document_digest != candidate data.digest`); exactly one `AcceptanceProofConflict`, body = 11 fields, `work_was_closed: false`, zero `OperationResolved` for that resolution; conflicting row byte-identical before/after and no new evidence row; op work `needs_attention`; row-status-at-resolution recorded (`verified` via real `verify_pending`; suite: pending/verified/invalid/revoked all pinned, row untouched each time); closed custom store keeps `status`/`outcome`/`completion` with `work_was_closed: true`; malformed id/kind/status/non-object bodies degrade to `null` while SQL `work_id`/`fingerprint` stay verbatim; publishing mirror (`published_count()==1`); inspector `event_types`/`body_raw`/op `proof_conflict` exposed with six-table equality across reads. RED reproduced: 21 `sqlite3.IntegrityError: UNIQUE constraint failed: evidence.source, evidence.event_id` occurrences across 17 conflict-family tests plus `1 != 76` on the process-death child (died on the IntegrityError before the injection point) | yes |
| S3 | same module run; probe P3 with the real `python -m work_runtime worker --crash-after-effect` child (exit 73) | Later ready operations reached; repeated reconcile/recover settled-op no-op; exception and real process-death rollback prove atomic retry | Probe: crash worker exit 73 with the effect committed (`accepted_count()==1`); `recover()` settles the poisoned op through the conflict path exactly once **and** confirms the later ready op (count 2); two further cycles: whole settled store byte-identical, no new events, zero re-execute through the runtime for the settled op (its single execute belongs to the child; shared adapter store proves the one retained effect), exactly one lookup, original business keys. Suite: exception injection and a real `os._exit(76)` child dying inside the resolution transaction roll back op/work/event together (op `dispatched`, zero events, no `proof_conflict`), redone deterministically once; lost accepted response (`timeout_after_commit`) recovers exactly once via lookup; repeated recover still verifies/expires other records (`EvidenceEvaluated`/`WaitExpired`) and dispatches a later op | yes |
| S4 | full battery in the source env: `python3 -m unittest discover -s tests -v`; all five configured gates verbatim; five demos; `python3 -m unittest examples.rehearsal.test_queue_adapter`; `python3 scripts/verify_install.py`; same-commit doc audit; this record precedes the merge | Exact coverage/skips and source limits; tracker evidence; final remote equality and exact-SHA CI | `Ran 726 tests ... OK (skipped=1)` = 702 baseline + 24 new, counted; the single skip quoted verbatim: `test_absent_backend_is_a_bounded_startup_error (test_ui_cli.AbsentBackendTests) ... skipped 'backend assembled: absent-install path unreachable'` (S5/S6-inherited guard). Gates: contracts `checked 85 markdown files, 344 local links, 0 broken` (actual tracked counts — reconciliation below); tests gate same run; `demo` exit 0; `compileall` exit 0; site `checked 2 pages, 0 findings`. Five demos (`demo`, `publish-demo`, `intervention-demo`, `adoption-demo`, `revocation-demo`) all exit 0. Rehearsal `Ran 14 tests ... OK`. `verify_install.py` `=== PASS ===` (fresh venv; installed module+console demos/ui/revocation outside the checkout; packaged web assets byte-equal over real HTTP). Existing tests byte-equal baseline (only the new test file added under `tests/`); frontend/data assets (`work_runtime/web`, `work_runtime/data`, website pages) byte-equal baseline — no browser sweep claimed, and the existing GUI demo on 127.0.0.1:52719 serves `index.html`/`app.js`/`app.css` byte-equal to the accepted packaged assets over real HTTP with live `/api/summary`/`/api/works`/`/api/work`/`/api/events` responses. Doc-sync same-commit rule satisfied natively; release remote equality and exact-SHA CI are recorded in the closing note at push time (S7/S8 precedent: acceptance precedes the merge by design) | yes |

## DoD Checklist

- [x] Accepted-source operation-ID intake is rejected atomically with pinned precedence and authority; legitimate imports, resends, old receipts and confirmed-proof conflicts remain valid across works and both policy families — S1 evidence: 6 prevention + dedup/conflict/replay pins green; independent probes P1/P5; RED reproduced on base; both families covered (publishing reservation + conflict mirrors)
- [x] Existing poisoned stores record actual accepted external results and a durable conflict snapshot without altering candidate identity, raw payload or fingerprints; closed outcome/completion history remains intact — S2 evidence: probes P2/P4 with real counters and row equality; suite pins nine/eleven exact field sets, byte-identical conflicting row across all status variants and malformed bodies, closed-store preservation
- [x] Repeated resolution is operation-scoped idempotent and recovery reaches later operations with one retained external effect, original keys and bounded calls; real exception/process-death rollback tests prove atomic retry — S3 evidence: real crash worker + probes; suite exception/`os._exit(76)`/lost-response/`timeout_after_commit`/repeated-recover pins
- [x] Python>=3.9, schema1 and zero runtime dependencies remain; full tests, five configured gates, five demos, standalone rehearsal and installed verification pass with exact counts/skips and truthful trusted-local limits — S4 evidence: 726/1-skip counted and named; all gates/demos/rehearsal/install green; limits truthful (corrupted-store repair explicitly out of scope in `docs/runtime-boundaries.md` and `docs/verification.md`; no authentication/compensation/fencing/key-rotation claim anywhere — the only matches in the changed docs are disclaimers)
- [x] Independent acceptance precedes integration-owned ordinary main merge/non-force push; runtime boundary docs share the implementation commit, TD-1 repayment cites verified evidence, and exact final remote equality/CI are proven — this record and the sprint-doc state flip precede the merge (ordering honored; commits `267e1d3`/`1063542` each carry `docs/runtime-boundaries.md` with `work_runtime/runtime.py`); TD-1 repayment and final remote equality/CI are the close act's items, recorded in `.agents/notes/2026-10-15-S9-close.md` at push time per the S7/S8 precedent

## Obstacles (verbatim)

- 2026-10-15 — independent probe P3 first reported
  `FAIL P3 repeated recover: whole store settled, no new events, bounded calls`.
  Diagnosed before any product conclusion: the probe asserted
  `counting.executes.count(op_key) == 1`, but the settled op's single
  execute happened in the real crash-worker **child** (outside the counting
  wrapper), so through-runtime executes for it are correctly 0 — a probe-side
  wrong expectation, not a product defect. Diagnostic re-run (with a 2s gap
  between settled cycles): zero new events, settled op body byte-identical,
  one conflict event, executes 1 (later op) / lookups 1 (settled op
  reconcile) — exactly the documented op-scoped idempotence. Probe corrected
  (`executes.count(op_key) == 0` + `accepted_count() == 2` as the real
  one-effect proof); re-run 27/27 PASS. No product change.
- 2026-10-15 — probe `GET /api/events?work=<id>` returned
  `HTTP Error 400: Bad Request` against the existing GUI demo on 52719:
  the probe used the wrong parameter name; the server's contract is
  `work_id` (unknown query parameters are rejected `BAD_QUERY` by design,
  `work_runtime/ui_server.py` allowed-params check). Retried with
  `work_id` + `limit`: 200 with events. Correct API behavior; no product
  change.
- 2026-10-15 — reconciliation, recorded not rewritten: the owner report's
  contracts row says "checked 90 markdown files"; this run's clean tracked
  count at the same tree is **85 files / 344 local links / 0 broken** (links
  match). The owner's 90 included worktree-local markdown present during
  their run (their `.superpowers` ledger workspace, since deleted; the owner
  worktree now shows 0 untracked `.md`). No defect; tracked counts quoted
  here.
- 2026-10-15 — recorded scope note (not a failure): no browser-based UI
  sweep was run because S9 changed no UI/reader/browser asset — verified by
  `git diff --name-status bcce865..dc1ea11` (8 files: runtime, one new test
  file, four docs, one plan, one report note; `work_runtime/web`,
  `work_runtime/data` and website pages byte-equal). GUI evidence is the
  real-HTTP asset byte-equality above plus `verify_install.py`'s
  fresh-instance HTTP checks; no visual change is claimed.

## Doc-Drift Audit

| map row (change, owes) | matched this sprint | doc state | detail |
|---|---|---|---|
| work_runtime/runtime.py → docs/runtime-boundaries.md | yes — runtime.py changed in `267e1d3` and `1063542` | current | both commits touch runtime.py and runtime-boundaries.md **in the same commit** (per-commit file lists verified) — the same-commit rule is satisfied natively, no S8-style consolidation needed; new "Accepted-evidence reservation" and "Acceptance-proof collision recovery" sections reviewed against observed behavior and the ratified D38–D42 field/precedence rules; recovery-contract guarantees and verification-table rows added |
| work_runtime/adapters.py → docs/runtime-boundaries.md | no — adapters.py unchanged | n/a | row owes nothing |
| scripts/check_docs.py → CONTRIBUTING.md | no — check_docs.py unchanged | n/a | row owes nothing |
| scripts/check_site.py → docs/website.md | no — check_site.py unchanged | n/a | row owes nothing |

Beyond the map: `docs/verification.md` (S9 coverage section, named classes,
limits), `docs/interventions.md` and `docs/evidence-revocation.md`
(TD-1-deferred parentheticals now point at the runtime-boundaries conflict
boundary with the tracker still owning repayment) were updated by the owner
in `5046f8a` and verified truthful this run; the changed docs make no
authentication, compensation, fencing, key-rotation or
distributed-exactly-once claim (only disclaimers), and invalid-JSON
corrupted-store repair is explicitly out of scope. Website pages unchanged.
