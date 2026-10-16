# S14 beyond-window compensation design reconnaissance — 2026-10-16 (post-S13)

## Scope and evidence

Master-authorized S14 design/reconnaissance for the roadmap 0.3 open item
"compensation beyond the bounded S10 window (publishing, post-closure,
chains)". **Design only — no implementation, no product/test/UI changes, no
dependencies, no merges/pushes, no extra workers.** The only repo writes from
this dispatch are the candidate DRAFT spec
[2026-10-16-beyond-window-compensation-design.md](../../docs/superpowers/specs/2026-10-16-beyond-window-compensation-design.md)
(pending master ratification + the independent design review the master
dispatches next) and this note. No roadmap, sprint, acceptance, ADR or
tech-debt ledger mutation was made; the master owns those. External fencing
and distributed guarantees stay out (AGENTS working agreement).

Fresh worktree asserted at published main
`678d7b48e844ee153325239259064eab9b806df3` (`git rev-parse HEAD` = the
task's named baseline, branch `WayJ/s14-compensation-design`,
`git status --porcelain` empty before this note). Baseline battery on this
tree: **`Ran 1015 tests … OK (skipped=3)`**. Sources read as truth:
[AGENTS.md](../../AGENTS.md) (working agreement incl. supervibe gates +
doc_sync_map),
[roadmap.md](../../docs/roadmap.md) 0.3 (lines 33: the open item, verbatim:
"compensation beyond that bounded window (publishing, post-closure, chains),
external fencing of in-flight calls and distributed guarantees remain open"),
[interventions.md](../../docs/interventions.md) (S10 compensation exception,
lines 73-128; limits 198-217),
[verification.md](../../docs/verification.md) (S10 coverage 191-235; bounded
compensation limit 571-580), [runtime-boundaries.md](../../docs/runtime-boundaries.md)
(compensation boundary section, lines 45-260), [tech-debt-tracker.md](../../docs/tech-debt-tracker.md)
(TD-1 repaid, no open rows), the S10 design spec
([v1/v2/v2.1 incl. MASTER §15 D43-D48](../../docs/superpowers/specs/2026-10-15-compensation-execution-design.md)),
the [S10 acceptance record](../../docs/superpowers/acceptances/2026-10-15-S10-acceptance.md)
and [S10 close note](2026-10-15-S10-close.md) (lessons + handover list), and
the actual sources at this SHA: `work_runtime/runtime.py`, `policy.py`,
`adapters.py`, `publishing.py`, `publishing_demo.py`,
`adapter_contract.py`, `ingress.py`, `tests/adapter_conformance.py`
(inventory + naming). Historical `idea.md` / `上一次建议.md` not consulted
(historical source material per AGENTS). Probes (§2) ran from
`/tmp/s14-recon/probe.py` against the public API with ephemeral synthetic
stores; two deterministic runs, **21/21 checks each**; probe stores are
throwaway under `/tmp` and the worktree re-asserted clean after.

## 1. Code-level findings (all line numbers at `678d7b48e844ee153325239259064eab9b806df3`)

### The S10 window machinery as shipped

- **F1 (window predicate).** `_propose` splits on payload variant: forward
  payloads reject `CANCELLATION_ACTIVE` under an active intent
  (`work_runtime/runtime.py:645-647`); the linked compensation variant
  instead **requires** the intent (`CANCELLATION_NOT_REQUESTED` otherwise,
  `runtime.py:648-652`), the gate sitting before the business-key branch so
  it covers fresh proposals AND re-admission. Authority is the current owner
  holding the compensating capability grant (`runtime.py:639-644`).
- **F2 (the window predicate does not know "closed" — post-closure
  landmine).** The cancellation intent object is never removed from the Work
  JSON: `finalize_cancel` copies it into the closure snapshot
  (`runtime.py:532-538`) and never pops `work["cancellation"]`; probe P-B1
  shows it present on the closed work. What actually excludes closed works is
  the `command()` dispatch gate: every kind except `create_work`,
  `record_evidence` and `revoke_evidence` is rejected `WORK_NOT_ACTIONABLE`
  on a closed work (`runtime.py:281-286`). **Consequence:** merely relaxing
  the closed-work gate would make the existing window check *silently pass*
  on closed-cancelled works — a post-closure design needs its own explicit
  predicate, not a gate deletion.
- **F3 (post-closure collisions, probed).** Post-closure linked and forward
  proposals both reject `WORK_NOT_ACTIONABLE` (P-B2/P-B3);
  `record_evidence` remains admissible on the closed work (P-B4 — the S8
  precedent: `_revoke` also runs on closed works and records
  `work_was_closed` without reopening, `runtime.py:283-284, 819-883`).
  `dispatch` cancels `STALE_INTENT` when `work["status"] == "closed"`
  (`runtime.py:1011-1018`). `finalize_cancel` can never run again (closed →
  the F2 gate), and the closure snapshot (`completion` JSON,
  `runtime.py:532-538`) is written once and never rewritten — so a
  post-closure compensation cannot join `operation_dispositions` without new
  amendment semantics, and **nothing blocks on it**: the
  unresolved-compensation-blocks-finalize safety (`runtime.py:504-510`)
  only exists because finalize has not happened yet.
- **F4 (family-agnosticism is real — probe-proven end to end).** With a
  probe-only `PublishingPolicy` subclass adding
  `compensation_capabilities = {"content.unpublish": "content.publish"}` and
  the paired-capability `action_blockers` branch (the exact S10
  `policy.py:133-139` shape), plus a probe adapter with
  `supports_action_context=True`, the **unmodified runtime** performs the
  whole publishing-family pipeline (P-A2..P-A16): linked proposal admitted
  with the immutable `{operation_id, external_id, capability}` snapshot;
  business key exactly `digest(["content-publish", "content.unpublish",
  target_op_id])` distinct from the forward key; replay under a new command
  id returns the same operation; chains refused `COMPENSATION_TARGET_INVALID`
  (P-A6; `runtime.py:740-743` admission, `runtime.py:1087-1093`
  dispatch-revalidation); forward-only `FakePublisher` holds
  `ADAPTER_ACTION_UNSUPPORTED` (P-A7), an action-declaring-but-not-opted-in
  contract holds `ADAPTER_ACTION_CONTEXT_UNSUPPORTED` (P-A8); the opted-in
  adapter receives explicit `action`/`compensates` kwargs (P-A10);
  resolution stores the full receipt as `adapter_result`; the `withdrawn`
  proof is appended at the family's accepted source `"publisher"` with
  `original_external_id` (P-A12; `runtime.py:946-960`); C04 stays satisfied
  by the forward accepted proof — the withdrawn kind never matches
  (`publishing.py:60-91` kind-literal `has()`) — P-A13; `finalize_cancel`
  accepts the exact original+retraction ack with the compensation
  disposition carrying `compensates` + `adapter_result` and both external
  ids in the closure (P-A14..P-A16).
- **F5 (today's publishing gap is exactly two policy attributes + one
  adapter opt-in).** `PublishingPolicy` declares no
  `compensation_capabilities` (`publishing.py:21-36`) and its
  `action_blockers` returns `CAPABILITY_UNSUPPORTED` for every capability
  except `content.publish` (`publishing.py:94-100`), so a linked
  `content.unpublish` proposal is rejected today `REQUIREMENT_UNSATISFIED`
  with the `CAPABILITY_UNSUPPORTED` blocker (P-D1 — note the pairing arm in
  `_validated_link` skips when the policy has no pairing, so the refusal
  surfaces at the blockers step). `FakePublisher`'s contract is forward-only
  without the context opt-in (`publishing.py:117-122`), its `execute` takes
  exactly three positional arguments (`publishing.py:141`), and its store is
  `receipts` (3 columns) + `publications(document_id, digest)` with
  same-content dedup reusing the external id (`publishing.py:130-166`).
- **F6 (conformance skips auto-activate on opt-in).** The generic opt-in
  conformance test skips adapters whose contract lacks
  `supports_action_context` (`tests/adapter_conformance.py:75-86`); the S10
  acceptance recorded exactly two such designed skips
  (`FakePublisher`/`FilePublisher` conformance). Opting `FakePublisher` in
  turns its skip into an active test with no mixin change.
- **F7 (withdrawn-proof lifecycle is family-agnostic and closed).** No
  policy maps a `"withdrawn"` source, so imports are denied for every actor
  (`runtime.py:775-777`) and revocation is admin-only
  (`runtime.py:805-817`); the S9 operation-id reservation covers withdrawal
  operation ids at every loaded policy's accepted source
  (`runtime.py:751-797`).
- **F8 (latent migration edge — unreachable today).** `migrate_policy`
  revalidates every verified proof under the target policy
  (`runtime.py:602-613`); a `withdrawn` proof would fail both the source
  match (`evidence_sources.get("withdrawn")` is `None`) and
  `validate_evidence` (`publishing.py:47-58` returns `False` for unknown
  kinds; `policy.py:89` shape mismatch for the three-field data). This is
  unreachable today because the permanent cancellation intent blocks
  migration (`runtime.py:574-575`) and closed works are `WORK_NOT_ACTIONABLE`
  (F2/F3) — a withdrawal can only exist on a work that is either inside the
  window or closed. Any future post-closure design that could ever migrate a
  compensated work must decide withdrawn-proof revalidation explicitly.
- **F9 (publishing-domain specifics that shape the adapter design).**
  Forward operation key is digest-based
  (`publishing.py:102-104`, `digest([id, capability, document_id,
  document_digest])`) — a document revision creates a new forward key, while
  the compensation key embeds the target operation id (stable regardless).
  `publications` rows are immutable hash-keyed artifacts; one publication id
  per `(document_id, digest)`; identical content under a new key reuses the
  id (`publishing.py:153-164`). Publishing works can also close **succeeded**
  via `request_completion` (`publishing_demo.py:127-130`) — retracting a
  completed work's artifact is post-closure territory (deferred, §spec);
  `request_cancel` is available to a publishing work at any open point
  (intervener rule, `runtime.py:473-492`; owner `agent` holds
  `work.manage` in the demo grants).
- **F10 (name-collision hazard).** S13 shipped `sop.withdraw` in the SOP
  authoring family ([sop-authoring.md](../../docs/sop-authoring.md)
  withdrawal section; verification.md "S13 coverage — publication
  withdrawal"). A content-family compensation must be named and documented so
  it cannot be confused with SOP-card withdrawal (different family, different
  store, different guarantees).
- **F11 (doc-sync surface).** `work_runtime/publishing.py` is not a
  `doc_sync_map` row (AGENTS.md); a slice that leaves `runtime.py`/
  `adapters.py` byte-unchanged fires no mapped row at all. However
  [runtime-boundaries.md](../../docs/runtime-boundaries.md):52-53 states the
  compensation variant "exists only for the expense family" and
  [interventions.md](../../docs/interventions.md):122-128 /
  [verification.md](../../docs/verification.md):572-580 list publishing
  compensation as open — those statements become false the moment a pairing
  ships and owe a same-commit truthfulness update even without a mapped code
  change.

## 2. Probe evidence

`/tmp/s14-recon/probe.py`, deterministic, fresh stores per scenario, two
runs **21/21 PASS each** (output captured in
`/tmp/s14-recon/probe-run2.log` for run 2):

| probe | claim pinned |
|---|---|
| P-D1 | unpaired publishing linked proposal → `REQUIREMENT_UNSATISFIED` + `CAPABILITY_UNSUPPORTED` blocker (today) |
| P-A1..A5 | paired policy: in-window admission, immutable snapshot, `digest([policy.id, capability, target])` key, replay stability — zero runtime changes |
| P-A6 | chain (compensating a compensation) → `COMPENSATION_TARGET_INVALID` |
| P-A7/A8 | forward-only adapter holds `ADAPTER_ACTION_UNSUPPORTED`; action-without-opt-in holds `ADAPTER_ACTION_CONTEXT_UNSUPPORTED` (zero attempts both) |
| P-A9..A11 | opted-in dispatch resolves; explicit `action`/`compensates` kwargs; full receipt stored as `adapter_result` |
| P-A12/A13 | `withdrawn` proof at source `publisher` with `original_external_id`; C04 inertness |
| P-A14..A16 | exact two-id ack; compensation disposition carries link + `adapter_result`; closure lists both external ids |
| P-B1 | cancellation intent persists in the closed work JSON (F2 landmine) |
| P-B2..B4 | post-closure proposals → `WORK_NOT_ACTIONABLE`; `record_evidence` still admissible (S8 precedent) |

The probe's paired policy and probe adapters exist only inside the probe
script — they model the candidate slice's policy/adapter additions and are
not product changes. Nothing in this recon was implemented or claimed as
shipped; stores are disposable.

## 3. What the recon implies (design input, not a decision)

The S10 machinery is family-agnostic by construction and probe-verified: a
publishing-family slice inside the cancellation window is **policy +
adapter work with zero runtime changes**. Post-closure compensation
collides with the closed-work command gate, the dispatch staleness branch,
closure-snapshot immutability and the absence of any finalize-style block
(F2/F3) — a genuine second design cycle, exactly as the S10 design §12
carried it. Chains are refused at two independent points today (F4/P-A6).
The candidate comparison, recommendation and deferred non-goals live in the
DRAFT spec; ratification is the master's.
