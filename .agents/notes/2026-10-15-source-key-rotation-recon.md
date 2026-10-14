# Source-key rotation reconnaissance — 2026-10-15 (post-S10)

## Scope and evidence

Master-authorized post-S10 design/reconnaissance for roadmap 0.2's owed
source-signing-key rotation. **Design only — no implementation, no
product/test/UI/scaffolding/install/merge/push changes, no extra workers.**
The only repo writes from this dispatch are the candidate DRAFT spec
[2026-10-15-source-key-rotation-design.md](../../docs/superpowers/specs/2026-10-15-source-key-rotation-design.md)
(pending master ratification + independent review) and this note. No roadmap,
sprint, acceptance, ADR or tech-debt ledger mutation was made; the master owns
those.

Fresh worktree asserted at published main `b594d757ca5a680d3656b89df45a606d13254011`
(= `git rev-parse HEAD` = `git rev-parse main`, branch
`WayJ/source-key-rotation-design`, `git status --porcelain` empty before this
note). Sources read as truth: [AGENTS.md](../../AGENTS.md) (incl. supervibe
gates + doc_sync_map), historical [idea.md](../../idea.md) /
[上一次建议.md](../../上一次建议.md) (source material only; grep confirms
neither mentions key rotation — the owe originates in
[roadmap.md](../../docs/roadmap.md) itself), [roadmap.md 0.2–0.4](../../docs/roadmap.md),
[RFC-001](../../docs/RFC-001-core-semantics.md) (§4.2, §5, §6 D6/D7, §7 D8),
[RFC-003](../../docs/RFC-003-runtime-protocol.md) (§2.1, §3 D16, §6 D17),
[signed-evidence.md](../../docs/signed-evidence.md),
[verification.md](../../docs/verification.md),
[runtime-boundaries.md](../../docs/runtime-boundaries.md),
[evidence-revocation.md](../../docs/evidence-revocation.md), the E10
compensation spec §12 (rotation explicitly carried as future 0.2 work), the
S10 [acceptance](../../docs/superpowers/acceptances/2026-10-15-S10-acceptance.md)
and [S10 close](2026-10-15-S10-close.md), and the actual `ingress.py`,
`policy.py`, `runtime.py`, `cli.py`, `demo.py`, `check_docs.py`,
`verify_install.py`, `test_ingress.py` plus the revocation/compensation test
files. Probes (§3) ran from `/tmp` via the public API with ephemeral
synthetic keys (`secrets.token_bytes(32)`); no real or production secret
material was used, printed or stored; probe stores were disposable and
deleted.

## 0. Fresh baseline (this checkout, this SHA — recorded before any write)

