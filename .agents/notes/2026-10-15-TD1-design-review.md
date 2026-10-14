# TD-1 design draft — builder feasibility review — 2026-10-15

Reviewer role: fresh-builder self-review of the candidate spec
[2026-10-15-td1-accepted-evidence-collision-design.md](../../docs/superpowers/specs/2026-10-15-td1-accepted-evidence-collision-design.md)
(no subagents; drafted and reviewed in one head, so this is a grounding
audit, not independence). Base: `a90ddc6` on `WayJ/next-core-recon` (asserted
clean). Inputs: the spec above, the [TD-1 row](../../docs/tech-debt-tracker.md),
the S8 [design review D-4](2026-10-14-S8-design-review.md), the post-S8
[recon](2026-10-15-next-core-recon.md), and the actual `runtime.py`,
`inspection.py`, `policy.py`, `publishing.py`, `ingress.py`, web assets and
runtime/revocation tests at this commit. Probes: the recon probe plus the
design-scope spike `/tmp/next-core-recon-2026-10-15/spike_td1_design_scope.py`
(throwaway, public API, temporary stores).

## Grounding audit — every load-bearing claim vs source

| spec claim | evidence at `a90ddc6` | holds |
|---|---|---|
| Evidence PK `(source, event_id)` is store-global | `runtime.py:107-110`; spike S1: colliding row stored against W1 blocked W2's INSERT | yes |
| `_receive` never consults operations; dedup precedes everything after authority | `runtime.py:657-682`; spike S3 (resend → current status; changed data → `SOURCE_EVENT_CONFLICT`) | yes |
| Collision requires source equality, not kind `accepted` | spike S2: colliding row written with kind `duplicate_clear` under a policy mapping that kind to the accepted-source actor | yes |
| `_resolve` INSERTs `(accepted_source, op id)` only on accepted results | `runtime.py:911-921`; rejected results take the no-INSERT path (`:922-923`) | yes |
| Every INSERT source ∈ loaded-registry accepted sources | `_accepted_source` → `_policy_for` resolves only loaded registry versions, fails closed otherwise (`runtime.py:161-175,804-809`) | yes — union predicate (§A1) is sound and complete |
| IntegrityError loop + stuck op + recover abort + starvation | recon probe §3; no test anywhere asserts the IntegrityError (grep clean), so changing it breaks no baseline | yes |
| P2a terminal early-return makes repeat reconcile/recover no-ops | `runtime.py:901-902` terminal guard; `reconcile` status guard `:876-877` | yes |
| `needs_attention` is sticky under later `_evaluate` | `runtime.py:197-199` (only completion/finalize set `closed` past it) | yes |
| One attempt guaranteed at `attempts[-1]` in `_resolve` | dispatch appends the attempt before execute (`runtime.py:852-855`); reconcile only reaches `_resolve` for dispatched/unknown ops | yes |
| Accepted source cannot change under an unresolved op | `migrate_policy` rejects `OUTCOME_UNRESOLVED` for dispatched/unknown ops (`runtime.py:563-567`) — no accepted-source race at resolution | yes |
| Conflict branch can reuse `_revoke`'s single-`_save` pattern | `runtime.py:729-760` computes diffs, one `_save` (one version bump, one event) | yes |
| Zero UI change for the new event type and op field | `inspection.py:243-257` passes event `type` through; `:204-215` `event_types` is a GROUP BY; operations DTO is an explicit allowlist **plus** `body_raw` raw passthrough (`:349-373`) so `proof_conflict` surfaces via raw JSON; web assets whitelist no event/field names (source scan) | yes |
| Crash idioms available for the atomicity test | `fault` injection points at `runtime.py:785,860-861`; real `os._exit` child pattern `tests/test_runtime.py:266,278` | yes |
| Legacy fixture can reproduce exact pre-fix row shape | row = 5 columns; fingerprint `digest([work_id, payload])`; body canonical candidate (`runtime.py:667,677-682`) — direct INSERT with accepted original inputs is faithful | yes |

## Implementability

Single product file touched (`work_runtime/runtime.py`); estimated diff:
precomputed accepted-source set in `__init__` (+2), reservation step in
`_receive` after the old-row branch (+~8), conflict pre-check and branch in
`_resolve`'s accepted path (+~20), no schema change (version stays `1`), no
new dependency, Python ≥3.9/stdlib unchanged. Doc obligation travels with the
file: `docs/runtime-boundaries.md` same commit (doc_sync_map). Test surface:
new named tests (~6 RED + preservation set) fit the existing unittest idiom;
the /tmp probe already demonstrated the RED behavior for spec tests 1, 2, 4
and 5 on the current runtime, so RED is proven reachable, not assumed.

## Risks and edges (all stated in the spec or acceptable)

- Union over-block (writer is an accepted source under one loaded version
  while the matched op belongs to a work with a different accepted source):
  conservative rejection of an operation-id import; documented trade for the
  predicate's completeness.
- Repeated distinct poisoning attempts persist one rejected receipt each —
  identical to any rejected command today; no write amplification.
- The synthetic row may sit `pending_verification` for a window and
  `verify_pending` may flip it either way before resolution; the conflict
  event snapshots the status at resolution and never mutates the row.
- `proof_conflict` on an operation does not reach the inspection DTO's
  allowlisted fields (only `body_raw`); a first-class DTO field would be a
  viewer change with DESIGN/browser obligations — correctly kept out of the
  minimal slice (candidate follow-up, master's call).
- Completion on a verified synthetic acceptance remains possible — the
  pre-existing trusted-local boundary; the design surfaces rather than
  removes it (decision D6 offers the stronger gate).

## Verdict

Implementable exactly as drafted at this commit: bounded single-file product
diff, additive JSON only, no baseline test depends on the broken behavior,
RED/GREEN reachable with the repo's existing idioms, and the master's
permanence constraints are structurally satisfiable (nothing deleted,
converted or fabricated). The design is **not** complete until the master
rules D1–D10 (spec §9) — the load-bearing ones being D1 (P2a vs P1) and D2
(predicate variant). Nothing in this note or the spec is a ratified
implementation instruction.
