# S9 core development — evidence collision prevention and recovery — report

Worker: S9 CORE DEVELOPMENT (checkout `s9-evidence-collision-core`, carrier
`WayJ/sprint-s9-evidence-collision` tip `bcce865` asserted ancestor/clean at
start; branch `WayJ/s9-evidence-collision-core`). Date: 2026-10-15.
Scope honored: `work_runtime/runtime.py`, focused tests in
`tests/test_accepted_evidence_collision.py`, `docs/runtime-boundaries.md`
(same commit as each runtime change), current
`docs/verification.md`/`docs/interventions.md`/`docs/evidence-revocation.md`,
scoped plan and this report. No policy/adapters/schema/inspection/web/CLI/
demo/install/README/site/AGENTS/roadmap/sprint/acceptance/debt edits; no
merge, no push, no full-S9-release claim. TD-1 stays open for integration
to repay with the merge hash.

Plan: `docs/superpowers/plans/2026-10-15-s9-core.md` (committed `cd07042`
before implementation), executed with superpowers executing-plans + TDD;
ledger `.superpowers/sdd/2026-10-15-s9-core/progress.md` (workspace deleted
after final review per skill; rulings carried below).

## Commits

| commit | subject |
|---|---|
| `cd07042` | docs: scoped S9 evidence-collision core implementation plan |
| `267e1d3` | feat: reserve stored operation ids at accepted-source intake (S9 D39) |
| `1063542` | feat: resolve accepted-proof collisions with actual result and conflict snapshot (S9 D40/D41) |
| `5046f8a` | test: pin collision preservation and idempotence; docs: current boundary references (S9) |
| (this commit) | docs: S9 core development report with RED/GREEN and DoD evidence |

## Baseline

- `python3 -m unittest discover -s tests` at `bcce865`: **702 tests, OK
  (skipped=1)** — fresh run in this checkout before any change.
- Runtime change is confined to `_receive` (one reservation branch +
  `_reserved_accepted_sources` helper, per-intake union), `_resolve`
  (accepted-branch pre-check via `_proof_conflict`, conflict event swap,
  `_body_str` module helper). Schema stays `1`; stdlib-only; Python 3.9
  (the local interpreter) used throughout.

## RED → GREEN evidence (observed)

- **Task 1 — intake reservation (D39)**, 6 new tests RED on unmodified
  runtime (`267e1d3` parent): 5 expense + 1 publishing prevention tests
  failed with `'accepted' != 'rejected'` (or
  `'AUTHORITY_DENIED' != 'OPERATION_ID_RESERVED'` where the actor was
  unmapped) — the op-id imports were accepted. After the guard: 6/6 GREEN,
  suite **708 OK (skipped=1)**. Two test-side setup corrections against
  real behavior before GREEN (granted `oa3`; `bind_contract` binds only the
  default version, so the V2 work goes through admin `migrate_policy`).
- **Task 2 — legacy conflict resolution (D40/D41)**, 9 new tests RED
  (`test_legacy_poisoned_store_resolves_with_proof_conflict`,
  status-variants ×3 subtests, recover liveness, exception crash, lost
  response, closed-work guard, malformed bodies ×5 subtests, publishing
  mirror): 14 errored with the exact pre-fix failure
  `sqlite3.IntegrityError: UNIQUE constraint failed: evidence.source,
  evidence.event_id`; `test_conflict_resolution_real_process_death` failed
  `1 != 76` (the child died on that same IntegrityError before the
  injection point). After implementation: 15/15 GREEN. The **full suite**
  then exposed `UnboundLocalError: conflict` on the pre-existing
  malformed-receipt quarantine path (`conflict` initialized only inside the
  valid-receipt branch) — 14 existing boundary/publishing/intervention
  errors, fixed by hoisting the initialization; suite **717 OK
  (skipped=1)**. Legacy fixtures are direct-SQL canonical `_receive` rows
  from accepted original inputs, labelled; no product bypass.
- **Task 3 — preservation/idempotence pins**, 9 new tests GREEN after
  Tasks 1–2 with no further runtime change (two test-side corrections:
  satisfied requirements trigger waits at registration and re-trigger
  expired-but-satisfied waits later — only `cancelled` is terminal; the
  expirable wait moved to the poisoned work whose E08 stays unsatisfied).
  Suite **726 OK (skipped=1)** = 702 baseline + 24 new.

