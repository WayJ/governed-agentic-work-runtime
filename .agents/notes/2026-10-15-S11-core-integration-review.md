# S11 W1 core integration review — PASS, assembled — 2026-10-15

Independent Orca integration review/assembly of the S11 source signing-key
rotation core, distinct from the owner's internal review recorded in
[the core report](2026-10-15-S11-core-report.md). Reviewer checkout:
`s11-release-control` (control branch `WayJ/s11-release-control`, base
`331172f` = carrier base, clean at start). No product file was modified by
this review; all gates, demos, rehearsals, the installed verifier, the RED
replays and the independent probes ran from the labelled
`/tmp/s11-integration-2026-10-15/` extractions (`git archive`, disposable) of
the accepted source and the baseline, plus fresh `/tmp` stores. Verdict:
**PASS — no unresolved material finding**; two minor findings recorded below
(mi-1, mi-2), neither blocking, neither requiring a product fix. This review
proves the **local S11 core only** — not the whole sprint: `rotation-demo`,
installer stage, README entries, final acceptance and the main merge are W2+.

## Scope and source

- Accepted source: `WayJ/s11-source-key-core` tip
  **`ce584d3fd3cc03b6239642ba912c20c0aa11114c`** (verified equal to the
  branch), **7 commits** `a60fc18..ce584d3` on merge-base `331172f` (my
  baseline) — plan `a60fc18`, four ingress commits, replay pins `82b5e54`,
  review fix `8e322cd`, report `ce584d3`, matching the dispatch and the
  owner's commit table exactly.
- Changed files (name-status verified, exactly 6, count asserted by the
  dispatch): `work_runtime/ingress.py` (+167/−33), `tests/test_key_rotation.py`
  (new, 943 lines, 50 tests by my own count), `docs/signed-evidence.md`,
  `docs/verification.md`, `docs/superpowers/plans/2026-10-15-s11-core.md`,
  `.agents/notes/2026-10-15-S11-core-report.md`.
- **Same-commit doc pairing (the S10 lesson) holds**: every commit touching
  `work_runtime/ingress.py` — exactly `f04cb99`, `e7cd1c7`, `59b21e6`,
  `8e322cd`, the four the dispatch named — also touches
  `docs/signed-evidence.md` in the same commit, and every test-carrying
  commit also updates `docs/verification.md` in the same commit. No S10-style
  gap.
- Protected paths byte-identical `331172f..ce584d3` (empty diff over
  `examples/`, `website/`, `work_runtime/web|data`, `runtime.py`, `policy.py`,
  `adapters.py`, `adapter_contract.py`, `cli.py`, `demo.py`, `publishing.py`,
  `file_adapter.py`, both check scripts, `verify_install.py`, both READMEs,
  `AGENTS.md`, `pyproject.toml`, `docs/website.md`, `CONTRIBUTING.md`,
  `tests/test_ingress.py`): no UI/runtime/adapters/policy/CLI/demo/install/
  package-export/legacy-test/asset edit of any kind; `rotation-demo` correctly
  absent (exit 2, unknown subcommand — W2); the five AGENTS gates unchanged.
- Trees/preview preserved throughout: all 22 worktrees intact; preview
  server on 127.0.0.1:52719 answered HTTP 200 before and after assembly.

## Static review against ratification D49–D53 (with F1–F4/M1–M4)

Read in full: AGENTS.md (incl. the new `doc_sync_map` ingress row),
[design DRAFT + MASTER ratification](../docs/superpowers/specs/2026-10-15-source-key-rotation-design.md),
[E11 roadmap](../docs/superpowers/roadmaps/2026-10-15-source-signing-key-rotation.md),
active [S11 sprint](../docs/superpowers/sprints/2026-10-15-S11-plan.md),
the independent design review
([ce07781](2026-10-15-source-key-rotation-independent-design-review.md)),
the core plan, the core report, and both doc diffs against implemented
behavior. Code reviewed as diff and in full.

