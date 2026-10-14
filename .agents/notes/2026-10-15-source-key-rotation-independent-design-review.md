# Source signing-key rotation candidate design — independent builder-check review — 2026-10-15

Independent Orca review of the DRAFT spec
`docs/superpowers/specs/2026-10-15-source-key-rotation-design.md` (candidate
branch `WayJ/source-key-rotation-design` tip `1ef6735`, single commit over
published main `b594d757` — the spec and its recon note live on that branch,
not in this tree, so both are cited by path/commit rather than linked; the
recon note is `.agents/notes/2026-10-15-source-key-rotation-recon.md` on the
candidate). Distinct from the designer's own §7 recon self-review and §13
designer self-check: every load-bearing claim below was re-derived against
this `b594d757` checkout and reproduced with fresh public-API probes
(`/tmp/skr-review/probe_skr_review.py`, throwaway, stores deleted; ephemeral
synthetic keys via `secrets.token_bytes(32)`, never printed). This is a
recommendation to the master, who owns ratification; no epic/sprint id is
allocated and nothing here is an implementation instruction.

## Verdict

**Implementable and scope-right — ratify Option A with four amendments
before implementation.** The problem is real and quoted verbatim from
[roadmap 0.2](../../docs/roadmap.md); Option A is the minimal coherent slice;
every "unchanged machinery" claim (cache authority, key-agnostic dedupe,
conflict, history preservation, admission, name-based authority) held up
under independent re-derivation (probes below); the optional signed `key_id`
preserves the legacy seven-field envelope, the published KAT vector, schema
`1`, stdlib-only and Python ≥3.9 verbatim. Required amendments: F1 (one
incorrect equivalence claim in the rollover ladder), F2 (a replay-path
conflation in §4.6 plus a missing test), F3 (the `SourceKey`
validation/copy contract is not implementation-ready), F4 (the clock-sample
contract is unpinned). Minors M1–M4 and the SKR-1…SKR-12 recommendation
concurrences are below. None of the amendments changes the slice's shape,
size or blast radius.

## Independent grounding (fresh probes on the main baseline)

`python3 -I /tmp/skr-review/probe_skr_review.py` against this checkout's
public API (`Runtime`, `SignedEvidenceGateway`, `sign_evidence`, demo
helpers), real SQLite stores under `/tmp/skr-review/`. 22 probes, 21
expectations met; the one divergence (PR-E3) corrected this reviewer's own
expectation and sharpens M1. Observed:

