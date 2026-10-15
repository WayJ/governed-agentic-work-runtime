# S13 independent design review — SOP publication withdrawal DRAFT (2026-10-16)

Independent builder-check dispatched by the master. **Review only:** this
note is the sole write of this dispatch; no product/test/spec edits, no
merge/push, no ratification, no extra agents. The master owns ratification
(D-number allocation, sprint materialization, doc_sync_map). This review
neither ratifies nor implements anything.

## 0. Scope, method, commits

- Candidate DRAFT:
  [2026-10-16-sop-publication-withdrawal-design.md](../../docs/superpowers/specs/2026-10-16-sop-publication-withdrawal-design.md)
  read **in full** at `WayJ/s13-withdrawal-design` tip
  `d3314950016607179045e22b349121075bf7de5d` (`git rev-parse` verified equal
  to the branch tip and to this review checkout's HEAD; the review worktree
  branch `WayJ/s13-withdrawal-design-review` sits at the same commit, and this
  note's commit lands on it as a direct child of the candidate tip — the
  candidate branch itself is checked out in the sibling design worktree, so it
  is portable by fast-forward or cherry-pick, nothing merged or pushed).
- Baseline: main `860571c5c89b7dd22dc2be2567d7870c9b093f66` verified by
  `git rev-parse`; `git diff --stat 860571c d331495` is docs-only (the spec +
  recon note, 804 insertions), so worktree code reads are baseline reads. All
  probes ran against a `git archive` extraction of `860571c` in `/tmp`; the
  repo itself was never modified.
- Recon note
  [2026-10-16-s13-design-recon.md](2026-10-16-s13-design-recon.md) read in
  full on the same commit; every load-bearing grounding claim (F1–F25, P1–P2)
  was re-verified against the actual code, and both probes were independently
  replicated (P1′, P2′ below).
- Fresh probe suite (R1–R3, P1′–P2′: 48 assertions, all passing; R1–R3 run
  twice with identical results): public API only, `/tmp` synthetic ephemeral
  stores, secrets generated in-process and never printed; probe stores and
  scripts deleted afterwards. R1 **implements the DRAFT's candidate surfaces
  exactly as sketched** (document-shape-discriminated family with W02/W03,
  withdrawal key, `SopWithdrawalStore` wrapper with target refusal, loader
  step-3 binding conditions) against the unmodified baseline Runtime — the
  builder-check proper; R2 is a counter-probe on the SWD-8 refusal channel;
  R3 covers key distinctness.
- Baseline gates re-verified independently on the extraction (§3 end).
- Finding numbering below is `RV-F*` — separate from the recon's F1–F25 and
  from S12's `IR-F*`.

## 1. Verdict

**Implementable with amendments.** The core model is sound and proven live:
the entire §6 governed withdrawal flow — withdrawal-request admission →
W02 gate (wrong-digest / wrong-version / cross-kind approvals all leave it
pending; tampered envelope refused with zero intake writes) → signed
`card_withdrawal` → proposal with business key = the withdrawal key →
dispatch through a SWD-8-shaped wrapper → response lost after commit →
one-attempt reconcile → runtime-written `accepted` proof under `sop-store` →
completion `succeeded`; plus publication works completing **unchanged in the
same family and database** (the F18 regression), D66 ordering for second
withdrawal works, same-version re-publish conflict, and the two-artifact
census with publication bytes untouched — all ran on the unmodified baseline
with **zero changes to `runtime.py`, `ingress.py`, `authoring.py` or
`FilePublisher`** (R1, 24 assertions). The coordinator's central
expressibility question — whether W02/W03 document-shape discrimination fits
the current policy family surface — answers **yes, demonstrated, not argued**:
the `Policy` protocol hands `evaluate`/`validate_evidence`/`operation_key`
the work and `action_blockers` a shape-revealing requirement list
(`policy.py:17-27`), which is exactly enough. One drafted decision needs
amendment before ratification (RV-F1: SWD-8's refusal channel strands the
governed work; a one-channel fix is probe-verified), plus four precision
notes (RV-F2…RV-F5). No safety hole, no immutability violation, no
overclaiming was found.

