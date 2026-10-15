# SOP rule-card publication — candidate design (DRAFT)

Status: **DRAFT, pending master ratification and the independent design
review the master dispatches next.** This is a candidate design for the
roadmap 0.4 gap *“the publication process itself — authority approvals, an
immutable publication store — is not implemented”*. It allocates no epic,
sprint, ADR or ledger entry; the master owns roadmap and ratification.
Nothing here is implemented. Local decision numbering is `SPD-1…SPD-13`
(no collision with global `D`/MASTER numbers, currently up to D53 from S11 —
recon F20). Grounding evidence — fresh baseline gates at
`56a7f2eaa35693d77bd60bdadf799a0ff9097973`, code cites and public-API
probes P1–P3c — is recorded in the
[recon note](../../../.agents/notes/2026-10-15-s12-design-recon.md); every
code reference below was read on that tree. Findings F1–F20 live in the
recon; the load-bearing subset is cited inline.

## 1. Problem (grounded)

Roadmap 0.4 names the gap verbatim ([roadmap.md](../../roadmap.md), 0.4
paragraph): the S4 slice delivered *“static rule-card linting with exact
content digests and packaged examples”*, while *“the publication process
itself — authority approvals, an immutable publication store — is not
implemented”* (F1). [verification.md](../../verification.md) confirms twice:
the rule-card publication process (RFC-002 §6) is **not implemented**, and
there is *“no link from a linted card to an executing Python policy”* (F2).
What exists today and must be composed, not reinvented:

- **Card identity is already exact.** `sop_digest` is a pure function —
  canonical SHA-256 over a lint-clean card, bounded `ValueError` otherwise
  (`work_runtime/authoring.py:634–650`, F4). Because it reuses
  `policy.digest`, for a clean card `sop_digest(card) ==
  digest(card) == the Runtime's own work["document_digest"]`
  (`runtime.py:359`) — the existing document-digest plumbing already carries
  SOP content identity with zero new machinery (probe P1; F5).
- **An immutable hash-named artifact engine already exists.** `FilePublisher`
  commits one canonical-JSON artifact per idempotency key at
  `<directory>/<sha256(key)>.json` — exclusive stage + fsync + `os.link`
  (atomic, non-overwriting), read-back validation, replay-stable receipts,
  changed-content refusal, corruption → bounded `ValueError`, never rewrite
  (`work_runtime/file_adapter.py:213–294`, F7; 45 tests incl. subprocess
  races and real process death).
- **A governed publish flow already exists in a sibling domain.** The
  content-publication demo runs blocked proposal → HMAC-signed approvals →
  dispatch → response loss → restart reconcile → accepted proof → completion
  (`work_runtime/publishing_demo.py:76–133`, F16), with version-bound
  approval precedent `{"digest", "policy_version"}` from
  `ExpensePolicyV2` (`work_runtime/policy.py:175–181`, F13).
- **Approval signing/verification with rotation already exists.**
  `SignedEvidenceGateway` + per-source keyrings
  (`work_runtime/ingress.py:40–53, 105–142, 246–268`, F15), shipped and
  test-pinned (S11).
- **RFC-002 §6 fixes the intended semantics** (F17): an authorized principal
  approves the *exact content identity*; any later change requires a new
  version; drafts/skill suggestions/chat history cannot become mandatory
  runtime rules. D13: publication determines rule meaning; only the
  publication mechanism may change it.

