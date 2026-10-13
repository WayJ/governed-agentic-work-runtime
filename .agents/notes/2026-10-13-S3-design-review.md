# S3 intervention design review (independent builder check)

Reviewer: s3-release-control worktree (WayJ/s3-release-control @ 2e2774d); carrier spec diffed identical
to local `docs/superpowers/specs/2026-10-13-s3-intervention-design.md`. Carrier sprint/epic read at
19ce3bb. Baseline reproduced: **172 tests pass** (`python3 -m unittest discover -s tests`), matching the
design's "all172". Read-only review; no product/spec/roadmap edits.

## Verdict

**Implementable** on the existing engine (single `_transaction`, command dedup, prepared-intent
invalidation, quarantine, CAS). No protocol redesign required. Two localized items need master
ratification before code (B1, B2); everything else is a bounded builder choice settled below.

## Blocking decisions (ratify in design/ADR)

- **B1 — `request_cancel` collides with an existing test expectation.**
  `tests/test_runtime.py:326-328` uses `request_cancel` as its unsupported-kind probe and asserts
  `COMMAND_UNSUPPORTED`. Once `request_cancel` is a real kind this breaks — with the empty payload it
  would raise `CommandError` (payload must be exactly `{reason}`), not return a receipt. "Preserve all
  172 tests, no edits to existing test expectations" is unsatisfiable as written. Proposal: amend that
  single test to probe a permanently unsupported kind (e.g. `request_refund`), keeping the assertion and
  the 172 count — an intent-preserving amendment under the design's own "tested safety need" clause.
- **B2 — replay invariant wording in `docs/runtime-boundaries.md:26`.**
  The doc pins "replays return the original receipt verbatim"; the ownership section requires
  re-checking authorization before replay. Ratify the amended invariant: *replays return the original
  receipt verbatim when current authority holds; when authority was lost, replay returns a fresh,
  unpersisted `AUTHORITY_DENIED` and the stored receipt is never modified.* `runtime-boundaries.md` is
  already owed same-commit via doc_sync_map, so no new obligation — but the wording change is a
  documented-boundary amendment and needs explicit sign-off.

## Settled bounded proposals

### 1. Constructor registry — exact signature and validation

```python
class Runtime:
    def __init__(self, path: str, policy: Policy, grants: Dict[str, set],
                 *, policies: Optional[Dict[str, Policy]] = None):
```

Keyword-only 4th parameter; every existing call site is 3-positional (`grep Runtime(` across
work_runtime/tests/scripts: all positional), so defaults stay compatible. Semantics:

- `policies is None` → `self._policies = {policy.version: policy}` (legacy behavior preserved:
  `test_policy_migration_is_not_implicit` at `tests/test_runtime.py:287-292` still raises
  `CommandError` for a foreign pinned version).
- Validation **before any DB write** (before `mkdir`/`executescript`), raising `CommandError`:
  dict; nonempty-str keys; each value structurally a `Policy` (id/version/goal nonempty str,
  `evidence_sources` dict, the five methods); `value.version == key`; `value.id == policy.id`
  (same family) and `value.goal == policy.goal`; `policies[policy.version] is policy` (identity —
  the default that new works bind to must be resolvable).
- Per-work resolution helper replacing the `self.policy` uses at work scope:
  `_policy_for(work)` → bound `self._policies[work["contract"]["policy_version"]]` (raise the
  existing "migration is not implicit" `CommandError` on mismatch/missing, i.e. today's
  `runtime.py:111-112` check generalized), else `self.policy` for unbound works. Call sites to
  convert: `_evaluate` (120), `revise_document` validate (264), `_propose` blockers/key (325, 336),
  `_receive` sources (365), `verify_pending` verifier (389), `dispatch` blockers (435), and
  `_accepted_source` (414) becomes `_accepted_source_for(work)` (used at 442, 477, 510).
  `get_work` keeps returning the work dict (public API unchanged).
- Registry is constructor state, **not persisted**; no schema change (`schema_version` stays "1";
  new state lives in the `works.state` JSON: `owner`, `cancellation`, `closure`, `migration`).

### 2. Migration evidence handling — exact dispositions

Inside one `_transaction`, after authority/payload checks and **before** any mutation:
`target.validate_document(work["document"])` (failure raises `CommandError`, matching
`_create`/`revise_document` precedent). Then per stored evidence row of the work:

Provenance rule (master constraint): revalidation checks **two** things for every kind — the target
verifier (`target.validate_evidence` checks shape only) and the explicit source mapping
`target.evidence_sources.get(kind) == candidate.source` — because shape alone does not adopt
authority. Old verified identity/history is preserved; wrong source or verifier failure → `invalid`.