## What the 24 new tests pin

Prevention: `OPERATION_ID_RESERVED` persisted rejection with
`blockers=[operation_id]` after unchanged authority and old-row
dedup/`SOURCE_EVENT_CONFLICT` precedence; per-intake loaded-source union
(renamed accepted source across a migration, mutated live policy object,
missing-version fail-closed unchanged); global across works and kinds
(overlapping-mapping poison); unrelated sources and fresh imports valid;
publishing mirror. Recovery: actual `confirmed_succeeded`/`finished`/
`external_id`/existing attempt status with exactly one retained external
effect (`FakeOA.accepted_count()`/`FakePublisher.published_count()`); exact
nine-field `proof_conflict` (body strings null on missing/wrong-type/
non-object, SQL work_id/fingerprint verbatim, adapter `external_id` and op
`document_digest` — never candidate `data.digest`); eleven-field
`AcceptanceProofConflict` replacing `OperationResolved` on the conflict
path only; conflicting row byte-identical across
pending/verified/invalid/revoked/malformed variants; `needs_attention`
only when not closed (closed custom store keeps
status/outcome/completion, `work_was_closed: true`); crash atomicity via
exception injection and a real `os._exit(76)` child dying inside the
conflict transaction, rolled back and redone deterministically; lost
accepted response (`timeout_after_commit`) recovered exactly once;
`recover()` reaches later operations; repeated `recover()` is
operation-scoped idempotent (counting adapter: zero executes/lookups for
the settled op, other records still verify/expire — `EvidenceEvaluated`/
`WaitExpired` observed — and a later prepared op dispatches); replay
verbatim with fresh `AUTHORITY_DENIED` on authority loss; no new
completion blocker (verified conflicting import cited; unverified one
blocks on normal E08 requirements); replacement proof via new event;
`finalize_cancel` acknowledges the confirmed conflict effect with its real
external id; read-only inspector exposes the event and `proof_conflict`
with zero writes.

## DoD evidence (commands run 2026-10-15 in this checkout)

| item | command | observed |
|---|---|---|
| tests gate | `python3 -m unittest discover -s tests -v` | **Ran 726 tests … OK (skipped=1)** (702 baseline + 24 new; the single S5/S6-inherited skip unchanged) |
| contracts gate | `python3 scripts/check_docs.py` | **checked 90 markdown files, 344 local links, 0 broken** |
| demo gate | `python3 -m work_runtime demo` | real crash recovery, exactly one external application, prints durable-history inspect hint — OK |
| syntax gate | `python3 -m compileall -q work_runtime tests scripts` | exit 0 |
| site gate | `python3 scripts/check_site.py` | **checked 2 pages, 0 findings** |
| demo 2 | `python3 -m work_runtime publish-demo` | OK |
| demo 3 | `python3 -m work_runtime intervention-demo` | OK (transfer/cancel + migrate stores) |
| demo 4 | `python3 -m work_runtime adoption-demo` | OK (lint + file adapter, committed artifact) |
| demo 5 | `python3 -m work_runtime revocation-demo` | OK (both families, revoked statuses/fingerprints) |
| rehearsal | `python3 -m unittest examples.rehearsal.test_queue_adapter` | **Ran 14 tests … OK** |
| installed verifier | `python3 scripts/verify_install.py` | **=== PASS ===** (fresh venv, import origin inside venv, no third-party runtime deps, module+console demos/ui/revocation outside the checkout; installer unchanged, test-only use) |

No browser re-run: no UI change (generic event/raw surfaces already expose
the conflict; pinned read-only by
`test_inspector_exposes_conflict_read_only`).

## Remaining risks / handoff

- Valid-JSON-but-corrupt bodies degrade to null snapshots; a non-JSON
  evidence body aborts only that operation's resolution (rollback + retry)
  — repair explicitly out of scope per ratification; documented.
- The reservation is a conservative over-block by design (documented in
  `docs/runtime-boundaries.md`); synthetic-acceptance trusted-local
  boundary stated explicitly, not an authentication claim.
- Integration-owned next: independent static/public-API review, fresh
  complete scenario/gate evidence, ordinary main merge + non-force push,
  exact published SHA/CI, TD-1 tracker repayment citing the merge hash,
  and the full-S9 release claim. This worker claims none of those.