One doc defect found while grounding: [sop-authoring.md](../../sop-authoring.md)
lines 25–26 still list *“a `lint-sop` CLI”* as later work, but that CLI
shipped with S4 (`cli.py:74–77`, `tests/test_adoption_demo.py:336`,
[verification.md](../../verification.md) S4 coverage) — F3. Repairing that
line is owed to the implementing sprint (docs changes are outside this
dispatch's scope).

## 2. Goals and non-goals

**Goal (smallest useful 0.4 slice):** a rule card can be published as an
immutable, hash-named artifact through the same governed command protocol
every other external effect uses, where publication is admitted only behind
a signed, version-bound approval of the card's exact content digest, and
where a loader can read the store back fail-closed for pinning and audit —
with no changes to `runtime.py`, `ingress.py`, `authoring.py` or the
`FilePublisher` commit machinery beyond one additive read surface.

**Non-goals (explicit):**

- **No external authors, no author-review workflow tooling.** Roadmap 0.4's
  *“external author feedback remains uncollected”* is a separate, unchanged
  gap; this design does not claim any author trial (Q5).
- **No multi-tenant anything.** Approvers and publishers are trusted-local
  principals in `grants` configuration — names, not authentication
  (`runtime.py:3–4`). Signed ingress authenticates *sources* within a
  shared-key boundary, nothing more (F15).
- **No network, no services, no credentials.** Offline, stdlib-only,
  Python ≥ 3.9, `unittest` (AGENTS).
- **No card execution or compilation.** A published card remains a
  reviewable specification with an exact content identity; the Runtime keeps
  running engineered Python policies. No link from card to executing policy
  is created beyond an explicit, operator-run cross-check (SPD-9).
- **No publication withdrawal/tombstone** in this slice (SPD-10); no
  multi-card bundles or SOP composition (RFC-002 §8 open question 4); no
  approval quorum (single configured authority source per family, Q2).
- No UI change, no new global gate, no schema change, no distributed
  exactly-once or security claim anywhere.

## 3. What a rule-card publication IS

A publication is **one committed artifact in an append-only store
directory**, identified by a three-part identity:

| aspect | definition | grounding |
|---|---|---|
| artifact identity | the store key `publication_key(card) = "sop-pub:" + card.policy.id + ":" + card.policy.version`; the committed path is the existing `sha256(key)` hash-name | `file_adapter.py:224–228` (F7); key discipline SPD-3 |
| content identity | `sop_digest(card)` — which equals the Runtime's `work["document_digest"]` for a lint-clean card, so every existing digest-bound mechanism (approvals, operation admission, receipt validation) binds SOP content with no new plumbing | `authoring.py:634–650`, `runtime.py:359`, probe P1 (F4/F5) |
| version | the card's own `policy.version` field, nonempty by lint (`sop-authoring.md` schema). Changed content under the same version is a **conflict**, never a mutation; changed content requires a new version string (RFC-002 §6, F17) | §7 |

The committed artifact is exactly `FilePublisher`'s pinned shape
(`file-adapter.md`): `{"artifact_version": 1, "key": <publication_key>,
"content_digest": <sop_digest>, "document": <the card itself>, "receipt":
{status, external_id, digest}}` — the bare card is the stored document, so
the store needs no new envelope format (SPD-6). What a publication is
*not*: it is not a Policy, not a registry entry, not executed, and not
authority by itself — it is the immutable content of record plus a receipt.

## 4. Who approves

The trusted-local principal model, consistent with grants (F11):

- The publishing policy family declares its authority source in
  `evidence_sources`, e.g. `{"card_approval": "sop-owner", "accepted":
  "sop-store"}` — exactly the reviewer/publisher pattern of
  `PublishingPolicy` (`publishing.py:32–36`). `sop-owner` is a configured
  principal holding `evidence.write` in `grants`; naming it confers no
  authentication (F11, AGENTS trust rules).
- An approval is **evidence, not a grant check**: it must be a signed
  envelope of kind `card_approval` whose `data` is exactly
  `{"digest": <sop_digest>, "policy_version": <card version>}` — the
  version-bound shape already proven by `ExpensePolicyV2` (F13). A missing,
  wrong-digest or wrong-version approval leaves requirement S02 pending and
  blocks the publish proposal (`REQUIREMENT_UNSATISFIED`), mirroring C02
  (`publishing.py:82–87`).
- One approving source per family in this slice (the `evidence_sources`
  map is single-source per kind, `policy.py:21`). Quorum/multiple approvers
  is explicit future work (Q2).
- The store's acceptance is *not* approval: the Runtime writes the
  `"accepted"` proof itself when resolving the confirmed effect (F12), under
  the family's `accepted` source — signed ingress keeps refusing that kind
  (`ingress.py:26, 318–319`).

## 5. What “immutable” means here

Append-only, hash-named, never mutated, trusted-local — inherited wholesale
from `FilePublisher` (F7) rather than re-invented:

- **Append-only:** a commit is an atomic `os.link` onto a never-existing
  path; there is no rename fallback and no overwrite anywhere
  (`file_adapter.py:266–275`). Crashes leave only ignorable `.stage` files.
- **Hash-named:** the publication key never touches the filesystem as a
  path; `sha256(key UTF-8)` bounds every basename to 64 hex
  (`file_adapter.py:224–228`).
- **No mutation:** replay of the same key + content returns the byte-identical
  winning receipt; same key + changed content is a bounded `ValueError` with
  zero side effects; any corruption found on read is a bounded `ValueError`
  and the file is never rewritten (probe P2/P2b, F7/F9).
- **Reuse vs new store (SPD-2):** the engine is `FilePublisher` **unchanged**.
  A thin `SopPublicationStore` wrapper (the `ResponseLossPublisher`
  composition pattern, `adoption_demo.py:243–255`) declares its own contract
  with `actions=("sop.publish",)` and delegates `execute`/`lookup`
  verbatim — so dispatch's action check (`runtime.py:1029–1036`) admits the
  new capability without touching the pinned adapter or its conformance
  tests. A new store module or SQLite store is rejected (§9).

Boundaries inherited as-is ([file-adapter.md](../../file-adapter.md)): the
directory is trusted local configuration; no hostile-filesystem, symlink,
power-loss or distributed exactly-once claim; hardlink support required;
best-effort directory fsync.

## 6. How the runtime and policies relate to published cards

The governed side and the read side are deliberately different surfaces:

**Governed publication (write path).** A `SopPublicationPolicy` family
(`id "sop-publish"`, goal `sop.published`, capability `sop.publish`) rides
the unchanged command protocol in its own database (one policy family per
database, F15/interventions.md): `create_work` with the card as the work
document → `bind_contract` → signed `card_approval` via the unchanged
gateway → `verify_pending` → `propose_action` → `dispatch` through
`SopPublicationStore` → `reconcile` on uncertainty → `request_completion`.
Requirements mirror the publishing domain: **S02** approval of the current
content digest (C02's shape) and **S03** store acceptance of the current
content (C04's shape, excluded from blockers like C04,
`publishing.py:94–100`). Card admission enforces lint through
`validate_document` (SPD-4): a dirty card is unpersisted API misuse
(`ValueError`), the house convention for malformed documents
(`policy.py:53–73`, `runtime.py:354`) — the lint workflow itself stays with
`lint-sop` where it lives today.

**Loading and pinning (read path, SPD-9).** New pure-ish functions, no
Runtime wiring:

- `publication_key(card)` and `load_published_card(directory, policy_id,
  policy_version)`: reads the hash-named artifact through a new additive
  `FilePublisher.read_validated(key)` (SPD-8 — the validation already
  exists as `_validated_artifact`, `file_adapter.py:167–200`), re-lints the
  stored card, recomputes `sop_digest` and checks it against the stored
  `content_digest` and receipt. Absent version, corrupt bytes, digest
  mismatch or key mismatch → bounded fail-closed error; **no fallback, no
  silent skip**.
- `pinned_card(directory, policy_id, policy_version, expected_digest)`:
  additionally requires the recomputed digest to equal the pin — the
  operator-side check that the engineered Python policy version being loaded
  corresponds to the published card of record.
- `published_card_matches(card, policy)`: structural cross-check of
  `(id, version, goal)` between a published card and a Python policy object.
  Capabilities have no runtime counterpart today (grants decide execution
  authority, F11) and are not compared — stated, not hidden.

**Fail-closed without the store:** `load_published_card`/`pinned_card`
raise; nothing degrades to an unpinned card. This deliberately stops short
of making the Runtime itself consult the store at construction — that would
create a card→policy binding the repo explicitly disclaims
([contributor-guide.md](../../contributor-guide.md) §“Static lint is not
executable authority”, F2/F6). Registry semantics for *executing* policies
remain the existing constructor registry with per-work pinning and
fail-closed reopen (F14, probes P3/P3c).

## 7. Replay, idempotency and conflict handling

Three existing layers compose; the design adds none:

1. **Command dedup:** `(actor, command_id)` replay returns the stored
   receipt while authority holds; changed content under the same command id
   is `COMMAND_ID_REUSED` (`runtime.py:263–272, 298–338`, F10).
2. **Operation convergence:** `SopPublicationPolicy.operation_key` returns
   `publication_key(work["document"])` — the *store key is the business
   key*. Re-proposing the same card converges on the same operation
   identity; a response-lost dispatch is resolved by reconciling the
   original key, never resent (F16). Consequence (SPD-13): a second work
   proposing the same card hits the existing business-key rule — same
   digest, different `work_id` → persisted `OPERATION_CONTENT_CONFLICT`
   (`runtime.py:686–690`); a doctored card with the same
   `(policy_id, version)` → different digest → persisted
   `OPERATION_CONTENT_CONFLICT` too. One publication identity per card
   version per database is intended semantics, pinned by tests.
3. **Store replay:** same publication key + same content → identical
   winning receipt across processes and restarts; same key + changed
   content → `ValueError`, zero overwrite (probe P2/P2b). A malformed
   stored result quarantines as `outcome_unknown` +
   `ADAPTER_RESULT_INVALID` with the work in `needs_attention` — explicit
   truth, never an overwrite (`runtime.py:1145–1150`, F16).

So *same card id + version + different content* is refused at three
independent layers (proposal, command id, store), each leaving the
committed artifact untouched.

## 8. Approval evidence: signing and verification

Reuse `sign_evidence` + `SignedEvidenceGateway` verbatim (F15): the approver
signs `{source, command_id, work_id, event_id, kind: "card_approval", data:
{digest, policy_version}, issued_at}` with the family's configured key;
the gateway authenticates (HMAC-SHA256 over canonical bytes,
`hmac.compare_digest`), checks freshness on one clock sample, and forwards
only `{event_id, kind, data}` to `record_evidence` — signature, timestamp
and `key_id` are never persisted. Rotation applies unchanged: configure the
approver as an S11 keyring, rotate by reconstruction; fingerprints are
key-agnostic so rotating the approver's key never withdraws an accepted
approval, and an expired replay is refused before the Runtime is involved
([signed-evidence.md](../../signed-evidence.md) rotation section, F15).
The approval binds the exact content because `data.digest` must equal the
work's current `document_digest` (== `sop_digest`) to satisfy S02 — the
same digest-bound invalidation that makes `revise_document` on the card
re-require approval (the C02/T05 pattern, `publishing.py:60–92`).

## 9. Alternatives considered (rejected options)

| alternative | why rejected |
|---|---|
| Direct trusted-local publish API (lint → verify → commit, no Work) | loses the durable command ledger, CAS, replay receipts and blocked-proposal story — the project's core accountability promise; parallel semantics to every other external effect |
| New dedicated store module / SQLite publication store | duplicates commit, race, corruption and recovery machinery that `FilePublisher` already ships test-pinned (subprocess races, real process death); a second store truth for no new guarantee |
| Extending `FilePublisher.contract.actions` in place to add `sop.publish` | touches a pinned adapter, its doc and conformance tests; a delegating wrapper isolates the blast radius (SPD-2) |
| Content-digest addressing as the store key | different content ⇒ different key ⇒ same `(id, version)` conflicts silently coexist as two artifacts; identity addressing is what makes §7's three-layer conflict detection work (SPD-3) |
| Extending the card schema with an approvals field | breaks the exact lint schema (`UNKNOWN_FIELD`), pollutes the review artifact with workflow data, and duplicates what the evidence store already records (SPD-6) |
| Approvals as a grants-only check (no signatures) | no exact-content binding, no rotation path, weaker than the existing ingress the project already trusts; version-bound signed evidence is the proven pattern (F13/F15) |
| Dirty cards admitted with a persisted S01 lint blocker | diverges from the house document-gate convention and lets unreviewable content occupy the publication workflow; lint stays at admission + CLI (SPD-4) |
| Runtime consulting the store at construction (auto card→policy binding) | contradicts the documented non-claim that linted cards are not executable policy; pinning stays an explicit operator check (SPD-9, Q3) |
| Publication withdrawal/tombstones now | a real withdrawal design (à la S8 evidence revocation) deserves its own slice; premature here (SPD-10, Q4) |

## 10. Rollback limits (honest)

- **There is no un-publish.** The store is append-only; “rolling back” a
  publication means publishing a corrected new version. Deleting or editing
  committed files is operator misuse outside the trust boundary — the
  loader's validation turns a tampered store into fail-closed errors, not
  into silently altered policy (SPD-9).
- **Approval revocation does not reach the store.** Revoking the
  `card_approval` proof (S8 machinery, F18) withdraws its current validity
  in the runtime database and re-blocks requirements, but the committed
  artifact stands; whether a *published version* can be withdrawn — and
  what that means for works already bound — is separately designed future
  work (Q4).
- **No history rewrite anywhere:** receipts, proofs, events and closure
  snapshots are immutable in the existing protocol; the publication store
  inherits the same discipline (F7, F10).

## 11. Proposed sprint shape (pending master ratification)

One bounded sprint, two waves (S11 precedent), `wip_limit 1`, TDD with
recorded RED/GREEN evidence per AGENTS/supervibe. Master assigns global
D-numbers (next free: D54) to the ratified SPD subset.

**Decisions pending ratification:** SPD-1 governed-protocol shape · SPD-2
wrapper-over-FilePublisher store · SPD-3 identity publication key · SPD-4
lint at admission · SPD-5 version-bound signed `card_approval` · SPD-6 bare
card as stored document · SPD-7 wrapper contract uniqueness wording ·
SPD-8 additive `FilePublisher.read_validated` · SPD-9 loader/pin functions,
no Runtime wiring · SPD-10 no withdrawal · SPD-11 `publication-demo` +
installer stage, no new global gate · SPD-12 doc set + master-owned
doc_sync_map rows · SPD-13 cross-work `OPERATION_CONTENT_CONFLICT` as
intended semantics.

**Story breakdown:**

1. **Store + read surface:** `FilePublisher.read_validated(key)` (additive);
   `publication.py`: `publication_key`, `SopPublicationStore` wrapper with
   declared contract; store replay/conflict tests (direct adapter level).
2. **Loader/pin:** `load_published_card`, `pinned_card`,
   `published_card_matches` + fail-closed matrix tests.
3. **Governed flow:** `SopPublicationPolicy` (S02/S03, operation_key =
   publication key, admission lint) + grants shape; blocked proposal,
   signed-approval verification, dispatch/reconcile/completion,
   replay-and-conflict tests through the real Runtime.
4. **Rotation interaction:** approver configured as keyring; rotate
   mid-flow; old-key refusal, cached-receipt verbatim replay, dedupe to
   same evidence identity (test_key_rotation discipline).
5. **Demo wave:** `publication-demo` CLI (`cli.py` subcommand), end-to-end
   assertions against the real artifact and SQLite, `verify_install.py`
   stage, bilingual README mention.
6. **Docs:** [sop-authoring.md](../../sop-authoring.md) publication
   sections rewritten (incl. the F3 stale-CLI repair),
   [verification.md](../../verification.md) coverage rows,
   [file-adapter.md](../../file-adapter.md) `read_validated` note; master
   adds doc_sync_map rows at ratification (workers never edit the
   agreement — SKR-9 precedent).

**Acceptance scenario sketch (the runnable story):** dirty fixture card →
`lint-sop` exit 1 diagnostics; packaged card lint-clean with pinned digest
→ publication work created (card = document) → proposal BLOCKED (S02
pending) → tampered approval rejected `EVIDENCE_AUTHENTICATION_FAILED`
with zero intake writes → valid signed `{digest, policy_version}` approval
verified → intent accepted → dispatch commits exactly one hash-named
artifact, response lost after commit → restart, reconcile the original key
→ `confirmed_succeeded`, one attempt, accepted proof written by the
Runtime → completion `closed/succeeded` → doctored same-version card →
persisted `OPERATION_CONTENT_CONFLICT`, artifact unchanged → loader
returns the card with matching digest; absent version and tampered file
fail closed → approver key rotated: old-key envelope refused, publication
history untouched. All five existing gates green; no new global gate.

## 12. TDD-shaped test implications (list only — no tests written here)

- `tests/test_publication.py`: admission gate (dirty card → bounded
  unpersisted error; clean card with `document_digest == sop_digest`);
  S02 blocking incl. wrong-digest/wrong-version approvals; wrong-source
  intake `AUTHORITY_DENIED`; full governed flow with real SQLite +
  directory; response-loss recovery (one attempt, nothing resent); accepted
  proof under the configured source with `event_id` = operation id;
  completion; artifact assertions (key = publication key, document =
  card, receipt digest = sop_digest, exactly one `.json`, zero `.stage`);
  command replay verbatim; cross-work and doctored-card
  `OPERATION_CONTENT_CONFLICT`; store-level same-key-different-content
  `ValueError` with no overwrite.
- `tests/test_file_adapter.py` (additive): `read_validated` returns the
  full validated artifact; existing corruption matrix applies.
- `tests/test_publication_rotation.py` (or folded): keyring approver —
  pre-rotation envelope refused after rotation (`EVIDENCE_KEY_RETIRED`
  retained / `EVIDENCE_AUTHENTICATION_FAILED` dropped), same-`command_id`
  re-sign returns the original receipt verbatim, new `command_id`/same
  `(source, event_id)` reports current status; six-table history
  preservation.
- `tests/test_publication_demo.py`: demo end-to-end (artifact enumeration,
  restart reconcile, printed `inspect` command verbatim), CLI usage,
  secret-echo hygiene (planted-marker discipline).

## 13. Open questions (each with a default recommendation)

| # | question | default |
|---|---|---|
| Q1 | Should the committed artifact embed approval identities (envelope v2)? | **Defer.** The runtime evidence store is the approval audit; the artifact is content of record. Embedding needs a wider adapter surface or envelope format — design then, not now (SPD-6). |
| Q2 | Multiple approving authorities / quorum? | **Single configured source per family now** (`evidence_sources` is single-source per kind); quorum is a real authority-model change, separately designed. |
| Q3 | Should Runtime construction verify executing policies against the store? | **No** — explicit operator check via `pinned_card`; automatic wiring would create the card→policy binding the docs disclaim (SPD-9). |
| Q4 | Publication withdrawal in a follow-up sprint? | **Yes, separately designed** on the S8 evidence-revocation model (withdraw current validity, never rewrite history); not this slice (SPD-10). |
| Q5 | Does this sprint owe 0.4's “external author feedback”? | **No** — a local prototype cannot collect it; the design keeps the boundary stated (§2). |
| Q6 | Version-string discipline for `policy.version`? | **Nonempty string, operator discipline** (lint already enforces nonempty); no semver machinery. |
| Q7 | Where does the demo's approver principal live in grants docs? | **Demo-local** (`{"agent": {"work.manage", "sop.publish"}, "sop-owner": {"evidence.write"}}`), mirroring `publishing_grants()` (F11). |

## 14. Honest limits

- Publication here is **trusted-local governance, not security**: the
  approver is a configured name with a shared-key signature; any key holder
  can sign as that source; the store directory is trusted configuration
  with no hostile-filesystem or power-loss guarantee (inherited
  [file-adapter.md](../../file-adapter.md) boundaries). No tenant
  authentication, TLS, KMS, non-repudiation or production-safety claim.
- **No card becomes executable.** The published card is the reviewable
  specification and content identity of record; correspondence to an
  executing Python policy is an explicit operator cross-check, partial by
  design (id/version/goal only — capabilities have no runtime counterpart).
- **The approval audit and the artifact are separate stores** (runtime
  database vs directory); a store-only reader sees content identity, not
  who approved (Q1). One runtime database serves one policy family, so one
  publication ledger per family per database.
- **Rollback is versioned forward only** (§10); approval revocation after
  publication leaves the artifact standing until a withdrawal design
  exists. Concurrent cross-process same-key commits follow `FilePublisher`'s
  race semantics (one winner; losers get the winner's receipt or a bounded
  refusal).
- **Grounding limits of this document:** every factual claim carries a
  file:line or probe reference read at `56a7f2e`; everything else is
  recommendation. The API shapes in §3–§8 are candidate sketches, not
  implemented or test-verified code. External author usability (RFC-002 §8
  question 1) remains untested. This draft self-ratifies nothing — the
  master's ratification and the independent review it dispatches are the
  counterweight (recon §5).

## MASTER ratification - 2026-10-15 D54-D66 (before implementation)

Ratified on the independent review
[61b50fc](../../../.agents/notes/2026-10-15-s12-independent-design-review.md)
(verdict: implementable with amendments; 31/31 probes, live end-to-end run of
§6, counter-probes IR-P16/P17). The DRAFT body above is ratified **as
amended** by this section; where they differ, this section governs.

- **D54** (=SPD-1) Governed-protocol shape: publication is a governed
  `sop.publish` policy-family Work riding the unchanged command protocol and
  `SignedEvidenceGateway` — zero changes to `runtime.py`/`ingress.py`/
  `authoring.py`/`FilePublisher` semantics.
- **D55** (=SPD-2) Thin `SopPublicationStore` wrapper delegating to
  `FilePublisher` unchanged (adoption-demo wrapper precedent).
- **D56** (=SPD-3, **amended per IR-F1 — replaces the drafted key**): the
  publication key is collision-free by construction,
  `publication_key = "sop-pub:" + digest([policy_id, policy_version])` (the
  Runtime's own compensation-key pattern). The drafted delimiter-joined key
  is **rejected**: IR-P16 proved two lint-clean cards colliding on it. All
  keys/receipts/loaders use the digest form from the first commit.
- **D57** (=SPD-4) Lint at admission: dirty card ⇒ bounded unpersisted
  `ValueError`; clean card ⇒ `work.document_digest == sop_digest(card)`.
- **D58** (=SPD-5) Version-bound signed `card_approval` `{digest,
  policy_version}`; tampered ⇒ `EVIDENCE_AUTHENTICATION_FAILED` with zero
  intake writes; wrong-version ⇒ candidate-but-unsatisfied.
- **D59** (=SPD-6) The stored document is the bare card; the runtime
  evidence store is the approval audit (Q1 defer ratified).
- **D60** (=SPD-7) Wrapper contract declares keyed uniqueness; conflict
  layers are the three verified ones (proposal business-key, command-id
  reuse, store refusal).
- **D61** (=SPD-8 + IR-F4 pin) Additive `FilePublisher.read_validated(key)`:
  returns `None` for an absent key (mirroring `lookup`); corrupt artifact ⇒
  bounded `ValueError`; `load_published_card` converts absence into its own
  bounded fail-closed error so corrupt and absent stay distinguishable.
- **D62** (=SPD-9, Q3 default ratified) Loader/pin functions only —
  `load_published_card`, `pinned_card`, `published_card_matches` — with **no
  Runtime wiring** and no card→policy compilation: published cards never
  execute.
- **D63** (=SPD-10, Q4 default ratified) No withdrawal in this slice; a
  follow-up designs it separately on the S8 revocation model.
- **D64** (=SPD-11) `publication-demo` + installed module/console stage as
  existing installer evidence — **no new global gate**; rehearsal set
  untouched.
- **D65** (=SPD-12) Doc set per story 6 (sop-authoring.md publication
  sections incl. the stale-CLI repair at lines 25–26, verification.md
  coverage, file-adapter.md `read_validated` note, IR-F5's correction to
  51 loader-counted file-adapter test cases); the master adds the
  `doc_sync_map` rows in the same ratification act (workers never edit
  AGENTS.md — SKR-9 precedent).
- **D66** (=SPD-13 + IR-F3 pin) Cross-work same-version/doctored content ⇒
  persisted `OPERATION_CONTENT_CONFLICT` is intended semantics, with the
  order pinned: `_propose` checks requirement blockers **before** the
  business-key branch, so the conflict surfaces only after the second work
  carries its own verified approval — tests pin this order.

**§8 re-framed per IR-F2 (overrides the drafted `revise_document`
sentence):** within a publication work the card document is effectively
immutable — `revise_document` requires a top-level `document["id"]` which
cards do not have (IR-P17 `KeyError`); content changes enter as **new
works**, same-version doctored content is refused by `OPERATION_CONTENT_CONFLICT`
(after the second work's approval, D66), and legitimate change requires a
new version string — exactly RFC-002 §6. No `runtime.py` change is
authorized for this.

**Ratified defaults:** Q1 defer · Q2 single configured source per family ·
Q3 no Runtime wiring · Q4 withdrawal as separately-designed follow-up · Q5
no external-author-feedback obligation · Q6 nonempty-string version
discipline · Q7 demo-local grants mirroring `publishing_grants()`.

**MD-3 wave split:** wave 1 = stories 1–4 (store/read surface, loader/pin,
governed flow, rotation interaction); wave 2 = stories 5–6 (demo+installer,
docs). `wip_limit 1` throughout.

**MD-4 boundary:** IR-F7 — two runtime databases sharing one store
directory fail closed at reconcile (`ADAPTER_RESULT_INVALID` +
`needs_attention`, no overwrite) — is an **accepted operator-discipline
boundary**, recorded in the sprint report, not new machinery.

No tenant authentication, TLS, external KMS, network, external authors,
multi-tenant or security-certification claim is made or implied; grants are
trusted-local names and ingress authenticates sources within a shared-key
boundary (S11 limits unchanged).
