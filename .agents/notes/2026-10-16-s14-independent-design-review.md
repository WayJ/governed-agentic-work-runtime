# S14 independent design review (builder-check) — 2026-10-16

## Scope, method, pins

Master-dispatched **independent design review / builder-check ONLY** of the
candidate DRAFT
[2026-10-16-beyond-window-compensation-design.md](../../docs/superpowers/specs/2026-10-16-beyond-window-compensation-design.md).
This review neither ratifies nor implements; the master owns ratification.
Pins verified at start: baseline main
`678d7b48e844ee153325239259064eab9b806df3` and candidate source
`WayJ/s14-compensation-design` = `9dd195c5dd75ade9360e94c05400696e679bcabd`
(`git rev-parse` equals tip; candidate delta vs baseline is exactly the two
doc files, 611 insertions, so all code citations below are identical at both
SHAs). Baseline battery re-run on a `git archive` extraction (worktree
untouched): **`Ran 1015 tests … OK (skipped=3)`** — matches the draft's claim.

Method: every load-bearing grounding claim F1–F11 was re-verified against the
actual code at `678d7b4` (line-by-line read of `runtime.py`, `publishing.py`,
`policy.py`, `adapters.py`, `adapter_contract.py`, `publishing_demo.py`,
`tests/adapter_conformance.py`, `cli.py`, `scripts/verify_install.py`, and the
cited doc passages), and the family-agnosticism core was **re-proven with an
independent probe** (`/tmp/s14-review/probe/probe.py`, written from scratch
for this review — not the recon's script): a probe-only paired
`PublishingPolicy` subclass (draft §4.8 shape) plus a probe adapter modeling
draft §4.4, driving the **unmodified baseline runtime** through the entire
publishing compensation pipeline. Deterministic, fresh synthetic `/tmp`
stores, no secrets, two runs: **50/50 checks PASS each**. Probe stores are
throwaway; the check inventory is preserved in §2.

## Verdict

**Implementable WITH AMENDMENTS.** No structural defect. Every load-bearing
grounding claim in the draft and recon verified accurate against `678d7b4`;
the recommended slice (publishing-family linked compensation inside the
active window) is genuinely policy + adapter + tests/demo/docs work with zero
runtime changes, independently re-proven end-to-end. The amendments are two
acceptance-wording/structure fixes (RF1, RF2) and three small pin additions
(RF3–RF5); none touches the design's mechanism choices.

## 1. Grounding verification matrix (draft F1–F11 at `678d7b4`)

| draft claim | verdict | independent evidence |
|---|---|---|
| F1 window machinery | **accurate** | `runtime.py:645-652` (forward `CANCELLATION_ACTIVE` / linked `CANCELLATION_NOT_REQUESTED`, gate before the business-key branch), `runtime.py:639-644` (owner + grant); probe R04/R05 |
| F2 predicate blind to "closed" | **accurate** | intent set at `runtime.py:481`, copied into closure at `532-538`, **never popped** (grep: no pop/del/clear of `cancellation` anywhere); closed gate `285-286`; probe R23 (intent present on closed work) |
| F3 post-closure collisions | **accurate** | `runtime.py:281-286`, dispatch staleness `1011-1018` (defensive: prepared ops cannot survive either closure command — both block on unresolved — so this branch, like `996-1003`, is unreachable via the public API today); closure snapshot written once; S8 precedent `_revoke` runs before the closed check (`283-284`) and records `work_was_closed` (`878`); probe R24/R24b/R24c/R25b |
| F4 family-agnosticism end-to-end | **accurate — independently re-proven** | probe R01–R29 on the unmodified runtime: admission, snapshot, D6 key, distinctness, replay, chain refusal (`740-743`/`1087-1093`), both holds, kwargs, withdrawn proof, C04 inertness, two-id ack, dispositions, recovery, refusal |
| F5 two attributes + one opt-in | **accurate** | `publishing.py:21-36` (no `compensation_capabilities`), `94-100` (off-family `CAPABILITY_UNSUPPORTED`), `117-122`/`141`/`130-166` (forward-only contract, 3-positional execute, 3-column receipts, `(document_id,digest)` publications with dedup); probe R01 (today's `REQUIREMENT_UNSATISFIED` + blocker) |
| F6 conformance skip auto-activates | **accurate** | `tests/adapter_conformance.py:75-86` skip at `85-86` keyed on `supports_action_context`; S13 acceptance names both designed skips incl. `test_publishing.FakePublisherConformanceTests` |
| F7 withdrawn lifecycle closed | **accurate** | no `withdrawn` source mapping → import denied (`775-777`), row-based revoke authority fails for unmapped kinds → admin-only (`805-817`), S9 reservation at every loaded accepted source (`751-797`); probe R19/R19b/R25/R25b |
| F8 migrate edge unreachable | **accurate** | `runtime.py:602-613` revalidation; `publishing.py:47-58` returns `False` for `withdrawn`; blocked by permanent intent (`574-575`) or closed gate — and nothing ever clears `cancellation` (verified by grep), so a withdrawn proof implies intent-or-closed always |
| F9 publishing specifics | **accurate** | forward key `publishing.py:102-104`; immutable publications `133-164`; succeeded closure via `request_completion` (`publishing_demo.py:127-130`); intervener cancel path `473-492` |
| F10 name hazard | **accurate** | `sop.withdraw` shipped in S13 (roadmap 0.4 / sop-authoring.md); `content.unpublish` appears **nowhere** in the baseline (grep 0 hits) |
| F11 doc-sync surface | **accurate** | `publishing.py`/`publishing_demo.py` are not `doc_sync_map` rows (AGENTS.md); the three quoted doc passages exist verbatim (`runtime-boundaries.md` "exists only for the expense family"; `interventions.md` deferred-scope; `verification.md` unimplemented list) and become false on pairing |

## 2. Independent probe inventory (50 checks, 2/2 deterministic runs)

R01 today's rejection · R02–R03 forward publish on probe store · R04 no-intent
linked rejection · R05/R05b in-window forward/document freeze · R06–R09 linked
admission, immutable `{operation_id, external_id, capability}` snapshot,
business key `digest(["content-publish","content.unpublish",target])`,
distinctness from forward keys · R10 replay re-admission without link rebind ·
R11* target matrix (unknown / cross-work / confirmed_failed — the last two go
beyond the recon's probe) · R12* both holds with zero attempts
(`ADAPTER_ACTION_UNSUPPORTED` on the unmodified `FakePublisher`;
`ADAPTER_ACTION_CONTEXT_UNSUPPORTED` on action-without-opt-in), held ≠
cancelled re-dispatchability · R13–R17 opted-in dispatch with explicit
`action`/`compensates` kwargs, `withdrawn` proof at source `publisher` with
`{digest, external_id, original_external_id}`, C04 satisfied by the forward
accepted proof, `adapter_result` stored · R18 chain refusal · R19/R19b
withdrawn-kind import denial + S9 operation-id reservation · R20–R23 partial
ack mismatch, exact two-id finalize, compensation disposition shape, closure
listing both external ids + persisted intent · R24* post-closure collisions
(proposal, request_cancel → `WORK_NOT_ACTIONABLE`; record_evidence
admissible) · R25* publisher cannot revoke the withdrawn proof, admin revoke
records `work_was_closed` · R26* crash-after-commit → outcome_unknown →
unresolved blocks finalize → restart reconcile confirms once, one retraction
effect · R27* refused retraction (`ORIGINAL_ABSENT`) → `confirmed_failed`,
recorded, never reversed, does not block closure · R28* adapter-level design:
forward/retraction replay identity, alias receipt reusing the retraction id,
re-publish-after-retraction artifact-id reuse with truthful counts
(published 1 / retracted 1), link-fingerprint conflict, three ValueError
guards, stored `ORIGINAL_ABSENT` rejection · R29* old-store additive
migration (legacy 3-column schema) with PRAGMA-probe ALTER, legacy replay and
dedup intact, idempotent reopen, no row rewritten.

## 3. Findings

Numbered RF to avoid collision with the draft's F1–F11. Severity: M medium,
L low, I informational.

- **RF1 (M) — D87's "forward path byte-unchanged" is not literally
  implementable; restate as behavior-level identity.** The forward branch's
  bare `INSERT INTO receipts VALUES (?,?,?)` (`publishing.py:165-166`) fails
  on the migrated 5-column table — verified directly: SQLite rejects it with
  "table receipts has 5 columns but 3 values were supplied". After the
  additive migration the forward INSERT must become column-named
  (`INSERT INTO receipts (key,digest,result) VALUES (?,?,?)`) or equivalent;
  the alternative (bifurcating receipt storage to keep `receipts` 3-column)
  merely moves the inevitable edit into the shared `lookup()` forward
  surface. The mechanism is fine — the probe ran the whole design — but the
  D87/§4.4 pin as worded would fail a literal byte-diff acceptance. Amend to:
  forward **semantics and store rows identical** for identical inputs
  (including same-content dedup reusing the publication id, and NULL
  `action`/`link_digest` on forward receipts), no withdraw-by-store-state
  branch in the forward path, with the single mechanical column-naming edit
  to the receipt INSERT allowed and disclosed. §9's GREEN pin "ordinary
  publishing flow byte-identical" should say result/store-state identity.
- **RF2 (M) — the demo chapter's asserted counts imply an unstated
  restructure of publish-demo's ending.** A linked retraction cannot follow a
  succeeded closure (closed works reject `request_cancel` and every proposal
  — probe R24/R24b), so "publish → cancel → linked retraction → … → two-id
  closure" with `published_count()==1, retracted_count()==1` is only
  reachable by **replacing** the current succeeded-completion ending
  (`request_completion`, `publishing_demo.py:127-130`) with the cancellation
  ending; appending a second work instead yields counts (2,1). The draft
  does not say which, and the replacement silently drops the
  succeeded-completion path from the demo. Also: the installer's publish-demo
  stage is **module-only today** (`scripts/verify_install.py:19,1538-1553`,
  asserting `publications == 1` and `PUBLISH_FINAL_LINE`) — unlike
  `publication-demo`'s module+console stages — so "installer gains a matching
  module+console stage" overstates the current shape: whichever structure is
  chosen, that stage's counts/final-line assertions must change in the same
  commit, and a console stage would be new coverage, not a match. Alternatives
  in §5; the master should pin one before W2.
- **RF3 (L) — pin the contract action order in D86.** The generic opt-in
  conformance test derives its forward context from `contract.actions[0]`
  (`adapter_conformance.py:87`). `FakePublisher`'s new contract must keep
  `"content.publish"` first (as §4.4 lists it); if an implementer ordered
  `content.unpublish` first, the newly activated test would call the
  withdrawal action with `compensates=None` and hit the `ValueError` guard.
  One line in D86 closes it. (Same place: pin the retraction receipt id
  prefix choice the draft leaves open, for deterministic docs.)
- **RF4 (L, strengthens the design) — Q4's boundary is narrower than
  documented.** Through the governed runtime, re-publish-after-retraction is
  **unreachable**: a same-work forward propose is refused
  `CANCELLATION_ACTIVE` under the permanent intent (`runtime.py:645-647`),
  and a cross-work publish of identical content collides on the store-global
  forward business key — `digest([policy.id, capability, document.id,
  document_digest])` embeds no work id — with `OPERATION_CONTENT_CONFLICT`
  (`runtime.py:686-690`). The alias-retraction interplay is likewise
  reachable only through direct adapter calls. Recommend documenting Q4's
  limit explicitly as an **adapter-model** statement with this reachability
  note; it makes the boundary airtight rather than merely described.
- **RF5 (L) — D91's doc set omits `roadmap.md` 0.3.** Line 33's "compensation
  beyond that bounded window (publishing, post-closure, chains) … remain
  open" also becomes partially stale at release; the roadmap is the master's
  ledger, so this belongs to the master's close-out edit — D91 should name it
  (or the master's close-out convention should cover it) so it is not
  missed. Also note `runtime-boundaries.md`'s compensation section heading
  itself ("S10 — expense family, active-cancellation window", line 45) needs
  the family update, not only the sentence at 52-53.
- **RF6 (I) — unreachable-today claims are structurally sound.** Nothing ever
  clears `work["cancellation"]` (grep-verified), so F8's migration edge is
  unreachable for any compensated work; the dispatch staleness branches
  (`996-1003`, `1011-1018`) are correctly characterized as defensive —
  prepared operations cannot survive either closure command because both
  block on unresolved operations.
- **RF7 (I) — the D82 runtime-byte-unchanged pin is feasible and is the right
  instrument.** The entire pipeline runs on the unmodified runtime
  (independent probe, 50/50 twice). Pin via exact hash/diff of
  `work_runtime/runtime.py` and `work_runtime/adapters.py` at acceptance,
  with the draft's escalation rule (any discovered runtime need escalates
  rather than silently widening).

## 4. Builder-check of D80–D91 and Q1–Q9

| id | verdict |
|---|---|
| D80 scope | implementable — probe-proven in-window; post-closure/chains refusals verified (R18/R24*) |
| D81 `content.unpublish` | implementable — zero baseline occurrences (grep); no collision with `sop.withdraw`/`expense.withdraw` |
| D82 byte-unchanged runtime | implementable + feasible to pin (RF7) |
| D83 owner + grant authority | implementable — `runtime.py:639-644`, replay recheck `326-328`; demo grants change is additive (`publishing_demo.py:24-26`) |
| D84 key/replay/conflict | implementable — R08–R10; no new codes needed anywhere in the pipeline |
| D85 `withdrawn` reuse | implementable — R15/R19/R25; kind ownership is per-policy validation, no cross-family coupling; F8 edge unreachable (RF6) |
| D86 FakePublisher design | implementable — every §4.4 detail ran in the probe (R28*, R29*); add RF3's action-order/prefix pin |
| D87 forward byte-unchanged | **challenged (RF1)** — amend to behavior-level identity; mechanism itself verified |
| D88 FilePublisher untouched | implementable — `file_adapter.py:213-214` declares `actions=("content.publish",)`, so a linked `content.unpublish` holds `ADAPTER_ACTION_UNSUPPORTED` at `runtime.py:1029-1036` (before the opt-in check); its conformance skip stays a designed skip |
| D89 policy attribute, no new version | implementable — exact `policy.py:133-139` shape; graceful degradation verified with the unmodified `PublishingPolicy` (R01) |
| D90 demo chapter + installer stage | implementable **after RF2's structure decision**; not a gate; no UI claim holds |
| D91 doc updates | implementable — F11 verified; add RF5's roadmap/close-out note |
| Q1 sub-slice | agree — §3's comparison is grounded; my probe adds independent evidence for the recommended row |
| Q2 name | agree (`content.unpublish`); RTR- receipt prefix stays builder-local within pinned shapes (RF3) |
| Q3 demo shape | chapter-in-`publish-demo` viable but carries RF2's structural decision; a new top-level demo avoids the restructure at higher cost — either is bounded |
| Q4 forward × retraction | agree, and sharpen per RF4 — governed flow cannot reach the interplay; document as adapter-model limit with reachability note |
| Q5 counters | agree — `published_count()` semantics unchanged, `retracted_count()` = retraction rows; R28d shows counts stay truthful through a retract→re-publish cycle |
| Q6 FilePublisher skip | agree — skip logic is contract-driven; asymmetry is by design |
| Q7 policy surface | agree — attribute inheritance, no version bump (ratified D10 reasoning) |
| Q8 runtime pin | agree — feasibility verified (RF7) |
| Q9 post-closure seeds | properly recorded-not-decided; RF6 strengthens the seeds' factual basis |

Hidden-runtime-assumption hunt (task-mandated): **none found beyond RF1/RF3**
— the paired surface needs no requirements entry for the new capability
(paired capabilities admit through the link check with empty blockers, the
exact `policy.py:133-139` mechanism); `_accepted_source` is satisfied by the
existing `accepted → publisher` mapping; the kwargs call shape matches the
design's `execute` signature exactly (probe R14); `receipt_is_valid` accepts
both accepted and `ORIGINAL_ABSENT`-rejected retraction receipts; the
resolution binding check consumes the designed `original_external_id` field
verbatim.

## 5. Alternatives (material)

- **A (RF2 demo structure)** — (a) restructure publish-demo's ending:
  publish → cancel → retraction → crash-recovery → two-id closure, counts
  (1,1); the succeeded-completion ending leaves the demo (coverage remains in
  `tests/test_publishing.py`); installer stage assertions updated in-commit.
  (b) keep completion and add a second article work through the retraction
  flow, counts (2,1); demo longer, completion stays visible. Both bounded;
  (a) is the tighter narrative and matches the draft's asserted counts, (b)
  preserves the existing demo contract exactly. Recommend the master pin (a)
  with an explicit note that `request_completion` coverage moves to tests
  only.
- **B (RF1 pin wording)** — behavior-level identity pin (recommended) vs
  bifurcating the receipt store to preserve literal bytes (rejected: it
  relocates the unavoidable edit into `lookup()`, a shared forward surface,
  and buys nothing the behavior pin does not).

## 6. Recommended master decisions

- **MD-1** Ratify D80–D91 as drafted **except** D87 amended per RF1
  (behavior-level forward-identity pin; the single column-naming INSERT edit
  allowed and disclosed) and D90/§4.10 settled per RF2 (pin demo structure
  alternative (a) or (b), its exact counts, and the installer-stage wording).
- **MD-2** Add to D86: `FakePublisher` contract keeps `"content.publish"`
  first in `actions`, and the retraction receipt id prefix is pinned at
  implementation (RF3).
- **MD-3** Add the RF4 reachability note to Q4's documentation obligation
  (adapter-model limit; governed flow cannot reach the interplay).
- **MD-4** Add `roadmap.md` 0.3 line 33 to the master-owned close-out doc set
  alongside D91's list (RF5).
- **MD-5** Keep D82's byte-unchanged runtime pin as a DoD acceptance check
  with the escalation rule (RF7).

**Exact pin-able decision list for ratification**: D80, D81, D82, D83, D84,
D85, D86 (+MD-2), D87-as-amended (RF1/MD-1), D88, D89, D90-as-settled
(RF2/MD-1), D91 (+MD-4); Q1–Q9 defaults as drafted with Q4 sharpened (MD-3).

## 7. Honest limits of this review

- The probe validates the design's public-API and adapter-store behavior with
  synthetic ephemeral material; it is not the sprint's test suite, and no
  product/test/spec/doc file was modified (this note is the only repo write,
  plus its commit on `WayJ/s14-compensation-design-review` at the candidate
  tip). No merge, no push, no extra agents.
- Concurrent-first-open migration was verified sequentially (double-open
  idempotence, old-store migration); the true interleaved race remains for
  the sprint's tests (the S10 `FakeOA` pattern the design mirrors is already
  race-tested in the shipped suite).
- Doc edits were not drafted here; D91's passages were verified to exist and
  to become stale, and `scripts/check_docs.py`/`test_docs.py` will govern the
  eventual wording. No UI is touched, so no browser check is owed by this
  slice (D90's no-UI claim holds).
- Everything stays trusted-local; this review asserts no fencing,
  distributed-exactly-once, tenant-authentication or production-safety
  property, and the draft's §10 limits were checked to contain no such claim.
