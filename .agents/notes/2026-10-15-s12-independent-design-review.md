# S12 independent design review — SOP rule-card publication DRAFT (2026-10-15)

Independent builder-check dispatched by the master. **Review only:** this note
is the sole write of this dispatch; no product/test/spec edits, no merge/push,
no ratification. The master owns ratification (D-number allocation, doc_sync_map).

## 0. Scope, method, commits

- Candidate DRAFT: [2026-10-15-sop-publication-design.md](../../docs/superpowers/specs/2026-10-15-sop-publication-design.md)
  read in full at `WayJ/s12-publication-design` tip `e18851a`
  (`git rev-parse` verified equal to this checkout's HEAD). Recon:
  [2026-10-15-s12-design-recon.md](2026-10-15-s12-design-recon.md) read in full
  on the same commit.
- Ground truth: extraction of baseline `56a7f2eaa35693d77bd60bdadf799a0ff9097973`
  via `git archive` into a temp directory; every load-bearing claim checked
  against that tree (`git show` / file reads); the repo itself untouched.
- Fresh probe suite (IR-P1…IR-P31, this review): public API only, `/tmp`
  synthetic ephemeral stores, secrets generated in-process and never printed;
  probe stores deleted. The suite (a) re-proves the recon's P1–P3c results,
  (b) executes the DRAFT §6 write path end-to-end with an inline sketch of the
  proposed `SopPublicationPolicy` + wrapper store against the real Runtime,
  and (c) runs three counter-probes aimed at hunted weaknesses (key collision,
  conflict ordering, `revise_document` on cards).
- Baseline gates re-verified independently: `Ran 874 tests … OK (skipped=3)`.
- Finding numbering below is `IR-F*` — a namespace separate from the recon's
  F1–F20.

## 1. Verdict

**Implementable with amendments.** The core architecture is sound and I proved
it live: the entire §6 governed write path (card as work document → admission
lint → blocked proposal → signed version-bound approval → dispatch through a
wrapper declaring `sop.publish` → runtime-written accepted proof → completion)
works on the unmodified baseline with zero changes to `runtime.py`,
`ingress.py`, `authoring.py` or `FilePublisher` (IR-P1–IR-P13). No safety or
security hole was found; immutability, fail-closed and refusal semantics all
check out. Two drafted decisions need amendment before ratification
(IR-F1 key collision in SPD-3; IR-F2 wrong grounding for `revise_document` in
§8), and three precision notes should ride along (IR-F3…IR-F5).

## 2. Load-bearing claims — verification matrix

| claim (DRAFT/recon) | result | evidence at 56a7f2e |
|---|---|---|
| `sop_digest == digest(card) == work["document_digest"]` for lint-clean cards | **verified** | `authoring.py:13,650` imports `policy.digest` as `_canonical_digest`; `runtime.py:16,359`; IR-P1a–c: packaged expense card digest `4876285f…7627` (matches recon), equals `policy.digest` and a real `create_work` document_digest |
| `FilePublisher` commit machinery: exclusive stage + fsync + `os.link`, no rename/overwrite, read-back validation, changed-content refusal, corruption → bounded `ValueError` | **verified** | `file_adapter.py:203–294` (contract 213, `_path_for` 224, `execute` 249, `lookup` 286), `_validated_artifact` 167–200 recomputes digest from stored bytes; keys/receipt sets at 29–30; race/death pins real: `tests/test_file_adapter.py:605–690` (same-key race, mixed-content race, death before link, death after commit). Loader count: 45 in-file `def test` + 6 inherited conformance cases = **51** test cases (recon "45" and verification.md "50" both imprecise — IR-F5) |
| replay/refusal store behavior | **verified** | IR-P18a–d reproduce recon P2/P2b/P2c byte-for-byte behavior (verbatim receipt replay; `ValueError` "idempotency key is already committed with different content"; different key → second artifact) |
| `SignedEvidenceGateway` + keyrings + rotation | **verified** | `ingress.py:26,40–53,105–142,246–268` (`SourceKey`, exactly-one-current, immutable tuple), `_select_key` no-try-all/no-fallback, one clock sample, freshness ±max_age, `RESERVED_KIND="accepted"` refused at 318–319; [signed-evidence.md](../../docs/signed-evidence.md):159–161 fingerprints key-agnostic; IR-P19a–d: pre-rotation acceptance, same-command_id re-sign under new key → **verbatim** stored receipt, cited retired key → `EVIDENCE_KEY_RETIRED`, removed key → `EVIDENCE_AUTHENTICATION_FAILED` |
| version-bound approval precedent `{digest, policy_version}` | **verified** | `policy.py:175–181` (`ExpensePolicyV2.validate_evidence`); migration revalidation `verified→invalid` never reverse (`runtime.py:602–613`) |
| grants/authority model (names not authentication) | **verified** | `runtime.py:3–4` docstring; `command` actor-in-grants 261–262; `record_evidence` source+`evidence.write` 775–777; propose owner+capability 639–644; dispatch re-check 1020–1029; admin = `work.intervene` 455–456 |
| registry pin/fail-closed | **verified** | `runtime.py:62–89` (`_validated_registry`: same family, key=version, default-maps-to-default-object — the exact rule recon P3 tripped); `_policy_for`/`_work` fail-closed 163–185 |
| command protocol Work shape (dedup, CAS, replay-while-authority) | **verified** | `runtime.py:250–292,298–338`: fingerprint `digest([work_id, kind, payload, expected_version])`, `COMMAND_ID_REUSED` on mismatch, `_replay_denial` returns fresh unpersisted rejection when authority lost |
| stale `sop-authoring.md:25` CLI claim (recon F3) | **verified stale** | doc lines 25–26 say a `lint-sop` CLI is "later sprint work"; `cli.py:74–77` ships it; `tests/test_adoption_demo.py:336` `LintCliUsageTests`; exit trio documented at verification.md:78 |
| publishing-domain pattern cites | **verified** | `publishing.py:32–36` sources map, 60–92 C02/C04 digest-bound blockers, 94–100 C04 excluded, 117–122 `FakePublisher` `uniqueness=("document.id+content_digest",)`; `publishing_demo.py:24–26,76–133` full blocked→signed→dispatch→lost→reconcile→completion flow |
| wrapper composition precedent | **verified** | `adoption_demo.py:243–255` `ResponseLossPublisher` (contract surfaced, delegate untouched); `_declared_contract` at `runtime.py:31–39` makes a present-but-invalid contract fail visibly |
| roadmap/verification gap statements (F1/F2) | **verified** | roadmap.md 0.4 verbatim; verification.md:445 "not implemented", :452 "no link from a linted card to an executing Python policy" |
| RFC-002 §6 semantics (F17) | **verified** | §6 lines 129–149: authorized principal approves exact content; later change ⇒ new version; drafts/suggestions/chat cannot become rules |
| D53 as current global numbering (F20) | **verified** | S11 acceptance "MASTER D49–D53" |

## 3. Probe log (IR-P*, this review; all 31 pass)

| # | probe | result |
|---|---|---|
| IR-P1a–c | identity chain end-to-end | `sop_digest(packaged expense) = 4876285f…7627` = `policy.digest` = `create_work` `document_digest` |
| IR-P4 | dirty card `create_work` | unpersisted `ValueError` "card is not lint-clean: 1 diagnostic(s); first: EMPTY_VALUE" (SPD-4 admission) |
| IR-P5 | proposal before approval | persisted `REQUIREMENT_UNSATISFIED` (S02 pending, C02 shape) |
| IR-P6 | tampered approval (`data.digest` flipped post-signing) | `EVIDENCE_AUTHENTICATION_FAILED`, evidence row count unchanged (zero intake writes) |
| IR-P7 | wrong-version approval | intake accepted as candidate; `verify_pending` → not satisfied; proposal still blocked |
| IR-P8 | valid `{digest, policy_version}` approval | verified; proposal accepted |
| IR-P9 | dispatch via wrapper `actions=("sop.publish",)` delegating to real `FilePublisher` | `confirmed_succeeded` — SPD-2's isolation mechanism works against the unchanged action check (`runtime.py:1035–1043`) |
| IR-P10 | accepted proof | runtime-written: kind `accepted`, source `sop-store` (absent from grants, correctly), `event_id` = operation id, `data.digest` = card digest |
| IR-P11 | store directory | exactly one 64-hex `.json`, zero `.stage` |
| IR-P12/12b | loader sketch via validation path | stored document **is the bare card**; `sop_digest(stored card)` equals stored `content_digest` and receipt digest (SPD-6 + §6 re-lint path) |
| IR-P13/13b | `request_completion` | `closed/succeeded` |
| IR-P14/P15 | cross-work same card / doctored same-version card | persisted `OPERATION_CONTENT_CONFLICT` — **but only after the second work carries its own verified approval** (see IR-F3) |
| IR-P16a–e | **key-collision counter-probe** | cards `("collide:one","v1")` and `("collide","one:v1")` are both lint-clean (no charset restriction: `authoring.py:154–161`), share `publication_key` `sop-pub:collide:one:v1`, have different digests; second one blocked `OPERATION_CONTENT_CONFLICT` (IR-F1) |
| IR-P17 | `revise_document` on an open card work | `KeyError: 'id'` — card root fields are exactly `{schema_version, policy, defaults, facts, collections, rules, advice}` (`authoring.py:36–37`); the only `document["id"]` consumer in `runtime.py` is the revise branch at 402–408 (IR-F2) |
| IR-P18a–d | `FilePublisher` direct | verbatim replay / changed-content `ValueError` / distinct-key second artifact |
| IR-P19a–d | rotation interactions | pre-rotation approval accepted pending; **same command_id re-signed under the rotated key replays the stored receipt verbatim**; cited key past `not_after` → `EVIDENCE_KEY_RETIRED`; removed key → `EVIDENCE_AUTHENTICATION_FAILED` (selector-less legacy envelopes verify against the current entry only — §12's wording should be read this way) |

## 4. Findings

### IR-F1 — Medium — SPD-3 as drafted allows store-key collisions between distinct cards
`publication_key = "sop-pub:" + card.policy.id + ":" + card.policy.version`
is delimiter-ambiguous. The card lint enforces only nonempty strings for
`policy.id`/`policy.version` (`authoring.py:154–161`, applied at 182–184) —
colons are legal. IR-P16 shows two distinct, lint-clean cards colliding on one
key with different digests; the governed protocol then refuses the second with
a persisted `OPERATION_CONTENT_CONFLICT`. Safety holds (fail-closed refusal,
zero overwrite — the store layer and receipt validation both refuse), but a
legitimate card can be made unpublishable by content the publisher does not
control, which contradicts §7's stated intent that the key identifies exactly
one card version. **Amendment (required):** derive the key collision-free —
e.g. `"sop-pub:" + digest([policy_id, version])`, the house pattern already
used by the Runtime's own compensation key (`runtime.py` `digest([policy.id,
capability, compensation_of])`, verified at the forward/compensation key
branch). Human-greppability of the caller key is cosmetic: the committed path
is `sha256(key)` either way, and §6's loader always recomputes the key from
the requested `(policy_id, version)`. See §5 alternatives.

### IR-F2 — Medium — §8's `revise_document` grounding is wrong for card documents
§8 claims approval invalidation mirrors "the C02/T05 pattern" via
`revise_document` on the card. `revise_document` requires a top-level
`document["id"]` (`runtime.py:405`); cards have no top-level id (exact root
field set, `authoring.py:36–37`), and IR-P17 shows the command crashing with
`KeyError: 'id'` on an open card work. The design itself promises no
`runtime.py` changes, so this path cannot be repaired in-slice. The
digest-bound invalidation **mechanism** is real and verified (evidence binds
to the current `document_digest`); what must change is the framing: within a
publication work the card document is effectively immutable (no usable
revision command), content changes enter as **new works**, same-version
doctored content is caught by `OPERATION_CONTENT_CONFLICT` (after the second
work's approval, IR-F3), and legitimate changes require a new version string —
which is exactly RFC-002 §6's model. The §11 scenario and §12 test list never
call `revise_document`, so no scenario text changes; §8's sentence and any
implementer guidance must be amended so story 3 does not pin a test against a
`KeyError`. (Note: `get_work`/inspection/UI have no other `document["id"]`
assumptions — verified by grep — so card documents are safe everywhere else.)

### IR-F3 — Low — conflict detection is masked by requirement blockers; pin the order
`_propose` checks `action_blockers` (`runtime.py:681–686`) **before** the
business-key branch (`runtime.py:687–690`). IR-P14/P15: an unapproved second
work gets `REQUIREMENT_UNSATISFIED`; only after recording and verifying that
work's own `card_approval` does the persisted `OPERATION_CONTENT_CONFLICT`
surface. §11's scenario ("doctored same-version card → persisted
OPERATION_CONTENT_CONFLICT") implicitly includes approving the doctored card.
Add one sentence to §7/§11–§12 so the tests pin this order instead of
discovering it.

### IR-F4 — Low — SPD-8 leaves `read_validated`'s absent-key behavior unpinned
`_validated_artifact` exists exactly where SPD-8 says (`file_adapter.py:167–200`)
and a private `_read_validated` already exists (244–247), so the additive
public method is real. But `lookup` returns `None` for a missing key while the
loader must "fail closed on absent version" — whether `read_validated`
returns `None` or raises for an absent key is unspecified. Either is
implementable; pin one (recommend `None` for absent, mirroring `lookup`, with
`load_published_card` converting absence into its bounded fail-closed error,
keeping "corrupt" and "absent" distinguishable for operators).

### IR-F5 — Info — test-count citations are slightly off (opportunistic fix)
Recon F7 says test_file_adapter has "45 tests"; verification.md:78 says "50".
Verified by loader: **51 test cases** (45 in-file `def test` methods + 6
inherited from `AdapterConformanceMixin`). Immaterial to the design; the
planned story-6 verification.md/file-adapter.md edits can correct the number
in passing.

### IR-F6 — Info — rotation language must stay inside the S11 boundary
[signed-evidence.md](../../docs/signed-evidence.md):214–220: key state lives
only in the keyring configuration — recreating a pre-rotation ring revives the
old secret; there is no persistent revocation memory. The DRAFT's §8 claims
("rotate by reconstruction") already respect this; story 4's tests should keep
asserting configuration-bound behavior only (IR-P19c/d show the two refusal
codes depend on key presence and `not_after` vs the verification clock, and
that selector-less envelopes verify against the current entry only).

### IR-F7 — Info — cross-database store sharing fails closed (verified acceptable)
If two runtime databases ever share one store directory, the second same-key
commit raises at the adapter → `outcome_unknown`; reconcile reads the
committed receipt whose digest differs from the operation's →
`ADAPTER_RESULT_INVALID` + `needs_attention` (`runtime.py:1105–1150`). No
overwrite, explicit truth. No action needed; recording it as the verified
answer to the "coverage holes" hunt.

**Hunt items with no findings:** digest/canonicalization (single `policy.canonical`
end-to-end: card → admission → store snapshot → loader re-lint; floats/ints
bounded by loader + `_snapshot_document`; no double-encoding path exists);
approval replay/rotation (all four interactions verified, §8 accurate);
schema/deps (artifact stays `artifact_version` 1 within pinned `_ARTIFACT_KEYS`;
no table, gate or dependency changes); UI/lifecycle (no UI change claimed and
none needed; `ui_server`/inspection have no card-shaped assumptions;
runtime-written accepted proof needs no grants — IR-P10); overclaiming (§14's
limits match the code's actual boundaries — grants are names, ingress
authenticates sources within a shared-key boundary, store is trusted-local);
two-wave boundedness (six stories with crisp artifacts and test files, clear
dependency order 1→3→4→5, comparable in size to the S4/S11 precedents —
bounded as claimed).

## 5. Alternatives (material)

**A (recommended) / B for IR-F1 (publication key encoding):**
- **A. Digest-based key:** `publication_key = "sop-pub:" + digest([policy_id,
  version])`. Collision-free by construction; matches the Runtime's own
  compensation-key precedent; zero user-visible change (paths are `sha256(key)`
  either way). Cost: caller key not human-readable in logs (the artifact's
  stored `key` field and the loader's key check still make provenance exact).
- **B. Escaped readable key:** length-prefixed or JSON-encoding of
  `(policy_id, version)`, e.g. `sop-pub:<len(id)>:<id>:<version>`. Keeps
  readability; adds a custom encoding that every reader/test must reimplement
  identically, for a benefit that only matters to humans reading raw key
  strings — which the hash-named store already denies.

**Not alternatives:** changing `revise_document` to tolerate id-less documents
(IR-F2) — violates the design's own no-runtime-change goal and touches pinned
lifecycle semantics; content-addressed keys — already rejected in §9 for the
right reason (verified: `uniqueness=()` means two artifacts would silently
coexist).

## 6. Recommended master decisions

- **MD-1:** Ratify the DRAFT **as amended**: SPD-3 replaced with the
  digest-based collision-free key (IR-F1 alternative A); §8 re-framed per
  IR-F2; IR-F3's ordering sentence, IR-F4's absent-key pin and IR-F5's count
  fix folded into the spec or carried as pinned test expectations by the
  implementing sprint. All other SPDs and Q1–Q7 defaults verified consistent
  with the baseline and ratified as drafted.
- **MD-2:** Allocate global D-numbers from **D54** to the ratified SPD subset
  and, at ratification, add the doc_sync_map rows for the new
  `work_runtime/publication.py` (+ demo/docs owed files) — master-owned
  (SKR-9 precedent; workers never edit AGENTS.md).
- **MD-3:** Confirm the two-wave split in the dispatch (wave 1 = stories 1–4
  core + rotation; wave 2 = stories 5–6 demo + docs), keeping `wip_limit 1`
  and the F3 doc repair (sop-authoring.md:25–26) inside story 6.
- **MD-4:** Record IR-F7 (cross-database store sharing fails closed) as an
  accepted operator-discipline boundary in the sprint report rather than new
  machinery.

## 7. Exact SPD list I would pin

Pin as drafted: **SPD-1, SPD-2, SPD-4, SPD-5, SPD-6, SPD-7, SPD-8** (with the
absent-key behavior pinned per IR-F4), **SPD-9, SPD-10, SPD-11, SPD-12,
SPD-13** (with the IR-F3 ordering note). Pin **SPD-3 only as amended**:
`publication_key(card) = "sop-pub:" + digest([card.policy.id,
card.policy.version])` (IR-F1-A). Q1–Q7: adopt all defaults as drafted.

## 8. Honesty limits of this review

All probes ran against a `git archive` extraction of `56a7f2e` through the
public API with synthetic ephemeral material; no probe printed secret bytes.
The inline `SopPublicationPolicy`/wrapper sketch is review scaffolding in
`/tmp`, not proposed product code; where the DRAFT leaves implementation
freedom (validate_document wording, loader error text), only the pinned
behaviors were probed. I did not review UI/design-token compliance (no UI
change is in scope), did not run browser checks (nothing visual changed), and
did not evaluate roadmap/ADR allocation (master-owned). The two Medium
findings concern the drafted spec text, not the baseline.