## 2. Load-bearing claims — verification matrix

| claim (DRAFT/recon) | result | evidence at 860571c |
|---|---|---|
| F4: store mechanically immutable; in-place tombstone not a legal state | **verified** | `file_adapter.py:167-199` pins `artifact_version == 1` (181-182), exact five-field shape (178-179), key equality (183-184), recomputed document digest (191-193), `receipt.status == "accepted"` (195-199); commit is exclusive stage + fsync + atomic `os.link` (267-269), replay returns winner (270-274), same-key changed content is bounded `ValueError` with zero side effects (273), the only `unlink` is the adapter's own stage (279-284) |
| F3/F5/F6: key form, read surface, loader chain | **verified** | `publication.py:28,35-45,48-62` (D56 digest key; committed path `sha256(key)` at `file_adapter.py:224-228`); `read_validated` None-on-absent + bounded corruption refusals (`file_adapter.py:296-309`); loader chain `publication.py:108-134` with messages 100-105 — the DRAFT's insertion point (after full validation, before return) is exactly between 133 and 134; foreign content under a publication key refused by the `sop_digest` re-lint (128, MD-4) |
| §5: `pinned_card` inherits the withdrawal error before the pin comparison | **verified** | `publication.py:158-162`: pin-argument gate, then `load_published_card`, then the pin compare — a load-side raise precedes any pin judgment |
| F7: family surface incl. the S8 hook | **verified** | `publication.py:195-262`: `evidence_sources` (198-201), admission lint (203-204), D58 approval shape (206-222), `evaluate` counts only `status == "verified"` (227 — exactly the hook S8 revocation uses), `action_blockers` excludes S03 and is the only capability-aware filter (251-257), `operation_key` = publication key (259-262) |
| F9–F12: S8 revoke machinery | **verified + replicated live** | routing before the closed-work guard (`runtime.py:281-288`), authority = admin or configured source with `evidence.revoke` (805-817), one-transaction effect with requirement diffs (819-883), resend/migration skip revoked (885-908); P1′ reproduces the whole composition on the real family (9 assertions) |
| F13: S10 owns the `"withdrawn"` proof kind | **verified** | `runtime.py:946-961`: kind choice 952-955, written only for ops carrying a `compensates` link; the DRAFT correctly creates none |
| F14: accepted-source reservation | **verified** | `runtime.py:751-766` (recomputed per intake across loaded policy versions); `"card_withdrawal"` is not an accepted source, so no interaction |
| F15/P1: S8 × sop-publish composition real but unpinned | **verified + replicated** | P1′ (below); `grep -ci revoke tests/test_publication*.py` → 0 in all three modules |
| F16/F17/P2: execute-refusal cannot fence re-publication; reconcile resolves from `lookup` | **verified + replicated** | exception path `runtime.py:1064-1065` → `outcome_unknown`; `reconcile` resolves from `adapter.lookup` (1105-1115) with no contract check; P2′ reproduces cross-database (4 assertions). Consequence for the DRAFT — validity must live at the read surface (SWD-7) — is therefore correct by construction |
| F18: completion gate capability-blind; works carry no capability | **verified** | `runtime.py:422-433` blocks on every unsatisfied requirement (plus unresolved operations 426-431); capability exists only as a `propose_action` payload field (642-643); R1.4 proves publication completion unchanged under the extended family |
| F19: one family per database, migration never implicit | **verified** | `runtime.py:62-89,163-185` |
| F20: D66 pinned order | **verified** | `_propose` requirement blockers (668-673) before the business-key branch (674-690, conflict at 689-690); pinned by `tests/test_publication.py:563` and `:579` (test definitions; the ordered assertions sit at 572/592); R1.21-22 reproduces for withdrawal works |
| F21: ingress surface for a new signed kind | **verified** | `RESERVED_KIND` is only `"accepted"` (`ingress.py:26,318-319`); rotation codes 283-286/304-311; gateway forwards with `expected_version=None` (320-325); R1 drives `card_withdrawal` through the unchanged gateway |
| F22: numbering ceiling | **verified** | epic ADR ledger D54–D66 (`docs/superpowers/roadmaps/2026-10-15-sop-publication.md` 36-48); no `D67+` anywhere in `docs/` or `.agents/` |
| F23: RFC-002 §6 forward-only version discipline | **verified** | `docs/RFC-002-sop-authoring-and-binding.md` §6 lines 129-146 |
| F24: demo/census surfaces | **verified** | `publication_demo.py:16-17` (D63 docstring), `:47` FINAL_LINE, `:82` six-table dump, `:245-260` per-call adapter dispatch + restart reconcile; `tests/test_publication.py:150` one-artifact census (the sprint must update it — DRAFT acknowledges) |
| F25: viewer needs no change | **verified** | generic tables (`runtime.py:124-127`) and event insert (216-218); the viewer is read-only over snapshots — withdrawal rows render like any other work/evidence/event |
| grants/evidence single-source-per-kind for `card_withdrawal` | **verified** | `evidence_sources` is a strict kind→source dict consulted identically by intake (775-777), `verify_pending` (897) and revoke authority (817); R1 adds the kind additively with no cross-talk |
| honest-limits claims (§14: byte-identical receipts, one-attempt reconcile, six tables, no fencing of running consumers) | **verified** | R1.12/R1.14-16/R1.18; `Runtime` never reads the store (only the caller-supplied adapter does — D62 intact) |