- **D50 rings/copy**: `SourceKey(NamedTuple)` with the exact five fields;
  per source either legacy `bytes` (validation path untouched) or a nonempty
  `list`/`tuple` of `SourceKey` only — generators/sets/str/bytes/int/None are
  shape `ValueError`s before any iteration; entry types exact (`type(key_id)
  is str` nonempty, `type(secret) is bytes` ≥32 — bytearray rejected,
  `type(current) is bool` — 1/0/None/"yes" rejected, bounds each `None` or
  `type(x) is int` — `True`/`False`/floats/str rejected), `not_before <=
  not_after`, unique ids per ring, exactly one `current` (zero and two
  rejected), global material distinctness across every entry and source
  including ring-vs-legacy. Normalized to fresh outer dicts holding immutable
  per-source tuples: my probes mutate the caller's outer dict (add/delete
  source) and inner list (append/replace) after construction and the gateway
  config — and verification — are unchanged, and a deleted-from-caller-map
  legacy source still records. The doc scopes this honestly as copying
  caller-supplied config, not a protection boundary against mutating gateway
  internals — no Python-internals-security overclaim.
- **D49 selector**: `SIGNED_FIELDS` and `ENVELOPE_FIELDS`-adjacent constants
  keep the legacy seven-field tuple; `OPTIONAL_KEY_FIELD = "key_id"` is the
  single admitted extra **signed** field; message/envelope accept exactly the
  seven legacy fields or those seven plus `key_id` (`_message_problem` /
  `_open_envelope` set logic verified: all seven required, nothing beyond
  seven+key_id, key_id nonempty str at step 1 → `EVIDENCE_ENVELOPE_INVALID`);
  the canonical HMAC bytes include `key_id` when present (selector swap breaks
  the signature — probed); no unsigned selector, no try-all-keys, no fallback:
  cited `key_id` → that entry else `EVIDENCE_AUTHENTICATION_FAILED`; keyring
  without `key_id` → `current` entry only, **both** directions pinned and
  probed (non-current key under the old config, retained old key under a
  rotated config — both fail HMAC against the current key, never silent);
  legacy `bytes` source + `key_id` envelope → `EVIDENCE_AUTHENTICATION_FAILED`.
  `key_id`/`issued_at`/`signature` are never forwarded (payload is exactly
  `{event_id, kind, data}` from the same canonical snapshot the HMAC saw),
  never persisted, never fingerprinted. The published KAT
  `84ba6259…c04ec08` reproduces through the public signer.
- **D51 time**: code order verified — shape → source → selector → HMAC
  (`hmac.compare_digest`, constant-time, single-read canonical snapshot) →
  **one** clock sample → key window → freshness → reserved kind →
  `runtime.command`. The clock is sampled only after HMAC succeeds (my
  counting probe: zero calls across five denial shapes, exactly one on
  success); one sample is shared by window and freshness (my sequencing probe
  fails a two-sample implementation in both directions); sample must be exact
  int/float (bool rejected) and, when float, finite — `nan`/`±inf`/str/bool/
  None/list samples and a raising ordinary `Exception` clock all return the
  minimal `{"decision":"rejected","code":"EVIDENCE_CLOCK_INVALID"}` with zero
  runtime calls/writes; `BaseException` (`KeyboardInterrupt`) propagates;
  huge-int samples (`±10**400`) are finite by construction, never pass
  through `isfinite` (no `OverflowError` exposure), and fail by exact
  comparison. Window bounds are inclusive on the **current verification
  time** (backdated/future `issued_at` cannot cross a closed window —
  probed); window precedes freshness (retired+stale and not-yet+stale report
  the window code); window codes are post-HMAC only (garbage signature +
  closed window → `EVIDENCE_AUTHENTICATION_FAILED` — no stranger oracle).
  Dropped key → `EVIDENCE_AUTHENTICATION_FAILED` vs retained-expired →
  `EVIDENCE_KEY_RETIRED` (distinct, probed). Freshness is the comparison form
  `issued_at - max_age <= now <= issued_at + max_age` — verified equivalent
  to the old `abs` form at all four boundary legs (`±300` accept, `±301`
  reject) on the legacy path. The legacy NaN fail-open is **intentionally
  fixed by ratification** (D51: "NaN fail-open intentionally fixed") — I
  reproduced the old behavior on the baseline extraction (stale envelope
  **accepted** under a NaN clock at `331172f`) and the new fail-closed
  behavior on the source, so this is a ratified compat change, not an
  unapproved break.
