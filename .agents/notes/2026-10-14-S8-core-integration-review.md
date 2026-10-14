# S8 Task2 core integration review — PASS, assembled — 2026-10-14/15

Independent Orca integration acceptance of the S8 revocation core, distinct
from the owner's internal fresh-context review recorded in
[the core report](2026-10-14-S8-core-report.md). Reviewer checkout:
`s8-release-control` (control branch `WayJ/s8-release-control`, base carrier
`7282c25`). No product files were modified by this review; probe scripts ran
from `/tmp/s8-integration-probe/` outside the checkout.

## Scope and source

- Accepted source: owner branch `WayJ/s8-revocation-core` tip `a1680a7`,
  merge-base with control = `7282c25` (verified), **8 scoped commits
  inclusive of `1188afe`** (7 in the exclusive range `1188afe..a1680a7`,
  matching the owner's commit table).
- Changed files (name-status verified): `work_runtime/runtime.py` (+103/−16),
  `tests/test_evidence_revocation.py` (new, 55 tests),
  `tests/test_interventions.py` (+2 D-1 tests), docs only
  (`evidence-revocation.md` new, `runtime-boundaries.md`, `interventions.md`,
  `verification.md`, task1 plan) plus the core report note.
  **No schema/policy/adapters/inspection/CLI/web/README changes; D37
  read-only surfaces untouched; TD-1 unchanged and open.**
- Assembly: `git merge --no-ff a1680a7` → control merge commit `7b22f0e`.

## Static review against FULL MASTER D33–D37 (spec
[2026-10-14-s8-evidence-revocation-design.md](../../docs/superpowers/specs/2026-10-14-s8-evidence-revocation-design.md))

- **D33**: payload exactly `{source,event_id,reason}` nonempty strings, else
  `CommandError` inside the transaction (rollback verified);
  version-bound envelope (`STATE_VERSION_CONFLICT` before handler);
  routing beside `record_evidence` ahead of the closed guard; two-phase
  order preliminary (admin, or `evidence.revoke`+current-source membership)
  → lookup (`EVIDENCE_UNKNOWN` → `EVIDENCE_SCOPE_MISMATCH`) → exact
  stored-kind authority → status codes; `command()` rejects unregistered
  actors before handlers, so `_revoke_authority`'s grants index is safe.
  Replay branch re-authorizes cached receipts (accepted and rejected) with
  fresh unpersisted `AUTHORITY_DENIED` on lost grant/source/admin; cached
  `EVIDENCE_UNKNOWN` receipts keep the preliminary check (the `a1680a7`
  fix) and never acquire mutation rights from a later row.
- **D34**: `_evaluate` unbound closed guard implements the master ruling
  (unbound correction allowed, D-1 fixed — not the review's
  `CONTRACT_NOT_ACTIVE` restriction); revoke is one transaction: status
  flip preserving id/source/event/kind/data/fingerprint, one version bump,
  one `EvidenceRevoked` event with exactly the 11 ratified fields and
  actual before/after `affected_requirements`/`wait_dispositions`;
  completion untouched.
- **D35**: no eager wait/operation mutation in revoke; holds surface only
  at next dispatch/recover (`REQUIREMENT_UNSATISFIED`); cancelled waits
  skipped by the evaluator (no resurrection); no deadline resets.
- **D36**: `verify_pending` selects only `pending_verification`;
  `_migrate_policy` revalidates only `verified` (revoked→revoked
  disposition); `_receive` dedup adds current `evidence_status` additively
  while original cached receipts stay verbatim; changed content stays
  `SOURCE_EVENT_CONFLICT`.
- **D37**: not in this slice's scope by design — reader/GUI fields remain
  for the client owners; nothing here persists derived annotations.
- Doc-sync owed by `work_runtime/runtime.py` → `runtime-boundaries.md` is
  paid (new "Evidence revocation boundary" section + migration/immutability
  updates, cross-checked against observed behavior). All test names cited
  in `docs/evidence-revocation.md` exist in the test files.

## Fresh verification (commands run on assembled control tree)