| gate | result |
|---|---|
| tests | `Ran 809 tests … OK (skipped=3)` |
| contracts | `checked 92 markdown files, 399 local links, 0 broken` (S10 close recorded 397; the close-out commit itself added links — 399 is today's tree) |
| syntax | `compileall -q work_runtime tests scripts` exit 0 |
| site | `checked 2 pages, 0 findings` |
| demos | all six (`demo`, `publish-demo`, `intervention-demo`, `adoption-demo`, `revocation-demo`, `compensation-demo`) exit 0 from the checkout into `/tmp` directories |

Rehearsal baseline (15 OK / 1 skipped, installer serial PASS) is the S10
close record's number for `examples/rehearsal` + `scripts/verify_install.py`;
not re-run here (no installer change is proposed by this design; the demo
wave proposes adding a stage, SKR-10).

## 1. The actual trust gate today (code-cited)

- **Envelope** (`ingress.py:20-21`): `SIGNED_FIELDS = (command_id, data,
  event_id, issued_at, kind, source, work_id)`; `ENVELOPE_FIELDS` = those
  plus `signature`. Exact field set enforced on both signer and gateway
  (`ingress.py:56-57,114-115`). There is **no key id, epoch or version
  field** — an envelope carrying any extra field is
  `EVIDENCE_ENVELOPE_INVALID` (probe P6).
- **Canonicalization/signature**: canonical sorted-key compact JSON
  (`policy.py:8-10`), HMAC-SHA256 hexdigest over the canonical UTF-8 bytes
  (`ingress.py:80-81`), pinned by a published known-answer vector
  (`test_ingress.py:40-47`). Comparison is `hmac.compare_digest` over the
  same single-read canonical snapshot that is forwarded
  (`ingress.py:106-123,158-176`).
- **Keys** (`ingress.py:137-156`): `keys: Dict[str, bytes]` — **exactly one
  secret per source**, ≥32 bytes, distinct material across sources enforced,
  map copied at construction, never persisted/logged/echoed. No default key.
  The doc states the gap verbatim: *"Rotation/revocation is out of scope:
  replacing a key takes effect for new envelopes only and there is no key id
  or revocation list"* (`signed-evidence.md:116-118`).
- **Gateway order** (`ingress.py:158-184`): schema → known source → HMAC →
  freshness (`abs(clock()-issued_at) <= max_age`, default 300, injectable
  clock) → reserved kind `accepted` → `runtime.command(actor=source,
  kind="record_evidence", payload={event_id, kind, data})`. Steps 1–5 write
  nothing; `signature`/`issued_at` are never persisted in the business
  payload.
- **Runtime dedup behind the gateway**: command receipts cached under
  `(actor, command_id)` with fingerprint `digest([work_id, kind, payload,
  expected_version])` (`runtime.py:259-292`); replay re-checks current
  authority and returns the stored receipt verbatim or a **fresh unpersisted**
  `AUTHORITY_DENIED` (`runtime.py:263-272,298-338`) — RFC-003 §3 D16: replays
  must not bypass identity verification. Evidence dedup is global on
  `(source, event_id)` with fingerprint `digest([work_id, payload])`
  (`runtime.py:768-803`); same fingerprint → same evidence id/status, changed
  content → `SOURCE_EVENT_CONFLICT`. **Fingerprints are key-agnostic** (no
  key, signature or timestamp material participates).
- **Authority is name-based, not key-based**: `record_evidence` admission =
  `policy.evidence_sources.get(kind) == actor` plus `evidence.write` grant
  (`runtime.py:775-777`); revocation authority likewise
  (`runtime.py:805-817`). Grants/policies/evidence_sources are trusted-local
  configuration; principal names are not authentication
  (`runtime.py:1-5`, `verification.md:10`).
- **Kinds**: signed ingress refuses `accepted` (`ingress.py:25,177-178`).
  The S10 `withdrawn` proof kind is not gateway-refused; it is refused by the
  authority mapping (`evidence_sources` has no "withdrawn"), producing an
  authenticated, persisted `AUTHORITY_DENIED` (probe P12); `OPERATION_ID_RESERVED`
  separately protects stored operation ids from accepted-source imports
  (`runtime.py:793-797`).

## 2. Why rotation is the missing 0.2 promise (repo-grounded)

- [roadmap.md:23](../../docs/roadmap.md) names the owe exactly: *"source-key
  rotation semantics (rotating a source's signing key is distinct from
  withdrawing an already-accepted proof — the latter, evidence revocation,
  shipped in S8)"* — the last named 0.2 gap after the S2/S4 waves.
- Today a rollover is a hard cutover: reconstruct the gateway with a new
  `keys` map and every in-flight envelope signed under the old key fails
  `EVIDENCE_AUTHENTICATION_FAILED` (probe P1) — no dual-key window, no key
  identity, no explicit retirement state, no operator-visible difference
  between "unknown key" and "retired key".
- Distinctness from S8/S10: rotation changes *future authentication* of a
  source; it must never touch the validity of already-verified proofs,
  confirmed operations, closures or compensation history (byte-preserved —
  probes P9/P9b).
- Priority input (§5): every external integration path (signed ingress,
  adapters) rests on this single pinned key; the S10-close carried list and
  compensation spec §12 both slot rotation as the small 0.2 item ahead of the
  larger 0.3/0.4 slices.

## 3. Probe log (public API, `/tmp`, ephemeral synthetic keys, stores deleted)

Script: `/tmp/skr-probe/probe_rotation.py` (throwaway; not committed).
Observed on `b594d757`:

| # | probe | observed | design consequence |
|---|---|---|---|
| P1 | accept under K1; reconstruct gateway with K2; submit fresh K1-signed envelope | `accepted`, then `EVIDENCE_AUTHENTICATION_FAILED` | cutover is instant and graceless today; keyring + window needed |
| P2 | replay the *accepted original* K1 envelope under the K2 gateway (its `(source, command_id)` receipt is cached) | `EVIDENCE_AUTHENTICATION_FAILED`, all table counts unchanged | gateway authentication precedes `runtime.command`; the cached receipt is unreachable behind a retired key — the cache-authority invariant to preserve |
| P3 | same `(source, event_id)`, same content, re-signed with K2, new `command_id` | `accepted`, **same evidence_id**, `commands` +1 | runtime fingerprints are key-agnostic; re-signing under a new key dedupes to the same proof/status — no new business row |
| P4 | same `command_id`, changed content, correct K2 | `COMMAND_ID_REUSED` | command identity unchanged by rotation |
| P5 | same `event_id`, changed content | `SOURCE_EVENT_CONFLICT` (+1 persisted rejection receipt) | conflict semantics unchanged |
| P6 | envelope with extra `key_id` field | `EVIDENCE_ENVELOPE_INVALID` | exact-field-set discipline: a selector field must be designed in, signed, not bolted on unsigned |
| P7 | unknown source | `EVIDENCE_AUTHENTICATION_FAILED`, zero writes | unchanged |
| P8 | two sources configured with identical key material | `ValueError: each source requires distinct key material` | distinctness must extend across whole keyrings |
| P9 | row-prefix byte comparison of all five tables across cutover + new K2 activity | `commands`/`evidence`/`operations`/`events` pre-rotation rows byte-identical; `works` row changes only where new evidence evaluation legitimately bumped `state_version` | rotation itself must stay write-free; history append-only |
| P9b | pure gateway reconstruction (K1→K2), no records | all five tables byte-identical | rotation is a pure config act today; keep it that way (Option A) |
| P10 | K2 for `finance` (rotated) keeps signing; brand-new keyed source without grants | `accepted` (finance grants are name-based); `AUTHORITY_DENIED` persisted | authority attaches to the source name — a new key grants no new rights, and a new key alone grants nothing |
| P11 | mutate the caller's `keys` dict after construction | old-key envelope `EVIDENCE_AUTHENTICATION_FAILED` | no live in-memory rotation; config is snapshotted at construction (mirrors `test_key_map_is_copied_at_construction`) |
| P12 | kind `accepted` / kind `withdrawn` through the gateway | `EVIDENCE_KIND_UNSUPPORTED` (gateway, zero writes) / `AUTHORITY_DENIED` (persisted business rejection) | admission rules are untouched by rotation; `withdrawn` refusal lives in the authority mapping |
| P13 | replay inside window / clock +301 | `accepted` (dedupe) / `EVIDENCE_EXPIRED` | freshness already bounds replay; key windows should share the same injectable clock domain |

## 4. Security principles the design must state and preserve

1. **Fresh gateway authentication precedes every `Runtime.command`**; the
   cached command receipt can never be reached with a retired key (P2;
   `ingress.py:158-184`, `runtime.py:263-272`; RFC-003 §3 D16).
2. **Replay denial never mutates** old receipts, evidence rows or versions
   (`runtime.py:270-272` fresh-unpersisted; gateway pre-runtime rejections
   write nothing — `test_ingress.py:202-227`).
3. **Business identity is authentication-agnostic**: same `(source,
   event_id)` + same content dedupes under any valid key (P3); changed
   content stays `SOURCE_EVENT_CONFLICT` (P5). Key fingerprints do not enter
   the evidence fingerprint.
4. **Rotation is forward-only history-wise**: proofs, confirmed operations,
   closures, compensation receipts and events are byte-preserved (P9/P9b).
5. **Admission unchanged**: approved kinds only; `accepted` reserved at the
   gateway, `withdrawn` refused by mapping (P12); grants and revoke authority
   stay name-based — rotating a key grants nothing new, and no key can
   bypass/revoke another source's proofs (P10).
6. **What a key proves**: possession by someone inside the configured
   shared-key boundary for that *source* — source authentication, not
   operator/principal authentication, not tenant auth, not transport
   security, and the codebase must keep saying so
   (`signed-evidence.md:10-25`, `verification.md:10`).

## 5. Priority recommendation input (rotation vs SOP publication vs broader compensation)

- **Rotation is the small, self-contained 0.2 remainder**: config-shaped
  (like grants/policies — no new store schema, no new command kind, no new
  authority model), additive to one module (`ingress.py`) plus docs; the
  probes show every needed runtime behavior already exists unchanged.
- **SOP publication** (roadmap 0.4, RFC-002 §6) is a larger author-workflow
  feature (publication authority, immutable store, author review) with no
  dependency on rotation and no unshipped dependency the other way.
- **Broader compensation** (post-closure, publishing family, chains) was
  explicitly deferred at S10 close and in compensation spec §12 as separate,
  larger designs; nothing in this repo currently blocks on them.
- Completing rotation closes the last named 0.2 gap, hardens the story every
  future external reviewer will probe ("what happens when a signing key is
  compromised?"), and the no-credentials rotation demo extends the existing
  demo ladder. Recommendation: rotation first, as the smallest useful slice.

## 6. Baseline-preservation requirements for the implementing sprint

809 tests / 3 skips; contracts 92 files / 399 links / 0 broken; compileall
clean; site 2 / 0; six demos exit 0; rehearsal 15 / 1 skip; installer serial
PASS. Additive only: schema stays `1`, Python ≥3.9 stdlib-only, existing
public signatures and the KAT vector
(`test_ingress.py:40-47`, `84ba6259ac240cab06a5f9df89b8525be99ecb20605b975d76ee6e7f0c04ec08`)
must keep passing verbatim.

## 7. Self-review (NOT independent — same session as the design)

Checked against the dispatch brief: base asserted clean at `b594d757` ✓;
AGENTS + historical sources read as material-not-instructions ✓ (grep shows
neither historical file mentions rotation; no instruction taken from them);
roadmap 0.2 + RFC-001/003 + boundary/evidence/verification docs read ✓;
ingress/models-equivalent(policy)/runtime/cache(commands-receipts)/evidence/
revocation tests/demo/CLI/install read ✓; S10 acceptance + close read ✓;
superpowers brainstorming (architectural path) followed with the master as
approver and the DRAFT-pending-ratification gate ✓; supervibe discipline —
no roadmap/sprint/acceptance/ADR/ledger writes ✓; scope = candidate spec
draft + this note + this self-review only ✓; no product code/tests/UI/
scaffolding/install/merge/push/extra agents ✓; probes public-API-only in
/tmp with synthetic keys, no secret material printed ✓; envelope/
canonicalization/pinned-source/dedup/version/order semantics grounded with
file:line ✓; keyring-vs-registry comparison + bounded-slice recommendation ✓;
rollover windows deterministic via the existing injectable clock, no store
timestamps, no invented in-memory-secret-change protection (P11) ✓;
authenticated key selector (no unsigned downgrade, P6) ✓; legacy compat
explicit per-source ✓; cache-authority principle grounded (P2) ✓; re-sign
dedupe with no artificial row (P3) ✓; history byte-preservation (P9/P9b) ✓;
admission/no-bypass/no-source-confusion (P10, P12) ✓; source-identity-not-
principal claim discipline ✓; priority recommendation repo-grounded (§5) ✓;
builder-ready API/codes/config/waves/compat in the spec ✓; Red/Green matrix
incl. bad/unknown/retired/tampered/grace/expiry/dedup/restart/byte-history/
cache-authority cases ✓; demo + installed-module/console proposed but not
globally gated (SKR-10) ✓; truthful deferred limitations ✓; unresolved
master decisions in a locally numbered table (SKR-1…SKR-12) ✓. Known
non-independent gaps: single-session authorship (independent review still
owed); rehearsal/installer baselines cited from the S10 close record, not
re-executed here; no browser/UI claims made because none are in scope.