- **D52 replay/history**: gateway authentication precedes the runtime command
  cache structurally and empirically — the *accepted original* envelope
  replayed under a rotated gateway (old entry retained expired) →
  `EVIDENCE_KEY_RETIRED` with **all six tables byte-identical** (ordered
  rowid dumps, not mocks); same `command_id` re-signed under the new valid
  key → the **original cached receipt verbatim**, zero writes, also after
  trusted-local revocation; new `command_id` same event → same evidence id +
  **current** status (`revoked` after revocation), exactly `commands +1`, no
  new evidence row; changed payload → persisted `SOURCE_EVENT_CONFLICT`;
  grant loss (store reopened without the source's grants) → fresh unpersisted
  `AUTHORITY_DENIED` with the stored receipt intact. History scope is
  per-act (M1, no universal works-prefix claim): pure reconstruction and
  every denial class leave all six tables byte-equal; legitimate new ingress
  keeps the four append-only tables prefix-equal with `works`/`metadata`
  untouched by a pending insertion. Deterministic same-config/same-clock
  restart decisions probed. Every new-code receipt is exactly
  `{decision, code}` — no key echo, no secret material anywhere in receipts
  or evidence bodies.
- **Admission/authority unchanged**: reserved `accepted` refused at the
  gateway (zero writes); `withdrawn` refused by the authority mapping as a
  persisted `AUTHORITY_DENIED` (`commands +1`); authority stays name-based
  (runtime/policy untouched — a rotated key inherits the source's grants, a
  new key grants nothing; cross-source material impersonation fails HMAC);
  the S9 reservation and business authority machinery are untouched by the
  empty protected-path diff. No persisted key revocation memory: the
  documented limitations state explicitly that redeploying a pre-rotation
  configuration revives the old secret, key-id reuse after a drop is operator
  discipline, and a compromised current key stays forgeable until rotation
  lands — all carried verbatim in `docs/signed-evidence.md`.
- **Secrets discipline**: tests and probes use `secrets.token_bytes(32)`
  ephemeral keys, never printed; the only signature value shown anywhere is
  the published non-secret KAT.

## Fresh verification (extraction of the accepted source = control content)

| item | command | actual result |
|---|---|---|
| independent baseline | `python3 -m unittest discover -s tests` on `331172f` | **Ran 809 tests … OK (skipped=3)** |
| tests (gate 2) | same, on `ce584d3` | **Ran 859 tests in 39.156s … OK (skipped=3)** = 809 + 50 arithmetic confirmed |
| named skips | verbose run | 2× `adapter does not opt into action/link execution context` (`adapter_conformance`) + `test_ui_cli.AbsentBackendTests.test_absent_backend_is_a_bounded_startup_error` — all pre-existing |
| legacy pin | `python3 -m unittest tests.test_ingress` | **Ran 40 tests … OK**, KAT `test_known_answer_vector_pins_hmac_sha256` ok — file byte-untouched |
| contracts (gate 1) | `python3 scripts/check_docs.py` | **96 markdown files, 423 local links, 0 broken** (owner said 101 files — see mi-1); baseline measures 95/420/0, so the committed delta is +1 file (the plan) / +3 links |
| demo (gate 3) | `python3 -m work_runtime demo` | exit 0 |
| syntax (gate 4) | `python3 -m compileall -q work_runtime tests scripts` | clean |
| site (gate 5) | `python3 scripts/check_site.py` | 2 pages, 0 findings |
| six demos | `demo`, `publish-demo`, `intervention-demo`, `adoption-demo`, `revocation-demo`, `compensation-demo` | all exit 0; **no `rotation-demo` command exists** (exit 2 — W2) |
| rehearsals | `python3 -m unittest discover -s examples/rehearsal` | **Ran 15 tests … OK (skipped=1)** (pre-existing opt-in skip) |
| installed verifier | `python3 scripts/verify_install.py`, **serial, nothing concurrent** | **`=== PASS ===`**, exit 0, **zero SKIPPED lines**, all 19 stages ran (fresh venv, import inside venv, zero third-party deps, module+console demos outside the checkout, packaged assets byte-equal) |

## Independent probes (my own; public API only; real SQLite stores)

`python3 -I /tmp/s11-integration-2026-10-15/probe.py <tree>` → **40 checks,
40 passed, 0 failed — deterministic across repeated runs** (plus 3 baseline
legs: KAT, NaN fail-open reproduced, pre-S11 `key_id` rejection). My harness
had four probe-side bugs across iterations (unconfigured secret in the NaN
leg, a source `demo_grants()` does not grant, `key_id` double-passed into a
message, a dropped-entry ring with no current, a stale snapshot after a
legitimate write) — every failure reproduced as probe-side; no product
behavior changed any finding. Coverage: KAT through the public signer; 24
bad-config rejections in one sweep; outer+inner caller-copy immutability with
verification and a removed-from-caller-map source still working; signed
selector round-trip via a non-current entry with receipt/evidence purity
(no `key_id`/`signature`/`issued_at` anywhere); five authentication-failure
shapes with zero writes across all six tables; rotated-direction legacy
rejection; inclusive window edges on both formats at both bounds; both window
codes, precedence over freshness, no-oracle, no-backdating, drop-vs-retain
distinct codes; clock order/sample-count/type/finiteness/raising/huge-int
matrix; legacy `±max_age` boundary equivalence; retired replay behind the
cache with six-table byte equality; both resend branches (verbatim original
receipt / current status `+1` command); revoked-evidence behavior; grant-loss
denial; `SOURCE_EVENT_CONFLICT`; per-act history preservation; reserved and
mapping-denied kinds; unsigned-extra-field rejection; deterministic restart.

### RED validation (representative replays, committed tests vs parent trees)

- Task 2 (`e7cd1c7` tests on parent `f04cb99`): **23 tests, 1 failure +
  8 errors** — exactly the owner's claim; failures are the selector tests
  (signer rejects `key_id`, selection unwired).
- Task 3 (`59b21e6` tests on parent `e7cd1c7`): **38 tests, 9 failures +
  1 error** — all window/clock tests fail for the right reasons (no new
  codes, NaN still fail-open-accepting, two-sample clock would pass). See
  mi-2 for the count nuance vs the owner's "12 of 15".
- The **old-NaN fail-open → fail-closed** change is independently
  demonstrated on both trees (baseline leg accepts; source leg rejects with
  `EVIDENCE_CLOCK_INVALID`) and is ratified by D51 verbatim — intentional,
  disclosed in the owner's report and in `docs/signed-evidence.md` step 5.

## Findings (both minor; no product change made; routed as disclosure)

- **mi-1 (gate count provenance, same class as S10 Mi-3).** The owner's
  report cites contracts as "101 markdown files, 423 local links, 0 broken";
  the committed accepted tree measures **96 files / 423 links / 0 broken**
  (baseline 95/420/0). Links and broken counts are identical; the 5-file
  delta is untracked local working files present at their gate time (their
  tree is clean now; the S10 precedent was the `.superpowers` ledger).
  Recorded here as the measured committed truth; no action owed.
- **mi-2 (RED count nuance).** The owner's report says Task 3's RED was "12
  of 15 new tests failed"; replaying the **committed** (post-GREEN) test
  file on the parent yields 10 of 15 failing, the other five being the
  disclosed cannot-go-RED/already-true pins (inclusive edges, BaseException
  propagation, clock-after-HMAC, legacy freshness boundaries, garbage-
  signature code) plus refinement during the GREEN loop. Load-bearing RED is
  independently reproduced; the discrepancy is report arithmetic about a
  mid-development snapshot, not coverage.

## W2 stable API (verified empirically, for the demo owner)

At the assembled control tip: `from work_runtime.ingress import SourceKey,
SignedEvidenceGateway, sign_evidence, SIGNED_FIELDS, OPTIONAL_KEY_FIELD`
(also `ENVELOPE_FIELDS`, `MIN_SECRET_BYTES`, the codes
`EVIDENCE_ENVELOPE_INVALID`, `EVIDENCE_AUTHENTICATION_FAILED`,
`EVIDENCE_CLOCK_INVALID`, `EVIDENCE_KEY_NOT_YET_VALID`,
`EVIDENCE_KEY_RETIRED`, `EVIDENCE_EXPIRED`, `EVIDENCE_KIND_UNSUPPORTED`).
Default configuration: per source either legacy `bytes` or a nonempty
list/tuple of `SourceKey(key_id, secret, current=False, not_before=None,
not_after=None)` with exactly one `current`, validated/copy-normalized at
construction; `max_age=300` int, `clock=time.time` injectable — **one sample
per record, post-HMAC, shared by the inclusive key window and freshness**;
`sign_evidence(secret, message)` signs seven fields or seven + `key_id`.
W2 demo data needs actual installed proof of: retired replay denial
(`EVIDENCE_KEY_RETIRED` behind the cache), the cached-receipt branch
(same command id verbatim, zero writes) and the new-command branch (current
status, `commands +1`), plus a six-table history digest — the demo must use
ephemeral keys (never printed) and an injected deterministic clock exactly as
the pinned tests and my probes do.

## Assembly record

- Control `WayJ/s11-release-control`: merge commit
  **`71bee0137f46bf63bd393d58f81c6d7a6f5c6140`** (`merge: assemble S11
  source-key core ce584d3 into release control`, `--no-ff` on base
  `331172f`), then this note committed on top.
- Carrier `WayJ/sprint-s11-source-key-rotation`: fast-forwarded to the
  control tip — this note's own commit (a commit cannot contain its own
  hash; the exact SHA equals `git rev-parse` of this file's commit and is
  reported to the coordinator; contains `ce584d3` + merge + this note). W2
  builds on that exact SHA.
- Post-assembly gates re-run on the control tree: full battery **859 OK
  (skipped=3)**, `check_docs.py` **96 files / 423 links / 0 broken** (this
  note lives under `.agents/`, excluded from the scan), `compileall` clean,
  `check_site.py` 0 findings, `demo` exit 0 — identical to the
  accepted-source runs.
- No main/root merge, no push, no sprint `state` flip, no acceptance record,
  no debt/ledger change — final S11 acceptance waits for W2 and a fresh
  final review. All worktrees and the preview server (127.0.0.1:52719,
  HTTP 200) preserved.

## Risks / limits (unchanged, truthful — Option A boundary)

No persistent key revocation memory: config rollback revives an old secret;
retired key-id reuse after a drop is operator discipline (uniqueness is
enforced within one configuration only); a compromised *current* key stays
forgeable until rotation lands and grace expires; which key admitted a proof
is never recorded (no rotation audit rows); wall-clock trust is the
operator's; `O(ring)` selector scans are config-sized by ratified design
(no cap). Nothing here is tenant authentication, TLS, an external KMS,
distributed revocation, federated key distribution, or any security
certification or production-safety claim; the shared-key HMAC boundary and
"local trusted principals ≠ authentication" remain exactly as documented.
