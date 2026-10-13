# Intervention lifecycle

This document is the reference for the four intervention commands in
`work_runtime/runtime.py`: `request_cancel`, `finalize_cancel`,
`transfer_owner` and `migrate_policy`. They ride the ordinary command
protocol — compare-and-swap on `expected_version`, durable deduplication
under `(actor, command_id)`, immutable receipts and the append-only event
history — and their machine-level guarantees (dispatch, recovery,
reconciliation) live in
[runtime-boundaries.md](runtime-boundaries.md). Everything here is
trusted-local: principal names are configuration, **not authentication**.

## Commands at a glance

| command | exact payload | authority | event |
|---|---|---|---|
| `request_cancel` | `reason` (nonempty string) | current owner with `work.manage`, or `work.intervene` admin | `CancellationRequested` |
| `finalize_cancel` | `acknowledged_operations` (list of distinct nonempty operation ids) | same as `request_cancel` | `WorkCancelled` |
| `transfer_owner` | `owner`, `reason` (nonempty strings) | current owner with `work.manage`, or `work.intervene` admin; ownerless legacy works: admin only | `OwnerTransferred` |
| `migrate_policy` | `policy_id`, `policy_version`, `reason` (nonempty strings) | `work.intervene` admin exclusively | `PolicyMigrated` |

Payloads are exact: extra keys or wrong types raise `CommandError` (API
misuse) and persist nothing. Business refusals are persisted rejected
receipts. Every command is CAS-guarded (`STATE_VERSION_CONFLICT`) and
deduplicated: a replay under the original command id returns the stored
receipt **only while current authority holds** — a lost-authority replay
gets a fresh, unpersisted `AUTHORITY_DENIED` with the currently observed
state version, and the stored receipt is never modified.

## Authority model

- New Works store `owner = creator`. Management mutations
  (`bind_contract`, `revise_plan`, `revise_document`, `register_wait`,
  `request_completion`) require the current owner with `work.manage`;
  `propose_action` requires the current owner with the requested
  capability — a former owner's global grant does not keep this Work's
  execution rights, and `dispatch` holds intents whose actor is no longer
  the owner.
- Evidence intake is never owner-gated: writers keep their
  source-specific authority (`evidence.write` plus the kind's configured
  source identity).
- A `work.intervene` administrator may cancel, finalize and transfer
  without being the owner; only an administrator may migrate policy.
- Databases whose Works predate ownership keep **grant-only** behavior
  for the commands that existed then. No owner is ever guessed from
  historical receipts; ownership begins when an administrator adopts the
  Work through `transfer_owner`, and from then on the Work is
  owner-gated.

## Cancellation

`request_cancel` records an intent (`cancellation.requested_by` /
`reason`) inside the Work's own JSON, deliberately separate from
presentation status so evaluation, expiry, outcome resolution and
recovery can never clear it. On acceptance it cancels waiting/triggered
waits and every never-dispatched prepared intent (reason
`WORK_CANCELLED`); a prepared operation is never relabeled as an
external `confirmed_failed`, and original accepted receipts are never
rewritten. Establishing (unbound) works can be cancelled.

While the intent is active the Work stops: new waits, proposals and
re-admission, plan/document edits, binding, completion requests and
policy migration are rejected `CANCELLATION_ACTIVE`; a second cancel
under a new id is `CANCELLATION_ALREADY_REQUESTED` and cannot overwrite
the original intent. Evidence intake, the internal verifier, expiry and
reconciliation continue. An attempt already durable when cancellation
arrives remains uncertain until queried through the original operation
key — cancellation is an internal stop, not an external fence.

`finalize_cancel` is the only way to close a cancelled Work, and there is
no automatic close. It refuses while any operation is unresolved
(`OUTCOME_UNRESOLVED` — a missing or malformed lookup answer can never be
finalized past). Once every effect is resolved, the acknowledgement must
equal **exactly** the set of `confirmed_succeeded` operation ids — an
empty list is correct only when there were no succeeded effects — else
`CANCEL_ACKNOWLEDGEMENT_MISMATCH` with the succeeded ids as blockers. An
accepted finalize closes the Work as `cancelled` (never `succeeded`) and
stores an immutable closure snapshot: the original cancellation intent,
the acknowledged succeeded operations with their external ids, and every
operation's disposition.