| gate | command | actual result |
|---|---|---|
| tests | `python3 -m unittest discover -s tests` | **Ran 679 tests … OK (skipped=1)** — matches the owner's claim; baseline 622 at `7282c25` derives arithmetically (−57 new) and `c324357..7282c25` is docs-only over the S7-verified tree |
| contracts | `python3 scripts/check_docs.py` | checked **78** markdown files, 299 local links, **0 broken** (owner report said 79 files — their worktree's untracked `.superpowers` SDD ledger; same links/broken) |
| demo | `python3 -m work_runtime demo` | exit 0 (real crash recovery) |
| syntax | `python3 -m compileall -q work_runtime tests scripts` | clean |
| site | `python3 scripts/check_site.py` | 2 pages, 0 findings |
| prior demos | `publish-demo`, `intervention-demo`, `adoption-demo` | all exit 0; `revocation-demo` correctly absent (Task3 owner) |

## Independent probes (my own, public API only; stored truth via sqlite + adapter counts)

`S8_REPO=<checkout> python3 -I /tmp/s8-integration-probe/probe.py` →
**49 checks, 49 passed, 0 failed** (three earlier probe-side bugs were mine:
wrong-actor grants for the malformed/code checks, two method-receiver
mixups, a random-vs-fixed approval event id; no product behavior changed
any finding). Coverage:

- Receipt shape exact; +1 version/command/event atomicity; identity,
  fingerprint and work binding preserved; admin and current-source paths;
  owner/`work.manage`/`evidence.write`-alone and unregistered-actor denial.
- Malformed (6 shapes) raise and persist nothing; stale version; codes
  unknown/scope-mismatch/already-revoked/not-revocable.
- Unbound revoke accepted and during active cancellation (master ruling).
- Replay verbatim with zero writes; `COMMAND_ID_REUSED`; lost
  `evidence.revoke`/admin-grant/source-retirement each yield fresh
  `AUTHORITY_DENIED` with immutable stored receipts and unchanged tables;
  old-source pending candidate correctable by the new configured source.
- Cached `EVIDENCE_UNKNOWN` rejection replays verbatim after the row
  appears (preliminary-check semantics; the requester-recorded confirmation
  would have failed the exact stored-kind check) and denies freshly on
  authority loss.
- Permanence: revoked pending never verifies; restart+recover keeps
  revoked with reacted requirements; migration records revoked→revoked;
  new-command resend reports current `evidence_status:"revoked"` while the
  original `record_evidence` receipt replays verbatim; changed content
  conflicts; replacement proof restores the rule.
- Closure byte equality (canonical completion JSON, before/after): bound
  successful, bound cancelled, unbound cancelled (D-1: finalize persists
  `closed`; revoke accepted; late verify/recover keep it closed); history
  append-only (prefix + exactly one `EvidenceRevoked`).
- Event has exactly the 11 ratified fields with actual prior status;
  affected-requirements diff only the real change; triggered wait unchanged
  with intact deadline; cancelled wait terminal; expired wait keeps state
  and sticky `needs_attention`; partial revocation (second sufficient
  proof) changes nothing; unrelated waiting wait untouched.
- Effects: prepared intent held at dispatch and at recover with zero
  attempts and zero adapter receipts/acceptances; replacement readmits the
  same operation id with exactly one accepted effect and
  `OperationReadmitted`; proposal/completion blocked with named blockers
  while the confirmed effect is retained; in-flight unknown reconciles once
  with retained `OA-` external id; confirmed operation never re-executes
  (accepted_count stays 1, one evidence row, revoked accepted proof).
- Real crashes: injected `_save` exception and a child dying
  `os._exit(75)` inside the revoke transaction — full five-table snapshot
  equality, retry then succeeds; external-effect worker death (exit 73)
  then revoke+recover — exactly one retained effect, confirmed op, revoked
  approval.
- Publishing family mirrored: admission blocked (`C02`), zero published
  artifacts under hold, closed correction preserves completion.

## Findings

**No material findings; PASS.** Reconciliation notes only (no owner
correction required): the 78-vs-79 check_docs file count above; the
master's "8 commits" is inclusive-of-base notation; the owner's already
deferred cosmetic `_receive` double-parse remains for a future owner.

## Carrier and public interfaces for the parallel client owners

- Carrier `WayJ/sprint-s8-revocation` fast-forwarded to the control tip
  (exact SHA recorded in the worker report; contains `a1680a7` + merge +
  this note). No main/root merge, push, acceptance-ledger flip, or sprint
  state change — final S8 acceptance waits for demo/viewer completion and
  a fresh final review.
- Public surface (stable for Task3/Task4): command
  `Runtime.command(actor, command_id, work_id, "revoke_evidence",
  {source, event_id, reason}, expected_version)`; accepted receipt
  `{command_id, decision, result_state_version, evidence_id,
  evidence_status:"revoked", prior_status}`; codes `EVIDENCE_UNKNOWN`,
  `EVIDENCE_SCOPE_MISMATCH`, `EVIDENCE_ALREADY_REVOKED`,
  `EVIDENCE_NOT_REVOKABLE`, `AUTHORITY_DENIED`, `STATE_VERSION_CONFLICT`
  (+ envelope `COMMAND_ID_REUSED`); event `EvidenceRevoked` with the eleven
  fields above; `record_evidence` dedup receipts add `evidence_status`.
  D37 reader/DTO fields are **not** implemented yet (viewer owner scope).

## Risks / limits (unchanged, truthful)

TD-1 (D-4 accepted-source event-id collision) deferred with open status;
no compensation, authentication, distributed fencing, in-flight external
call revocation or key rotation is implemented or claimed; pre-existing
erroneous unbound-finalize snapshots are not rewritten retroactively
(documented limit); decision codes reveal row existence — never status —
to actors passing the preliminary check.