## 3. Probe log (RV probes; 48/48 pass)

Ran from `/tmp` against the extracted baseline, public API only. The probe
sketch will be deleted with the probe stores; the assertion list is the
reproducible spec.

| probe | asserts (one line each) |
|---|---|
| R3.1–R3.4 | withdrawal key vs publication key: distinct prefixes + 64-hex digests, distinct committed paths, delimiter-hostile identities distinct (D56 basis), version-scoped |
| R1.1–R1.4 | publication propose blocked/accepted, dispatch confirmed, **work completes unchanged under the extended family** (F18 regression) |
| R1.5–R1.10 | withdrawal propose blocked on W02; `card_approval` never satisfies W02; tampered envelope → `EVIDENCE_AUTHENTICATION_FAILED` with zero evidence rows; wrong-digest and wrong-version `card_withdrawal` leave W02 pending |
| R1.11–R1.13 | propose accepted with business key = withdrawal key; command replay verbatim; **wrong-adapter dispatch held `ADAPTER_ACTION_UNSUPPORTED`** (bounded, re-dispatchable) |
| R1.14–R1.17 | fault after commit (response lost) → reconcile `confirmed_succeeded` in one attempt; `accepted` proof under `sop-store` with `event_id` = operation id; withdrawal work completes `succeeded` |
| R1.18–R1.20 | census exactly two hash-named artifacts; publication bytes unchanged; loader step-3 binding conditions hold (record = request, digests bind, distinct from the publication artifact's) |
| R1.21–R1.24 | second withdrawal work: `REQUIREMENT_UNSATISFIED` first then `OPERATION_CONTENT_CONFLICT` (D66); same-version re-publish conflicts after own approval with census unchanged; `sop.publish` on a withdrawal work → bounded `CAPABILITY_UNSUPPORTED` blocker |
| R2.1–R2.5 | **counter-probe**: absent-target withdrawal proposes fine (W02 is the only gate); SWD-8's drafted `ValueError` refusal → `outcome_unknown` → reconcile `NO_AUTHORITATIVE_RESULT` + `needs_attention`; completion **and** `finalize_cancel` both refuse `OUTCOME_UNRESOLVED` — the work is permanently stuck |
| R2.6–R2.7 | amendment channel: refusal as a `{"status": "rejected", …}` receipt → `confirmed_failed` (terminal) and the work closes as `cancelled` |
| P1′.1–P1′.9 | recon P1 replicated: owner and source-without-`evidence.revoke` denied; admin revokes `card_approval` and the runtime-written `accepted` proof on the closed work; closed/succeeded preserved, completion byte-identical, S02/S03 pending, two `EvidenceRevoked` events, one untouched artifact |
| P2′.1–P2′.4 | recon P2 replicated: cross-database same-card proposal accepted; refusing `execute` → `outcome_unknown`; reconcile → `confirmed_succeeded` from the standing artifact via `lookup`; still one artifact |

Baseline gates re-run independently on the extraction: full unittest
discover **OK** (944 tests, skipped=3), plus `compileall` clean. The
worktree itself is untouched by probing (`git status --porcelain` empty
before this note).

## 4. Findings

### RV-F1 — Medium — SWD-8's refusal channel as drafted strands the governed work permanently

The DRAFT (§6/SWD-8) has `SopWithdrawalStore.execute` "refuse bounded" —
house style for a `ValueError` — when the target publication artifact is
absent or its `content_digest` ≠ the record's `published_digest`. That
channel has a governed-flow consequence the DRAFT does not state: the
refusal is reachable on a first-class operator path (the authority can sign
a `card_withdrawal` for a digest that is not committed in this directory —
wrong directory config, digest typo in the request, or artifact deleted
between approval and dispatch; W02 binds approval to the *request's*
`published_digest`, and nothing at admission or proposal checks the target
exists). Probe R2: the `ValueError` → `outcome_unknown`
(`runtime.py:1064-1065`) → reconcile finds no artifact (`lookup` → None) →
`NO_AUTHORITATIVE_RESULT` + `needs_attention` (`runtime.py:1114-1127`) — and
this outcome is **terminal-in-practice**: `request_completion` refuses
`OUTCOME_UNRESOLVED` (426-431) and so does `finalize_cancel` (504-510),
while `_cancel_prepared` only cancels `prepared` intents (444-453). The work
can never close and never cancel. The DRAFT's own acceptance scenario and
§13 test list stop at the adapter-level refusal, so an implementer following
the draft as-is would ship this trap unpinned. Fix is one channel swap (§5):
`receipt_is_valid` already accepts `status: "rejected"`
(`adapter_contract.py`, `_ACCEPTED_STATUSES`), which resolves
`confirmed_failed` — terminal, truthful, and the work stays cancellable
(R2.6-2.7). S12 precedent note: the nearest existing relative is the
cross-database doctored-card quarantine (`ADAPTER_RESULT_INVALID` +
`needs_attention`, documented in sop-authoring.md 203-212) — but that trigger
is a hostile edge case, while SWD-8's refusal is a designed, plausible
outcome and deserves a designed resolution.

### RV-F2 — Low — withdrawal request documents are effectively immutable via `revise_document`; say so

The closed four-field request shape has no top-level `id`, so
`revise_document` on a withdrawal work raises an unbounded `KeyError` at
`runtime.py:405` (`payload["document"]["id"]`) — the exact S12 IR-F2
finding for cards, ratified there as a docs-only re-frame ("the card document
is effectively immutable… content changes enter as new works",
sop-authoring.md 251-266). The DRAFT never mentions `revise_document`. One
sentence in §3 or §6 stating the same effective immutability for withdrawal
requests (consistent with determinism and forward-only correction) closes
it; no code change is wanted (S12 explicitly rejected teaching
`revise_document` to tolerate id-less documents, and the DRAFT's own
zero-runtime-change goal agrees).

### RV-F3 — Low — the adapter is per-call; the per-capability adapter discipline must be stated

`dispatch`, `reconcile` and `recover` all take the adapter as an argument
(`runtime.py:976, 1105, 1180-1194`). A database holding both publication and
withdrawal operations must dispatch/reconcile each with the matching adapter:
the wrong adapter's dispatch is **held** `ADAPTER_ACTION_UNSUPPORTED`
(bounded, re-dispatchable — R1.13), and `recover(adapter)` with a single
adapter holds the other capability's prepared ops the same way. Reconcile
itself never checks `contract.actions` (1105-1115) and both wrappers
delegate `lookup` to the same `FilePublisher`, so cross-adapter reconcile
happens to resolve correctly — worth knowing, not relying on. The DRAFT's
flow (§6) shows only the correctly-wired calls; SWD-11's demo/installer
story should state the discipline explicitly (the S12 demo already drives
per-call adapters; `recover()` is used by other demos' restart flows, so an
operator copying that pattern needs the sentence).

### RV-F4 — Low — §13 test-list gaps

Three pins the DRAFT's test implications omit: (a) **capability ×
document-shape pairing** — `sop.publish` on a withdrawal work and
`sop.withdraw` on a card work must produce the bounded
`CAPABILITY_UNSUPPORTED` blocker (R1.24 shows the correct behavior; without
the pin, a naive `action_blockers` that checks only the capability could let
a mismatched pair reach `operation_key` → `publication_key(request)` → an
unpersisted `ValueError` escaping `command()` instead of a rejected
receipt); (b) the **governed outcome of the SWD-8 refusal** (whatever RV-F1
channel the master ratifies — `confirmed_failed` + cancellability, or the
documented stranded-work boundary); (c) the **wrong-adapter dispatch hold**
(R1.13). All three are cheap; (a) and (b) are load-bearing.

### RV-F5 — Low — SWD-6 must state the corrupt-record error mapping

A corrupt withdrawal-record file surfaces as `read_validated`'s own bounded
`ValueError`s (`file_adapter.py:167-199`: `PARSE/SHAPE/VERSION/…`), not as a
new class. Step 4's `WITHDRAWAL_RECORD_INVALID_MESSAGE` therefore requires
an explicit catch-and-re-raise around the `read_validated` call (mapping
every adapter violation class onto the one withdrawal-record class). The
DRAFT implies it ("corrupt or does not bind this artifact → a distinct
bounded fail-closed error") but should state the mapping, so the
"six bounded, distinguishable classes" claim in §5 stays literally true at
the loader surface (the adapter's internal vocabulary must not leak as
seventh-plus classes).

### RV-F6 — Info — hunted weaknesses: none found (negative results)

- **Store-key collisions/ambiguity:** none — R3; different prefix namespaces
  (`sop-pub:` vs `sop-withdrawn:`), digest basis inherited from D56,
  committed paths `sha256(key)`; compensation keys live in the operations
  table, a different namespace entirely.
- **Withdrawal-then-republish vs the immutable store:** in-database
  same-version re-publish is refused `OPERATION_CONTENT_CONFLICT` after its
  own approval with census unchanged (R1.23); cross-database re-publish
  replays the winner and commits nothing new (P2′ machinery; recon F17) —
  the DRAFT's §8.1-8.2 account is accurate.
- **Replay/idempotency incl. response loss mid-withdrawal:** command replay
  verbatim (R1.12); response loss after commit → one-attempt reconcile →
  `confirmed_succeeded` (R1.14-15); the record's determinism (canonical JSON
  over the closed four-field shape) makes store-level replay byte-identical
  by the pinned F4 machinery.
- **Loader matrix completeness:** the existing four classes are distinct and
  bounded (F6 verified); the two new classes are expressible with the
  R1.20-verified binding conditions and the RV-F5 mapping; absent-artifact
  precedence over withdrawal-record presence matches the DRAFT's stated
  order note (artifact read first, `publication.py:119-126`).
- **Conflict-layer interactions:** `OPERATION_CONTENT_CONFLICT` (proposal
  business-key, D66 order) composes with the wrapper refusal and with
  publication works in the same family/database without cross-talk
  (R1.21-23, R2.1).
- **W02/W03 expressibility without runtime.py changes:** proven end-to-end
  (R1) — no hidden runtime assumption found; the `Policy` protocol surface
  (`policy.py:17-27`) is sufficient, including `action_blockers`' access to
  the shape via the requirement list's rule ids.
- **Schema/dependency violations:** none — stdlib-only, no new imports
  beyond existing modules' (`hashlib/json/os`), Python ≥3.9 idioms
  untouched; no database schema change (operations/evidence reuse
  unchanged).
- **Unclaimed UI/lifecycle writes:** none — the DRAFT's writes are
  `publication.py` (additive), `publication_demo.py`, tests, docs; the
  viewer is untouched (F25 verified) and the Runtime never consults the
  store (D62 intact).
- **Overclaiming:** none found — §14's limits match what the code does;
  "byte-identical", "one attempt", "six tables", rotation codes and the
  no-TLS/KMS/distributed posture all verified or replicated.
- **Sprint shape bounded:** yes — two waves, six stories, test-first, scope
  comparable to S12 core+demo; the only scope watch is story 4 (composition
  + rotation battery), which is test-only and already precisely enumerated.

### RV-F7 — Info — SWD-12's doc_sync_map rows likely number zero

`AGENTS.md` already maps `work_runtime/publication.py` and
`work_runtime/publication_demo.py` → `docs/sop-authoring.md`. The DRAFT's
"master adds doc_sync_map rows" should be read as "master confirms none are
needed" unless the sprint introduces a new module (the DRAFT says
publication.py grows additively — covered).