**Acknowledgement is not compensation.** Closing as cancelled admits the
listed external effects exist and will not be reversed by this runtime;
effect reversal/compensation execution is deferred scope. Evidence
revocation (un-verifying an accepted proof outside policy migration) is
likewise not supported.

## Ownership transfer

`transfer_owner` moves accountability atomically: it persists actor,
previous/next owner and reason, reassigns outstanding `waiting`/`expired`
waits owned by the prior owner, and invalidates never-dispatched
prepared intents (reason `OWNERSHIP_TRANSFERRED`) so the new owner must
re-propose — the operation business key is retained, so re-proposal
re-admits the same operation identity. In-flight operations keep their
actor, key, attempts and results, and reconciliation never requires the
old execution authority. The target must exist in `grants` with
`work.manage` (otherwise `AUTHORITY_DENIED`); transferring to the
current owner is `TRANSFER_SAME_OWNER`. Transfer works while a
cancellation intent is active, never erases it, and grants no
capabilities. Receipt contents are never modified by a transfer.

## Policy registry and migration

`Runtime(path, policy, grants, *, policies=None)` takes an optional
registry of explicitly loaded versions of one policy family and goal
(validation contract and per-work resolution: see
[runtime-boundaries.md](runtime-boundaries.md)). New works bind the
default version; every existing Work resolves its pinned version from
the registry, and a missing pinned version fails closed.

`migrate_policy` rebinds a bound, open, uncancelled Work to another
registered same-family version — exclusively on administrator command.
Refused before any mutation: another family
(`MIGRATION_FAMILY_MISMATCH`), unregistered version
(`MIGRATION_TARGET_UNREGISTERED`), the unchanged current version
(`MIGRATION_TARGET_UNCHANGED`), and any dispatched/unknown effect
(`OUTCOME_UNRESOLVED`). The target must validate the current document
(its `ValueError` becomes `CommandError`; nothing persists). The rebind
is one transaction: contract revision increments, every verified proof is
revalidated under the target (source match plus target verifier, else it
becomes `invalid` — invalid never resurrects, pending stays pending and
an old-source pending proof can never reappear verified), prepared
intents and waits are cancelled (`POLICY_MIGRATED`), requirements are
re-evaluated by the target, and dispositions are recorded. Any failure —
including a target evaluation or verifier exception — rolls back
binding, evidence, operations and events together. Old receipts and
external results are retained; restart never implicitly migrates in
either direction.

The published example family demonstrates this: `ExpensePolicy`
(`demo-1`) requires approval only over limit, while
`work_runtime.policy.ExpamplePolicyV2`... `ExpensePolicyV2` (`demo-2`,
same id/goal/capability/business key) requires version-bound approval
(`digest` + `policy_version: demo-2`) for **every** known amount.
Migrating a low-amount Work from `demo-1` to `demo-2` therefore turns a
previously satisfied submission back into a blocked one until new-shape
approval arrives — the runnable pin of evidence revalidation.

## Rejection codes

New in this slice: `CANCELLATION_ALREADY_REQUESTED`,
`CANCELLATION_NOT_REQUESTED`, `CANCEL_ACKNOWLEDGEMENT_MISMATCH`,
`CANCELLATION_ACTIVE`, `TRANSFER_SAME_OWNER`,
`MIGRATION_TARGET_UNCHANGED`, `MIGRATION_TARGET_UNREGISTERED`,
`MIGRATION_FAMILY_MISMATCH`. Reused from the core protocol:
`AUTHORITY_DENIED`, `WORK_NOT_ACTIONABLE`, `OUTCOME_UNRESOLVED`,
`CONTRACT_NOT_ACTIVE`, `COMMAND_UNSUPPORTED`, `COMMAND_ID_REUSED`,
`STATE_VERSION_CONFLICT` and the contract/plan/scope revision codes.

## Limits (honest boundaries)

- No compensation or reversal execution; acknowledgement records effects,
  it does not undo them.
- No evidence revocation status; proof invalidation exists only through
  policy migration revalidation.
- One coordinator, local process, no distributed leases or fencing; an
  in-flight external call cannot be revoked.
- One policy family per database; cross-domain registries are rejected.
- Local trusted principals only — no tenant authentication, no
  multi-tenant service surface. Deferred items are tracked on the public
  roadmap.

The behavior tables these contracts summarize are pinned test-by-test in
`tests/test_interventions.py`.