| status today | kind | disposition under target |
|---|---|---|
| `pending_verification` | any | stays `pending_verification` (target verifier runs later via `verify_pending`; applying the same source-mapping check at that point is the builder's bounded choice — recommended for consistency) |
| `verified` | any | `verified` iff `target.validate_evidence` passes **and** `target.evidence_sources.get(kind) == candidate.source`, else `invalid` (covers `accepted` effect proofs and all business kinds alike) |
| `invalid` | any | stays `invalid` — no resurrection (no `revoked` status exists in code; out of scope) |

Then atomically: swap binding (`policy_id`/`policy_version`/`goal` from target,
`revision = old + 1`), cancel prepared intents (reason `POLICY_MIGRATED`) and waits, `_save` with
target policy (recomputes requirements), record old/new binding + actor/reason + per-evidence
dispositions in event and `work["migration"]`. Operations with status `dispatched`/`outcome_unknown`
reject up front with `OUTCOME_UNRESOLVED` (reuse). Confirmed operations, receipts and `external_id`s
are retained untouched. Rollback evidence: test via a target policy whose `evaluate`/`validate_evidence`
raises mid-migration (public surface; no new fault plumbing — commands cannot carry `fault`).

### 3. Bounded error-code table (new codes only; reuse otherwise)

New rejected-codes (8): `CANCELLATION_ALREADY_REQUESTED`, `CANCELLATION_NOT_REQUESTED`,
`CANCEL_ACKNOWLEDGEMENT_MISMATCH`, `CANCELLATION_ACTIVE`, `TRANSFER_SAME_OWNER`,
`MIGRATION_TARGET_UNCHANGED`, `MIGRATION_TARGET_UNREGISTERED`, `MIGRATION_FAMILY_MISMATCH`.
New prepared-op reasons (3): `WORK_CANCELLED`, `POLICY_MIGRATED`, `OWNERSHIP_TRANSFERRED`
(`STALE_INTENT` stays for plan/document revision). Reused as-is: `AUTHORITY_DENIED`
(owner/capability/target-qualification/replay loss), `WORK_NOT_ACTIONABLE` (closed work),
`OUTCOME_UNRESOLVED` (finalize + migration in-flight), `CONTRACT_NOT_ACTIVE` (migrating an
establishing work), `COMMAND_UNSUPPORTED`, `COMMAND_ID_REUSED`. Malformed payloads
(`request_cancel`/`finalize_cancel`/`transfer_owner`/`migrate_policy` shapes) raise `CommandError`,
matching the existing raise style (`runtime.py:256-257, 274-277, 360-364`).

### 4. Replay: unchanged historical receipts vs current authority

Keep `request_hash`/dedup exactly as-is (`runtime.py:187-192`); after fingerprint match and before
returning the stored receipt, recompute authority for protected kinds: `create_work` → `work.manage`;
`record_evidence` → actor still holds the source identity for that kind plus `evidence.write`;
`propose_action` → current owner (when set) plus capability; other management kinds → current owner
with `work.manage` or `work.intervene` admin where the design allows it. Failure returns a fresh,
**unpersisted** `AUTHORITY_DENIED` with the current `observed_state_version`; the stored receipt is
never modified, so a later re-authorized replay still gets the original. Ownerless legacy works skip
owner checks entirely (grant-only, today's behavior). Existing replay tests stay green: the actors
retain authority in all of them (`test_rejected_command_replay_remains_rejected`,
`test_boundaries.py:266-267`).

## Named boundary questions — findings

- **Unchanged historical receipts vs pre-replay current authority** — compatible once B2 wording is
  ratified; see proposal 4. Receipt immutability is structural (receipts written once at
  `runtime.py:207-209`; replay only reads).
- **Closed-work evidence/verify behavior** — current semantics: `record_evidence` is exempt from the
  closed check by ordering (`runtime.py:199-205`), `verify_pending` runs on closed works, status stays
  `closed`, `completion` snapshot immutable — pinned by `test_late_event_does_not_reopen_closed_work`
  (`tests/test_runtime.py:300-309`). Preserve and document; new management kinds route through the
  existing closed check → `WORK_NOT_ACTIONABLE`; replay dedup precedes actionability, so a replayed
  `finalize_cancel` after close still returns its stored receipt.
- **Prepared operations cancelled without external failure** — machinery exists and is tested
  (`_cancel_prepared` `runtime.py:304-310`; dispatch early-returns for cancelled dispatch_state
  `runtime.py:425-426`; `recover` skips them `runtime.py:539`;
  `test_document_revision_cancels_unstarted_intent` asserts zero OA calls). `request_cancel` reuses it
  with reason `WORK_CANCELLED`; it also covers `held` intents (filter is `status == "prepared"`).
  Dispatched/outcome-unknown ops are never relabelled — they stay queryable/reconcilable via the
  original key (reconciliation needs no execution authority, `runtime.py:473-495`). Dispatch boundary
  (master constraint): once `AttemptStarted` is durable (`runtime.py:451-454`), cancellation cannot
  retroactively prevent that attempt — such operations must reconcile before `finalize_cancel`; the
  runtime claims no external fencing of in-flight calls.
- **Cancellation flag surviving `_evaluate`/reconciliation** — store intent as a dedicated
  `work["cancellation"] = {actor, reason, requested_state_version}` field, never as status.
  `_evaluate` rewrites only `requirements` and `status` (`runtime.py:119-133`); `verify_pending`,
  `expire_waits`, `_resolve`, `reconcile` touch evidence/waits/status only — none can clear a separate
  field, and the only writers are `request_cancel`/`finalize_cancel`. This is why the design's
  "distinct from presentation status" is load-bearing: encoding it in `status` would be clobbered by
  `_save`→`_evaluate` on every subsequent event. `request_completion` during intent → `CANCELLATION_ACTIVE`;
  cancelled prepared ops already drop out of its unresolved scan (`dispatch_state != "cancelled"`,
  `runtime.py:288-289`). Establishing-work cancellation works if the new kinds are handled before the
  `not work["contract"]` guard (`runtime.py:252-253`).
- **Multiple same-family pinned versions and adapter routing** — per-work policy resolution
  (proposal 1) is the only runtime change; adapter selection stays caller-side per `dispatch` call (no
  version-keyed routing, per "no cross-domain routing redesign"). One `FakeOA` serves both demo
  versions iff v2 keeps the capability name `expense.submit` (its contract declares exactly that
  action). Operation-key stability across migration holds by construction for the demo family because
  `operation_key` digests `[policy.id, capability, document.id, document_revision]`
  (`policy.py:136-138`) and `policy.id` is the family constant — but it is a policy-author obligation
  the runtime cannot enforce; the migration test must pin it.
- **Operation contract revision / re-admission** — three concrete gaps, all fixable in wave 1:
  new ops hardcode `"contract_revision": 1` (`runtime.py:353`); re-admission updates actor/plan
  revision but not contract revision (`runtime.py:342-346`); `dispatch` never compares the op's
  contract revision to the work's (`runtime.py:428-429` checks digest and plan revision only).
  Fix: store `work["contract"]["revision"]`; refresh it on re-admission; dispatch treats a mismatch
  like plan staleness (cancelled/`STALE_INTENT`). Proposal admission already CASes the current
  revision (`runtime.py:316-317`). Existing rows carry revision 1 == work revision 1, so old data is
  compatible.
- **Legacy DBs without owner** — gate every new ownership check on `work.get("owner")`; unset keeps
  grant-only behavior (publishing/ingress flows are actor-`agent`-managed or evidence-only, so the
  172 stay green). Adoption only via `transfer_owner` by a `work.intervene` admin; never infer owners
  from receipt shapes; no backfill.

## Inspection / demo v2 registry path (coordinator follow-up)

`python3 -m work_runtime inspect` builds a single-policy runtime (`cli.py:35-39`), so a migrated v2
work fails closed with the existing `CommandError` — which *is* the no-implicit-upgrade property.
Smallest compatible path: wave 1 publishes an illustrative same-family `ExpensePolicyV2` in
`work_runtime/policy.py` (`version = "demo-2"`, same id/goal/capability/`operation_key`, strengthened
`evaluate` only — no new module, no doc-map impact); wave 3 adds an opt-in inspect flag (e.g.
`--policy-versions demo-1,demo-2`) that constructs the explicit registry, default behavior unchanged.
The intervention demo and installed `verify_install.py` use the same explicit registry. Old receipts
and accepted-effect identity are untouched by construction (migration never rewrites commands,
operations or external results).

## Minor choices left to the builder (no ratification needed)

`register_wait`/`record_evidence` remain allowed during cancellation (not in the design's prohibited
list; harmless — completion is blocked first). Wait cancel reuses `revise_document`'s
`waiting→cancelled` shape (`runtime.py:270`). `finalize_cancel` stores the closure record
(`acknowledged_operations`, `external_ids`, per-op dispositions) in `work["closure"]`; close sets
`outcome = "cancelled"`, never `succeeded`, no reversal claims. Transfer invalidates prepared intents
(reason `OWNERSHIP_TRANSFERRED`) and reassigns waiting/expired waits; in-flight ops untouched;
same-owner rejected `TRANSFER_SAME_OWNER`; unqualified target → `AUTHORITY_DENIED`.