| # | probe (fresh, this session) | observed |
|---|---|---|
| PR-A1 | accept under K1; reconstruct gateway with K2; fresh K1 envelope | `EVIDENCE_AUTHENTICATION_FAILED` |
| PR-A2 | replay the *accepted original* K1 envelope under the K2 gateway (receipt cached) | `EVIDENCE_AUTHENTICATION_FAILED` — cache unreachable behind retired key |
| PR-A3 | table counts across both denials | unchanged (zero writes) |
| PR-B1 | **same `command_id`** + same content, **re-signed under K2**, inside freshness | the **original cached receipt verbatim** (same `evidence_id`, original `evidence_status="pending_verification"`, original `result_state_version=3`) |
| PR-B2 | counts across PR-B1 | unchanged — zero writes, no new command row |
| PR-B3 | **new `command_id`** + same `(source, event_id)` content under K2 | `accepted`, same `evidence_id`, **current** status |
| PR-B4 | counts across PR-B3 | exactly `commands +1`, `evidence +0` |
| PR-C1–C3 | revoke the evidence (trusted-local `revoke_evidence`), then same-`command_id` resend under K2 | evidence `status="revoked"`; resend still returns the **original** receipt verbatim (`pending_verification`); zero writes |
| PR-C4 | new-`command_id` resend after revocation | same `evidence_id`, `evidence_status="revoked"` (current status), `commands +1` |
| PR-D1–D2 | reopen the same store with grants omitting the source; same-`command_id` resend under K2 | fresh unpersisted `AUTHORITY_DENIED`, zero writes (authority rechecked before the cached receipt — RFC-003 §3 D16) |
| PR-E1 | snapshot all five tables; pure gateway reconstruction | all five byte-identical |
| PR-E2 | new accepted evidence afterwards | `commands`/`evidence`/`operations`/`events` stay prefix-equal |
| PR-E3 | `works` row across PR-E2 | **unchanged by the mere insertion** (state_version moved 3→4 earlier only at revocation's re-evaluation) — equality scope is per-act, not per-table |
| PR-F1 | envelope with extra `key_id` field | `EVIDENCE_ENVELOPE_INVALID` (today's exact-field rule) |
| PR-F2 | receipt key set on every denial | exactly `{decision, code}` |
| PR-F3 | unknown source | `EVIDENCE_AUTHENTICATION_FAILED`, zero writes |
| PR-G1 | clock sample `nan`, envelope 999999 s stale | **`accepted`** — `abs(nan−x) > max_age` is False, freshness passes (pre-existing fail-open quirk on the trusted clock) |
| PR-G2 | clock sample `+inf`, same envelope | `EVIDENCE_EXPIRED` (`abs(inf−x) > max_age` is True — asymmetric with nan) |

Code re-derivation agrees with the recon's §1 table where it matters:
`SIGNED_FIELDS`/`ENVELOPE_FIELDS` and exact-set enforcement
([ingress.py](../../work_runtime/ingress.py) 20–21, 53–65, 106–123),
canonicalization `allow_nan=False` ([policy.py](../../work_runtime/policy.py)
8–10), single-read canonical snapshot + `compare_digest` (ingress.py
158–176), minimal `_reject` (36–38), constructor validation incl. the
already-**global** material-distinctness check and the bool-trap discipline
`type(max_age) is not int` (137–156), the single `self.clock()` call per
record (175), reserved-kind refusal post-authentication (177–178), and the
runtime receipt/evidence machinery — key-agnostic fingerprints, cached
receipt replay with authority recheck, current-status new-command resends,
`SOURCE_EVENT_CONFLICT`, `OPERATION_ID_RESERVED`
([runtime.py](../../work_runtime/runtime.py) command/_replay_denial/_receive).
`withdrawn` is genuinely absent from `ExpensePolicy.evidence_sources`
(policy.py 40–46), so that refusal is the authority mapping's, as claimed.
`tests/test_ingress.py` re-run green on this tree (40 tests, OK), including
the KAT vector at lines 40–47 and `test_key_map_is_copied_at_construction`
at 416–424; `scripts/check_docs.py` reproduces `92 markdown files, 399
local links, 0 broken` exactly as the recon §0 recorded.

## Material findings (amendments required before ratification)

- **F1 — §4.5 ladder step 4's "verification outcome is identical" is false
  for `key_id` envelopes: denial is identical, the code is not.** With K1
  dropped, a `key_id: K1` envelope dies at step 3 (absent entry →
  `EVIDENCE_AUTHENTICATION_FAILED` — indistinguishable from an unknown or
  attacker key). With K1 retained under an expired `not_after`, the same
  envelope passes HMAC and dies at step 5 with `EVIDENCE_KEY_RETIRED` —
  exactly the operator-actionable signal SKR-3 argues for ("your signer is
  still using the retired key"). Only the legacy-format path is truly
  identical (legacy selects the `current` entry only, so a K1-signed legacy
  envelope fails HMAC against K2's secret whether or not K1 is listed).
  Amend the sentence to scope it, state the trade-off (retaining the expired
  entry preserves retired-key observability; dropping it collapses the
  signal), and pin T18's fixture — its expected `EVIDENCE_KEY_RETIRED`
  equally depends on K1 remaining listed with an expired `not_after`
  (dropped K1 would make T18 an `EVIDENCE_AUTHENTICATION_FAILED` case).
- **F2 — §4.6 bullet 3 conflates two replay paths; "one new command row" is
  conditional on a *new* `command_id`.** Grounded PR-B1/B2 vs PR-B3/B4:
  re-signing the same content under a new valid key with the **same**
  `command_id` returns the **original cached receipt verbatim** (original
  status and version — PR-C2 shows this still holds after the evidence was
  revoked, and PR-D1 shows grant loss converts it to a fresh unpersisted
  `AUTHORITY_DENIED`), with **zero** writes; only a **new** `command_id`
  yields "same evidence id and current status, one new command row". Both
  paths are key-agnostic; neither mutates the old receipt or evidence row.
  Amend the bullet to state both branches, and add T17b: same-`command_id`
  re-sign under the new key → original receipt verbatim, zero table writes
  (plus the revoked-evidence and grant-loss variants). T17's "+1" stays
  correct for its own new-`command_id` scenario (mirrors the existing
  `test_timestamp_refresh_under_new_command_keeps_event_identity`).
- **F3 — the `SourceKey` validation/copy contract is not
  implementation-ready; §4.3 lists value constraints but no types, no
  sequence rules, and a copy promise the current code cannot keep.** Pin:
  `type(key_id) is str` and nonempty; `type(secret) is bytes`, ≥32 bytes;
  `type(current) is bool` **exactly** (1/0 must not pass — repo precedent is
  the `type(...) is not int`/`not bool` discipline at ingress.py 58–59 and
  149–150); `not_before`/`not_after` each `None` or `type(x) is int`
  (`True`/`False` must not silently act as 0/1 bounds); every keyring entry
  `isinstance(entry, SourceKey)` (a `str`/`bytes` value is itself a
  `Sequence` and must fail as a shape error, not iterate as characters);
  accepted sequence types named (list/tuple; a generator is not a
  `Sequence` — reject, or materialize once and say which); and the internal
  representation normalized to an immutable per-source **tuple**, because
  `dict(keys)` (ingress.py 154) is a *shallow* copy — a caller's list-valued
  keyring would stay live-connected and §4.3's "copied at construction and
  immutable thereafter" would be false (today's bytes values are immutable,
  which is why the legacy path needs nothing). T22 must mutate the inner
  sequence, not only the outer dict — the existing
  `test_key_map_is_copied_at_construction` mutates only the outer map.
  Also pin the envelope-side shape code for a non-str/empty `key_id`
  (step 1 → `EVIDENCE_ENVELOPE_INVALID`; T24 pins only the signer's
  `ValueError`).
- **F4 — the clock contract must pin one finite sample per record.** §4.5's
  "pure function of `(envelope, config, clock())`" does not say **one**
  `clock()` call serves both the window check (step 5) and freshness
  (step 6); today `record` calls `self.clock()` exactly once (ingress.py
  175), and two samples would let window and freshness disagree across a
  boundary tick. Pin: a single sample per record, and state that the sample
  must be a finite epoch second — a `nan` sample **passes freshness today**
  (PR-G1; all comparisons False) while `+inf` fails it (PR-G2) and the
  design's window check would fail closed on `nan` only by evaluation
  accident, an inconsistent triad no implementer should inherit silently.
  The clock is trusted-local configuration, so this is contract precision,
  not a vulnerability; T21 should add non-finite-sample cases expecting
  rejection. While there, state explicitly what §4.4 step 5 implies: the
  window evaluates the **current verification time** (`clock()`), never the
  signed `issued_at`, so a key holder cannot backdate around a `not_after`
  — one sentence, and it forecloses the one implementation that would.

## Minor findings

- **M1 — T19's "row-prefix equality over all five tables" overclaims.**
  §4.8 itself words it correctly ("the `works` row changes only when new
  evidence evaluation legitimately bumps `state_version`"); PR-E shows the
  precise split — pure reconstruction and denials leave all five
  byte-identical, subsequent legitimate ingress keeps the four append-only
  tables prefix-equal, and `works` rewrites exactly when evaluation changes
  (revocation bumped 3→4 in PR-C; a mere pending insertion did not touch
  it — PR-E3). Scope T19 to the rotation acts and mirror §4.8's caveat.
- **M2 — three missing matrix cases.** (a) The migration bridge's *happy
  path* is untested: keyring source + legacy-format envelope signed with the
  **current** entry's secret, valid window → accepted (only the negative T15
  and the bytes-source T16 exist). (b) Legacy-format envelope against a
  current entry outside its window → `EVIDENCE_KEY_NOT_YET_VALID` /
  `EVIDENCE_KEY_RETIRED` on the legacy path (T9/T10 exercise the `key_id`
  path). (c) F3's envelope-side non-str/empty `key_id` shape pin.
- **M3 — §12 should state configuration-rollback revival explicitly.**
  Option A has no persistent revocation memory: redeploying a pre-rotation
  keyring revives the old secret for future envelopes. Adjacent to SKR-11
  (id reuse) but distinct (whole-config rollback vs one id); one sentence
  under truthful limitations.
- **M4 — §4.3's "extends the existing per-source rule" mischaracterizes
  today's check.** The existing distinctness check is already global across
  sources (ingress.py 141–148 collects every secret; probe P8's own evidence
  is a two-source collision). The actual extension is within one source
  across keyring entries. Wording only.

## Master decisions input (SKR-1…SKR-12)

All twelve recommendations concur with this grounding; F1 adds an input to
SKR-3/SKR-4 (the two codes are worth keeping precisely because dropping a
retired entry destroys the `EVIDENCE_KEY_RETIRED` signal — see F1), and F3's
type/copy contract belongs in the ratification text so the implementing
sprint cannot diverge. Verified specifically: **SKR-9** is correctly
master-owned — [AGENTS.md](../../AGENTS.md) `doc_sync_map` has no
`ingress.py` row today, and adding one is a working-agreement change; the
implementing worker must not edit AGENTS.md. **SKR-10**: `rotation-demo`
collides with no existing demo; the proposed installer stage matches the
existing module+console-outside-checkout discipline (verify_install stages
13–16 precedent) and adds no global gate — the five supervibe gates stay
exactly as listed in AGENTS.md. **Baseline numbers** check out: 809 tests /
3 skips and rehearsals 15 / 1 skip are the S10 close record's counts for
this identical tree (`.agents/notes/2026-10-15-S10-close.md` 31–36); all six
demos exit 0 and the installer passed serial with zero SKIPPED lines at S10
acceptance; contracts re-run *here* reproduces 92/399/0; the sprint will
re-run all gates fresh per custom. Option A vs B (SKR-1): concur with A —
B's blocking question ("who may rotate?") has no grounded answer in this
repo's authority model, and every downstream behavior A relies on already
exists and is pinned (probes above).

## Agreements independently confirmed

Optional **signed** `key_id` with `SIGNED_FIELDS` unchanged preserves the
legacy envelope, canonicalization and the published KAT
(`test_ingress.py` 40–47 signs the seven-field message; the vector must keep
passing before and after — T25); no unsigned selector is possible (today's
exact-field rule rejects any naive extra field — PR-F1); key selection
before HMAC leaks nothing beyond existing codes (unknown `key_id` and bad
HMAC share `EVIDENCE_AUTHENTICATION_FAILED`; the window codes sit post-HMAC,
reachable only by genuine key holders — T13's no-oracle pin); freshness
boundary semantics and injectable clock unchanged; admission untouched
(`accepted` reserved at the gateway; `withdrawn` refused by the authority
mapping as an authenticated persisted `AUTHORITY_DENIED`; grants, revoke
authority and `evidence_sources` stay name-based — PR-D); authentication
always precedes `runtime.command`, so a cached receipt is unreachable behind
a failed key (PR-A2) and replay denial never mutates (PR-A2/A3/B2/C3/D2);
re-sign dedupe is key-agnostic with no artificial business row (PR-B);
`SOURCE_EVENT_CONFLICT` unchanged; history preservation scoped as §4.8 says
(PR-E); signer surface unchanged and key-id-agnostic in keyrings (§4.10);
schema `1`, stdlib-only, Python ≥3.9, additive-to-`ingress.py` blast radius
(§4.11); alternatives in §10 (no try-all-keys, no version field, no
asymmetric crypto, no store-clock key state) all correctly rejected on
grounded grounds; no tenant-auth/TLS/KMS/distributed-security/production
claim appears anywhere in the draft (§2/§12 stay inside the documented
shared-key boundary).

## Limits

Review-only: no product, test, UI, scaffolding or install changes were made;
the only repo write is this note. Probes used public APIs on throwaway
`/tmp/skr-review/` stores with synthetic ephemeral keys that were never
printed and are deleted with the directory; the candidate branch, its
worktree and every other worktree are untouched. The 809/3 and 15/1 numbers
are cited from the S10 records for this identical tree rather than re-run
(the dispatch scoped this as a read-only review; the ingress file itself was
re-run green, 40/40); the implementing sprint re-runs all gates fresh. This
review is an implementation-readiness check against the repo's own contracts
and is not a security certification or production-safety claim.