### RV-F8 — Info — citation precision

All file:line cites in the DRAFT and recon were checked; two are
range-approximate but in-range and not load-bearing (DRAFT §4's
`runtime.py:942-961` for the `"withdrawn"` kind — assignment at 952-955;
recon F14's `751-759` — actual 751-766). Everything else is exact.

## 5. Alternatives (material)

**For RV-F1 only** (refusal channel of SWD-8):

- **A (recommended): refuse by rejected receipt.** `execute` returns
  `{"status": "rejected", "external_id": "<stable refusal id>",
  "digest": <record document digest>}` when the target is absent or the
  digest does not bind. `receipt_is_valid` accepts it
  (`adapter_contract.py`), `_resolve` marks `confirmed_failed`
  (`runtime.py:1151-1153`), the work lands `needs_attention`, W03 stays
  pending (truthful — nothing was withdrawn), and the work remains
  cancellable (`finalize_cancel` accepts terminal-failed ops, R2.6-2.7).
  Cost: the wrapper's refusal must mint a stable `external_id`; the
  D55-style "delegates verbatim" symmetry with `FilePublisher` (which only
  raises) is consciously extended — the wrapper already adds a refusal of
  its own, so this is a channel choice, not new surface.
- **B: keep the `ValueError` and own the strand.** Matches the FilePublisher
  refusal idiom and the S12 quarantine precedent; then §14 must add the
  boundary ("an approved withdrawal of an uncommitted target leaves the work
  permanently unresolvable — operator discipline: verify the target before
  signing") and §13 must pin both `OUTCOME_UNRESOLVED` refusals. Honest but
  strictly worse operability for a designed-for path.

Not alternatives: validating the target at proposal time (the policy family
would need the store directory — a new family↔store coupling the DRAFT
rightfully avoids); teaching `reconcile` a failed-lookup resolution (a
runtime.py change the DRAFT forbids itself, and lookup-absent is genuinely
ambiguous after a crash).

## 6. Recommended master decisions

- **MD-1:** Ratify SWD-1…SWD-7, SWD-9…SWD-13 as drafted (assign D67+; the
  ceiling and house numbering are verified, F22).
- **MD-2:** Amend SWD-8 per Alternative A (rejected-receipt refusal channel
  → `confirmed_failed`, work cancellable) and pin it in story 3's tests —
  or explicitly ratify Alternative B with the §14 boundary sentence and the
  two `OUTCOME_UNRESOLVED` pins. A is recommended.
- **MD-3:** Add three disclosure sentences to the spec at ratification:
  withdrawal requests are effectively immutable under `revise_document`
  (RV-F2, IR-F2 precedent); the per-capability adapter discipline for
  dispatch/reconcile/recover (RV-F3); the corrupt-record catch-and-re-raise
  mapping (RV-F5).
- **MD-4:** Extend §13's test list with: capability × document-shape pairing
  (both directions), the governed refusal outcome per MD-2, and the
  wrong-adapter dispatch hold (RV-F4).
- **MD-5:** Treat SWD-12's doc_sync_map step as a confirmation that zero new
  rows are needed (RV-F7), keeping "master adds rows" as the master's own
  check.

## 7. Exact SWD list I would pin

| SWD | status | note |
|---|---|---|
| SWD-1 second immutable record artifact, same directory | **pin as drafted** | R1.18-19: two hash-named artifacts, publication bytes unchanged |
| SWD-2 `"sop-withdrawn:" + digest([id, version])` | **pin as drafted** | R3; D56 basis; no collision in any namespace |
| SWD-3 deterministic closed record, no free text | **pin as drafted** | determinism verified via canonical form; add the RV-F2 sentence |
| SWD-4 same family / `sop.withdraw` / shape-discriminated W02/W03 / operation key = withdrawal key | **pin as drafted** | R1 — proven with zero runtime changes; add the RV-F4(a) pin |
| SWD-5 signed `card_withdrawal` `{digest, policy_version}`, no admin bypass | **pin as drafted** | R1.6-10 (isolation, tamper, wrong-digest/version); Q2 default consistent |
| SWD-6 loader step + two new bounded errors + `withdrawal_record()` + no override | **pin with RV-F5 amendment** | insertion point verified; binding conditions R1.20 |
| SWD-7 no write-path fencing; validity at the read surface | **pin as drafted** | P2′ — structurally enforced by reconcile-from-lookup |
| SWD-8 `SopWithdrawalStore` wrapper with target refusal | **amend per MD-2** | RV-F1: channel choice; disclosure RV-F3 |
| SWD-9 D66 order inherited and pinned for withdrawal works | **pin as drafted** | R1.21-22; `runtime.py:668-690`; tests 563/579 |
| SWD-10 no un-withdrawal, no compensation semantics, no Runtime wiring, no UI change | **pin as drafted** | kind ownership verified (952-955); F25 verified |
| SWD-11 demo chapter + installer stage, no new global gate | **pin as drafted** | add the RV-F3 discipline sentence; census/count updates owed (F24) |
| SWD-12 doc set + master-added doc_sync_map rows | **pin as confirmation** | RV-F7: existing rows cover both modules |
| SWD-13 pin the S8 × sop-publish composition | **pin as drafted** | P1′ — composition real, currently zero coverage |

Q1–Q10 defaults: all verified implementable and internally consistent with
the code; none challenged. Q1 (same family) is proven by R1 running both
capabilities in one family/database/ledger; Q2's asymmetry note is backed by
P1′ (the admin's real reach is `revoke_evidence`, which never touches the
store); Q7 (separate wrapper) composes with the per-call adapter discipline
(RV-F3).

## 8. Honesty limits of this review

- The probes sketch the candidate surfaces as the DRAFT specifies them; the
  sprint's real code may differ in detail. The loader's two new error
  classes were verified for expressibility and binding conditions, not as
  shipped code; no UI/browser checks were run because the DRAFT claims (and
  this review confirms by surface inspection) no UI change.
- Single reviewer, one machine, synthetic ephemeral stores; no
  hostile-filesystem, power-loss, concurrency-stress or multi-process
  testing (inherited file-adapter boundaries, unchanged by the DRAFT).
- P1′/P2′ are rebuilt equivalents of the recon's deleted probe scripts, not
  re-runs of the same code; they assert the same outcomes on the same
  baseline.
- This note's commit lands on the review worktree branch (a direct child of
  the candidate tip, §0); the master decides how it travels. Nothing here is
  ratified, implemented or merged by this dispatch.
