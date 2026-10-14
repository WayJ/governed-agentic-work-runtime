# Acceptance record — sprint S8, 2026-10-15

Independent Orca acceptance run on the sprint's own environment: worktree
`WayJ/sprint-s8-revocation` (carrier) at consolidated assembly `d208b22`
— tree `68448e3641a019302467a33c03edcc822d039abf`, byte-identical to the
reviewed control assembly `d348cb0` (verified `git rev-parse ^{tree}`
equality). Accepted sources: core `a1680a7`, viewer `37ef814`, demo
`06f33f6`, all on core base `41583e2` (= accepted core assembly + core
integration review `41583e2`), each independently reviewed:
[core](../../../.agents/notes/2026-10-14-S8-core-integration-review.md),
[viewer](../../../.agents/notes/2026-10-15-S8-viewer-integration-review.md);
demo reviewed this run (below). Python 3.9.6; zero runtime dependencies.

## Verdict

pass — all six scenarios green on fresh runs in the sprint environment;
every DoD item checked with evidence; no unpaid doc-sync drift on triggered
rows (the one pre-merge arrears was repaired by the sanctioned, disclosed,
tree-identical carrier consolidation `d208b22` and the audit re-run green).

## Scenario Results

| id | command | expected | actual | pass |
|---|---|---|---|---|
| S1 | `python3 -m unittest tests.test_evidence_revocation tests.test_interventions` (carrier worktree); independent public-API probes from the core review (49/49, `/tmp/s8-integration-probe`, incl. malformed/stale/owner-only/cross-work/replay/lost-cap/cached-unknown) | Both-family malformed/stale/source/admin/retired/owner-only/cross-work/replay tests; correct rejected codes/rollback, one version/event on success, original receipts immutable | `Ran 135 tests ... OK` (55 revocation incl. publishing family + 80 interventions incl. 2 D-1); core probes had verified receipt shape, single version/event/command atomicity, immutable receipts under replay denial | yes |
| S2 | same module run; independent demo-store probe (this run): statuses/fingerprints/business keys recomputed locally for the three `revocation-demo` stores | Revoked never revives; fresh current proof restores only intended rules | revoked pending never verifies (`verify_pending`=0), restart/migration keep revoked (migration records revoked→revoked), resend reports current `evidence_status:"revoked"` while original receipts replay verbatim; probe 3/3 stores OK with recomputed SHA-256 fingerprints | yes |
| S3 | same module run; demo probe hold/uncertain stores | All wait states/deadlines, prepared hold/readmit, in-flight/confirmed; no cancelled resurrection/reset, zero predispatch calls, exactly one retained uncertain effect | hold store: `DispatchHeld` reason REQUIREMENT_UNSATISFIED, zero attempts/calls, replacement readmits SAME operation id (business key recomputed), exactly 1 receipt; uncertain store: 1 retained receipt, reconcile once, confirmed op never re-executes, cancelled/expired waits terminal (module tests) | yes |
| S4 | same module run (crash tests: injected exception, real `os._exit(75)` child, external-death worker exit 73); demo probe publish store | Closed/outcome/completion stable; current validity/event visible; rollback atomic | five-table snapshot equality on both crash paths with retry-then-succeed; publish store: closed/succeeded kept, completion cites the revoked acceptance byte-identically, C04 pending, `EvidenceRevoked` work_was_closed + completion_cites_evidence | yes |
| S5 | `python3 -m unittest tests.test_revocation_viewer tests.test_inspection tests.test_ui_cli tests.test_ui_demo tests.test_ui_server tests.test_revocation_demo`; fresh browser `python3 .agents/notes/2026-10-15-S8-viewer-browser.py --phase green --out /tmp/s8f-carrier-green`; `python3 scripts/verify_install.py`; committed RED assets + independent RED reproduction (Task4: 8/8 on pre-notice `542db87` extraction) | Real current DTOs, actual browser notice RED/GREEN desktop390/320, raw huge/XSS/zero-writes, both-family demo installed module+console | `Ran 114 tests ... OK (skipped=1)`; browser GREEN 30/30 (notice closed-only EN/ZH, derived citations only, computed DESIGN tokens, contrast ≥4.5, keyboard/poll/disconnect, no overflow 1440/390/320, six-table byte equality); verifier `=== PASS ===` 7.8s — module+console revocation-demo outside the checkout with independent store proof, installed UI assets byte-equal over real HTTP, store tables unchanged | yes |
| S6 | `python3 -m unittest discover -s tests`; `python3 -m unittest discover -s examples/rehearsal`; the five AGENTS gates verbatim; all five demos | Exact coverage/skips/docs synchronized; release equality/CI per DoD ordering | `Ran 702 tests ... OK (skipped=1)` — 679 base + 11 viewer + 12 demo, counted; the single skip is `test_absent_backend_is_a_bounded_startup_error (test_ui_cli.AbsentBackendTests)` — `'backend assembled: absent-install path unreachable'` (S5/S6-inherited guard; the "root chmod" phrasing in one owner report is inaccurate, actual reason quoted); rehearsal `Ran 14 tests ... OK`; contracts `checked 80 markdown files, 313 local links, 0 broken`; compileall clean; site `2 pages, 0 findings`; `demo`/`publish-demo`/`intervention-demo`/`adoption-demo`/`revocation-demo` all exit 0. Release remote equality and exact-SHA CI are recorded in the closing note at push time (S7 precedent; acceptance precedes the merge by design) | yes |

## DoD Checklist

- [x] Explicit version-bound authorized revocation preserves source identity/payload/fingerprints and historical receipts; replay, stale/cross-work/malformed/retired-authority cases are atomic and revoked candidates never silently reactivate through verification, restart, migration or dedup resend — 135-test module run + 49 independent probes (S1/S2 evidence); fingerprints recomputed independently in the demo probe and `verify_install.py`
- [x] Current requirements and future action/completion admission react to revoked proof; replacement evidence, wait disposition and prepared-intent handling are explicit and cannot resurrect cancelled waits or dispatch stale permission — hold/readmission/blocker module tests + demo stores (S3 evidence); no cancelled-wait resurrection, no deadline reset
- [x] In-flight and confirmed external effects retain their original business keys/results and reconcile without extra calls or pretend reversal; closed-work correction preserves original outcome/completion history and explicitly exposes current invalidity/audit attention — uncertain/publish stores + viewer DTO/event flags (S3/S4/S5 evidence); `effects reversed: 0` is a counted fact
- [x] Expense and publishing scenarios, meaningful RED/GREEN/real crash rollback/process-death tests, inspect/read-only GUI and installed no-credentials trials prove actual stored truth and external effect counts; UI change follows DESIGN with actual browser/zero-write proof — crash tests in-suite; browser GREEN 30/30 with computed tokens/contrast at 1440/390/320 and six-table zero-write; installed module+console trials PASS; committed RED + independently reproduced RED (8/8)
- [x] Python>=3.9/zero dependencies/existing stores and prior tests/demos remain valid; all configured gates, standalone rehearsal and installed verifier pass with exact coverage/skips, doc-sync current and trusted-local/residual external-race limits truthful — Python 3.9.6, `verify_install` reports no third-party runtime deps; 702/1skip disclosed; 14 rehearsal; five gates green; arrears repaired (below); limits stated in runtime-boundaries/evidence-revocation/verification docs and README
- [x] Independent acceptance precedes integration-owned main merge/non-force push; actual final remote equality and exact-SHA CI verified, with usable inspect/GUI/demo instructions and no false compensation/distributed claim — this record precedes the merge (ordering honored); remote equality + CI on the exact final SHA are verified and recorded in `.agents/notes/2026-10-15-S8-close.md` (same close act); inspect/demo instructions printed by `revocation-demo` run verbatim; docs explicitly disclaim compensation/authentication/fencing/distributed exactly-once

## Obstacles (verbatim)

- 2026-10-15 — pre-merge arrears check: no commit in the carrier range
  `48c01fd..tip` touched both `work_runtime/runtime.py` and
  `docs/runtime-boundaries.md` (owner commits `97a0452`/`1188afe`/… vs docs
  commit `37dce2a` are separate). Sanctioned repair applied: carrier history
  consolidated into single commit `d208b22` (reset --soft to `48c01fd`),
  tree byte-identical (`68448e36…` before and after, `git rev-parse ^{tree}`
  equality), owner branches (`a1680a7`, `37ef814`, `06f33f6`) and control
  branch (`d348cb0`) retain full original history; full battery re-run green
  in the carrier worktree after the transformation. Disclosed here and in the
  closing note; no product semantic change; carrier never pushed before.
- 2026-10-15 — this session's harness cannot display images
  (`[Unsupported Image]` for PNG and JPEG). Workaround: screenshot evidence is
  programmatic — fresh CDP session (30/30), committed-asset pixel forensics
  with an independent stdlib decoder (cream-soft 124,471 vs 17,804 px;
  chip 1,035 px; dimensions exact) — plus the root coordinator's direct
  viewing of the committed 320px PNG ("notice/button wrapping readable,
  contrast/warm tokens as expected"), cited as the human visual check. No
  eyeball claim is made by this reviewer.
- 2026-10-15 — reconciliation, recorded not rewritten: owner demo report
  prose says "679 baseline + 12" with suite "691" on its viewer-less base
  (consistent); the viewer report's "+13 new" prose (692) was a slip —
  actual +11; demo owner gates table said "83 files/307 links" vs this run's
  80/313 (links grew with demo docs; file counts included worktree-local
  untracked markdown). Skip-reason wording disagreed between reports
  ("root chmod" vs "installed UI backend"); actual current reason quoted in
  S6 above. No product change required by any of these.

## Doc-Drift Audit

| map row (change, owes) | matched this sprint | doc state | detail |
|---|---|---|---|
| work_runtime/runtime.py → docs/runtime-boundaries.md | yes — runtime.py (revoke command, D-1 guard) | current | "Evidence revocation boundary" section + migration/immutability updates present and cross-checked against observed behavior; same-commit rule satisfied by consolidated carrier commit `d208b22` (disclosed transformation, arrears repaired pre-merge) |
| work_runtime/adapters.py → docs/runtime-boundaries.md | no — adapters.py unchanged this sprint | n/a | row owes nothing |
| scripts/check_docs.py → CONTRIBUTING.md | no — check_docs.py unchanged | n/a | row owes nothing |
| scripts/check_site.py → docs/website.md | no — check_site.py unchanged | n/a | row owes nothing |

Beyond the map: `docs/evidence-revocation.md` (new reference),
`docs/verification.md`, `docs/interventions.md`, `docs/gui-api.md`,
`docs/gui.md`, both READMEs updated by owners and verified truthful this run;
website pages intentionally unchanged (older optional examples remain listed;
website scope is outside S8, per roadmap).
